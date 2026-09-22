from __future__ import annotations

import logging
import logging.handlers
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Protocol, TypeAlias

import numpy as np
from rich import box
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from modules.rf.bands import BANDAS_RF, COLORES_TIPO, identify_band
from modules.rf.dsp import DSPEngine, Signal
from modules.rf.rf_config import RFConfig, load_config
from modules.rf.rf_database import RFDatabase
from modules.rf.rf_demod import Demodulator
from modules.rf.rf_recorder import RFRecorder
from modules.rf.rf_storage import CSVExporter, SigMFWriter, SignalDB

log: Final = logging.getLogger("sentinel.rf.scanner")

_WF_CHARS: Final[str] = " ·░▒▓█"
_RTL_FREQ_MIN_MHZ: Final[float] = 24.0
_RTL_FREQ_MAX_MHZ: Final[float] = 1766.0
_RICH_TAG_PATTERN: Final = re.compile(r"\[/?[^\]]*\]")

PsdArray: TypeAlias = np.ndarray
FreqArray: TypeAlias = np.ndarray
IqArray: TypeAlias = np.ndarray
ScanResult: TypeAlias = tuple[FreqArray, PsdArray, list[Signal], float]


class HardwareBackend(Protocol):
    hw_name: str

    def tune(self, freq_hz: float) -> None: ...
    def read_raw(self, n_samples: int) -> IqArray | None: ...
    def set_gain(self, gain: float | str) -> None: ...
    def close(self) -> None: ...


@dataclass(slots=True)
class FrequencyTrack:
    detections: int = 0
    absences: int = 0
    first_seen: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    power_history: deque[float] = field(default_factory=lambda: deque(maxlen=20))

    def is_active(self) -> bool:
        return self.detections > 0

    def duty_cycle(self, total_frames: int) -> float:
        return 0.0 if total_frames == 0 else min(1.0, self.detections / total_frames)

    def mean_power(self) -> float:
        return float(np.mean(self.power_history)) if self.power_history else -999.0


class DCRemover:
    _DEFAULT_HALF_WIDTH: Final[int] = 5

    def remove(self, psd: PsdArray, half_width: int = _DEFAULT_HALF_WIDTH) -> PsdArray:
        center = len(psd) // 2
        lo = max(0, center - half_width)
        hi = min(len(psd), center + half_width + 1)
        if lo == 0 or hi == len(psd):
            return psd.copy()
        result = psd.copy()
        result[lo:hi] = np.interp(
            np.arange(lo, hi),
            [lo - 1, hi],
            [psd[lo - 1], psd[hi]],
        )
        return result


class PeakHoldBuffer:
    def __init__(self, avg_frames: int = 8) -> None:
        self._frames: deque[PsdArray] = deque(maxlen=avg_frames)
        self._peak: PsdArray | None = None

    def update(self, psd: PsdArray) -> None:
        self._frames.append(psd)
        self._peak = (
            np.maximum(self._peak, psd)
            if self._peak is not None and self._peak.shape == psd.shape
            else psd.copy()
        )

    def peak(self) -> PsdArray | None:
        return self._peak

    def average(self) -> PsdArray | None:
        return np.mean(np.stack(self._frames), axis=0) if self._frames else None

    def reset(self) -> None:
        self._frames.clear()
        self._peak = None


class SignalTracker:
    FREQ_BIN_KHZ: Final[float] = 5.0
    MIN_CONSECUTIVE_FRAMES: Final[int] = 2
    DECAY_FRAME_COUNT: Final[int] = 5

    def __init__(self) -> None:
        self._tracks: dict[int, FrequencyTrack] = {}
        self._consecutive: dict[int, int] = defaultdict(int)
        self._total_frames: int = 0

    def _to_bin(self, freq_mhz: float) -> int:
        return round(freq_mhz * 1000 / self.FREQ_BIN_KHZ)

    def update(self, peaks: list[Signal]) -> list[Signal]:
        self._total_frames += 1
        seen_bins: set[int] = {self._to_bin(s.freq_mhz) for s in peaks}

        for signal in peaks:
            freq_bin = self._to_bin(signal.freq_mhz)
            track = self._tracks.setdefault(freq_bin, FrequencyTrack(first_seen=time.monotonic()))
            track.detections += 1
            track.absences = 0
            track.last_seen = time.monotonic()
            track.power_history.append(signal.potencia)
            self._consecutive[freq_bin] += 1

        stale_bins = [b for b in list(self._tracks) if b not in seen_bins]
        for freq_bin in stale_bins:
            self._tracks[freq_bin].absences += 1
            self._consecutive[freq_bin] = 0
            if self._tracks[freq_bin].absences > self.DECAY_FRAME_COUNT:
                del self._tracks[freq_bin]
                self._consecutive.pop(freq_bin, None)

        return [
            s for s in peaks
            if self._consecutive[self._to_bin(s.freq_mhz)] >= self.MIN_CONSECUTIVE_FRAMES
        ]

    def duty_cycle(self, freq_mhz: float) -> float:
        track = self._tracks.get(self._to_bin(freq_mhz))
        return track.duty_cycle(self._total_frames) if track else 0.0

    def time_active(self, freq_mhz: float) -> float:
        track = self._tracks.get(self._to_bin(freq_mhz))
        return time.monotonic() - track.first_seen if track else 0.0

    def reset(self) -> None:
        self._tracks.clear()
        self._consecutive.clear()
        self._total_frames = 0


class AGCController:
    SAT_THRESHOLD_DBM: Final[float] = -5.0
    WEAK_THRESHOLD_DBM: Final[float] = -85.0
    GAIN_STEP_UP_DB: Final[float] = 5.0
    GAIN_STEP_DOWN_DB: Final[float] = 10.0
    GAIN_MIN_DB: Final[float] = 0.0
    GAIN_MAX_DB: Final[float] = 49.6
    COOLDOWN_SECONDS: Final[float] = 2.0
    PEAK_PERCENTILE: Final[float] = 99.0
    MIN_GAIN_DELTA_DB: Final[float] = 0.5

    def __init__(self, initial_gain_db: float = 30.0) -> None:
        self._last_adjustment_ts: float = 0.0
        self.current_gain_db: float = initial_gain_db

    def step(self, psd_dbm: PsdArray, backend: HardwareBackend) -> float | None:
        if time.monotonic() - self._last_adjustment_ts < self.COOLDOWN_SECONDS:
            return None

        peak_dbm = float(np.percentile(psd_dbm, self.PEAK_PERCENTILE))

        if peak_dbm > self.SAT_THRESHOLD_DBM:
            candidate = max(self.GAIN_MIN_DB, self.current_gain_db - self.GAIN_STEP_DOWN_DB)
            reason = f"saturation ({peak_dbm:.0f} dBm) gain -{self.GAIN_STEP_DOWN_DB:.0f} dB"
        elif peak_dbm < self.WEAK_THRESHOLD_DBM:
            candidate = min(self.GAIN_MAX_DB, self.current_gain_db + self.GAIN_STEP_UP_DB)
            reason = f"weak signal ({peak_dbm:.0f} dBm) gain +{self.GAIN_STEP_UP_DB:.0f} dB"
        else:
            return None

        if abs(candidate - self.current_gain_db) < self.MIN_GAIN_DELTA_DB:
            return None

        try:
            backend.set_gain(candidate)
            self.current_gain_db = candidate
            self._last_adjustment_ts = time.monotonic()
            log.info("AGC: %s  new_gain=%.1f dB", reason, candidate)
            return candidate
        except Exception as exc:
            log.warning("AGC set_gain failed: %s", exc)
            return None


