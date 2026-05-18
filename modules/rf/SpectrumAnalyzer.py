from __future__ import annotations

import csv
import json
import logging
import os
import queue
import select
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from core.platform import PlatformInfo, detect as detect_platform
from core.keybindings import BandPreset, KeyBindings, load as load_keys
from modules.rf.rf_mock import MockSDRManager, SyntheticSignal

if TYPE_CHECKING:
    from Main import ApexSentinel

log = logging.getLogger("sentinel.rf.spectrum")

_SDR_CLASS  = None
_SDR_DRIVER = "MockSDR"
try:
    from rtlsdr import RtlSdr as _RtlSdr
    _SDR_CLASS  = _RtlSdr
    _SDR_DRIVER = "RTL-SDR"
except ImportError:
    pass

_SUB          = " ▁▂▃▄▅▆▇█"
_PEAK_CHR     = "▪"
_MARKER_CHR   = "▼"
_THRESH_CHR   = "╌"
_FREQ_MIN_MHZ =  24.0
_FREQ_MAX_MHZ = 1766.0
_EVIDENCE_DIR = Path("data/evidence/rf")

_FKEY_MAP: dict[bytes, str] = {
    b"P": "F1",  b"Q": "F2",  b"R": "F3",  b"S": "F4",
    b"11~": "F1", b"12~": "F2", b"13~": "F3", b"14~": "F4",
    b"15~": "F5", b"17~": "F6", b"18~": "F7", b"19~": "F8",
    b"20~": "F9", b"21~": "F10",
    b"A": "UP",  b"B": "DOWN", b"C": "RIGHT", b"D": "LEFT",
}


# ══════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════

