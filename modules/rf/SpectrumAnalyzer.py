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
from typing import TYPE_CHECKING, NamedTuple, Sequence

import numpy as np
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from core.platform import PlatformInfo, detect as detect_platform
from core.keybindings import BandPreset, KeyBindings, load as load_keys
if TYPE_CHECKING:
    from Main import ApexSentinel
    from modules.rf.rf_source import SDRBackend

log = logging.getLogger("sentinel.rf.spectrum")

_SUB = " ▁▂▃▄▅▆▇█"
_PEAK_CHR = "▪"
_MARKER_CHR = "▼"
_THRESH_CHR = "╌"
_FREQ_MIN_MHZ = 24.0
_FREQ_MAX_MHZ = 1766.0
_EVIDENCE_DIR = Path("data/evidence/rf")

_FKEY_MAP: dict[bytes, str] = {
    b"P": "F1",  b"Q": "F2",  b"R": "F3",  b"S": "F4",
    b"11~": "F1", b"12~": "F2", b"13~": "F3", b"14~": "F4",
    b"15~": "F5", b"17~": "F6", b"18~": "F7", b"19~": "F8",
    b"20~": "F9", b"21~": "F10",
    b"A": "UP",  b"B": "DOWN", b"C": "RIGHT", b"D": "LEFT",
}

_COLOR_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.90, "bold bright_red"),
    (0.75, "red"),
    (0.55, "bright_yellow"),
    (0.35, "yellow"),
    (0.15, "green"),
    (0.00, "dim green"),
)

_WF_DELTA_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (40.0, "bold bright_red"),
    (30.0, "bright_red"),
    (20.0, "yellow"),
    (10.0, "bright_green"),
    (0.0,  "cyan"),
    (-10.0, "blue"),
    (-999.0, "dim"),
)


