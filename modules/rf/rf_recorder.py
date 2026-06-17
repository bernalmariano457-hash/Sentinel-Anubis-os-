from __future__ import annotations

import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Iterator, Protocol, TypeAlias

import numpy as np
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

log: Final = logging.getLogger("sentinel.rf.recorder")

IQ_DIR: Final[Path] = Path("data/evidence/rf/iq")
SIGMF_VERSION: Final[str] = "1.0.0"
SIGMF_AUTHOR: Final[str] = "rfscanner"
SIGMF_DATATYPE: Final[str] = "cf32_le"
DEFAULT_SAMPLE_RATE: Final[int] = 2_048_000
DEFAULT_DURATION_S: Final[int] = 10
AUDIO_OUTPUT_RATE: Final[int] = 48_000
AUDIO_PLAYBACK_VOLUME: Final[float] = 0.85
PLAYBACK_BLOCK_SECONDS: Final[int] = 1
WRITE_QUEUE_MAXSIZE: Final[int] = 64
COMPATIBLE_TOOLS: Final[str] = "SDR# · GQRX · GNU Radio · URH · SigMF"

IQ_GLOB_PATTERNS: Final[tuple[str, ...]] = ("*.iq", "*.sigmf-data")
META_EXTENSIONS: Final[tuple[str, ...]] = (".sigmf-meta", ".json")

IqArray: TypeAlias = np.ndarray
MetaDict: TypeAlias = dict[str, Any]


class RFSource(Protocol):
    hw_name: str

    def _capturar(self, freq_hz: int) -> IqArray | None: ...


class TelemetrySink(Protocol):
    def registrar_evento(self, event_type: str, message: str) -> None: ...


class SentinelHost(Protocol):
    console: Console
    rf_scanner: RFSource

    @property
    def reportes(self) -> TelemetrySink: ...


@dataclass(slots=True)
class RecordingConfig:
    freq_mhz: float
    duration_s: int = DEFAULT_DURATION_S
    sample_rate: int = DEFAULT_SAMPLE_RATE
    name: str | None = None
    format: str = "sigmf"

    @property
    def freq_hz(self) -> int:
        return int(self.freq_mhz * 1e6)

    @property
    def freq_label(self) -> str:
        return f"{self.freq_mhz:.3f} MHz"

    @property
    def sps_label(self) -> str:
        return f"{self.sample_rate / 1e6:.2f} Msps"

    def build_stem(self, timestamp: str) -> str:
        return self.name or f"iq_{self.freq_mhz:.3f}MHz_{timestamp}"

    def build_output_path(self, timestamp: str) -> Path:
        ext = "sigmf-data" if self.format == "sigmf" else "iq"
        return IQ_DIR / f"{self.build_stem(timestamp)}.{ext}"


@dataclass(slots=True)
class RecordingResult:
    path: Path
    freq_mhz: float
    sample_rate: int
    total_samples: int
    bytes_written: int
    duration_s: float
    timestamp_utc: str
    hardware: str

    @property
    def size_mb(self) -> float:
        return self.bytes_written / 1e6

    @property
    def actual_duration_s(self) -> float:
        return self.total_samples / self.sample_rate

    def to_legacy_meta(self) -> MetaDict:
        return {
            "frecuencia_hz": int(self.freq_mhz * 1e6),
            "sample_rate": self.sample_rate,
            "formato": "complex64",
            "byte_order": "little-endian",
            "timestamp_utc": self.timestamp_utc,
            "duracion_seg": self.duration_s,
            "muestras_totales": self.total_samples,
            "hardware": self.hardware,
        }


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, data: MetaDict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _build_sigmf_meta(result: RecordingResult, requested_duration_s: int) -> MetaDict:
    return {
        "global": {
            "core:datatype": SIGMF_DATATYPE,
            "core:sample_rate": result.sample_rate,
            "core:version": SIGMF_VERSION,
            "core:hw": result.hardware,
            "core:description": f"APEX SENTINEL capture @ {result.freq_mhz:.3f} MHz",
            "core:author": SIGMF_AUTHOR,
            "core:date": result.timestamp_utc,
            "rfscanner:duration_s": requested_duration_s,
            "rfscanner:samples": result.total_samples,
        },
        "captures": [{
            "core:sample_start": 0,
            "core:frequency": int(result.freq_mhz * 1e6),
            "core:datetime": result.timestamp_utc,
        }],
        "annotations": [],
    }