class SpectrumRenderer:
    _POWER_STYLE_THRESHOLDS: Final[tuple[tuple[float, str], ...]] = (
        (0.85, "bold red"),
        (0.65, "red"),
        (0.45, "yellow"),
        (0.25, "green"),
        (0.0, "dim green"),
    )

    def __init__(self, console: Console, cfg: RFConfig) -> None:
        self._console = console
        self._cfg = cfg

    def _power_bar_style(self, ratio: float) -> str:
        for threshold, style in self._POWER_STYLE_THRESHOLDS:
            if ratio >= threshold:
                return style
        return "dim green"

    def _normalize_y(self, value: float, height: int, db_min: float, db_max: float) -> int:
        return int(np.clip((value - db_min) / (db_max - db_min) * height, 0, height))

    def spectrum(
        self,
        freqs_hz: FreqArray,
        psd_dbm: PsdArray,
        center_freq_mhz: float,
        peaks: list[Signal],
        sample_rate: float,
        hw_name: str,
        peak_hold: PsdArray | None = None,
        avg_psd: PsdArray | None = None,
    ) -> Panel:
        disp = self._cfg.display
        width = disp.spectrum_width
        height = disp.spectrum_height
        db_min = disp.dbm_floor
        db_max = disp.dbm_ceil

        col_indices = np.linspace(0, len(psd_dbm) - 1, width).astype(int)
        psd_cols = psd_dbm[col_indices]
        ph_cols = peak_hold[col_indices] if peak_hold is not None and peak_hold.shape == psd_dbm.shape else None
        av_cols = avg_psd[col_indices] if avg_psd is not None and avg_psd.shape == psd_dbm.shape else None

        bar_heights = np.vectorize(lambda v: self._normalize_y(v, height, db_min, db_max))(psd_cols)
        ph_heights = (
            np.vectorize(lambda v: self._normalize_y(v, height, db_min, db_max))(ph_cols)
            if ph_cols is not None else None
        )
        av_heights = (
            np.vectorize(lambda v: self._normalize_y(v, height, db_min, db_max))(av_cols)
            if av_cols is not None else None
        )

        noise_floor = float(np.median(psd_dbm))
        snr_threshold_y = self._normalize_y(
            noise_floor + self._cfg.dsp.snr_threshold, height, db_min, db_max
        )

        canvas = Text()
        for row in range(height, -1, -1):
            db_label = db_min + (row / height) * (db_max - db_min)
            canvas.append(f"{db_label:>6.0f} │", style="dim green")
            for col in range(width):
                bar_h = int(bar_heights[col])
                ph_h = int(ph_heights[col]) if ph_heights is not None else None
                av_h = int(av_heights[col]) if av_heights is not None else None
                if bar_h >= row:
                    canvas.append("█", style=self._power_bar_style(bar_h / height))
                elif ph_h is not None and ph_h == row:
                    canvas.append("▔", style="cyan")
                elif av_h is not None and av_h == row:
                    canvas.append("─", style="dim cyan")
                elif row == snr_threshold_y:
                    canvas.append("─", style="dim red")
                else:
                    canvas.append(" ")
            canvas.append("\n")

        bw_mhz = sample_rate / 1e6
        freq_lo = center_freq_mhz - bw_mhz / 2
        freq_hi = center_freq_mhz + bw_mhz / 2
        pad_l = max(0, width // 2 - 9)
        pad_r = max(0, width // 2 - 11)

        canvas.append("       └" + "─" * width + "\n", style="dim green")
        canvas.append(
            f"  {freq_lo:.3f}" + " " * pad_l
            + f"{center_freq_mhz:.3f} [centro]" + " " * pad_r
            + f"{freq_hi:.3f} MHz\n",
            style="dim green",
        )
        if ph_heights is not None:
            canvas.append("  [dim cyan]▔[/dim cyan] peak-hold  ", style="dim")
        if av_heights is not None:
            canvas.append("  [dim cyan]─[/dim cyan] promedio  ", style="dim")
        if peaks:
            canvas.append(
                f"  [dim red]umbral={noise_floor:.0f}+{self._cfg.dsp.snr_threshold:.0f}"
                f"={noise_floor + self._cfg.dsp.snr_threshold:.0f} dBm[/dim red]"
            )

        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        return Panel(
            canvas,
            title=(
                f"[bold green]ESPECTRO RF — {center_freq_mhz:.4f} MHz"
                f"[/bold green]  [dim]{hw_name}[/dim]  [dim]{timestamp}[/dim]"
            ),
            border_style="green",
            box=box.HEAVY_HEAD,
        )

    def waterfall(self, history: deque[PsdArray], center_freq_mhz: float) -> Panel:
        if not history:
            return Panel(
                "[dim]Sin datos.[/dim]",
                title="WATERFALL",
                border_style="dim green",
            )

        width = self._cfg.display.spectrum_width
        db_min = self._cfg.display.dbm_floor
        db_max = self._cfg.display.dbm_ceil
        n_rows = max(len(history) - 1, 1)
        canvas = Text()

        for row_idx, psd in enumerate(history):
            col_indices = np.linspace(0, len(psd) - 1, width).astype(int)
            row_psd = psd[col_indices]
            age_ratio = row_idx / n_rows
            canvas.append("  ")
            normalized = np.clip((row_psd - db_min) / (db_max - db_min), 0, 1)
            char_indices = (normalized * (len(_WF_CHARS) - 1)).astype(int)
            for v, char_idx in zip(normalized, char_indices):
                char = _WF_CHARS[char_idx]
                v_float = float(v)
                if v_float > 0.75:
                    style = "bold red" if age_ratio < 0.3 else "red"
                elif v_float > 0.50:
                    style = "yellow" if age_ratio < 0.3 else "dark_orange"
                elif v_float > 0.25:
                    style = "green" if age_ratio < 0.3 else "dark_green"
                else:
                    style = "dim"
                canvas.append(char, style=style)
            canvas.append("\n")

        return Panel(
            canvas,
            title=(
                f"[bold green]WATERFALL — {center_freq_mhz:.3f} MHz"
                f"[/bold green]  [dim]{len(history)} capturas[/dim]"
            ),
            border_style="dim green",
            box=box.SIMPLE,
        )

    def signal_table(
        self,
        peaks: list[Signal],
        tracker: SignalTracker | None = None,
    ) -> Panel:
        if not peaks:
            return Panel(
                "[dim]No se detectaron señales sobre el umbral.[/dim]",
                title="[green]SEÑALES DETECTADAS[/green]",
                border_style="dim green",
            )

        table = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold green",
            show_edge=False,
            expand=True,
        )
        table.add_column("Frecuencia", style="cyan", min_width=15, no_wrap=True)
        table.add_column("Potencia", justify="right", min_width=11)
        table.add_column("SNR", justify="right", min_width=8)
        table.add_column("BW", justify="right", min_width=10)
        table.add_column("Mod.", min_width=10)
        table.add_column("Duty", justify="right", min_width=7)
        table.add_column("t activo", justify="right", min_width=9)
        table.add_column("Banda", min_width=16)

        for signal in peaks:
            if signal.potencia > -50:
                power_style = "bold red"
            elif signal.potencia > -70:
                power_style = "yellow"
            else:
                power_style = "green"

            band_str = "—"
            if signal.banda:
                color = signal.banda.get("color", "dim")
                band_str = f"[{color}]{signal.banda['nombre']}[/{color}]"

            duty_str = time_active_str = "—"
            if tracker:
                duty_str = f"{tracker.duty_cycle(signal.freq_mhz) * 100:.0f}%"
                time_active_str = f"{tracker.time_active(signal.freq_mhz):.0f}s"

            table.add_row(
                f"{signal.freq_mhz:.4f} MHz",
                Text(f"{signal.potencia:.1f} dBm", style=power_style),
                f"{signal.snr_db:.1f} dB",
                f"{signal.bw_khz:.2f} kHz",
                signal.mod_hint or "—",
                duty_str,
                time_active_str,
                band_str,
            )

        return Panel(
            table,
            title=f"[bold green]SEÑALES DETECTADAS  [{len(peaks)}][/bold green]",
            border_style="green",
            box=box.HEAVY_HEAD,
        )

    def scan_stats_panel(
        self,
        freq_mhz: float,
        iteration: int,
        duration_s: int,
        elapsed_s: float,
        n_peaks: int,
        n_session: int,
        n_captures: int,
        noise_floor_dbm: float,
        gain_db: float,
        agc_active: bool,
    ) -> Panel:
        progress_pct = min(1.0, elapsed_s / duration_s)
        bar_width = 24
        filled = int(progress_pct * bar_width)
        bar = "█" * filled + "░" * (bar_width - filled)

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="dim green", justify="right", min_width=14)
        grid.add_column(style="white", min_width=14)

        grid.add_row("Frecuencia", f"{freq_mhz:.4f} MHz")
        grid.add_row("Progreso", f"[green][{bar}][/green] {progress_pct * 100:.0f}%")
        grid.add_row("Tiempo", f"{elapsed_s:.1f}s / {duration_s}s")
        grid.add_row("Iteración", str(iteration))
        grid.add_row("Capturas", str(n_captures))
        grid.add_row("Señales", f"[yellow]{n_peaks}[/yellow]")
        grid.add_row("Sesión tot.", str(n_session))
        grid.add_row("Piso RF", f"{noise_floor_dbm:.1f} dBm")
        grid.add_row(
            "Ganancia",
            f"[cyan]{gain_db:.1f} dB [AGC][/cyan]" if agc_active else f"{gain_db:.1f} dB",
        )

        return Panel(grid, title="[bold green]ESCANEO[/bold green]", border_style="green", box=box.ROUNDED)

    def sweep_map(self, results: list[dict[str, Any]]) -> Panel:
        table = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold green",
            show_edge=False,
            expand=True,
        )
        table.add_column("Frecuencia", style="cyan", min_width=14, no_wrap=True)
        table.add_column("Actividad", min_width=22)
        table.add_column("Pot. máx", justify="right", min_width=10)
        table.add_column("SNR", justify="right", min_width=8)
        table.add_column("Piso RF", justify="right", min_width=10)
        table.add_column("Ocup. %", justify="right", min_width=8)
        table.add_column("Banda", min_width=18)

        bar_max_chars = 22
        sorted_results = sorted(results, key=lambda x: x["snr"], reverse=True)[:35]
        for r in sorted_results:
            snr = r["snr"]
            bar_len = int(np.clip(snr / 35 * bar_max_chars, 0, bar_max_chars))
            bar = "█" * bar_len + "·" * (bar_max_chars - bar_len)

            if snr > 25:
                row_style = "bold red"
            elif snr > 15:
                row_style = "yellow"
            elif snr > 8:
                row_style = "green"
            else:
                row_style = "dim"

            band = r.get("banda")
            band_str = (
                f"[{band['color']}]{band['nombre']}[/{band['color']}]"
                if band else "—"
            )

            table.add_row(
                f"{r['freq_mhz']:.3f} MHz",
                Text(bar, style=row_style),
                Text(f"{r['pot_max']:.1f} dBm", style=row_style),
                f"{snr:.1f} dB",
                f"{r['piso']:.1f} dBm",
                f"{r.get('ocupacion_pct', 0):.0f}%",
                band_str,
            )

        return Panel(table, title="[bold green]MAPA DE ACTIVIDAD RF[/bold green]", border_style="green", box=box.HEAVY_HEAD)

    def scan_summary(
        self,
        freq_mhz: float,
        peaks: list[Signal],
        duration_s: float,
        hw_name: str,
        iterations: int,
        tracker: SignalTracker | None = None,
        agc_adjustments: int = 0,
    ) -> Panel:
        snr_max = max((s.snr_db for s in peaks), default=0.0)
        pot_max = max((s.potencia for s in peaks), default=-999.0)
        bw_mean = sum(s.bw_khz for s in peaks) / len(peaks) if peaks else 0.0
        band_names = {s.banda["nombre"] for s in peaks if s.banda}
        duty_max = max((tracker.duty_cycle(s.freq_mhz) for s in peaks), default=0.0) if tracker and peaks else 0.0

        grid = Table.grid(padding=(0, 3))
        grid.add_column(style="dim green", justify="right", min_width=22)
        grid.add_column(style="white")
        grid.add_row("Frecuencia", f"{freq_mhz:.4f} MHz")
        grid.add_row("Hardware", hw_name)
        grid.add_row("Duración real", f"{duration_s:.1f} s")
        grid.add_row("Iteraciones FFT", str(iterations))
        grid.add_row("Señales persistentes", str(len(peaks)))
        grid.add_row("Potencia máxima", f"{pot_max:.1f} dBm")
        grid.add_row("SNR máximo", f"{snr_max:.1f} dB")
        grid.add_row("BW promedio", f"{bw_mean:.2f} kHz")
        grid.add_row("Duty cycle máx.", f"{duty_max * 100:.0f}%")
        grid.add_row("Ajustes AGC", str(agc_adjustments))
        grid.add_row("Bandas", ", ".join(band_names) if band_names else "—")

        return Panel(grid, title="[bold green]RESUMEN[/bold green]", border_style="green")