@dataclass
class SAConfig:
    center_mhz:     float = 433.920
    span_mhz:       float = 2.0
    rbw_khz:        float = 12.5
    ref_dbm:        float = -20.0
    floor_dbm:      float = -110.0
    gain:           str = "auto"
    avg_frames:     int = 1
    peak_hold:      bool = False
    display_width:  int = 120
    display_height: int = 14
    sample_rate:    int = 2_048_000
    band_label:     str = ""
    ppm_offset:     float = 0.0
    threshold_dbm:  float = -80.0
    waterfall_h:    int = 8
    waterfall_on:   bool = True
    show_labels:    bool = True
    record_wf:      bool = False

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
        sc = info.screen
        cols = kb.display_cols if kb.display_cols > 0 else sc.spectrum_width
        var = max(16, sc.rows - 14)
        wf_h = max(4, min(10, var // 3))
        sp_h = max(8, var - wf_h)
        if kb.display_rows > 0:
            sp_h = kb.display_rows
        return cls(display_width=cols, display_height=sp_h, waterfall_h=wf_h)


@dataclass
class Marker:
    name:      str
    freq_mhz:  float = 0.0
    power_dbm: float = 0.0
    active:    bool = False


@dataclass
class _DetectedSignal:
    bin_idx:   int
    freq_mhz:  float
    power_dbm: float
    snr_db:    float
    bw_khz:    float


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


class _WaterfallBuffer:

    def __init__(self, h: int = 8) -> None:
        self._h:    int = h
        self._rows: deque[np.ndarray] = deque(maxlen=h)
        self._rec:  list[tuple[float, np.ndarray]] = []
        self._recording = False

    def push(self, psd: np.ndarray, ts: float) -> None:
        self._rows.appendleft(psd.copy())
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
            window = psd_db[i - min_spacing: i + min_spacing + 1]
            if psd_db[i] < window.max():
                continue

            lo, hi = i, i
            thr_3db = psd_db[i] - 3.0
            while lo > 0 and psd_db[lo] > thr_3db:
                lo -= 1
            while hi < n - 1 and psd_db[hi] > thr_3db:
                hi += 1
            bw_khz = max(0.1, (freqs_mhz[hi] - freqs_mhz[lo]) * 1_000)

            signals.append(_DetectedSignal(
                bin_idx=i,
                freq_mhz=float(freqs_mhz[i]),
                power_dbm=float(psd_db[i]),
                snr_db=float(psd_db[i] - noise_floor),
                bw_khz=bw_khz,
            ))

        signals.sort(key=lambda s: s.power_dbm, reverse=True)
        return signals[:max_signals]


class _KeyReader(threading.Thread):

    def __init__(self) -> None:
        super().__init__(daemon=True, name="sa-keyreader")
        self._q:    queue.Queue[str] = queue.Queue()
        self._stop: threading.Event = threading.Event()

    def run(self) -> None:
        if not sys.stdin.isatty():
            return
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
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


class _SDRAdapter:
    def __init__(self, cfg: SAConfig) -> None:
        self._cfg = cfg
        from modules.rf.rf_source import open_backend
        self._backend = open_backend(
            freq_hz=int(cfg.center_mhz * 1e6),
            sample_rate=cfg.sample_rate,
            gain=float(cfg.gain) if str(cfg.gain).lower() != "auto" else 49.6,
        )
        log.info("SA backend: %s", self._backend.hw_name)

    @property
    def hw_name(self) -> str:
        return self._backend.hw_name

    def tune(self, mhz: float) -> None:
        self._backend.tune(mhz * 1e6)
        self._cfg.center_mhz = mhz

    def set_gain(self, gain: "str | float") -> None:
        self._backend.set_gain(gain)
        self._cfg.gain = str(gain)

    def read_iq(self, n: int) -> np.ndarray:
        iq = self._backend.read_raw(n)
        if iq is None or len(iq) == 0:
            return np.zeros(n, dtype=np.complex64)
        return iq.astype(np.complex64)

    def close(self) -> None:
        self._backend.close()

    def swap_backend(self, backend: "SDRBackend") -> None:
        self._backend.close()
        self._backend = backend
        log.info("SA backend cambiado → %s", backend.hw_name)


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


class _DoubleBuffer:

    def __init__(self) -> None:
        self._slots: list[_SpectrumFrame | None] = [None, None]
        self._front: int = 0
        self._swap_lock = threading.Lock()

    def write(self, frame: _SpectrumFrame) -> None:
        back = 1 - self._front
        self._slots[back] = frame
        with self._swap_lock:
            self._front = back

    def read(self) -> _SpectrumFrame | None:
        with self._swap_lock:
            idx = self._front
        return self._slots[idx]


class _SpectrumRenderState(NamedTuple):
    powers:     np.ndarray
    peak_psd:   np.ndarray | None
    norm_mat:   np.ndarray
    peak_norm:  np.ndarray | None
    mcols:      dict[int, Marker]
    det_cols:   dict[int, _DetectedSignal]
    thresh_row: int


def _build_render_state(
    frame:   _SpectrumFrame,
    buf:     FrameBuffer,
    cfg:     SAConfig,
    markers: list[Marker],
    W:       int,
    H:       int,
) -> _SpectrumRenderState:
    powers = _interp(frame.powers_dbm, W)

    peak_psd: np.ndarray | None = None
    if cfg.peak_hold:
        ph = buf.peak()
        if ph is not None:
            peak_psd = _interp(ph, W)

    db_range = max(cfg.ref_dbm - cfg.floor_dbm, 1e-6)
    norm_mat = np.clip((powers - cfg.floor_dbm) / db_range * H, 0.0, H)
    peak_norm: np.ndarray | None = None
    if peak_psd is not None:
        peak_norm = np.clip((peak_psd - cfg.floor_dbm) / db_range * H, 0.0, H)

    mcols: dict[int, Marker] = {}
    for m in markers:
        if not m.active:
            continue
        rel = (m.freq_mhz - cfg.freq_start_mhz()) / max(cfg.span_mhz, 1e-9)
        mcols[int(np.clip(rel * W, 0, W - 1))] = m

    det_cols: dict[int, _DetectedSignal] = {}
    if cfg.show_labels:
        for s in frame.detected:
            rel = (s.freq_mhz - cfg.freq_start_mhz()) / max(cfg.span_mhz, 1e-9)
            col = int(np.clip(rel * W, 0, W - 1))
            det_cols[col] = s

    thresh_row = int(
        (cfg.threshold_dbm - cfg.floor_dbm)
        / max(cfg.ref_dbm - cfg.floor_dbm, 1)
        * H
    )

    return _SpectrumRenderState(
        powers=powers,
        peak_psd=peak_psd,
        norm_mat=norm_mat,
        peak_norm=peak_norm,
        mcols=mcols,
        det_cols=det_cols,
        thresh_row=thresh_row,
    )


def _render_spectrum_matrix(
    state:  _SpectrumRenderState,
    cfg:    SAConfig,
    H:      int,
    W:      int,
    body:   Text,
) -> None:
    norm = state.norm_mat
    rows = np.arange(H - 1, -1, -1)
    db_values = cfg.floor_dbm + (rows / H) * (cfg.ref_dbm - cfg.floor_dbm)

    for row_idx, (row, db) in enumerate(zip(rows, db_values)):
        body.append(f"{db:>6.0f} │", style="dim green")

        norm_row = norm
        row_f = float(row)

        filled = norm_row >= row_f + 1
        partial = (~filled) & (norm_row > row_f)
        sub_idxs = np.where(partial, np.clip(
            (norm_row - row_f) * 8, 1, 8).astype(np.int8), 0)

        color_ratios = (row_f + 0.5) / H
        col_color = _color(color_ratios)

        peak_visible: np.ndarray | None = None
        if state.peak_norm is not None:
            peak_filled = state.peak_norm >= row_f + 1
            peak_partial = state.peak_norm > row_f
            peak_visible = peak_filled | peak_partial

        is_thresh_row = (row == state.thresh_row)

        for col in range(W):
            if filled[col]:
                ch, st = "█", col_color
            elif partial[col]:
                ch, st = _SUB[int(sub_idxs[col])], col_color
            elif peak_visible is not None and peak_visible[col]:
                ch, st = _PEAK_CHR, "dim white"
            elif is_thresh_row:
                ch, st = _THRESH_CHR, "dim yellow"
            elif col in state.mcols:
                ch, st = " ", ""
            else:
                ch, st = " ", ""
            body.append(ch, style=st)

        body.append("\n")


class _Renderer:

    def __init__(self, cfg: SAConfig, info: PlatformInfo) -> None:
        self._cfg = cfg
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
        W = cfg.display_width
        H = cfg.display_height

        state = _build_render_state(frame, buf, cfg, markers, W, H)
        body = Text()

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

        if cfg.show_labels and frame.detected:
            lbl_line = Text("       ")
            prev_end = 0
            for col in sorted(state.det_cols):
                s = state.det_cols[col]
                txt = f"{s.freq_mhz:.2f}"
                pad = max(0, col - prev_end)
                lbl_line.append(" " * pad)
                lbl_line.append(txt, style="bold yellow")
                prev_end = col + len(txt)
            lbl_line.append("\n")
            body.append_text(lbl_line)

        mline = Text("       ")
        for c in range(W):
            m = state.mcols.get(c)
            mline.append(_MARKER_CHR if m else " ",
                         style="bold yellow" if m else "")
        body.append_text(mline)
        body.append("\n")

        _render_spectrum_matrix(state, cfg, H, W, body)

        body.append("       └" + "─" * W + "\n", style="dim green")
        body.append(
            "        " + _freq_axis(cfg.freq_start_mhz(), cfg.freq_end_mhz(), W))
        body.append("\n")

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
            for _ in range(cfg.waterfall_h - len(wf_rows)):
                body.append("       │" + " " * W + "│\n", style="dim")
            body.append("       └" + "─" * W + "┘\n", style="dim")

        m1, m2 = markers[0], markers[1]
        mbar = Text()
        mbar.append_text(_marker_txt(m1, "bold yellow", "yellow"))
        mbar.append("   │   ", style="dim")
        mbar.append_text(_marker_txt(m2, "bold cyan", "cyan"))
        if m1.active and m2.active:
            df = abs(m2.freq_mhz - m1.freq_mhz) * 1_000
            dp = abs(m2.power_dbm - m1.power_dbm)
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

        pk = "[green]ON[/green]" if cfg.peak_hold else "[dim]OFF[/dim]"
        avg = (f"[green]{cfg.avg_frames}f[/green]"
               if cfg.avg_frames > 1 else "[dim]OFF[/dim]")
        wf = "[green]ON[/green]" if cfg.waterfall_on else "[dim]OFF[/dim]"
        lbl = "[green]ON[/green]" if cfg.show_labels else "[dim]OFF[/dim]"
        status = Text.from_markup(
            f"[dim]PEAK[/dim] {pk}  [dim]AVG[/dim] {avg}  "
            f"[dim]WF[/dim] {wf}  [dim]LABELS[/dim] {lbl}  "
            f"[dim]NOISE[/dim] {frame.noise_floor:.1f} dBm  "
            f"[dim]SDR[/dim] [dim white]{hw_name}[/dim white]"
        )
        body.append_text(status)
        body.append("\n")

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


class _ExportPayload(NamedTuple):
    timestamp:           str
    platform_name:       str
    platform_model:      str | None
    center_mhz:          float
    span_mhz:            float
    rbw_khz:             float
    ppm_offset:          float
    threshold_dbm:       float
    ref_dbm:             float
    gain:                str
    hardware:            str
    band_label:          str
    noise_floor:         float
    peak_freq_mhz:       float
    peak_power_dbm:      float
    channel_power_dbm:   float | None
    detected_signals:    list[_DetectedSignal]
    markers:             list[Marker]
    freqs_mhz:           np.ndarray
    powers_dbm:          np.ndarray


class _RecordingPayload(NamedTuple):
    timestamp:   str
    center_mhz:  float
    freq_start:  float
    freq_end:    float
    bin_count:   int
    frames:      list[tuple[float, np.ndarray]]


def _build_export_payload(
    frame:     _SpectrumFrame,
    cfg:       SAConfig,
    platform:  PlatformInfo,
    hw_name:   str,
    markers:   list[Marker],
) -> _ExportPayload:
    m1, m2 = markers[0], markers[1]
    ch_pow: float | None = None
    if m1.active and m2.active:
        ch_pow = _channel_power(
            frame.powers_dbm, frame.freqs_mhz,
            min(m1.freq_mhz, m2.freq_mhz),
            max(m1.freq_mhz, m2.freq_mhz),
        )
    return _ExportPayload(
        timestamp=datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
        platform_name=platform.kind.name,
        platform_model=platform.model,
        center_mhz=cfg.center_mhz,
        span_mhz=cfg.span_mhz,
        rbw_khz=cfg.rbw_actual_khz(),
        ppm_offset=cfg.ppm_offset,
        threshold_dbm=cfg.threshold_dbm,
        ref_dbm=cfg.ref_dbm,
        gain=cfg.gain,
        hardware=hw_name,
        band_label=cfg.band_label,
        noise_floor=frame.noise_floor,
        peak_freq_mhz=frame.peak_freq,
        peak_power_dbm=frame.peak_power,
        channel_power_dbm=ch_pow,
        detected_signals=list(frame.detected),
        markers=list(markers),
        freqs_mhz=frame.freqs_mhz,
        powers_dbm=frame.powers_dbm,
    )


def _build_recording_payload(
    data:  list[tuple[float, np.ndarray]],
    cfg:   SAConfig,
) -> _RecordingPayload:
    return _RecordingPayload(
        timestamp=datetime.now(UTC).strftime("%Y%m%d_%H%M%S"),
        center_mhz=cfg.center_mhz,
        freq_start=cfg.freq_start_mhz(),
        freq_end=cfg.freq_end_mhz(),
        bin_count=len(data[0][1]) if data else 0,
        frames=data,
    )


def _serialize_export_to_json(payload: _ExportPayload) -> str:
    return json.dumps({
        "timestamp":      payload.timestamp,
        "platform":       payload.platform_name,
        "model":          payload.platform_model,
        "center_mhz":     payload.center_mhz,
        "span_mhz":       payload.span_mhz,
        "rbw_khz":        payload.rbw_khz,
        "ppm_offset":     payload.ppm_offset,
        "threshold_dbm":  payload.threshold_dbm,
        "ref_dbm":        payload.ref_dbm,
        "gain":           payload.gain,
        "hardware":       payload.hardware,
        "band_label":     payload.band_label,
        "noise_floor":    payload.noise_floor,
        "peak_freq_mhz":  payload.peak_freq_mhz,
        "peak_power_dbm": payload.peak_power_dbm,
        "channel_power_dbm": payload.channel_power_dbm,
        "detected_signals": [
            {"freq_mhz": s.freq_mhz, "power_dbm": s.power_dbm,
             "snr_db": s.snr_db, "bw_khz": s.bw_khz}
            for s in payload.detected_signals
        ],
        "markers": [
            {"name": m.name, "freq_mhz": m.freq_mhz,
             "power_dbm": m.power_dbm, "active": m.active}
            for m in payload.markers
        ],
        "spectrum": [
            {"freq_mhz": float(f), "power_dbm": float(p)}
            for f, p in zip(payload.freqs_mhz.tolist(), payload.powers_dbm.tolist())
        ],
    }, indent=2)


def _write_export_csv(path: Path, payload: _ExportPayload) -> None:
    rows: list[tuple[float, float]] = list(
        zip(payload.freqs_mhz.tolist(), payload.powers_dbm.tolist())
    )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_mhz", "power_dbm"])
        w.writerows(rows)


def _write_recording_csv(path: Path, payload: _RecordingPayload) -> None:
    freq_headers = np.linspace(
        payload.freq_start, payload.freq_end, payload.bin_count)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp"] + [f"{f:.4f}" for f in freq_headers])
        for ts_row, psd in payload.frames:
            w.writerow([f"{ts_row:.3f}"] + [f"{p:.2f}" for p in psd])


class SpectrumAnalyzer:

    def __init__(self, sentinel: ApexSentinel) -> None:
        self._s = sentinel
        self._console: Console = sentinel.console
        self._log = sentinel.log
        _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

        self._platform = detect_platform()
        self._kb = load_keys(self._platform)
        self._log.info(f"SpectrumAnalyzer v2 listo — {self._platform}", "SA")

    def run(self, cfg: SAConfig | None = None) -> None:
        self._cfg = cfg or SAConfig.from_platform(self._platform, self._kb)
        self._buf = FrameBuffer()
        self._wf_buf = _WaterfallBuffer(self._cfg.waterfall_h)
        self._markers = [Marker("M1"), Marker("M2")]
        self._sdr = _SDRAdapter(self._cfg)
        self._keys = _KeyReader()
        self._renderer = _Renderer(self._cfg, self._platform)
        self._action = self._kb.key_to_action()
        self._double_buf = _DoubleBuffer()

        for k, a in {
            "t": "auto_tune",   "z": "toggle_wf",
            "l": "toggle_labels", "r": "toggle_record",
            "[": "thresh_down", "]": "thresh_up",
        }.items():
            self._action.setdefault(k, a)

        self._stop = threading.Event()
        self._fps_buf: list[float] = []

        self._log.info(
            f"SA activo — CTR {self._cfg.center_mhz:.3f} MHz  "
            f"WF {self._cfg.display_width}×{self._cfg.display_height}+"
            f"{self._cfg.waterfall_h}  HW {self._sdr.hw_name}",
            "SA",
        )

        acq = threading.Thread(target=self._acq_loop,
                               daemon=True, name="sa-acq")
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

    def use_tcp(self, host: str, port: int = 1234, gain: int = 400) -> None:
        from modules.rf.rf_source import tcp_backend
        if hasattr(self, "_sdr"):
            freq_hz = int(self._cfg.center_mhz * 1e6)
            self._sdr.swap_backend(
                tcp_backend(host, port, freq_hz, self._cfg.sample_rate, gain)
            )
            self._log.info(f"SA → rtl_tcp://{host}:{port}", "SA")

    def use_file(self, path: str, loop: bool = True) -> None:
        from modules.rf.rf_source import file_backend
        if hasattr(self, "_sdr"):
            self._sdr.swap_backend(file_backend(path, loop))
            self._log.info(f"SA → FILE:{path}", "SA")

    def _acq_loop(self) -> None:
        cfg = self._cfg
        n_fft = cfg.fft_size()
        window = np.hanning(n_fft).astype(np.float32)
        wgain = float(np.sum(window ** 2))

        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                iq = self._sdr.read_iq(n_fft)
                if len(iq) < n_fft:
                    continue
                iq_w = iq[:n_fft].astype(np.complex64) * window
                spec = np.fft.fftshift(np.fft.fft(iq_w))
                psd = (np.abs(spec) ** 2) / (cfg.sample_rate * wgain)
                pdb = 10 * np.log10(psd + 1e-20) + 30

                if len(pdb) > cfg.display_width * 2:
                    step = len(pdb) // cfg.display_width
                    n_steps = len(pdb) // step
                    pdb = pdb[:n_steps *
                              step].reshape(n_steps, step).max(axis=1)

                self._buf.push(pdb)
                if cfg.avg_frames > 1:
                    avg = self._buf.average(cfg.avg_frames)
                    if avg is not None:
                        pdb = avg

                freqs = np.linspace(cfg.freq_start_mhz(),
                                    cfg.freq_end_mhz(), len(pdb))
                noise = float(np.percentile(pdb, 15))
                pidx = int(np.argmax(pdb))

                detected = _SignalDetector.detect(
                    pdb, freqs, noise, cfg.threshold_dbm)

                elapsed = time.perf_counter() - t0
                self._fps_buf.append(elapsed)
                if len(self._fps_buf) > 20:
                    self._fps_buf.pop(0)

                now_ts = time.time()
                frame = _SpectrumFrame(
                    freqs_mhz=freqs,
                    powers_dbm=pdb,
                    noise_floor=noise,
                    peak_freq=float(freqs[pidx]),
                    peak_power=float(pdb[pidx]),
                    fps=1.0 / (sum(self._fps_buf) / len(self._fps_buf)),
                    ts=datetime.now(UTC).strftime("%H:%M:%S"),
                    detected=detected,
                )
                self._double_buf.write(frame)
                self._wf_buf.push(pdb, now_ts)

            except Exception as exc:
                log.debug("Adquisición: %s", exc)
                time.sleep(0.1)

    def _display_loop(self) -> None:
        with Live(console=self._console, refresh_per_second=15, screen=True) as live:
            while not self._stop.is_set():
                key = self._keys.get()
                if key and not self._handle_key(key):
                    break
                frame = self._double_buf.read()
                if frame is not None:
                    live.update(self._renderer.render(
                        frame, self._buf, self._wf_buf,
                        self._markers, self._sdr.hw_name, self._kb,
                    ))
                time.sleep(0.04)

    def _handle_key(self, key: str) -> bool:
        action = self._action.get(key, "")

        if action.startswith("band:"):
            preset = self._kb.bands.get(action[5:])
            if preset:
                self._jump_band(preset)
            return True

        cfg = self._cfg
        step = cfg.span_mhz / 10

        runners: dict[str, object] = {
            "tune_right": lambda: self._tune(cfg.center_mhz + step),
            "tune_left": lambda: self._tune(cfg.center_mhz - step),
            "span_up": lambda: self._set_span(cfg.span_mhz * 2),
            "span_down": lambda: self._set_span(cfg.span_mhz / 2),
            "ref_up": lambda: setattr(cfg, "ref_dbm",  min(-10.0,  cfg.ref_dbm + 5)),
            "ref_down": lambda: setattr(cfg, "ref_dbm",  max(-140.0, cfg.ref_dbm - 5)),
            "thresh_up": lambda: setattr(cfg, "threshold_dbm",
                                         min(cfg.ref_dbm - 5, cfg.threshold_dbm + 5)),
            "thresh_down": lambda: setattr(cfg, "threshold_dbm",
                                           max(cfg.floor_dbm, cfg.threshold_dbm - 5)),
            "toggle_peak": lambda: setattr(cfg, "peak_hold", not cfg.peak_hold),
            "toggle_avg": lambda: self._cycle_avg(),
            "toggle_wf": lambda: setattr(cfg, "waterfall_on", not cfg.waterfall_on),
            "toggle_labels": lambda: setattr(cfg, "show_labels", not cfg.show_labels),
            "toggle_record": lambda: self._toggle_record(),
            "clear_buffer": lambda: self._clear_all(),
            "auto_tune": lambda: self._auto_tune(),
            "marker_1": lambda: self._place_marker(0),
            "marker_2": lambda: self._place_marker(1),
            "cycle_gain": lambda: self._cycle_gain(),
            "export_frame": lambda: self._export(),
        }

        if action in ("quit", "CTRL_C") or key in ("\x03", "ESC"):
            return False

        fn = runners.get(action)
        if fn:
            fn()  # type: ignore[operator]
        return True

    def _tune(self, mhz: float) -> None:
        mhz = float(np.clip(mhz, _FREQ_MIN_MHZ, _FREQ_MAX_MHZ))
        self._cfg.center_mhz = mhz
        self._cfg.band_label = ""
        self._sdr.tune(mhz)
        self._buf.clear()
        self._wf_buf.clear()

    def _auto_tune(self) -> None:
        frame = self._double_buf.read()
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
        self._cfg.span_mhz = p.span_mhz
        self._cfg.band_label = p.label
        self._sdr.tune(p.freq_mhz)
        self._buf.clear()
        self._wf_buf.clear()
        self._log.info(f"Banda: {p.label} — {p.freq_mhz:.3f} MHz", "SA")

    def _set_span(self, span: float) -> None:
        lo = self._cfg.rbw_actual_khz() * 2 / 1_000
        hi = self._cfg.sample_rate / 1e6
        self._cfg.span_mhz = float(np.clip(span, lo, hi))
        self._cfg.band_label = ""
        self._buf.clear()
        self._wf_buf.clear()

    def _cycle_avg(self) -> None:
        ciclo = [1, 4, 8, 16, 32]
        idx = ciclo.index(
            self._cfg.avg_frames) if self._cfg.avg_frames in ciclo else 0
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
        payload = _build_recording_payload(data, self._cfg)
        csv_path = _EVIDENCE_DIR / f"waterfall_rec_{payload.timestamp}.csv"
        _write_recording_csv(csv_path, payload)
        self._log.info(
            f"Waterfall grabado: {csv_path} ({len(data)} frames)", "SA")
        if hasattr(self._s, "gp") and self._s.gp and self._s.gp.proyecto_activo:
            self._s.gp.registrar_evidencia(
                "waterfall_rec",
                f"Grabación de waterfall — {self._cfg.center_mhz:.3f} MHz",
                {"csv": str(csv_path), "frames": len(data)},
            )

    def _place_marker(self, idx: int) -> None:
        frame = self._double_buf.read()
        if frame is None:
            return
        pows = frame.powers_dbm.copy()
        if idx == 1 and self._markers[0].active:
            m0c = int(
                np.argmin(np.abs(frame.freqs_mhz - self._markers[0].freq_mhz)))
            pows[max(0, m0c - 5):min(len(pows), m0c + 5)] = -999.0
        pi = int(np.argmax(pows))
        self._markers[idx] = Marker(
            name=f"M{idx + 1}",
            freq_mhz=float(frame.freqs_mhz[pi]),
            power_dbm=float(frame.powers_dbm[pi]),
            active=True,
        )

    def _export(self) -> None:
        frame = self._double_buf.read()
        if frame is None:
            return
        payload = _build_export_payload(
            frame, self._cfg, self._platform, self._sdr.hw_name, self._markers
        )
        stem = f"spectrum_{self._cfg.center_mhz:.3f}MHz_{payload.timestamp}"

        json_path = _EVIDENCE_DIR / f"{stem}.json"
        json_path.write_text(
            _serialize_export_to_json(payload), encoding="utf-8")

        csv_path = _EVIDENCE_DIR / f"{stem}.csv"
        _write_export_csv(csv_path, payload)

        if hasattr(self._s, "gp") and self._s.gp and self._s.gp.proyecto_activo:
            self._s.gp.registrar_evidencia(
                "spectrum",
                f"Frame exportado — {self._cfg.center_mhz:.3f} MHz "
                f"({self._cfg.band_label or 'freq libre'})",
                {"json": str(json_path), "csv": str(csv_path)},
            )
        log.info("Exportado → %s", json_path)


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
    for threshold, style in _COLOR_THRESHOLDS:
        if r >= threshold:
            return style
    return "dim green"


def _wf_style(power: float, threshold: float) -> str:
    delta = power - threshold
    for threshold_val, style in _WF_DELTA_THRESHOLDS:
        if delta >= threshold_val:
            return style
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
    n = min(6, W // 12)
    line = [" "] * W
    for pos, f in zip(np.linspace(0, W - 1, n).astype(int), np.linspace(start, end, n)):
        lbl = f"{f:.1f}"
        s = max(0, pos - len(lbl) // 2)
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
