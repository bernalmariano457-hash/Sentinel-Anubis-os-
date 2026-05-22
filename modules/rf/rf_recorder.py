from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
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
from rich import box


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log = logging.getLogger("sentinel.rf.recorder")


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

IQ_DIR           = Path("data/evidence/rf/iq")
SIGMF_VERSION    = "1.0.0"
SIGMF_AUTHOR     = "rfscanner"
SIGMF_DATATYPE   = "cf32_le"
DEFAULT_SR       = 2_048_000
DEFAULT_DURATION = 10
AUDIO_RATE       = 48_000
AUDIO_VOLUME     = 0.85
BLOCK_SIZE_SECS  = 1            # segundos por bloque de reproducción

IQ_GLOB_PATTERNS = ("*.iq", "*.sigmf-data")
META_EXTENSIONS  = (".sigmf-meta", ".json")

COMPATIBLE_TOOLS = "SDR# · GQRX · GNU Radio · URH · SigMF"


# ---------------------------------------------------------------------------
# Modelos de datos
# ---------------------------------------------------------------------------

@dataclass
class RecordingConfig:
    freq_mhz:    float
    duration_s:  int   = DEFAULT_DURATION
    sample_rate: int   = DEFAULT_SR
    name:        Optional[str] = None
    format:      str   = "sigmf"

    @property
    def freq_hz(self) -> int:
        return int(self.freq_mhz * 1e6)

    @property
    def freq_label(self) -> str:
        return f"{self.freq_mhz:.3f} MHz"

    @property
    def sps_label(self) -> str:
        return f"{self.sample_rate / 1e6:.2f} Msps"

    def build_filename(self, timestamp: str) -> str:
        return self.name or f"iq_{self.freq_mhz:.3f}MHz_{timestamp}"

    def build_path(self, timestamp: str) -> Path:
        ext = "sigmf-data" if self.format == "sigmf" else "iq"
        return IQ_DIR / f"{self.build_filename(timestamp)}.{ext}"


@dataclass
class RecordingResult:
    path:          Path
    freq_mhz:      float
    sample_rate:   int
    total_samples: int
    bytes_written: int
    duration_s:    float
    timestamp_utc: str
    hardware:      str

    @property
    def size_mb(self) -> float:
        return self.bytes_written / 1e6

    @property
    def actual_duration(self) -> float:
        return self.total_samples / self.sample_rate

    def to_meta_dict(self) -> dict:
        return {
            "frecuencia_hz":    int(self.freq_mhz * 1e6),
            "sample_rate":      self.sample_rate,
            "formato":          "complex64",
            "byte_order":       "little-endian",
            "timestamp_utc":    self.timestamp_utc,
            "duracion_seg":     self.duration_s,
            "muestras_totales": self.total_samples,
            "hardware":         self.hardware,
        }


# ---------------------------------------------------------------------------
# Helpers de metadatos
# ---------------------------------------------------------------------------