def _configure_rotating_file_logger(log_cfg: Any) -> None:
    root_logger = logging.getLogger("sentinel.rf")
    if root_logger.handlers:
        return
    root_logger.setLevel(getattr(logging, log_cfg.level.upper(), logging.INFO))
    Path(log_cfg.file).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_cfg.file,
        maxBytes=log_cfg.max_mb * 1_048_576,
        backupCount=log_cfg.backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    root_logger.addHandler(handler)


def _strip_rich_markup(text: str) -> str:
    return _RICH_TAG_PATTERN.sub("", text)


class RFScanner:
    def __init__(self, sentinel: Any, config_path: str | None = None) -> None:
        self._sentinel = sentinel
        self._console: Console = getattr(sentinel, "console", Console())
        self._gp: Any = getattr(sentinel, "gp", None)
        self._cfg: RFConfig = load_config(config_path)

        self._dsp = DSPEngine(self._cfg.dsp, self._cfg.hardware.sample_rate)
        self._renderer = SpectrumRenderer(self._console, self._cfg)
        self._rf_db = RFDatabase(self._cfg.storage.db_path)
        self._signal_db = SignalDB(self._cfg.storage)
        self._csv_exporter = CSVExporter(self._cfg.storage)
        self._sigmf_writer = SigMFWriter(self._cfg.storage)
        self._recorder = RFRecorder(self)
        self._demod: Demodulator | None = None

        self._backend: HardwareBackend | None = None
        self._backend_lock = threading.Lock()

        self._waterfall_history: deque[PsdArray] = deque(maxlen=self._cfg.display.waterfall_rows)
        self._session_signals: deque[Signal] = deque(maxlen=5_000)
        self._session_capture_count: int = 0

        self._dc_remover = DCRemover()
        self._peak_hold_buf = PeakHoldBuffer(avg_frames=8)
        self._signal_tracker = SignalTracker()
        self._agc = AGCController(initial_gain_db=self._cfg.hardware.gain_db)
        self._agc_enabled: bool = False
        self._agc_adjustment_count: int = 0

        _configure_rotating_file_logger(self._cfg.logging)
        self._connect_hardware()

    def _connect_hardware(self) -> None:
        from modules.rf.rf_source import open_backend
        hw_cfg = self._cfg.hardware
        self._backend = open_backend(
            freq_hz=hw_cfg.sample_rate,
            sample_rate=hw_cfg.sample_rate,
            gain=hw_cfg.gain_db,
            ppm=hw_cfg.ppm_correction,
            device_index=hw_cfg.device_index,
        )
        self.hw_name: str = self._backend.hw_name
        self._agc.current_gain_db = hw_cfg.gain_db

        if hw_cfg.bias_tee:
            try:
                self._backend._sdr.set_bias_tee(True)
            except Exception:
                log.debug("bias_tee not supported by this backend")

        is_mock = "Mock" in self.hw_name
        self._emit(
            f"[yellow][!] No physical SDR hardware — {self.hw_name}[/yellow]\n"
            "[dim]    pip install pyrtlsdr  |  https://www.rtl-sdr.com/[/dim]"
            if is_mock
            else f"[green][+] RF backend: {self.hw_name}[/green]"
        )
        log.info("RF backend connected: %s", self.hw_name)

    @property
    def sample_rate(self) -> int:
        return self._cfg.hardware.sample_rate

    @property
    def hw_available(self) -> bool:
        return self._backend is not None

    def set_gain(self, gain: object) -> None:
        if not self.hw_available:
            self._emit("[red][!] No SDR hardware connected.[/red]")
            return
        try:
            resolved = "auto" if str(gain).lower() == "auto" else float(gain)
            self._backend.set_gain(resolved)
            if resolved != "auto":
                self._cfg.hardware.gain_db = float(resolved)
                self._agc.current_gain_db = float(resolved)
            self._emit(f"[green][+] Gain set to {gain} dB[/green]")
            log.info("Gain adjusted to %s dB", gain)
        except Exception as exc:
            self._emit(f"[red][!] Gain adjustment error: {exc}[/red]")

    def set_agc_enabled(self, enabled: bool) -> None:
        self._agc_enabled = enabled
        state = "[green]enabled[/green]" if enabled else "[yellow]disabled[/yellow]"
        self._emit(f"[cyan][RF] AGC {state}[/cyan]")

    def load_iq_file(self, path: str) -> None:
        from modules.rf.rf_source import file_backend
        self._backend = file_backend(path, loop=True)
        self.hw_name = self._backend.hw_name
        self._emit(f"[cyan][RF] IQ loaded from: {path}[/cyan]")

    def configure_tcp_source(self, host: str, port: int = 1234, gain: int = 400) -> None:
        from modules.rf.rf_source import tcp_backend
        try:
            self._backend = tcp_backend(
                host, port,
                freq_hz=self._cfg.hardware.sample_rate,
                sample_rate=self._cfg.hardware.sample_rate,
                gain=gain,
            )
            self.hw_name = self._backend.hw_name
            self._emit(f"[green][+] rtl_tcp connected — {self.hw_name}[/green]")
        except Exception as exc:
            self._emit(f"[red][!] TCP connection error: {exc}[/red]")

    def inject_mock_signal(
        self,
        freq_offset_hz: float,
        power_dbm: float = -60.0,
        mode: str = "tone",
        bw_hz: float = 12_500.0,
    ) -> None:
        from modules.rf.rf_source import _MockBackend, mock_backend
        from modules.rf.rf_mock import SyntheticSignal
        if not isinstance(self._backend, _MockBackend):
            self._backend = mock_backend(self._cfg.hardware.sample_rate)
            self.hw_name = self._backend.hw_name
        self._backend._mock.add_signal(
            SyntheticSignal(freq_offset=freq_offset_hz, power_dbm=power_dbm, mode=mode, bw_hz=bw_hz)
        )

    def _capture_iq(self, freq_hz: float) -> IqArray | None:
        if not self.hw_available:
            self._emit("[red][!] No SDR hardware available.[/red]")
            return None
        with self._backend_lock:
            try:
                self._backend.tune(freq_hz)
                samples = self._backend.read_raw(self._cfg.dsp.samples_per_read)
                if samples is not None:
                    self._session_capture_count += 1
                return samples
            except Exception as exc:
                self._emit(f"[red][!] Capture @ {freq_hz / 1e6:.3f} MHz: {exc}[/red]")
                log.error("IQ capture @ %.3f MHz: %s", freq_hz / 1e6, exc)
                return None

    def _is_rtlsdr_freq_valid(self, freq_mhz: float) -> bool:
        from modules.rf.rf_source import _RTLSDRBackend
        if isinstance(self._backend, _RTLSDRBackend):
            if not (_RTL_FREQ_MIN_MHZ <= freq_mhz <= _RTL_FREQ_MAX_MHZ):
                self._emit(f"[yellow][!] {freq_mhz:.3f} MHz out of RTL-SDR range. Skipped.[/yellow]")
                return False
        return True

    def _get_or_create_demodulator(self) -> Demodulator:
        if self._demod is None:
            self._demod = Demodulator(self._cfg.demod, self.sample_rate)
        return self._demod

    def _run_dsp_pipeline(self, freq_hz: float) -> ScanResult | None:
        samples = self._capture_iq(freq_hz)
        if samples is None:
            return None

        freqs_hz, psd_raw = self._dsp.compute_psd(samples)
        psd_dbm = self._dc_remover.remove(psd_raw)
        self._peak_hold_buf.update(psd_dbm)
        raw_peaks = self._dsp.detect_peaks(freqs_hz, psd_dbm, freq_hz)
        persistent_peaks = self._signal_tracker.update(raw_peaks)
        noise_floor = float(np.median(psd_dbm))

        return freqs_hz, psd_dbm, persistent_peaks, noise_floor

    def _persist_signals(self, signals: list[Signal], scan_id: int) -> None:
        rows = [dict(s.to_dict(), banda=s.banda) for s in signals]
        self._rf_db.insertar_senales_bulk(rows, scan_id)
        self._signal_db.insert_signals_batch(signals)

    def _export_csv_peaks(self, peaks: list[Signal], freq_mhz: float) -> None:
        try:
            filename = self._csv_exporter.export_signals(peaks, freq_mhz, self.hw_name)
            self._emit(f"[green][+] CSV exported → {filename}[/green]")
        except OSError as exc:
            self._emit(f"[red][!] CSV export error: {exc}[/red]")

    def _export_csv_sweep(self, results: list[dict], freq_lo: float, freq_hi: float) -> None:
        try:
            filename = self._csv_exporter.export_sweep(results, freq_lo, freq_hi)
            self._emit(f"[green][+] CSV sweep → {filename}[/green]")
        except OSError as exc:
            self._emit(f"[red][!] CSV sweep export error: {exc}[/red]")

    def _register_evidence(self, freq_mhz: float, peaks: list[Signal], duration_s: float) -> None:
        if not self._gp or not peaks:
            return
        try:
            self._gp.registrar_evidencia(
                "rf_scan",
                f"RF scan {freq_mhz:.3f} MHz: {len(peaks)} signals",
                {
                    "freq_mhz": freq_mhz,
                    "duracion_s": round(duration_s, 1),
                    "hardware": self.hw_name,
                    "senales": [s.to_dict() for s in peaks],
                },
            )
            for s in peaks:
                if not s.banda and s.snr_db > 20:
                    self._gp.registrar_hallazgo(
                        "MEDIO",
                        f"Unclassified signal at {s.freq_mhz:.3f} MHz",
                        (
                            f"Power: {s.potencia:.1f} dBm  SNR: {s.snr_db:.1f} dB  "
                            f"BW: {s.bw_khz:.2f} kHz  "
                            f"Duty: {self._signal_tracker.duty_cycle(s.freq_mhz) * 100:.0f}%"
                        ),
                        "Investigate origin. Possible illicit device.",
                    )
        except Exception as exc:
            log.warning("register_evidence failed: %s", exc)

    def scan_frequency(self, freq_mhz: float, duration_s: int = 10) -> None:
        if not self.hw_available:
            self._emit("[red][!] No SDR hardware available.[/red]")
            return

        freq_hz = freq_mhz * 1e6
        band = identify_band(freq_mhz)

        self._peak_hold_buf.reset()
        self._signal_tracker.reset()
        self._agc_adjustment_count = 0

        self._emit()
        if band:
            color = band.get("color", "white")
            self._emit(
                f"[bold green][RF] {freq_mhz:.4f} MHz — "
                f"[{color}]{band['nombre']}[/{color}]  "
                f"[dim]{band['desc']}[/dim][/bold green]"
            )
        else:
            self._emit(f"[bold green][RF] {freq_mhz:.4f} MHz — Unclassified[/bold green]")

        self._emit(
            f"[dim]  HW: {self.hw_name}  BW: {self.sample_rate / 1e6:.3f} MHz  "
            f"FFT: {self._cfg.dsp.fft_size}pts  Res: {self._dsp.freq_resolution_khz:.2f} kHz/bin  "
            f"AGC: {'ON' if self._agc_enabled else 'OFF'}  Ctrl+C to stop[/dim]\n"
        )

        scan_id = self._rf_db.iniciar_escaneo(
            freq_mhz=freq_mhz,
            hardware=self.hw_name,
            sample_rate=self.sample_rate,
            fft_size=self._cfg.dsp.fft_size,
        )
        self._signal_db.open_session(
            hw_type=self.hw_name,
            sample_rate=self.sample_rate,
            notes=f"scan {freq_mhz:.4f} MHz {duration_s}s",
        )

        t_start = time.monotonic()
        iteration = 0
        all_peaks: list[Signal] = []
        demod = self._get_or_create_demodulator() if self._cfg.demod.mode != "none" else None
        noise_floor = -99.0
        current_peaks: list[Signal] = []
        freqs_hz = psd_dbm = np.empty(0)

        def _build_live_view() -> Group:
            return Group(
                self._renderer.spectrum(
                    freqs_hz, psd_dbm, freq_mhz, current_peaks,
                    self.sample_rate, self.hw_name,
                    peak_hold=self._peak_hold_buf.peak(),
                    avg_psd=self._peak_hold_buf.average(),
                ),
                self._renderer.waterfall(self._waterfall_history, freq_mhz),
                self._renderer.signal_table(current_peaks, self._signal_tracker),
                self._renderer.scan_stats_panel(
                    freq_mhz, iteration, duration_s,
                    time.monotonic() - t_start,
                    len(current_peaks), len(self._session_signals),
                    self._session_capture_count, noise_floor,
                    self._agc.current_gain_db, self._agc_enabled,
                ),
            )

        try:
            with Live(console=self._console, refresh_per_second=4, screen=False) as live:
                while time.monotonic() - t_start < duration_s:
                    pipeline_result = self._run_dsp_pipeline(freq_hz)
                    if pipeline_result is None:
                        break

                    freqs_hz, psd_dbm, current_peaks, noise_floor = pipeline_result
                    all_peaks.extend(current_peaks)
                    self._session_signals.extend(current_peaks)
                    self._waterfall_history.appendleft(psd_dbm.copy())

                    if current_peaks:
                        self._persist_signals(current_peaks, scan_id)

                    if self._agc_enabled:
                        new_gain = self._agc.step(psd_dbm, self._backend)
                        if new_gain is not None:
                            self._agc_adjustment_count += 1

                    if demod:
                        try:
                            audio = demod.demodulate(self._capture_iq(freq_hz) or np.empty(0))
                            if audio is not None and len(audio) > 0:
                                squelch_open = (
                                    not current_peaks
                                    or current_peaks[0].snr_db >= self._cfg.demod.squelch_db
                                )
                                if squelch_open:
                                    demod.play(audio)
                                if self._cfg.demod.save_audio:
                                    ts_str = datetime.now(timezone.utc).strftime("%H%M%S")
                                    demod.save_wav(
                                        audio,
                                        str(self._cfg.storage.iq_path / f"audio_{freq_mhz:.3f}MHz_{ts_str}.wav"),
                                    )
                        except Exception as exc:
                            log.debug("Demodulator error: %s", exc)

                    live.update(_build_live_view())
                    iteration += 1

        except KeyboardInterrupt:
            self._emit("\n[yellow][!] Scan interrupted.[/yellow]")

        finally:
            elapsed = time.monotonic() - t_start
            self._rf_db.finalizar_escaneo(scan_id, elapsed)
            self._signal_db.close_session()

            self._console.print()
            self._console.print(self._renderer.scan_summary(
                freq_mhz, all_peaks, elapsed,
                self.hw_name, iteration,
                self._signal_tracker, self._agc_adjustment_count,
            ))

            if all_peaks:
                self._export_csv_peaks(all_peaks, freq_mhz)
            self._register_evidence(freq_mhz, all_peaks, elapsed)

            if self._cfg.storage.db_retention_days > 0:
                self._rf_db.limpiar_antiguas(self._cfg.storage.db_retention_days)
                self._signal_db.purge_old(self._cfg.storage.db_retention_days)

            log.info(
                "Scan %.3f MHz — %d signals in %.0fs  hw=%s",
                freq_mhz, len(all_peaks), elapsed, self.hw_name,
            )

    def sweep_spectrum(
        self,
        freq_lo_mhz: float,
        freq_hi_mhz: float,
        step_mhz: float = 1.0,
    ) -> None:
        if not self.hw_available:
            self._emit("[red][!] No SDR hardware available.[/red]")
            return

        freq_points = np.arange(freq_lo_mhz, freq_hi_mhz + step_mhz * 0.5, step_mhz)
        self._emit(
            f"\n[bold green][RF] Sweep: "
            f"{freq_lo_mhz:.1f} to {freq_hi_mhz:.1f} MHz  "
            f"step={step_mhz:.3f} MHz  {len(freq_points)} points[/bold green]\n"
        )

        results: list[dict[str, Any]] = []
        occupancy_samples: dict[float, list[float]] = defaultdict(list)

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self._console,
            transient=True,
        ) as progress:
            task = progress.add_task("Sweeping...", total=len(freq_points))

            try:
                for freq in freq_points:
                    freq_f = float(freq)
                    if not self._is_rtlsdr_freq_valid(freq_f):
                        progress.advance(task)
                        continue

                    pipeline_result = self._run_dsp_pipeline(freq_f * 1e6)
                    if pipeline_result is None:
                        break

                    _, psd_dbm, _, _ = pipeline_result
                    noise_floor = float(np.median(psd_dbm))
                    peak_power = float(np.max(psd_dbm))
                    snr = peak_power - noise_floor
                    band = identify_band(freq_f)
                    freq_key = round(freq_f, 3)

                    for _ in range(3):
                        occupancy_result = self._run_dsp_pipeline(freq_f * 1e6)
                        if occupancy_result:
                            _, occ_psd, _, _ = occupancy_result
                            occupancy_samples[freq_key].append(float(np.max(occ_psd)) - noise_floor)

                    occ_window = occupancy_samples.get(freq_key, [])
                    occupancy_pct = (
                        sum(1 for v in occ_window if v >= self._cfg.dsp.snr_threshold)
                        / len(occ_window) * 100
                        if occ_window else 0.0
                    )

                    results.append({
                        "freq_mhz": freq_key,
                        "pot_max": round(peak_power, 1),
                        "piso": round(noise_floor, 1),
                        "snr": round(snr, 1),
                        "banda": band,
                        "ocupacion_pct": round(occupancy_pct, 1),
                    })

                    band_label = band["nombre"] if band else "—"
                    progress.update(
                        task, advance=1,
                        description=f"[bold green]{freq_f:.2f} MHz  {snr:+.0f} dB SNR  {band_label[:18]}",
                    )

            except KeyboardInterrupt:
                self._emit("\n[yellow][!] Sweep interrupted.[/yellow]")

        if results:
            self._console.print(self._renderer.sweep_map(results))
            self._export_csv_sweep(results, freq_lo_mhz, freq_hi_mhz)
            self._rf_db.insertar_barrido(
                freq_ini=freq_lo_mhz, freq_fin=freq_hi_mhz,
                paso_mhz=step_mhz, hardware=self.hw_name,
                resultados=results,
            )
            active_count = sum(1 for r in results if r["snr"] >= self._cfg.dsp.snr_threshold)
            self._signal_db.insert_sweep(
                freq_ini=freq_lo_mhz, freq_fin=freq_hi_mhz,
                paso=step_mhz, puntos=len(results), activas=active_count,
            )
            if self._gp:
                try:
                    self._gp.registrar_evidencia(
                        "rf_sweep",
                        f"RF sweep {freq_lo_mhz:.0f}–{freq_hi_mhz:.0f} MHz: {len(results)} points",
                        {"ini_mhz": freq_lo_mhz, "fin_mhz": freq_hi_mhz,
                         "paso_mhz": step_mhz, "puntos": len(results), "hardware": self.hw_name},
                    )
                except Exception as exc:
                    log.warning("gp sweep evidence failed: %s", exc)

        log.info(
            "Sweep %.1f–%.1f MHz step=%.3f — %d points hw=%s",
            freq_lo_mhz, freq_hi_mhz, step_mhz, len(results), self.hw_name,
        )

    def scan_known_bands(self) -> None:
        if not self.hw_available:
            self._emit("[red][!] No SDR hardware available.[/red]")
            return

        band_list = [
            {
                "nombre": name,
                "tipo": band_type,
                "desc": desc,
                "color": COLORES_TIPO.get(band_type, "dim"),
                "freq_min": fmin,
                "freq_max": fmax,
            }
            for fmin, fmax, name, band_type, desc, _ in BANDAS_RF
        ]

        self._emit(f"\n[bold green][RF] Scanning {len(band_list)} known bands...[/bold green]\n")
        results: list[dict[str, Any]] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]{task.description}"),
            BarColumn(bar_width=44),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self._console,
            transient=True,
        ) as progress:
            task = progress.add_task("Scanning bands...", total=len(band_list))
            try:
                for band in band_list:
                    center_freq = (band["freq_min"] + band["freq_max"]) / 2.0
                    if not self._is_rtlsdr_freq_valid(center_freq):
                        progress.advance(task)
                        continue

                    pipeline_result = self._run_dsp_pipeline(center_freq * 1e6)
                    if pipeline_result is None:
                        break

                    _, psd_dbm, _, _ = pipeline_result
                    noise_floor = float(np.median(psd_dbm))
                    peak_power = float(np.max(psd_dbm))
                    snr = peak_power - noise_floor

                    results.append({
                        "freq_mhz": round(center_freq, 3),
                        "pot_max": round(peak_power, 1),
                        "piso": round(noise_floor, 1),
                        "snr": round(snr, 1),
                        "banda": band,
                        "ocupacion_pct": 0.0,
                    })
                    progress.update(
                        task, advance=1,
                        description=f"[bold green]{band['nombre'][:26]:<26} {center_freq:>9.3f} MHz",
                    )

            except KeyboardInterrupt:
                self._emit("\n[yellow][!] Band scan interrupted.[/yellow]")

        if results:
            self._console.print(self._renderer.sweep_map(results))
            self._export_csv_sweep(results, 0.0, 0.0)
            if self._gp:
                try:
                    self._gp.registrar_evidencia(
                        "rf_bands_scan",
                        f"Band scan: {len(results)} measurements",
                        {"hardware": self.hw_name, "bandas": len(results)},
                    )
                except Exception as exc:
                    log.warning("gp bands scan evidence failed: %s", exc)

        log.info("Band scan: %d measurements hw=%s", len(results), self.hw_name)

    def show_db_statistics(self) -> None:
        rf_stats = self._rf_db.estadisticas()
        sig_stats = self._signal_db.stats()
        grid = Table.grid(padding=(0, 3))
        grid.add_column(style="dim green", justify="right", min_width=22)
        grid.add_column(style="white")
        grid.add_row("[bold]RFDatabase[/bold]", "")
        for k, v in rf_stats.items():
            grid.add_row(k.replace("_", " ").title(), str(v) if v is not None else "—")
        grid.add_row("", "")
        grid.add_row("[bold]SignalDB[/bold]", "")
        for k, v in sig_stats.items():
            grid.add_row(k.replace("_", " ").title(), str(v) if v is not None else "—")
        self._console.print(Panel(grid, title="[bold green]DB STATISTICS[/bold green]", border_style="green"))

    def show_top_signals(self, n: int = 10) -> None:
        rows = self._rf_db.top_senales(n)
        table = Table(box=box.SIMPLE_HEAD, header_style="bold green", show_edge=False, expand=True)
        table.add_column("Frecuencia", style="cyan", min_width=14)
        table.add_column("Potencia", justify="right", min_width=11)
        table.add_column("SNR", justify="right", min_width=8)
        table.add_column("BW", justify="right", min_width=9)
        table.add_column("Mod.", min_width=10)
        table.add_column("Banda", min_width=16)
        table.add_column("Timestamp", style="dim", min_width=22)
        for r in rows:
            table.add_row(
                f"{r['freq_mhz']:.4f} MHz",
                f"{r['potencia']:.1f} dBm",
                f"{r['snr_db']:.1f} dB",
                f"{r.get('bw_khz', 0):.2f} kHz",
                r.get("mod_hint") or "—",
                r.get("banda") or "—",
                r.get("timestamp", "")[:19],
            )
        self._console.print(Panel(table, title=f"[bold green]TOP {n} SIGNALS[/bold green]", border_style="green"))

    def show_active_frequencies(self, snr_min: float = 10.0, hours: int = 24) -> None:
        rows = self._rf_db.frecuencias_activas(snr_min=snr_min, horas=hours)
        if not rows:
            self._emit(f"[dim]No active frequencies in the last {hours}h with SNR >= {snr_min} dB.[/dim]")
            return
        table = Table(box=box.SIMPLE_HEAD, header_style="bold green", show_edge=False, expand=True)
        table.add_column("Frecuencia", style="cyan", min_width=14)
        table.add_column("Detecciones", justify="right", min_width=12)
        table.add_column("SNR máx", justify="right", min_width=9)
        table.add_column("Pot. media", justify="right", min_width=11)
        table.add_column("Banda", min_width=16)
        for r in rows:
            table.add_row(
                f"{r['freq_mhz']:.3f} MHz",
                str(r["detecciones"]),
                f"{r['snr_max']:.1f} dB",
                f"{r.get('pot_media', 0):.1f} dBm",
                r.get("banda") or "—",
            )
        self._console.print(Panel(
            table,
            title=f"[bold green]ACTIVE FREQUENCIES (last {hours}h  SNR>={snr_min}dB)[/bold green]",
            border_style="green",
        ))

    def record_iq(self, freq_mhz: float, duration_s: int = 10, fmt: str = "sigmf") -> None:
        if not self.hw_available:
            self._emit("[red][!] No SDR hardware available.[/red]")
            return

        freq_hz = freq_mhz * 1e6

        if fmt != "sigmf":
            self._recorder.grabar(
                freq_mhz=freq_mhz,
                duracion_seg=duration_s,
                sample_rate=self.sample_rate,
                formato=fmt,
            )
            return

        recording = self._sigmf_writer.open(
            freq_hz=freq_hz,
            sample_rate=self.sample_rate,
            hw_type=self.hw_name,
            notes=f"Field recording {freq_mhz:.3f} MHz",
        )
        self._emit(
            f"[bold cyan][RF] Recording {freq_mhz:.3f} MHz · "
            f"{duration_s}s · SigMF streaming[/bold cyan]"
        )

        t_start = time.monotonic()
        total_samples = 0

        with Progress(
            SpinnerColumn(),
            BarColumn(bar_width=30),
            TextColumn("[bold cyan]{task.description}"),
            TimeElapsedColumn(),
            console=self._console,
            transient=True,
        ) as progress:
            task = progress.add_task(f"Recording {freq_mhz:.3f} MHz", total=duration_s)
            with recording:
                while time.monotonic() - t_start < duration_s:
                    block = self._capture_iq(freq_hz)
                    if block is None:
                        break
                    recording.write(block)
                    total_samples += len(block)
                    elapsed = time.monotonic() - t_start
                    size_mb = recording.data_path.stat().st_size / 1e6
                    progress.update(
                        task,
                        completed=elapsed,
                        description=(
                            f"{freq_mhz:.3f} MHz  "
                            f"{total_samples:,} samples  "
                            f"{size_mb:.1f} MB"
                        ),
                    )

        size_mb = recording.data_path.stat().st_size / 1e6
        actual_duration = total_samples / self.sample_rate
        self._signal_db.register_iq(
            freq_mhz=freq_mhz,
            duration_s=actual_duration,
            sample_rate=self.sample_rate,
            hw_type=self.hw_name,
            filename=str(recording.data_path),
            size_mb=round(size_mb, 2),
        )
        self._emit(
            f"[green][+] IQ saved → {recording.data_path.name}  "
            f"({actual_duration:.1f}s  {size_mb:.1f} MB)[/green]"
        )
        log.info("IQ recorded: %s  %.1fs  %.1fMB", recording.data_path.name, actual_duration, size_mb)

    def replay_iq(self, filepath: str, mode: str = "wfm") -> None:
        self._recorder.reproducir(filepath, modo=mode, sample_rate=self.sample_rate)

    def show_hardware_status(self) -> None:
        rf_stats = self._rf_db.estadisticas()
        sig_stats = self._signal_db.stats()
        grid = Table.grid(padding=(0, 3))
        grid.add_column(style="dim green", justify="right", min_width=24)
        grid.add_column(style="white")
        grid.add_row("Hardware", self.hw_name)
        grid.add_row("Backend type", type(self._backend).__name__ if self._backend else "N/A")
        grid.add_row("Sample rate", f"{self.sample_rate / 1e6:.3f} MHz")
        grid.add_row("Gain", f"{self._agc.current_gain_db:.1f} dB")
        grid.add_row("AGC", "[green]ON[/green]" if self._agc_enabled else "[dim]OFF[/dim]")
        grid.add_row("PPM correction", str(self._cfg.hardware.ppm_correction))
        grid.add_row("FFT size", str(self._cfg.dsp.fft_size))
        grid.add_row("DSP window", self._cfg.dsp.window)
        grid.add_row("SNR threshold", f"{self._cfg.dsp.snr_threshold} dB")
        grid.add_row("Resolution", f"{self._dsp.freq_resolution_khz:.2f} kHz/bin")
        grid.add_row("Min. persistence", f"{SignalTracker.MIN_CONSECUTIVE_FRAMES} frames")
        grid.add_row("Demod mode", self._cfg.demod.mode)
        grid.add_row("DB path", str(self._cfg.storage.db_path))
        grid.add_row("Session captures", str(self._session_capture_count))
        grid.add_row("Session signals", str(len(self._session_signals)))
        grid.add_row("─" * 22, "─" * 18)
        grid.add_row("DB total signals", str(rf_stats.get("total_senales", 0)))
        grid.add_row("DB scans", str(rf_stats.get("escaneos", 0)))
        grid.add_row("SignalDB sessions", str(sig_stats.get("sessions", 0)))
        grid.add_row("IQ recordings", str(sig_stats.get("iq_files", 0)))
        grid.add_row("DB size", f"{sig_stats.get('db_size_mb', 0):.2f} MB")
        self._console.print(Panel(grid, title="[bold green]RF SCANNER STATUS[/bold green]", border_style="green"))

    def interactive_menu(self) -> None:
        self._console.print()
        self._console.print(Panel(
            "[bold green]RF SCANNER — " + self.hw_name + "[/bold green]\n\n"
            " [green][1][/green]  Scan specific frequency\n"
            " [green][2][/green]  Spectrum sweep (range)\n"
            " [green][3][/green]  Scan known bands\n"
            " [green][4][/green]  Adjust gain\n"
            " [green][5][/green]  Toggle AGC\n"
            " [green][6][/green]  View session signals\n"
            " [green][7][/green]  Hardware status\n"
            " [green][8][/green]  Record IQ\n"
            " [green][9][/green]  Replay IQ\n"
            " [green][10][/green] Active frequencies (DB)\n"
            " [green][11][/green] Top signals (DB)",
            border_style="green",
            title="[bold green]RF SCANNER[/bold green]",
        ))

        option = self._console.input("[bold green][?] Option: [/bold green]").strip()

        menu_handlers: dict[str, Any] = {
            "1": self._handle_menu_scan_frequency,
            "2": self._handle_menu_sweep,
            "3": self.scan_known_bands,
            "4": self._handle_menu_set_gain,
            "5": lambda: self.set_agc_enabled(not self._agc_enabled),
            "6": lambda: self._console.print(
                self._renderer.signal_table(list(self._session_signals)[-50:], self._signal_tracker)
            ),
            "7": self.show_hardware_status,
            "8": self._handle_menu_record_iq,
            "9": self._handle_menu_replay_iq,
            "10": self._handle_menu_active_frequencies,
            "11": self._handle_menu_top_signals,
        }

        handler = menu_handlers.get(option)
        if handler:
            handler()
        else:
            self._emit("[yellow][!] Unrecognized option.[/yellow]")

    def _handle_menu_scan_frequency(self) -> None:
        freq_str = self._console.input("[bold cyan][?] Frequency (MHz): [/bold cyan]").strip()
        dur_str = self._console.input("[bold cyan][?] Duration seconds [10]: [/bold cyan]").strip()
        try:
            self.scan_frequency(float(freq_str), int(dur_str) if dur_str else 10)
        except ValueError:
            self._emit("[red][!] Invalid value.[/red]")

    def _handle_menu_sweep(self) -> None:
        lo_str = self._console.input("[bold cyan][?] Start freq. (MHz): [/bold cyan]").strip()
        hi_str = self._console.input("[bold cyan][?] End freq. (MHz): [/bold cyan]").strip()
        step_str = self._console.input("[bold cyan][?] Step MHz [1.0]: [/bold cyan]").strip()
        try:
            self.sweep_spectrum(float(lo_str), float(hi_str), float(step_str) if step_str else 1.0)
        except ValueError:
            self._emit("[red][!] Invalid values.[/red]")

    def _handle_menu_set_gain(self) -> None:
        gain_str = self._console.input(
            "[bold cyan][?] Gain dB (0-49.6, 'auto'): [/bold cyan]"
        ).strip()
        try:
            self.set_gain("auto" if gain_str.lower() == "auto" else float(gain_str))
        except ValueError:
            self._emit("[red][!] Invalid value.[/red]")

    def _handle_menu_record_iq(self) -> None:
        freq_str = self._console.input("[bold cyan][?] Frequency to record (MHz): [/bold cyan]").strip()
        dur_str = self._console.input("[bold cyan][?] Duration seconds [10]: [/bold cyan]").strip()
        fmt_str = self._console.input("[bold cyan][?] Format (sigmf/raw) [sigmf]: [/bold cyan]").strip() or "sigmf"
        try:
            self.record_iq(float(freq_str), int(dur_str) if dur_str else 10, fmt_str)
        except ValueError:
            self._emit("[red][!] Invalid value.[/red]")

    def _handle_menu_replay_iq(self) -> None:
        filepath = self._console.input("[bold cyan][?] IQ file (path): [/bold cyan]").strip()
        mode = self._console.input("[bold cyan][?] Demod mode (wfm/nfm/am/usb/lsb) [wfm]: [/bold cyan]").strip() or "wfm"
        self.replay_iq(filepath, mode)

    def _handle_menu_active_frequencies(self) -> None:
        snr_str = self._console.input("[bold cyan][?] Min SNR dB [10]: [/bold cyan]").strip()
        hrs_str = self._console.input("[bold cyan][?] Hours back [24]: [/bold cyan]").strip()
        try:
            self.show_active_frequencies(
                snr_min=float(snr_str) if snr_str else 10.0,
                hours=int(hrs_str) if hrs_str else 24,
            )
        except ValueError:
            self._emit("[red][!] Invalid value.[/red]")

    def _handle_menu_top_signals(self) -> None:
        n_str = self._console.input("[bold cyan][?] How many signals [10]: [/bold cyan]").strip()
        try:
            self.show_top_signals(int(n_str) if n_str else 10)
        except ValueError:
            self._emit("[red][!] Invalid value.[/red]")

    def close(self) -> None:
        if self._demod:
            try:
                self._demod.stop_audio()
            except Exception:
                pass

        if self._backend is not None:
            try:
                self._backend.close()
                self._emit("[green][+] SDR disconnected.[/green]")
                log.info("RF backend closed")
            except Exception as exc:
                self._emit(f"[yellow][!] Error closing RF backend: {exc}[/yellow]")
            finally:
                self._backend = None

        for storage_obj in (self._signal_db, self._rf_db):
            try:
                getattr(storage_obj, "close_session", lambda: None)()
                getattr(storage_obj, "cerrar", lambda: None)()
            except Exception:
                pass

    def __enter__(self) -> RFScanner:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _emit(self, msg: str = "") -> None:
        if self._console:
            self._console.print(msg)
        else:
            print(_strip_rich_markup(msg))
