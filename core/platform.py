from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

# Paths de identificación de hardware
_DT_MODEL       = Path("/proc/device-tree/model")
_DT_BASE        = Path("/sys/firmware/devicetree/base/model")
_DT_COMPAT      = Path("/proc/device-tree/compatible")
_CPUINFO        = Path("/proc/cpuinfo")
_DSI_DRM        = Path("/sys/class/drm/card0/card0-DSI-1")
_FRAMEBUFFER    = Path("/dev/fb0")
_TTYAMA         = Path("/dev/ttyAMA0")

class Platform(Enum):
    UCONSOLE    = auto()   # ClockworkPi uConsole (cualquier modelo)
    TERMUX      = auto()   # Android / Termux
    KALI        = auto()   # Kali Linux / Debian / Ubuntu x86-64
    RASPI       = auto()   # Raspberry Pi genérico (no uConsole)
    GENERIC     = auto()   # Linux genérico

@dataclass(frozen=True)
class ScreenProfile:
    cols:        int    = 80
    rows:        int    = 24
    width_px:    int    = 0
    height_px:   int    = 0
    has_dsi:     bool   = False
    is_tty:      bool   = False
    dpi:         int    = 0

    @property
    def is_wide(self) -> bool:
        return self.cols >= 140

    @property
    def spectrum_width(self) -> int:
        # Deja 10 cols para etiquetas dBm + bordes del panel
        return max(60, min(self.cols - 12, 200))

    @property
    def spectrum_height(self) -> int:
        # Deja 8 filas para header, marcadores, controles y bordes
        return max(10, min(self.rows - 9, 30))

@dataclass(frozen=True)
class PlatformInfo:
    kind:     Platform
    screen:   ScreenProfile
    machine:  str
    hostname: str
    model:    str
    is_tty:   bool

    @property
    def is_uconsole(self) -> bool:
        return self.kind == Platform.UCONSOLE

    @property
    def is_termux(self) -> bool:
        return self.kind == Platform.TERMUX

    @property
    def is_arm(self) -> bool:
        return self.machine in ("aarch64", "armv7l", "armv6l")

    def __str__(self) -> str:
        parts = [self.kind.name]
        if self.model:
            parts.append(self.model)
        parts.append(f"{self.screen.cols}×{self.screen.rows}")
        return " | ".join(parts)

# Cache de instancia única
_cached: Optional[PlatformInfo] = None

def detect(force: bool = False) -> PlatformInfo:
    global _cached
    if _cached is not None and not force:
        return _cached
    _cached = _build()
    return _cached

# Construcción de PlatformInfo

def _build() -> PlatformInfo:
    machine  = platform.machine()
    hostname = platform.node()
    model    = _read_model()
    is_tty   = _is_tty()
    screen   = _build_screen(model, is_tty)
    kind     = _classify(model, machine)

    return PlatformInfo(
        kind=kind,
        screen=screen,
        machine=machine,
        hostname=hostname,
        model=model,
        is_tty=is_tty,
    )

def _read_model() -> str:
    for path in (_DT_MODEL, _DT_BASE, _DT_COMPAT):
        if path.exists():
            try:
                return path.read_bytes().rstrip(b"\x00").decode("utf-8", errors="ignore").strip()
            except OSError:
                pass
    return ""

def _classify(model: str, machine: str) -> Platform:
    model_lo = model.lower()

    # Termux — siempre primero, independiente de la arquitectura
    if os.environ.get("TERMUX_VERSION") or Path("/data/data/com.termux").exists():
        return Platform.TERMUX

    # uConsole — identificación definitiva por device-tree
    if "uconsole" in model_lo or "clockworkpi" in model_lo:
        return Platform.UCONSOLE

    # uConsole — fallback por hardware cuando no hay device-tree
    if machine == "aarch64" and _is_bcm2711() and _DSI_DRM.exists():
        return Platform.UCONSOLE

    # Raspberry Pi genérico
    if "raspberry" in model_lo or "raspberrypi" in model_lo or (
        machine in ("aarch64", "armv7l") and _is_bcm27xx()
    ):
        return Platform.RASPI

    return Platform.KALI if sys.platform == "linux" else Platform.GENERIC

def _build_screen(model: str, is_tty: bool) -> ScreenProfile:
    # Intentar tamaño real del terminal
    cols, rows = _terminal_size()

    # uConsole — pantalla DSI 1280×480
    if "uconsole" in model.lower() or "clockworkpi" in model.lower():
        w_px, h_px, dpi = 1280, 480, 227
        # Si el terminal reportó algo raro, usar heurística para esta pantalla
        if cols < 80 or rows < 20:
            cols = 160
            rows = 40
        return ScreenProfile(
            cols=cols, rows=rows,
            width_px=w_px, height_px=h_px,
            has_dsi=True, is_tty=is_tty, dpi=dpi,
        )

    # uConsole por hardware (sin device-tree)
    if _DSI_DRM.exists():
        px = _read_drm_resolution()
        if cols < 80:
            cols = 160
            rows = 40
        return ScreenProfile(
            cols=cols, rows=rows,
            width_px=px[0], height_px=px[1],
            has_dsi=True, is_tty=is_tty,
        )

    return ScreenProfile(cols=cols, rows=rows, is_tty=is_tty)

def _terminal_size() -> tuple[int, int]:
    # 1. os.get_terminal_size (stdout)
    for fd in (1, 2, 0):
        try:
            sz = os.get_terminal_size(fd)
            if sz.columns > 10 and sz.lines > 5:
                return sz.columns, sz.lines
        except OSError:
            pass

    # 2. Variables de entorno de algunos emuladores
    try:
        cols = int(os.environ.get("COLUMNS", "0"))
        rows = int(os.environ.get("LINES",   "0"))
        if cols > 10 and rows > 5:
            return cols, rows
    except ValueError:
        pass

    # 3. Framebuffer — estimar desde resolución de pantalla
    fb_info = _read_fb_resolution()
    if fb_info:
        w_px, h_px = fb_info
        # Suponemos fuente monoespaciada de ~8×16 px
        return w_px // 8, h_px // 16

    return 80, 24

def _is_tty() -> bool:
    return (
        not os.environ.get("DISPLAY")
        and not os.environ.get("WAYLAND_DISPLAY")
        and os.environ.get("XDG_SESSION_TYPE", "") not in ("x11", "wayland")
    )

def _is_bcm2711() -> bool:
    return _cpuinfo_has("bcm2711")

def _is_bcm27xx() -> bool:
    return any(_cpuinfo_has(s) for s in ("bcm2835", "bcm2836", "bcm2837", "bcm2711"))

def _cpuinfo_has(token: str) -> bool:
    if not _CPUINFO.exists():
        return False
    try:
        return token in _CPUINFO.read_text(errors="ignore").lower()
    except OSError:
        return False

def _read_drm_resolution() -> tuple[int, int]:
    modes_path = _DSI_DRM / "modes"
    if modes_path.exists():
        try:
            first = modes_path.read_text().splitlines()[0].strip()
            w, _, h = first.partition("x")
            return int(w), int(h)
        except (ValueError, IndexError, OSError):
            pass
    return 1280, 480

def _read_fb_resolution() -> tuple[int, int] | None:
    virtual = Path("/sys/class/graphics/fb0/virtual_size")
    if virtual.exists():
        try:
            w_str, _, h_str = virtual.read_text().strip().partition(",")
            return int(w_str), int(h_str)
        except (ValueError, OSError):
            pass
    return None