def _build_sigmf_meta(result: RecordingResult, duration_s: int) -> dict:
    return {
        "global": {
            "core:datatype":         SIGMF_DATATYPE,
            "core:sample_rate":      result.sample_rate,
            "core:version":          SIGMF_VERSION,
            "core:hw":               result.hardware,
            "core:description":      f"APEX SENTINEL capture @ {result.freq_mhz:.3f} MHz",
            "core:author":           SIGMF_AUTHOR,
            "core:date":             result.timestamp_utc,
            "rfscanner:duration_s":  duration_s,
            "rfscanner:samples":     result.total_samples,
        },
        "captures": [{
            "core:sample_start": 0,
            "core:frequency":    int(result.freq_mhz * 1e6),
            "core:datetime":     result.timestamp_utc,
        }],
        "annotations": [],
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_meta(meta_path: Path) -> tuple[float, int, float, str]:
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    if "global" in raw:
        sr      = int(raw["global"].get("core:sample_rate", DEFAULT_SR))
        freq_hz = int(raw.get("captures", [{}])[0].get("core:frequency", 0))
        dur     = float(raw["global"].get("rfscanner:duration_s", 0))
        hw      = raw["global"].get("core:hw", "?")
    else:
        sr      = raw.get("sample_rate", DEFAULT_SR)
        freq_hz = raw.get("frecuencia_hz", 0)
        dur     = float(raw.get("duracion_seg", 0))
        hw      = raw.get("hardware", "?")
    return freq_hz / 1e6, sr, dur, hw


def _locate_meta(iq_path: Path) -> Optional[Path]:
    for ext in META_EXTENSIONS:
        candidate = iq_path.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class RFRecorder:

    def __init__(self, sentinel) -> None:
        self.sentinel = sentinel
        self.console: Console = getattr(sentinel, "console", Console())
        IQ_DIR.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # API pública
    # -----------------------------------------------------------------------

    def record(self, cfg: RecordingConfig) -> Optional[Path]:
        rf = getattr(self.sentinel, "rf_scanner", None)
        if rf is None:
            self.console.print("[red][!] rf_scanner not available.[/red]")
            return None

        timestamp = _utc_timestamp()
        out_path  = cfg.build_path(timestamp)

        self.console.print(
            f"[bold cyan][RF] Recording {cfg.freq_label} · "
            f"{cfg.duration_s}s · {cfg.sps_label} · "
            f"fmt={cfg.format.upper()}[/bold cyan]"
        )

        result = self._capture_iq(rf, cfg, out_path, timestamp)
        if result is None:
            return None

        self._persist_metadata(result, cfg)
        self._print_summary(result)
        self._emit_event(result)
        return result.path

    def grabar(
        self,
        freq_mhz:    float,
        duracion_seg: int  = DEFAULT_DURATION,
        sample_rate:  int  = DEFAULT_SR,
        nombre:       Optional[str] = None,
        formato:      str  = "sigmf",
    ) -> Optional[Path]:
        # Wrapper de compatibilidad hacia atrás
        return self.record(RecordingConfig(
            freq_mhz   = freq_mhz,
            duration_s = duracion_seg,
            sample_rate= sample_rate,
            name       = nombre,
            format     = formato,
        ))

    def playback(
        self,
        file:        str | Path,
        mode:        str = "wfm",
        sample_rate: int = DEFAULT_SR,
    ) -> None:
        from modules.rf.rf_demod  import Demodulator
        from modules.rf.rf_config import DemodConfig

        path = Path(file)
        if not path.exists():
            self.console.print(f"[red][!] File not found: {path}[/red]")
            return

        sample_rate = self._resolve_sample_rate(path, sample_rate)

        self.console.print(
            f"[cyan][RF] Playing [bold]{path.name}[/bold] "
            f"mode=[bold]{mode.upper()}[/bold][/cyan]"
        )

        samples = self._load_iq(path)
        if samples is None:
            return

        self._demodulate_and_play(samples, sample_rate, mode)

    def reproducir(
        self,
        archivo:     str | Path,
        modo:        str = "wfm",
        sample_rate: int = DEFAULT_SR,
    ) -> None:
        self.playback(archivo, modo, sample_rate)

    def list_recordings(self) -> None:
        files = sorted(
            (f for pat in IQ_GLOB_PATTERNS for f in IQ_DIR.glob(pat)),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not files:
            self.console.print("[dim]No IQ recordings found.[/dim]")
            return

        table = Table(
            title=f"[bold]IQ RECORDINGS[/bold] — {IQ_DIR}",
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            show_edge=False,
        )
        table.add_column("File",     style="white",  min_width=32)
        table.add_column("Size",     justify="right", width=9)
        table.add_column("Date",     width=20,        style="dim")
        table.add_column("Info",     style="dim")

        for f in files:
            size_mb  = f.stat().st_size / 1e6
            modified = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            info     = self._file_info_label(f)
            table.add_row(f.name, f"{size_mb:.1f} MB", modified, info)

        self.console.print(table)

    def listar(self) -> None:
        self.list_recordings()

    def delete(self, filename: str) -> None:
        path = (
            IQ_DIR / filename
            if not Path(filename).is_absolute()
            else Path(filename)
        )
        if not path.exists():
            self.console.print(f"[red][!] Not found: {filename}[/red]")
            return

        path.unlink()
        for ext in META_EXTENSIONS:
            sidecar = path.with_suffix(ext)
            if sidecar.exists():
                sidecar.unlink()
                log.debug("Removed sidecar: %s", sidecar)

        self.console.print(f"[green][+] Deleted: {path.name}[/green]")

    def eliminar(self, archivo: str) -> None:
        self.delete(archivo)

    # -----------------------------------------------------------------------
    # Captura IQ
    # -----------------------------------------------------------------------

    def _capture_iq(
        self,
        rf,
        cfg:       RecordingConfig,
        out_path:  Path,
        timestamp: str,
    ) -> Optional[RecordingResult]:
        sample_counts: list[int] = []
        bytes_written  = 0
        start          = time.monotonic()

        with Progress(
            SpinnerColumn(),
            "[cyan]{task.description}[/cyan]",
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"Capturing {cfg.freq_label}...",
                total=cfg.duration_s,
            )

            with out_path.open("wb") as fh:
                while (elapsed := time.monotonic() - start) < cfg.duration_s:
                    block = rf._capturar(cfg.freq_hz)
                    if block is None:
                        log.warning("rf._capturar returned None — stopping early.")
                        break

                    block_c64 = block.astype(np.complex64)
                    fh.write(block_c64.tobytes())
                    sample_counts.append(len(block_c64))
                    bytes_written += block_c64.nbytes
                    progress.update(task, completed=min(elapsed, cfg.duration_s))

        total_samples = sum(sample_counts)
        if total_samples == 0:
            self.console.print("[red][!] No samples captured.[/red]")
            out_path.unlink(missing_ok=True)
            return None

        hw = getattr(rf, "hw_nombre", "unknown")

        return RecordingResult(
            path          = out_path,
            freq_mhz      = cfg.freq_mhz,
            sample_rate   = cfg.sample_rate,
            total_samples = total_samples,
            bytes_written = bytes_written,
            duration_s    = cfg.duration_s,
            timestamp_utc = timestamp,
            hardware      = hw,
        )

    # -----------------------------------------------------------------------
    # Persistencia de metadatos
    # -----------------------------------------------------------------------

    def _persist_metadata(self, result: RecordingResult, cfg: RecordingConfig) -> None:
        if cfg.format == "sigmf":
            meta = _build_sigmf_meta(result, cfg.duration_s)
            _write_json(result.path.with_suffix(".sigmf-meta"), meta)
        else:
            fname = cfg.build_filename(result.timestamp_utc)
            _write_json(IQ_DIR / f"{fname}.json", result.to_meta_dict())

    # -----------------------------------------------------------------------
    # Reproducción
    # -----------------------------------------------------------------------

    def _resolve_sample_rate(self, path: Path, fallback: int) -> int:
        meta_path = _locate_meta(path)
        if meta_path is None:
            return fallback
        try:
            freq_mhz, sr, dur, hw = _read_meta(meta_path)
            self.console.print(
                f"[dim]Metadata: {freq_mhz:.3f} MHz · {sr / 1e6:.2f} Msps[/dim]"
            )
            return sr
        except Exception as exc:
            log.warning("Could not read metadata from %s: %s", meta_path, exc)
            return fallback

    def _load_iq(self, path: Path) -> Optional[np.ndarray]:
        try:
            return np.fromfile(str(path), dtype=np.complex64)
        except Exception as exc:
            self.console.print(f"[red][!] Failed to read IQ file: {exc}[/red]")
            log.exception("IQ file read error: %s", path)
            return None

    def _demodulate_and_play(
        self,
        samples:     np.ndarray,
        sample_rate: int,
        mode:        str,
    ) -> None:
        from modules.rf.rf_demod  import Demodulator
        from modules.rf.rf_config import DemodConfig

        block_size = sample_rate * BLOCK_SIZE_SECS
        n_blocks   = len(samples) // block_size

        self.console.print(
            f"[dim]{len(samples):,} samples · "
            f"{len(samples) / sample_rate:.1f}s · {n_blocks} blocks[/dim]"
        )

        cfg   = DemodConfig(mode=mode, audio_rate=AUDIO_RATE, volume=AUDIO_VOLUME)
        demod = Demodulator(cfg, sample_rate)

        for i in range(n_blocks):
            block = samples[i * block_size:(i + 1) * block_size]
            audio = demod.demodulate(block)
            if audio is not None and len(audio) > 0:
                demod.play(audio)

        demod.stop_audio()
        self.console.print("[green][RF] Playback complete.[/green]")

    # -----------------------------------------------------------------------
    # UI helpers
    # -----------------------------------------------------------------------

    def _print_summary(self, result: RecordingResult) -> None:
        self.console.print(Panel(
            f"[bold green]Recording complete[/bold green]\n\n"
            f"  File:     [white]{result.path}[/white]\n"
            f"  Samples:  [white]{result.total_samples:,}[/white]\n"
            f"  Size:     [white]{result.size_mb:.1f} MB[/white]\n"
            f"  Duration: [white]{result.actual_duration:.1f}s[/white]\n\n"
            f"[dim]Compatible with: {COMPATIBLE_TOOLS}[/dim]",
            border_style="green",
        ))

    def _file_info_label(self, path: Path) -> str:
        meta_path = _locate_meta(path)
        if meta_path is None:
            return ""
        try:
            freq_mhz, sr, dur, hw = _read_meta(meta_path)
            return f"{freq_mhz:.3f} MHz · {dur:.0f}s · {hw}"
        except Exception:
            return ""

    # -----------------------------------------------------------------------
    # Telemetría
    # -----------------------------------------------------------------------

    def _emit_event(self, result: RecordingResult) -> None:
        try:
            self.sentinel.reportes.registrar_evento(
                "RF_REC",
                f"IQ recording: {result.freq_mhz:.3f} MHz, "
                f"{result.actual_duration:.1f}s, {result.size_mb:.1f} MB",
            )
        except Exception as exc:
            log.debug("Could not emit RF_REC event: %s", exc)