@dataclass
class SAConfig:
    center_mhz:     float = 433.920
    span_mhz:       float = 2.0
    rbw_khz:        float = 12.5
    ref_dbm:        float = -20.0
    floor_dbm:      float = -110.0
    gain:           str   = "auto"
    avg_frames:     int   = 1
    peak_hold:      bool  = False
    display_width:  int   = 120
    display_height: int   = 14
    sample_rate:    int   = 2_048_000
    band_label:     str   = ""
    # v2: corrección y detección
    ppm_offset:     float = 0.0     # PPM de error del reloj RTL-SDR
    threshold_dbm:  float = -80.0   # umbral de detección de señales
    waterfall_h:    int   = 8       # filas del waterfall
    waterfall_on:   bool  = True    # mostrar waterfall
    show_labels:    bool  = True    # etiquetar picos detectados
    record_wf:      bool  = False   # grabar frames a disco

    def fft_size(self) -> int:
        raw = int(1.5 * self.sample_rate / (self.rbw_khz * 1_000))
        n = 1
        while n < raw:
            n <<= 1
        return max(256, min(n, 65_536))

    def rbw_actual_khz(self) -> float:
        return 1.5 * self.sample_rate / (self.fft_size() * 1_000)

    def freq_start_mhz(self) -> float:
        return (self.center_mhz - self.span_mhz / 2) * (1 + self.ppm_offset / 1e6)

    def freq_end_mhz(self) -> float:
        return (self.center_mhz + self.span_mhz / 2) * (1 + self.ppm_offset / 1e6)

    def apply_ppm(self, freq_mhz: float) -> float:
        return freq_mhz * (1 + self.ppm_offset / 1e6)

    @classmethod
    def from_platform(cls, info: PlatformInfo, kb: KeyBindings) -> SAConfig:
        sc   = info.screen
        cols = kb.display_cols if kb.display_cols > 0 else sc.spectrum_width
        # Repartir filas: fijas ~14 (header+axis+bar+status+ctrl+bordes)
        # variables = rows - 14 → 2/3 espectro, 1/3 waterfall
        var  = max(16, sc.rows - 14)
        wf_h = max(4, min(10, var // 3))
        sp_h = max(8, var - wf_h)
        if kb.display_rows > 0:
            sp_h = kb.display_rows
        return cls(display_width=cols, display_height=sp_h, waterfall_h=wf_h)


# ══════════════════════════════════════════════════════════════════════
# MARCADORES Y SEÑALES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class Marker:
    name:      str
    freq_mhz:  float = 0.0
    power_dbm: float = 0.0
    active:    bool  = False


@dataclass
class _DetectedSignal:
    bin_idx:   int
    freq_mhz:  float
    power_dbm: float
    snr_db:    float
    bw_khz:    float


# ══════════════════════════════════════════════════════════════════════
# BUFFER DE FRAMES — peak hold + promedio
# ══════════════════════════════════════════════════════════════════════

class FrameBuffer:

    def __init__(self, max_frames: int = 64) -> None:
        self._frames: list[np.ndarray] = []
        self._peak:   np.ndarray | None = None
        self._max:    int = max_frames

    def push(self, psd: np.ndarray) -> None:
        self._frames.append(psd.copy())
        if len(self._frames) > self._max:
            self._frames.pop(0)
        if self._peak is None or len(self._peak) != len(psd):
            self._peak = psd.copy()
        else:
            np.maximum(self._peak, psd, out=self._peak)

    def average(self, n: int) -> np.ndarray | None:
        if not self._frames:
            return None
        return np.mean(self._frames[-n:] if n > 0 else self._frames, axis=0)

    def peak(self) -> np.ndarray | None:
        return self._peak.copy() if self._peak is not None else None

    def clear(self) -> None:
        self._frames.clear()
        self._peak = None


# ══════════════════════════════════════════════════════════════════════
# WATERFALL BUFFER — historia de frames para display y grabación
# ══════════════════════════════════════════════════════════════════════

class _WaterfallBuffer:

    def __init__(self, h: int = 8) -> None:
        self._h:    int = h
        self._rows: deque[np.ndarray] = deque(maxlen=h)
        # Grabación en memoria
        self._rec:  list[tuple[float, np.ndarray]] = []
        self._recording = False

    def push(self, psd: np.ndarray, ts: float) -> None:
        self._rows.appendleft(psd.copy())   # más reciente al frente
        if self._recording:
            self._rec.append((ts, psd.copy()))

    def rows(self) -> list[np.ndarray]:
        return list(self._rows)

    def start_recording(self) -> None:
        self._rec.clear()
        self._recording = True

    def stop_recording(self) -> list[tuple[float, np.ndarray]]:
        self._recording = False
        data = list(self._rec)
        self._rec.clear()
        return data

    def clear(self) -> None:
        self._rows.clear()
        self._rec.clear()

    @property
    def is_recording(self) -> bool:
        return self._recording


# ══════════════════════════════════════════════════════════════════════
# DETECTOR DE SEÑALES — picos sobre umbral con estimación de BW y SNR
# ══════════════════════════════════════════════════════════════════════

class _SignalDetector:

    @staticmethod
    def detect(
        psd_db:        np.ndarray,
        freqs_mhz:     np.ndarray,
        noise_floor:   float,
        threshold_dbm: float,
        min_spacing:   int = 5,
        max_signals:   int = 8,
    ) -> list[_DetectedSignal]:
        signals: list[_DetectedSignal] = []
        n = len(psd_db)

        for i in range(min_spacing, n - min_spacing):
            if psd_db[i] < threshold_dbm:
                continue
            # Máximo local
            window = psd_db[i - min_spacing: i + min_spacing + 1]
            if psd_db[i] < window.max():
                continue

            # Ancho de banda −3 dB
            lo, hi = i, i
            thr_3db = psd_db[i] - 3.0
            while lo > 0 and psd_db[lo] > thr_3db:
                lo -= 1
            while hi < n - 1 and psd_db[hi] > thr_3db:
                hi += 1
            bw_khz = max(0.1, (freqs_mhz[hi] - freqs_mhz[lo]) * 1_000)

            signals.append(_DetectedSignal(
                bin_idx   = i,
                freq_mhz  = float(freqs_mhz[i]),
                power_dbm = float(psd_db[i]),
                snr_db    = float(psd_db[i] - noise_floor),
                bw_khz    = bw_khz,
            ))

        signals.sort(key=lambda s: s.power_dbm, reverse=True)
        return signals[:max_signals]


# ══════════════════════════════════════════════════════════════════════
# TECLADO — raw mode, flechas, F-keys
# ══════════════════════════════════════════════════════════════════════

class _KeyReader(threading.Thread):

    def __init__(self) -> None:
        super().__init__(daemon=True, name="sa-keyreader")
        self._q:    queue.Queue[str] = queue.Queue()
        self._stop: threading.Event  = threading.Event()

    def run(self) -> None:
        if not sys.stdin.isatty():
            return
        try:
            import termios, tty  # noqa: PLC0415
            fd  = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setraw(fd)
            try:
                self._loop(fd)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except (ImportError, Exception):
            pass

    def _loop(self, fd: int) -> None:
        while not self._stop.is_set():
            ready, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not ready:
                continue
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                self._q.put(self._read_escape(fd))
            else:
                decoded = ch.decode("utf-8", errors="ignore")
                self._q.put("CTRL_C" if decoded == "\x03" else decoded)

    def _read_escape(self, fd: int) -> str:
        def _r(t: float = 0.05) -> bytes:
            rdy, _, _ = select.select([sys.stdin], [], [], t)
            return os.read(fd, 1) if rdy else b""

        ch2 = _r()
        if not ch2:
            return "ESC"
        if ch2 == b"O":
            return _FKEY_MAP.get(_r(), "ESC")
        if ch2 == b"[":
            seq = b""
            for _ in range(6):
                c = _r(0.03)
                if not c:
                    break
                seq += c
                if c.isalpha() or c == b"~":
                    break
            return _FKEY_MAP.get(seq, "ESC")
        return "ESC"

    def get(self) -> str | None:
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None

    def stop(self) -> None:
        self._stop.set()


# ══════════════════════════════════════════════════════════════════════
# ADAPTADOR SDR — interfaz uniforme hardware / MockSDR
# ══════════════════════════════════════════════════════════════════════

class _SDRAdapter:

    def __init__(self, cfg: SAConfig) -> None:
        self._cfg   = cfg
        self._hw    = None
        self._mock: MockSDRManager | None = None
        self._toff: float = 0.0
        self.hw_name = "MockSDR"
        self._init()

    def _init(self) -> None:
        if _SDR_CLASS is not None:
            try:
                sdr             = _SDR_CLASS()
                sdr.sample_rate = self._cfg.sample_rate
                sdr.center_freq = int(self._cfg.center_mhz * 1e6)
                sdr.gain        = self._cfg.gain
                self._hw        = sdr
                self.hw_name    = f"{_SDR_DRIVER} · {self._cfg.sample_rate/1e6:.2f} MSPS"
                return
            except Exception as exc:
                log.warning("Hardware SDR no disponible: %s — MockSDR activo", exc)

        self._mock   = MockSDRManager(sample_rate=self._cfg.sample_rate)
        self.hw_name = f"MockSDR · {self._cfg.sample_rate/1e6:.2f} MSPS"
        for sig in (
            SyntheticSignal(freq_offset= 200_000, power_dbm=-44, mode="nfm", bw_hz=12_500),
            SyntheticSignal(freq_offset=-300_000, power_dbm=-58, mode="wfm", bw_hz=200_000),
            SyntheticSignal(freq_offset= 500_000, power_dbm=-72, mode="tone", bw_hz=500),
            SyntheticSignal(freq_offset=-700_000, power_dbm=-81, mode="tone", bw_hz=1_000),
        ):
            self._mock.add_signal(sig)

    def tune(self, mhz: float) -> None:
        if self._hw is not None:
            self._hw.center_freq = int(mhz * 1e6)

    def set_gain(self, gain: str | float) -> None:
        if self._hw is not None:
            self._hw.gain = gain
        self._cfg.gain = str(gain)

    def read_iq(self, n: int) -> np.ndarray:
        if self._hw is not None:
            return np.array(self._hw.read_samples(n), dtype=np.complex64)
        assert self._mock is not None
        iq = self._mock.capture(int(self._cfg.center_mhz * 1e6), n, t_offset=self._toff)
        self._toff += n / self._cfg.sample_rate
        return iq

    def close(self) -> None:
        if self._hw is not None:
            try:
                self._hw.close()
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════
# FRAME — resultado de un ciclo de adquisición
# ══════════════════════════════════════════════════════════════════════

@dataclass
class _SpectrumFrame:
    freqs_mhz:   np.ndarray
    powers_dbm:  np.ndarray
    noise_floor: float
    peak_freq:   float
    peak_power:  float
    fps:         float
    ts:          str
    detected:    list[_DetectedSignal] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════════════
# RENDERER
# ══════════════════════════════════════════════════════════════════════

class _Renderer:

    def __init__(self, cfg: SAConfig, info: PlatformInfo) -> None:
        self._cfg  = cfg
        self._info = info

    def render(
        self,
        frame:   _SpectrumFrame,
        buf:     FrameBuffer,
        wf_buf:  _WaterfallBuffer,
        markers: list[Marker],
        hw_name: str,
        kb:      KeyBindings,
    ) -> Panel:
        cfg = self._cfg
        W   = cfg.display_width
        H   = cfg.display_height

        # Interpolar PSD al ancho de display
        powers = _interp(frame.powers_dbm, W)
        peak_psd = None
        if cfg.peak_hold:
            ph = buf.peak()
            if ph is not None:
                peak_psd = _interp(ph, W)

        # Posición de marcadores
        mcols: dict[int, Marker] = {}
        for m in markers:
            if not m.active:
                continue
            rel = (m.freq_mhz - cfg.freq_start_mhz()) / max(cfg.span_mhz, 1e-9)
            mcols[int(np.clip(rel * W, 0, W - 1))] = m

        # Posición de señales detectadas
        det_cols: dict[int, _DetectedSignal] = {}
        if cfg.show_labels:
            for s in frame.detected:
                rel = (s.freq_mhz - cfg.freq_start_mhz()) / max(cfg.span_mhz, 1e-9)
                col = int(np.clip(rel * W, 0, W - 1))
                det_cols[col] = s

        # Fila del umbral en el display
        thresh_row = int(
            (cfg.threshold_dbm - cfg.floor_dbm)
            / max(cfg.ref_dbm - cfg.floor_dbm, 1)
            * H
        )

        body = Text()

        # ── Encabezado ────────────────────────────────────────────────
        hdr = Text(justify="center")
        if cfg.band_label:
            hdr.append(f"[{cfg.band_label}]  ", style="bold yellow")
        hdr.append("CTR ", style="dim")
        hdr.append(f"{cfg.center_mhz:.3f} MHz", style="bold cyan")
        if cfg.ppm_offset != 0:
            hdr.append(f" ({cfg.ppm_offset:+.1f}ppm)", style="dim yellow")
        hdr.append("  SPAN ", style="dim")
        hdr.append(f"{cfg.span_mhz:.3f} MHz", style="bold white")
        hdr.append("  RBW ", style="dim")
        hdr.append(f"{cfg.rbw_actual_khz():.1f} kHz", style="bold white")
        hdr.append("  REF ", style="dim")
        hdr.append(f"{cfg.ref_dbm:.0f}", style="bold white")
        hdr.append("  THR ", style="dim")
        hdr.append(f"{cfg.threshold_dbm:.0f} dBm", style="bold yellow")
        hdr.append("  GAIN ", style="dim")
        hdr.append(cfg.gain, style="bold white")
        hdr.append(f"  {frame.fps:.1f}fps", style="dim")
        if wf_buf.is_recording:
            hdr.append("  [REC]", style="bold red")
        body.append_text(hdr)
        body.append("\n")

        # ── Etiquetas de señales detectadas ───────────────────────────
        if cfg.show_labels and frame.detected:
            lbl_line = Text("       ")
            prev_end  = 0
            for col in sorted(det_cols):
                s   = det_cols[col]
                txt = f"{s.freq_mhz:.2f}"
                pad = max(0, col - prev_end)
                lbl_line.append(" " * pad)
                lbl_line.append(txt, style="bold yellow")
                prev_end = col + len(txt)
            lbl_line.append("\n")
            body.append_text(lbl_line)

        # ── Línea de marcadores ───────────────────────────────────────
        mline = Text("       ")
        for c in range(W):
            m = mcols.get(c)
            mline.append(_MARKER_CHR if m else " ",
                         style="bold yellow" if m else "")
        body.append_text(mline)
        body.append("\n")

        # ── Espectro con línea de umbral integrada ────────────────────
        for row in range(H - 1, -1, -1):
            db = cfg.floor_dbm + (row / H) * (cfg.ref_dbm - cfg.floor_dbm)
            body.append(f"{db:>6.0f} │", style="dim green")
            for col in range(W):
                ch, st = _cell(powers[col], row, H, cfg.ref_dbm, cfg.floor_dbm)
                # Peak hold
                if ch == " " and peak_psd is not None:
                    pch, _ = _cell(peak_psd[col], row, H, cfg.ref_dbm, cfg.floor_dbm)
                    if pch != " ":
                        ch, st = _PEAK_CHR, "dim white"
                # Línea de umbral
                if ch == " " and row == thresh_row:
                    ch, st = _THRESH_CHR, "dim yellow"
                body.append(ch, style=st)
            body.append("\n")

        body.append("       └" + "─" * W + "\n", style="dim green")
        body.append("        " + _freq_axis(cfg.freq_start_mhz(), cfg.freq_end_mhz(), W))
        body.append("\n")

        # ── Waterfall ─────────────────────────────────────────────────
        if cfg.waterfall_on:
            wf_rows = wf_buf.rows()
            body.append("  WF   │", style="dim")
            body.append("─" * W + "│\n", style="dim")
            for wrow in wf_rows[:cfg.waterfall_h]:
                body.append("       │", style="dim")
                interp = _interp(wrow, W)
                for val in interp:
                    body.append("█", style=_wf_style(val, cfg.threshold_dbm))
                body.append("│\n", style="dim")
            # Rellenar si hay menos filas que waterfall_h
            for _ in range(cfg.waterfall_h - len(wf_rows)):
                body.append("       │" + " " * W + "│\n", style="dim")
            body.append("       └" + "─" * W + "┘\n", style="dim")

        # ── Marcadores y canal de potencia ────────────────────────────
        m1, m2 = markers[0], markers[1]
        mbar = Text()
        mbar.append_text(_marker_txt(m1, "bold yellow", "yellow"))
        mbar.append("   │   ", style="dim")
        mbar.append_text(_marker_txt(m2, "bold cyan", "cyan"))
        if m1.active and m2.active:
            df   = abs(m2.freq_mhz - m1.freq_mhz) * 1_000
            dp   = abs(m2.power_dbm - m1.power_dbm)
            ch_p = _channel_power(
                frame.powers_dbm, frame.freqs_mhz,
                min(m1.freq_mhz, m2.freq_mhz),
                max(m1.freq_mhz, m2.freq_mhz),
            )
            mbar.append(
                f"   ΔF {df:.1f} kHz  ΔP {dp:.1f} dB  "
                f"CH {ch_p:.1f} dBm",
                style="dim white",
            )
        body.append_text(mbar)
        body.append("\n")

        # ── Señales detectadas resumidas ──────────────────────────────
        if frame.detected:
            sig_line = Text("  ")
            for i, s in enumerate(frame.detected[:5]):
                sig_line.append(
                    f"S{i+1} {s.freq_mhz:.3f}MHz {s.power_dbm:.1f}dBm "
                    f"SNR{s.snr_db:.0f}dB {s.bw_khz:.1f}kHz  ",
                    style="yellow" if i == 0 else "dim yellow",
                )
            body.append_text(sig_line)
            body.append("\n")

        # ── Estado ────────────────────────────────────────────────────
        pk  = "[green]ON[/green]"  if cfg.peak_hold   else "[dim]OFF[/dim]"
        avg = (f"[green]{cfg.avg_frames}f[/green]"
               if cfg.avg_frames > 1 else "[dim]OFF[/dim]")
        wf  = "[green]ON[/green]"  if cfg.waterfall_on else "[dim]OFF[/dim]"
        lbl = "[green]ON[/green]"  if cfg.show_labels  else "[dim]OFF[/dim]"
        status = Text.from_markup(
            f"[dim]PEAK[/dim] {pk}  [dim]AVG[/dim] {avg}  "
            f"[dim]WF[/dim] {wf}  [dim]LABELS[/dim] {lbl}  "
            f"[dim]NOISE[/dim] {frame.noise_floor:.1f} dBm  "
            f"[dim]SDR[/dim] [dim white]{hw_name}[/dim white]"
        )
        body.append_text(status)
        body.append("\n")

        # ── Controles ────────────────────────────────────────────────
        ctrl = Text(style="dim")
        ctrl.append(
            "  ←→ tune  +- span  ↑↓ ref  []thr  p peak  v avg  "
            "m M1  n M2  t auto  z wf  l labels  r rec  e export  q quit"
        )
        band_hint = "  Fn+1…0" if self._info.is_uconsole else "  F1…F10"
        ctrl.append(band_hint + " bandas",
                    style="dim yellow" if self._info.is_uconsole else "dim cyan")
        body.append_text(ctrl)

        return Panel(
            body,
            title=(
                "[bold green]APEX SENTINEL[/bold green] [dim]·[/dim] "
                "[bold white]SPECTRUM ANALYZER v2[/bold white]"
            ),
            border_style="green",
            box=box.ROUNDED,
            expand=False,
        )


# ══════════════════════════════════════════════════════════════════════
# ANALIZADOR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class SpectrumAnalyzer:

    def __init__(self, sentinel: ApexSentinel) -> None:
        self._s        = sentinel
        self._console: Console = sentinel.console
        self._log      = sentinel.log
        _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

        self._platform = detect_platform()
        self._kb       = load_keys(self._platform)
        self._log.info(f"SpectrumAnalyzer v2 listo — {self._platform}", "SA")

    # ── API pública ───────────────────────────────────────────────────

    def run(self, cfg: SAConfig | None = None) -> None:
        self._cfg      = cfg or SAConfig.from_platform(self._platform, self._kb)
        self._buf      = FrameBuffer()
        self._wf_buf   = _WaterfallBuffer(self._cfg.waterfall_h)
        self._markers  = [Marker("M1"), Marker("M2")]
        self._sdr      = _SDRAdapter(self._cfg)
        self._keys     = _KeyReader()
        self._renderer = _Renderer(self._cfg, self._platform)
        self._action   = self._kb.key_to_action()

        # Teclas nuevas en v2 (sin pasar por TOML si no están)
        for k, a in {
            "t": "auto_tune",   "z": "toggle_wf",
            "l": "toggle_labels", "r": "toggle_record",
            "[": "thresh_down", "]": "thresh_up",
        }.items():
            self._action.setdefault(k, a)

        self._stop     = threading.Event()
        self._lock     = threading.Lock()
        self._frame:   _SpectrumFrame | None = None
        self._fps_buf: list[float] = []

        self._log.info(
            f"SA activo — CTR {self._cfg.center_mhz:.3f} MHz  "
            f"WF {self._cfg.display_width}×{self._cfg.display_height}+"
            f"{self._cfg.waterfall_h}  HW {self._sdr.hw_name}",
            "SA",
        )

        acq = threading.Thread(target=self._acq_loop, daemon=True, name="sa-acq")
        self._keys.start()
        acq.start()
        try:
            self._display_loop()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            self._keys.stop()
            acq.join(timeout=2)
            self._sdr.close()
            if self._wf_buf.is_recording:
                self._save_recording()
            self._log.info("SpectrumAnalyzer cerrado.", "SA")

    def info(self) -> dict[str, str]:
        p = self._platform
        return {
            "plataforma":   p.kind.name,
            "modelo":       p.model or "desconocido",
            "arquitectura": p.machine,
            "pantalla":     f"{p.screen.cols}×{p.screen.rows}",
            "spectrum":     f"{p.screen.spectrum_width}×{p.screen.spectrum_height}",
            "tty":          str(p.is_tty),
            "dsi":          str(p.screen.has_dsi),
        }

    # ── Adquisición IQ + FFT ──────────────────────────────────────────

    def _acq_loop(self) -> None:
        cfg    = self._cfg
        n_fft  = cfg.fft_size()
        window = np.hanning(n_fft).astype(np.float32)
        wgain  = float(np.sum(window ** 2))

        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                iq = self._sdr.read_iq(n_fft)
                if len(iq) < n_fft:
                    continue
                iq_w  = iq[:n_fft].astype(np.complex64) * window
                spec  = np.fft.fftshift(np.fft.fft(iq_w))
                psd   = (np.abs(spec) ** 2) / (cfg.sample_rate * wgain)
                pdb   = 10 * np.log10(psd + 1e-20) + 30

                # Submuestrear al ancho de display
                if len(pdb) > cfg.display_width * 2:
                    step = len(pdb) // cfg.display_width
                    pdb  = np.array([
                        pdb[i: i + step].max()
                        for i in range(0, len(pdb) - step + 1, step)
                    ])

                self._buf.push(pdb)
                if cfg.avg_frames > 1:
                    avg = self._buf.average(cfg.avg_frames)
                    if avg is not None:
                        pdb = avg

                # Vector de frecuencias con corrección PPM
                freqs = np.linspace(cfg.freq_start_mhz(), cfg.freq_end_mhz(), len(pdb))
                noise = float(np.percentile(pdb, 15))
                pidx  = int(np.argmax(pdb))

                # Detección de señales
                detected = _SignalDetector.detect(
                    pdb, freqs, noise, cfg.threshold_dbm)

                elapsed = time.perf_counter() - t0
                self._fps_buf.append(elapsed)
                if len(self._fps_buf) > 20:
                    self._fps_buf.pop(0)

                now_ts = time.time()
                with self._lock:
                    self._frame = _SpectrumFrame(
                        freqs_mhz   = freqs,
                        powers_dbm  = pdb,
                        noise_floor = noise,
                        peak_freq   = float(freqs[pidx]),
                        peak_power  = float(pdb[pidx]),
                        fps         = 1.0 / (sum(self._fps_buf) / len(self._fps_buf)),
                        ts          = datetime.now(UTC).strftime("%H:%M:%S"),
                        detected    = detected,
                    )
                self._wf_buf.push(pdb, now_ts)

            except Exception as exc:
                log.debug("Adquisición: %s", exc)
                time.sleep(0.1)

    # ── Display loop ──────────────────────────────────────────────────

    def _display_loop(self) -> None:
        with Live(console=self._console, refresh_per_second=15, screen=True) as live:
            while not self._stop.is_set():
                key = self._keys.get()
                if key and not self._handle_key(key):
                    break
                with self._lock:
                    frame = self._frame
                if frame is not None:
                    live.update(self._renderer.render(
                        frame, self._buf, self._wf_buf,
                        self._markers, self._sdr.hw_name, self._kb,
                    ))
                time.sleep(0.04)

    # ── Manejador de teclas ───────────────────────────────────────────

    def _handle_key(self, key: str) -> bool:
        action = self._action.get(key, "")

        if action.startswith("band:"):
            preset = self._kb.bands.get(action[5:])
            if preset:
                self._jump_band(preset)
            return True

        cfg  = self._cfg
        step = cfg.span_mhz / 10

        runners: dict[str, object] = {
            "tune_right":    lambda: self._tune(cfg.center_mhz + step),
            "tune_left":     lambda: self._tune(cfg.center_mhz - step),
            "span_up":       lambda: self._set_span(cfg.span_mhz * 2),
            "span_down":     lambda: self._set_span(cfg.span_mhz / 2),
            "ref_up":        lambda: setattr(cfg, "ref_dbm",  min(-10.0,  cfg.ref_dbm + 5)),
            "ref_down":      lambda: setattr(cfg, "ref_dbm",  max(-140.0, cfg.ref_dbm - 5)),
            "thresh_up":     lambda: setattr(cfg, "threshold_dbm",
                                     min(cfg.ref_dbm - 5, cfg.threshold_dbm + 5)),
            "thresh_down":   lambda: setattr(cfg, "threshold_dbm",
                                     max(cfg.floor_dbm, cfg.threshold_dbm - 5)),
            "toggle_peak":   lambda: setattr(cfg, "peak_hold",   not cfg.peak_hold),
            "toggle_avg":    lambda: self._cycle_avg(),
            "toggle_wf":     lambda: setattr(cfg, "waterfall_on", not cfg.waterfall_on),
            "toggle_labels": lambda: setattr(cfg, "show_labels",  not cfg.show_labels),
            "toggle_record": lambda: self._toggle_record(),
            "clear_buffer":  lambda: self._clear_all(),
            "auto_tune":     lambda: self._auto_tune(),
            "marker_1":      lambda: self._place_marker(0),
            "marker_2":      lambda: self._place_marker(1),
            "cycle_gain":    lambda: self._cycle_gain(),
            "export_frame":  lambda: self._export(),
        }

        if action in ("quit", "CTRL_C") or key in ("\x03", "ESC"):
            return False

        fn = runners.get(action)
        if fn:
            fn()  # type: ignore[operator]
        return True

    # ── Controles ────────────────────────────────────────────────────

    def _tune(self, mhz: float) -> None:
        mhz = float(np.clip(mhz, _FREQ_MIN_MHZ, _FREQ_MAX_MHZ))
        self._cfg.center_mhz = mhz
        self._cfg.band_label  = ""
        self._sdr.tune(mhz)
        self._buf.clear()
        self._wf_buf.clear()

    def _auto_tune(self) -> None:
        with self._lock:
            frame = self._frame
        if frame is None:
            return
        pidx = int(np.argmax(frame.powers_dbm))
        self._tune(float(frame.freqs_mhz[pidx]))
        self._log.info(
            f"Auto-tune → {self._cfg.center_mhz:.3f} MHz  "
            f"{frame.powers_dbm[pidx]:.1f} dBm",
            "SA",
        )

    def _jump_band(self, p: BandPreset) -> None:
        self._cfg.center_mhz = p.freq_mhz
        self._cfg.span_mhz   = p.span_mhz
        self._cfg.band_label  = p.label
        self._sdr.tune(p.freq_mhz)
        self._buf.clear()
        self._wf_buf.clear()
        self._log.info(f"Banda: {p.label} — {p.freq_mhz:.3f} MHz", "SA")

    def _set_span(self, span: float) -> None:
        lo = self._cfg.rbw_actual_khz() * 2 / 1_000
        hi = self._cfg.sample_rate / 1e6
        self._cfg.span_mhz   = float(np.clip(span, lo, hi))
        self._cfg.band_label  = ""
        self._buf.clear()
        self._wf_buf.clear()

    def _cycle_avg(self) -> None:
        ciclo = [1, 4, 8, 16, 32]
        idx   = ciclo.index(self._cfg.avg_frames) if self._cfg.avg_frames in ciclo else 0
        self._cfg.avg_frames = ciclo[(idx + 1) % len(ciclo)]
        self._buf.clear()

    def _cycle_gain(self) -> None:
        ciclo = ["auto", "20", "40", "60"]
        try:
            idx = ciclo.index(str(self._cfg.gain))
        except ValueError:
            idx = 0
        nuevo = ciclo[(idx + 1) % len(ciclo)]
        self._sdr.set_gain(nuevo if nuevo == "auto" else int(nuevo))
        self._cfg.gain = nuevo

    def _clear_all(self) -> None:
        self._buf.clear()
        self._wf_buf.clear()

    def _toggle_record(self) -> None:
        if self._wf_buf.is_recording:
            self._save_recording()
        else:
            self._wf_buf.start_recording()
            self._log.info("Grabación de waterfall iniciada.", "SA")

    def _save_recording(self) -> None:
        data = self._wf_buf.stop_recording()
        if not data:
            return
        ts       = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        csv_path = _EVIDENCE_DIR / f"waterfall_rec_{ts}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            with self._lock:
                frame = self._frame
            if frame is not None:
                freqs = np.linspace(
                    self._cfg.freq_start_mhz(),
                    self._cfg.freq_end_mhz(),
                    len(data[0][1]),
                )
                w.writerow(["timestamp"] + [f"{f:.4f}" for f in freqs])
            for ts_row, psd in data:
                w.writerow([f"{ts_row:.3f}"] + [f"{p:.2f}" for p in psd])
        self._log.info(f"Waterfall grabado: {csv_path} ({len(data)} frames)", "SA")
        if hasattr(self._s, "gp") and self._s.gp and self._s.gp.proyecto_activo:
            self._s.gp.registrar_evidencia(
                "waterfall_rec",
                f"Grabación de waterfall — {self._cfg.center_mhz:.3f} MHz",
                {"csv": str(csv_path), "frames": len(data)},
            )

    def _place_marker(self, idx: int) -> None:
        with self._lock:
            frame = self._frame
        if frame is None:
            return
        pows = frame.powers_dbm.copy()
        if idx == 1 and self._markers[0].active:
            m0c = int(np.argmin(np.abs(frame.freqs_mhz - self._markers[0].freq_mhz)))
            pows[max(0, m0c - 5):min(len(pows), m0c + 5)] = -999.0
        pi = int(np.argmax(pows))
        self._markers[idx] = Marker(
            name=f"M{idx + 1}",
            freq_mhz=float(frame.freqs_mhz[pi]),
            power_dbm=float(frame.powers_dbm[pi]),
            active=True,
        )

    def _export(self) -> None:
        with self._lock:
            frame = self._frame
        if frame is None:
            return
        ts   = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        stem = f"spectrum_{self._cfg.center_mhz:.3f}MHz_{ts}"

        m1, m2 = self._markers
        ch_pow = None
        if m1.active and m2.active:
            ch_pow = _channel_power(
                frame.powers_dbm, frame.freqs_mhz,
                min(m1.freq_mhz, m2.freq_mhz),
                max(m1.freq_mhz, m2.freq_mhz),
            )

        json_path = _EVIDENCE_DIR / f"{stem}.json"
        json_path.write_text(json.dumps({
            "timestamp":      ts,
            "platform":       self._platform.kind.name,
            "model":          self._platform.model,
            "center_mhz":     self._cfg.center_mhz,
            "span_mhz":       self._cfg.span_mhz,
            "rbw_khz":        self._cfg.rbw_actual_khz(),
            "ppm_offset":     self._cfg.ppm_offset,
            "threshold_dbm":  self._cfg.threshold_dbm,
            "ref_dbm":        self._cfg.ref_dbm,
            "gain":           self._cfg.gain,
            "hardware":       self._sdr.hw_name,
            "band_label":     self._cfg.band_label,
            "noise_floor":    frame.noise_floor,
            "peak_freq_mhz":  frame.peak_freq,
            "peak_power_dbm": frame.peak_power,
            "channel_power_dbm": ch_pow,
            "detected_signals": [
                {"freq_mhz": s.freq_mhz, "power_dbm": s.power_dbm,
                 "snr_db": s.snr_db, "bw_khz": s.bw_khz}
                for s in frame.detected
            ],
            "markers": [
                {"name": m.name, "freq_mhz": m.freq_mhz,
                 "power_dbm": m.power_dbm, "active": m.active}
                for m in self._markers
            ],
            "spectrum": [
                {"freq_mhz": float(f), "power_dbm": float(p)}
                for f, p in zip(frame.freqs_mhz.tolist(), frame.powers_dbm.tolist())
            ],
        }, indent=2), encoding="utf-8")

        csv_path = _EVIDENCE_DIR / f"{stem}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["freq_mhz", "power_dbm"])
            w.writerows(zip(frame.freqs_mhz.tolist(), frame.powers_dbm.tolist()))

        if hasattr(self._s, "gp") and self._s.gp and self._s.gp.proyecto_activo:
            self._s.gp.registrar_evidencia(
                "spectrum",
                f"Frame exportado — {self._cfg.center_mhz:.3f} MHz "
                f"({self._cfg.band_label or 'freq libre'})",
                {"json": str(json_path), "csv": str(csv_path)},
            )
        log.info("Exportado → %s", json_path)


# ══════════════════════════════════════════════════════════════════════
# HELPERS DE MÓDULO
# ══════════════════════════════════════════════════════════════════════

def _interp(arr: np.ndarray, n: int) -> np.ndarray:
    return np.interp(np.linspace(0, len(arr) - 1, n), np.arange(len(arr)), arr)


def _cell(p: float, row: int, H: int, ref: float, floor: float) -> tuple[str, str]:
    norm = float(np.clip((p - floor) / max(ref - floor, 1e-6) * H, 0.0, H))
    if norm >= row + 1:
        return "█", _color((row + 0.5) / H)
    if norm > row:
        sub = max(1, min(8, int((norm - row) * 8)))
        return _SUB[sub], _color((row + 0.5) / H)
    return " ", ""


def _color(r: float) -> str:
    if r >= 0.90: return "bold bright_red"
    if r >= 0.75: return "red"
    if r >= 0.55: return "bright_yellow"
    if r >= 0.35: return "yellow"
    if r >= 0.15: return "green"
    return "dim green"


def _wf_style(power: float, threshold: float) -> str:
    delta = power - threshold
    if delta >= 40: return "bold bright_red"
    if delta >= 30: return "bright_red"
    if delta >= 20: return "yellow"
    if delta >= 10: return "bright_green"
    if delta >=  0: return "cyan"
    if delta >= -10: return "blue"
    return "dim"


def _channel_power(
    psd_db:    np.ndarray,
    freqs_mhz: np.ndarray,
    f_lo:      float,
    f_hi:      float,
) -> float:
    mask = (freqs_mhz >= f_lo) & (freqs_mhz <= f_hi)
    if not mask.any():
        return -999.0
    linear = 10 ** (psd_db[mask] / 10)
    return float(10 * np.log10(np.sum(linear) + 1e-20))


def _freq_axis(start: float, end: float, W: int) -> str:
    n    = min(6, W // 12)
    line = [" "] * W
    for pos, f in zip(np.linspace(0, W - 1, n).astype(int), np.linspace(start, end, n)):
        lbl = f"{f:.1f}"
        s   = max(0, pos - len(lbl) // 2)
        for i, ch in enumerate(lbl):
            if s + i < W:
                line[s + i] = ch
    return "".join(line) + " MHz"


def _marker_txt(m: Marker, title_st: str, val_st: str) -> Text:
    t = Text()
    if m.active:
        t.append(f"{m.name} ", style=title_st)
        t.append(f"{m.freq_mhz:.3f} MHz  {m.power_dbm:.1f} dBm", style=val_st)
    else:
        t.append(f"{m.name} —", style="dim")
    return t