def _locate_meta(iq_path: Path) -> Path | None:
    return next(
        (iq_path.with_suffix(ext) for ext in META_EXTENSIONS if iq_path.with_suffix(ext).exists()),
        None,
    )


def _parse_meta(meta_path: Path) -> tuple[float, int, float, str]:
    raw: MetaDict = json.loads(meta_path.read_text(encoding="utf-8"))
    if "global" in raw:
        sample_rate = int(raw["global"].get("core:sample_rate", DEFAULT_SAMPLE_RATE))
        freq_hz = int((raw.get("captures") or [{}])[0].get("core:frequency", 0))
        duration = float(raw["global"].get("rfscanner:duration_s", 0))
        hardware = raw["global"].get("core:hw", "?")
    else:
        sample_rate = int(raw.get("sample_rate", DEFAULT_SAMPLE_RATE))
        freq_hz = int(raw.get("frecuencia_hz", 0))
        duration = float(raw.get("duracion_seg", 0))
        hardware = str(raw.get("hardware", "?"))
    return freq_hz / 1e6, sample_rate, duration, hardware


def _resolve_output_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else IQ_DIR / path


class _AsyncFileWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._queue: queue.Queue[bytes | None] = queue.Queue(maxsize=WRITE_QUEUE_MAXSIZE)
        self._bytes_written = 0
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._writer_loop, daemon=True, name="rf-iq-writer")
        self._thread.start()

    def _writer_loop(self) -> None:
        try:
            with self._path.open("wb") as fh:
                while True:
                    chunk = self._queue.get()
                    if chunk is None:
                        break
                    fh.write(chunk)
                    self._bytes_written += len(chunk)
        except Exception as exc:
            self._error = exc
            log.error("Async IQ writer failed: %s", exc)

    def submit(self, raw_bytes: bytes) -> None:
        if self._error is not None:
            raise RuntimeError(f"IQ writer thread failed: {self._error}") from self._error
        self._queue.put(raw_bytes)

    def flush_and_close(self) -> int:
        self._queue.put(None)
        self._thread.join()
        if self._error is not None:
            raise RuntimeError(f"IQ writer thread failed: {self._error}") from self._error
        return self._bytes_written

    def abort(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put(None)
        self._thread.join()
        self._path.unlink(missing_ok=True)


class IQCaptureSession:
    def __init__(self, rf_source: RFSource, cfg: RecordingConfig, out_path: Path) -> None:
        self._rf = rf_source
        self._cfg = cfg
        self._out_path = out_path
        self._writer: _AsyncFileWriter | None = None
        self._total_samples = 0

    def __enter__(self) -> IQCaptureSession:
        self._writer = _AsyncFileWriter(self._out_path)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._writer is not None and exc_type is not None:
            self._writer.abort()

    def run(self, progress: Progress, task_id: Any) -> RecordingResult | None:
        assert self._writer is not None
        t_start = time.monotonic()

        try:
            while (elapsed := time.monotonic() - t_start) < self._cfg.duration_s:
                block = self._rf._capturar(self._cfg.freq_hz)
                if block is None:
                    log.warning("rf._capturar returned None at %.1fs — stopping early.", elapsed)
                    break
                encoded = block.astype(np.complex64)
                self._writer.submit(encoded.tobytes())
                self._total_samples += len(encoded)
                progress.update(task_id, completed=min(elapsed, self._cfg.duration_s))

        except KeyboardInterrupt:
            log.info("IQ capture interrupted by user after %.1fs.", time.monotonic() - t_start)

        finally:
            bytes_written = self._writer.flush_and_close()

        if self._total_samples == 0:
            self._out_path.unlink(missing_ok=True)
            return None

        return RecordingResult(
            path=self._out_path,
            freq_mhz=self._cfg.freq_mhz,
            sample_rate=self._cfg.sample_rate,
            total_samples=self._total_samples,
            bytes_written=bytes_written,
            duration_s=self._cfg.duration_s,
            timestamp_utc=_utc_timestamp(),
            hardware=getattr(self._rf, "hw_name", "unknown"),
        )


class MetadataWriter:
    @staticmethod
    def persist(result: RecordingResult, cfg: RecordingConfig) -> None:
        if cfg.format == "sigmf":
            _write_json(
                result.path.with_suffix(".sigmf-meta"),
                _build_sigmf_meta(result, cfg.duration_s),
            )
        else:
            stem = cfg.build_stem(result.timestamp_utc)
            _write_json(IQ_DIR / f"{stem}.json", result.to_legacy_meta())


class IQPlaybackEngine:
    def __init__(self, console: Console) -> None:
        self._console = console

    def play_file(self, path: Path, mode: str, sample_rate: int) -> None:
        from modules.rf.rf_demod import Demodulator
        from modules.rf.rf_config import DemodConfig

        resolved_rate = self._resolve_sample_rate(path, sample_rate)
        self._console.print(
            f"[cyan][RF] Playing [bold]{path.name}[/bold] "
            f"mode=[bold]{mode.upper()}[/bold][/cyan]"
        )

        samples = self._load_iq_file(path)
        if samples is None:
            return

        block_size = resolved_rate * PLAYBACK_BLOCK_SECONDS
        n_blocks = len(samples) // block_size

        self._console.print(
            f"[dim]{len(samples):,} samples · "
            f"{len(samples) / resolved_rate:.1f}s · {n_blocks} blocks[/dim]"
        )

        demod_cfg = DemodConfig(mode=mode, audio_rate=AUDIO_OUTPUT_RATE, volume=AUDIO_PLAYBACK_VOLUME)
        demod = Demodulator(demod_cfg, resolved_rate)

        try:
            for block_idx in range(n_blocks):
                block = samples[block_idx * block_size:(block_idx + 1) * block_size]
                audio = demod.demodulate(block)
                if audio is not None and len(audio) > 0:
                    demod.play(audio)
        finally:
            demod.stop_audio()

        self._console.print("[green][RF] Playback complete.[/green]")

    def _resolve_sample_rate(self, path: Path, fallback: int) -> int:
        meta_path = _locate_meta(path)
        if meta_path is None:
            return fallback
        try:
            _, sample_rate, _, _ = _parse_meta(meta_path)
            self._console.print(f"[dim]Metadata loaded from: {meta_path.name}[/dim]")
            return sample_rate
        except Exception as exc:
            log.warning("Could not parse metadata %s: %s", meta_path, exc)
            return fallback

    def _load_iq_file(self, path: Path) -> IqArray | None:
        try:
            return np.fromfile(str(path), dtype=np.complex64)
        except Exception as exc:
            self._console.print(f"[red][!] Failed to read IQ file: {exc}[/red]")
            log.exception("IQ file read error: %s", path)
            return None


class RecordingListView:
    def __init__(self, console: Console, iq_dir: Path) -> None:
        self._console = console
        self._iq_dir = iq_dir

    def render(self) -> None:
        files = sorted(
            (f for pat in IQ_GLOB_PATTERNS for f in self._iq_dir.glob(pat)),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not files:
            self._console.print("[dim]No IQ recordings found.[/dim]")
            return

        table = Table(
            title=f"[bold]IQ RECORDINGS[/bold] — {self._iq_dir}",
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            show_edge=False,
        )
        table.add_column("File", style="white", min_width=32)
        table.add_column("Size", justify="right", width=9)
        table.add_column("Date", width=20, style="dim")
        table.add_column("Info", style="dim")

        for file_path in files:
            stat = file_path.stat()
            size_mb = stat.st_size / 1e6
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            info_label = self._build_info_label(file_path)
            table.add_row(file_path.name, f"{size_mb:.1f} MB", modified, info_label)

        self._console.print(table)

    def _build_info_label(self, path: Path) -> str:
        meta_path = _locate_meta(path)
        if meta_path is None:
            return ""
        try:
            freq_mhz, _, duration, hardware = _parse_meta(meta_path)
            return f"{freq_mhz:.3f} MHz · {duration:.0f}s · {hardware}"
        except Exception:
            return ""


class RFRecorder:
    def __init__(self, sentinel: Any) -> None:
        self._sentinel = sentinel
        self._console: Console = getattr(sentinel, "console", Console())
        self._playback = IQPlaybackEngine(self._console)
        self._list_view = RecordingListView(self._console, IQ_DIR)
        IQ_DIR.mkdir(parents=True, exist_ok=True)

    def record(self, cfg: RecordingConfig) -> Path | None:
        rf_source: RFSource | None = getattr(self._sentinel, "rf_scanner", None)
        if rf_source is None:
            self._console.print("[red][!] rf_scanner not available.[/red]")
            return None

        timestamp = _utc_timestamp()
        out_path = cfg.build_output_path(timestamp)

        self._console.print(
            f"[bold cyan][RF] Recording {cfg.freq_label} · "
            f"{cfg.duration_s}s · {cfg.sps_label} · "
            f"fmt={cfg.format.upper()}[/bold cyan]"
        )

        result = self._run_capture(rf_source, cfg, out_path)
        if result is None:
            self._console.print("[red][!] No samples captured.[/red]")
            return None

        MetadataWriter.persist(result, cfg)
        self._render_summary(result)
        self._emit_telemetry(result)
        log.info(
            "IQ recorded: %s  %.1fs  %.1fMB  hw=%s",
            out_path.name, result.actual_duration_s, result.size_mb, result.hardware,
        )
        return result.path

    def grabar(
        self,
        freq_mhz: float,
        duracion_seg: int = DEFAULT_DURATION_S,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        nombre: str | None = None,
        formato: str = "sigmf",
    ) -> Path | None:
        return self.record(RecordingConfig(
            freq_mhz=freq_mhz,
            duration_s=duracion_seg,
            sample_rate=sample_rate,
            name=nombre,
            format=formato,
        ))

    def playback(self, file: str | Path, mode: str = "wfm", sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        path = _resolve_output_path(file)
        if not path.exists():
            self._console.print(f"[red][!] File not found: {path}[/red]")
            return
        self._playback.play_file(path, mode, sample_rate)

    def reproducir(self, archivo: str | Path, modo: str = "wfm", sample_rate: int = DEFAULT_SAMPLE_RATE) -> None:
        self.playback(archivo, modo, sample_rate)

    def list_recordings(self) -> None:
        self._list_view.render()

    def listar(self) -> None:
        self.list_recordings()

    def delete(self, filename: str) -> None:
        path = _resolve_output_path(filename)
        if not path.exists():
            self._console.print(f"[red][!] Not found: {filename}[/red]")
            return

        path.unlink()
        for ext in META_EXTENSIONS:
            sidecar = path.with_suffix(ext)
            if sidecar.exists():
                sidecar.unlink()
                log.debug("Removed sidecar: %s", sidecar)

        self._console.print(f"[green][+] Deleted: {path.name}[/green]")

    def eliminar(self, archivo: str) -> None:
        self.delete(archivo)

    def _run_capture(
        self,
        rf_source: RFSource,
        cfg: RecordingConfig,
        out_path: Path,
    ) -> RecordingResult | None:
        with Progress(
            SpinnerColumn(),
            "[cyan]{task.description}[/cyan]",
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self._console,
            transient=True,
        ) as progress:
            task_id = progress.add_task(f"Capturing {cfg.freq_label}...", total=cfg.duration_s)
            session = IQCaptureSession(rf_source, cfg, out_path)
            with session:
                return session.run(progress, task_id)

    def _render_summary(self, result: RecordingResult) -> None:
        self._console.print(Panel(
            f"[bold green]Recording complete[/bold green]\n\n"
            f"  File:     [white]{result.path}[/white]\n"
            f"  Samples:  [white]{result.total_samples:,}[/white]\n"
            f"  Size:     [white]{result.size_mb:.1f} MB[/white]\n"
            f"  Duration: [white]{result.actual_duration_s:.1f}s[/white]\n\n"
            f"[dim]Compatible with: {COMPATIBLE_TOOLS}[/dim]",
            border_style="green",
        ))

    def _emit_telemetry(self, result: RecordingResult) -> None:
        try:
            self._sentinel.reportes.registrar_evento(
                "RF_REC",
                f"IQ recording: {result.freq_mhz:.3f} MHz, "
                f"{result.actual_duration_s:.1f}s, {result.size_mb:.1f} MB",
            )
        except Exception as exc:
            log.debug("Could not emit RF_REC telemetry event: %s", exc)
