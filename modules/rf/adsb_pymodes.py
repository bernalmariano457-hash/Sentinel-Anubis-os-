from __future__ import annotations

import logging
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from math import atan2, cos, degrees, radians, sin, sqrt
from typing import TYPE_CHECKING, Callable, Deque

import numpy as np
from rich import box
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from rich.console import Console

from modules.rf.rf_source import Source, rtlsdr_source, open_backend

log = logging.getLogger("sentinel.rf.adsb")

try:
    from pyModeS.message import Message as _PMMessage
    from pyModeS.position import (
        airborne_position_pair as _pm_pair,
        airborne_position_with_ref as _pm_ref,
    )
    _PYMODES_OK = True
except ImportError:
    _PYMODES_OK = False
    _PMMessage = None
    _pm_pair = None
    _pm_ref = None

IcaoHex = str

CPR_MAX_AGE = 10.0
STALE_TIMEOUT = 60.0
HISTORY = 30
RATE_WINDOW = 90
CRC24_POLY = 0xFFF409

SQUAWK_MAP: dict[str, tuple[str, str]] = {
    "7500": ("HIJACK", "bold white on red"),
    "7600": ("RADIO",  "bold yellow on dark_red"),
    "7700": ("MAYDAY", "bold white on dark_red"),
}

_BANDS: list[tuple[int, int, str]] = [
    (0x0C0000, 0x0FFFFF, "🇫🇷"), (0x380000, 0x38FFFF, "🇩🇰"),
    (0x3C0000, 0x3FFFFF, "🇩🇪"), (0x400000, 0x43FFFF, "🇪🇸"),
    (0x480000, 0x48FFFF, "🇳🇱"), (0x4CA000, 0x4CAFFF, "🇮🇪"),
    (0x500000, 0x5003FF, "🇧🇪"), (0x700000, 0x71FFFF, "🇲🇽"),
    (0x7C0000, 0x7FFFFF, "🇦🇺"), (0x800000, 0x83FFFF, "🇮🇳"),
    (0xA00000, 0xAFFFFF, "🇺🇸"), (0xC00000, 0xC3FFFF, "🇨🇦"),
    (0xE00000, 0xE3FFFF, "🇦🇷"),
]


def _flag(icao: IcaoHex) -> str:
    n = int(icao, 16)
    for lo, hi, f in _BANDS:
        if lo <= n <= hi:
            return f
    return "  "


def _crc24(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= CRC24_POLY
    return crc & 0xFFFFFF


def _crc_ok(raw: bytes) -> bool:
    return _crc24(raw[:-3]) == int.from_bytes(raw[-3:], "big")


_R = 6_371.0


def _haversine(la1: float, lo1: float, la2: float, lo2: float) -> float:
    φ1, φ2 = radians(la1), radians(la2)
    Δφ, Δλ = radians(la2 - la1), radians(lo2 - lo1)
    a = sin(Δφ / 2) ** 2 + cos(φ1) * cos(φ2) * sin(Δλ / 2) ** 2
    return _R * 2 * atan2(sqrt(a), sqrt(1 - a))


def _bearing(la1: float, lo1: float, la2: float, lo2: float) -> float:
    Δλ = radians(lo2 - lo1)
    y = sin(Δλ) * cos(radians(la2))
    x = cos(radians(la1)) * sin(radians(la2)) - \
        sin(radians(la1)) * cos(radians(la2)) * cos(Δλ)
    return (degrees(atan2(y, x)) + 360) % 360


_ARROW = "↑↗→↘↓↙←↖"


def _compass(deg: float) -> str:
    return _ARROW[round(deg / 45) % 8]


@dataclass
class _CprFrame:
    lat: int
    lon: int
    fmt: int
    alt: float | None
    ts:  float


@dataclass
class Aircraft:
    icao:     IcaoHex
    cs:       str | None = None
    lat:      float | None = None
    lon:      float | None = None
    alt:      float | None = None
    gs:       float | None = None
    hdg:      float | None = None
    vr:       float | None = None
    squawk:   str | None = None
    ra:       bool = False
    msgs:     int = 0
    pos_msgs: int = 0
    last:     float = field(default_factory=time.monotonic)
    trail:    Deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=HISTORY), repr=False)
    _even:    _CprFrame | None = field(default=None, repr=False)
    _odd:     _CprFrame | None = field(default=None, repr=False)
    _gs_e:    float | None = field(default=None, repr=False)
    _hdg_e:   float | None = field(default=None, repr=False)
    _vr_e:    float | None = field(default=None, repr=False)

    _α = 0.25

    def _ema(self, prev: float | None, x: float) -> float:
        return x if prev is None else self._α * x + (1 - self._α) * prev

    def smooth_vel(self, gs: float | None, hdg: float | None,
                   vr: float | None) -> None:
        if gs is not None:
            self._gs_e = self._ema(self._gs_e,  gs)
            self.gs = self._gs_e
        if hdg is not None:
            self._hdg_e = self._ema(self._hdg_e, hdg)
            self.hdg = self._hdg_e
        if vr is not None:
            self._vr_e = self._ema(self._vr_e,  vr)
            self.vr = self._vr_e

    def absorb_cpr(self, frame: _CprFrame) -> bool:
        if not _PYMODES_OK:
            return False

        if frame.fmt == 0:
            self._even, other, newer = frame, self._odd,  True
        else:
            self._odd,  other, newer = frame, self._even, False

        if other is None or abs(frame.ts - other.ts) > CPR_MAX_AGE:
            return False

        if self.lat is not None:
            try:
                la, lo = _pm_ref(
                    frame.fmt, frame.lat, frame.lon, self.lat, self.lon)
                self._commit(la, lo, frame.alt or (
                    other.alt if other else None))
                return True
            except Exception:
                pass

        try:
            r = _pm_pair(
                self._even.lat, self._even.lon,
                self._odd.lat,  self._odd.lon,
                even_is_newer=newer,
            )
        except Exception:
            return False

        if r is None:
            return False

        self._commit(r[0], r[1], frame.alt or (other.alt if other else None))
        return True

    def _commit(self, lat: float, lon: float, alt: float | None) -> None:
        self.lat = lat
        self.lon = lon
        if alt is not None:
            self.alt = alt
        self.trail.append((lat, lon))
        self.pos_msgs += 1

    @property
    def age(self) -> float:
        return time.monotonic() - self.last

    @property
    def stale(self) -> bool:
        return self.age > STALE_TIMEOUT


class FlightTracker:
    def __init__(self, rx_lat: float = 0.0, rx_lon: float = 0.0) -> None:
        self._db:    dict[IcaoHex, Aircraft] = {}
        self._rx = (rx_lat, rx_lon)
        self._total = 0
        self._pos = 0
        self._err = 0
        self._t0 = time.monotonic()
        self._rbuf:  Deque[float] = deque(maxlen=RATE_WINDOW)
        self._rlast = time.monotonic()

    def feed(self, d: dict, ts: float | None = None) -> None:
        if not d.get("crc_valid", True):
            self._err += 1
            return

        icao = d.get("icao", "").upper()
        if not icao:
            return

        self._total += 1
        self._tick()

        t = ts or time.monotonic()
        ac = self._db.setdefault(icao, Aircraft(icao=icao, last=t))
        ac.last = t
        ac.msgs += 1

        bds = d.get("bds", "")
        df = d.get("df", 0)

        if bds == "0,8":
            cs = d.get("callsign", "").strip()
            if cs:
                ac.cs = cs

        elif bds == "0,5" and "cpr_lat" in d:
            frame = _CprFrame(
                d["cpr_lat"], d["cpr_lon"],
                d["cpr_format"], d.get("altitude"), t,
            )
            if ac.absorb_cpr(frame):
                self._pos += 1

        elif bds == "0,9":
            ac.smooth_vel(
                d.get("groundspeed"),
                d.get("track"),
                d.get("vertical_rate"),
            )

        if d.get("altitude") is not None:
            ac.alt = d["altitude"]
        if d.get("squawk"):
            ac.squawk = str(d["squawk"])
        if df in (16, 17):
            ac.ra = bool(d.get("ra_active", False))

    def feed_hex(self, h: str, ts: float | None = None) -> None:
        if not _PYMODES_OK:
            return
        try:
            self.feed(_PMMessage(h.upper()).decode(), ts)
        except Exception:
            pass

    def _tick(self) -> None:
        now = time.monotonic()
        if now - self._rlast >= 1.0:
            self._rbuf.append(self._total)
            self._rlast = now

    def live(self) -> list[Aircraft]:
        return sorted(
            (ac for ac in self._db.values() if not ac.stale),
            key=lambda a: a.last, reverse=True,
        )

    def dist(self, ac: Aircraft) -> float | None:
        if ac.lat is None or self._rx == (0.0, 0.0):
            return None
        return _haversine(*self._rx, ac.lat, ac.lon)

    def brg(self, ac: Aircraft) -> float | None:
        if ac.lat is None:
            return None
        return _bearing(*self._rx, ac.lat, ac.lon)

    def rate(self) -> float:
        buf = list(self._rbuf)
        return (buf[-1] - buf[-2]) if len(buf) >= 2 else self._total / max(1.0, self.up())

    def spark(self, w: int = 20) -> str:
        _B = " ▁▂▃▄▅▆▇█"
        buf = list(self._rbuf)
        if len(buf) < 2:
            return " " * w
        rs = [max(0, buf[i] - buf[i - 1]) for i in range(1, len(buf))]
        mx = max(rs) or 1
        return "".join(_B[min(8, int(v / mx * 8))] for v in rs[-w:])

    def up(self) -> float:
        return max(1.0, time.monotonic() - self._t0)


def demodulate(raw_iq: np.ndarray, sr: int = 2_000_000) -> list[bytes]:
    sps = sr // 1_000_000
    pre = 8 * sps

    I = raw_iq[0::2].astype(np.float32) - 127.5
    Q = raw_iq[1::2].astype(np.float32) - 127.5
    amp = np.hypot(I, Q)

    mad = np.median(np.abs(amp - np.median(amp)))
    noise = mad * 1.4826
    thr = max(noise * 3.5, 20.0)

    n = len(amp)
    L = n - pre - 112 * sps - 4
    if L <= 0:
        return []

    score = np.zeros(L, np.float32)
    for off in (0, 1, 3, 4):
        score += amp[off * sps: off * sps + L]
    for off in (2, 5, 6, 8):
        end = off * sps + L
        if end <= n:
            score -= amp[off * sps: end] * 0.5

    out: list[bytes] = []
    i = 0
    while i < L - 1:
        if score[i] < thr * 3:
            i += 1
            continue

        lo = max(0, i - 1)
        hi = min(L, i + 2)
        i = lo + int(np.argmax(score[lo:hi]))

        bs = i + pre
        seg = amp[bs: bs + 112 * sps]
        if len(seg) < 112 * sps:
            break

        pwr = seg.reshape(112, sps).mean(axis=1)
        msg_thr = (pwr.max() + pwr.min()) * 0.5
        bits = (pwr > msg_thr).astype(np.uint8)

        df_val = int.from_bytes(np.packbits(
            bits[:8]).tobytes()[:1], "big") >> 3
        n_bits = 112 if df_val >= 16 else 56
        raw_msg = np.packbits(bits[:n_bits]).tobytes()[: n_bits // 8]

        if _crc_ok(raw_msg):
            out.append(raw_msg)

        i += pre + n_bits * sps

    return out


_ALT_BANDS = (
    (10_000, "bright_green"), (18_000, "green"),
    (28_000, "yellow"),       (36_000, "bright_yellow"),
    (99_999, "bright_cyan"),
)


def _alt_color(alt: float | None) -> str:
    if alt is None:
        return "dim white"
    for limit, c in _ALT_BANDS:
        if alt < limit:
            return c
    return "bright_cyan"


def _v(x, fmt: str = ".0f") -> str:
    return f"{x:{fmt}}" if x is not None else "[dim]·[/dim]"


def _vr_str(vr: float | None) -> str:
    if vr is None:
        return "[dim]·[/dim]"
    sym = "↑" if vr > 64 else "↓" if vr < -64 else "→"
    color = "green" if vr > 64 else "red" if vr < -64 else "dim"
    return f"[{color}]{sym}{abs(vr):.0f}[/{color}]"


def _sq_str(sq: str | None) -> str:
    if sq is None:
        return "[dim]·[/dim]"
    if sq in SQUAWK_MAP:
        label, style = SQUAWK_MAP[sq]
        return f"[{style}] {sq} {label} [/{style}]"
    return f"[yellow]{sq}[/yellow]"


def _age_bar(age: float, width: int = 6) -> str:
    ratio = min(1.0, age / STALE_TIMEOUT)
    filled = round(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    color = "green" if ratio < 0.33 else "yellow" if ratio < 0.66 else "red"
    return f"[{color}]{bar}[/{color}]"


def _table(tracker: FlightTracker) -> Table:
    t = Table(
        show_header=True,
        header_style="bold grey82",
        border_style="grey27",
        box=box.SIMPLE_HEAD,
        row_styles=["", "on grey7"],
        expand=True,
        show_edge=False,
        padding=(0, 1),
    )
    cols = [
        ("",       dict(width=2,  no_wrap=True)),
        ("ICAO",   dict(width=7,  style="bold white",  no_wrap=True)),
        ("CS",     dict(width=8,  style="bright_cyan", no_wrap=True)),
        ("Lat",    dict(width=10, justify="right")),
        ("Lon",    dict(width=11, justify="right")),
        ("Alt ft", dict(width=8,  justify="right")),
        ("GS kt",  dict(width=6,  justify="right")),
        ("Hdg",    dict(width=7,  justify="right")),
        ("VS",     dict(width=8,  justify="right")),
        ("Squawk", dict(width=14, justify="center")),
        ("Dist",   dict(width=7,  justify="right", style="dim")),
        ("Brg",    dict(width=5,  justify="center", style="dim")),
        ("Msgs",   dict(width=5,  justify="right", style="dim")),
        ("Vida",   dict(width=6,  justify="center")),
    ]
    for col, kw in cols:
        t.add_column(col, **kw)

    for ac in tracker.live():
        ac_ = _alt_color(ac.alt)
        row_ = "on dark_red" if ac.ra else ("dim" if ac.age > 30 else "")
        dist = tracker.dist(ac)
        brg = tracker.brg(ac)
        hdg = f"{_v(ac.hdg, '.0f')} {_compass(ac.hdg) if ac.hdg is not None else ''}"
        t.add_row(
            _flag(ac.icao),
            ac.icao,
            ac.cs or "[dim]·[/dim]",
            _v(ac.lat, "+.4f") if ac.lat is not None else "[dim]·[/dim]",
            _v(ac.lon, "+.4f") if ac.lon is not None else "[dim]·[/dim]",
            f"[{ac_}]{_v(ac.alt)}[/{ac_}]",
            _v(ac.gs),
            hdg,
            _vr_str(ac.vr),
            _sq_str(ac.squawk),
            f"{dist:.0f}" if dist else "[dim]·[/dim]",
            f"{_compass(brg)} {brg:.0f}°" if brg else "[dim]·[/dim]",
            str(ac.msgs),
            _age_bar(ac.age),
            style=row_,
        )
    return t


def _stats(tracker: FlightTracker) -> Panel:
    n = len(tracker.live())
    spark = tracker.spark(18)
    body = Text.assemble(
        ("Aviones  ", "dim"), (f"{n:>4}\n",              "bold bright_white"),
        ("Msgs     ", "dim"), (f"{tracker._total:>4}\n", "white"),
        ("Pos.     ", "dim"), (f"{tracker._pos:>4}\n",   "bright_green"),
        ("CRC err  ", "dim"), (f"{tracker._err:>4}\n",   "bright_red"),
        ("msg/s    ", "dim"), (f"{tracker.rate():>4.1f}\n", "bright_yellow"),
        ("Uptime   ", "dim"), (f"{tracker.up():>4.0f}s\n\n", "dim"),
        (spark,               "bright_blue"),
    )
    return Panel(body, title="[dim]Stats[/dim]", border_style="grey27", padding=(0, 1))


def _layout(tracker: FlightTracker) -> Layout:
    n = len(tracker.live())
    hdr = Text(
        f"  ✈  ADS-B · 1090 MHz · {n} aviones · pyModeS  ",
        style="bold white on grey15", justify="center",
    )
    root = Layout()
    root.split_column(Layout(name="h", size=1), Layout(name="b"))
    root["b"].split_row(Layout(name="tbl", ratio=5),
                        Layout(name="st", minimum_size=22))
    root["h"].update(hdr)
    root["tbl"].update(_table(tracker))
    root["st"].update(_stats(tracker))
    return root


class ADSBPipeline:
    def __init__(
        self,
        source:     Source,
        sr:         int = 2_000_000,
        hz:         int = 4,
        rx_lat:     float = 0.0,
        rx_lon:     float = 0.0,
        console:    "Console" | None = None,
    ) -> None:
        from rich.console import Console as _Console
        self._src = source
        self._sr = sr
        self._hz = hz
        self.tracker = FlightTracker(rx_lat, rx_lon)
        self._con = console or _Console()

    def feed_hex(self, h: str, ts: float | None = None) -> None:
        self.tracker.feed_hex(h, ts)

    def _consume(self, iq: bytes) -> None:
        arr = np.frombuffer(iq, dtype=np.uint8)
        ts = time.monotonic()
        if not _PYMODES_OK:
            return
        for raw in demodulate(arr, self._sr):
            try:
                self.tracker.feed(_PMMessage(raw.hex().upper()).decode(), ts)
            except Exception:
                pass

    def run(self) -> None:
        if not _PYMODES_OK:
            self._con.print(
                "[bold red]pyModeS no instalado — pip install pyModeS[/bold red]")
            return
        with Live(
            _layout(self.tracker),
            console=self._con,
            refresh_per_second=self._hz,
            screen=True,
        ) as live:
            try:
                while True:
                    chunk = self._src()
                    if chunk:
                        self._consume(chunk)
                    live.update(_layout(self.tracker))
                    time.sleep(1.0 / self._hz)
            except KeyboardInterrupt:
                pass
        self._con.print("[bold green]✈  Sesión finalizada[/bold green]")


_HEX_DEMO = [
    "8D40621D58C382D690C8AC2863A7",
    "8D40621D58C386435CC412692AD6",
    "8D485020994409940838175B284F",
    "8D4840D6202CC371C32CE0576098",
    "8D44067958BF073CF8B0E10000CD",
    "8D44067958BF0469EBB8C520FAFF",
    "8D400A3458A9808C72F60808A5BB",
    "2800000000496C",
    "8DA7F6428931357100E88ABB3FB2",
    "8DA7F6428931757219C0ABD9C514",
    "8DA7F642990A4109040C0825BC2E",
    "8DA7F6420104A4B8E35F8A8AE3B1",
]


def run_demo(
    rx_lat:  float = 0.0,
    rx_lon:  float = 0.0,
    console: "Console" | None = None,
) -> None:
    from rich.console import Console as _Console
    con = console or _Console()
    if not _PYMODES_OK:
        con.print(
            "[bold red]pyModeS no instalado — pip install pyModeS[/bold red]")
        return
    tracker = FlightTracker(rx_lat, rx_lon)
    idx = 0
    with Live(
        _layout(tracker),
        console=con,
        refresh_per_second=4,
        screen=True,
    ) as live:
        try:
            while True:
                tracker.feed_hex(_HEX_DEMO[idx % len(_HEX_DEMO)])
                idx += 1
                live.update(_layout(tracker))
                time.sleep(0.3)
        except KeyboardInterrupt:
            pass

#  MÓDULO SENTINEL — AircraftMonitor
#  Mismo patrón que GeoPrecise / OSINTEngine / NOAADecoder.
#  Uso:  AircraftMonitor(sentinel).menu()


class AircraftMonitor:
    _MODULE = "ADS-B"

    def __init__(self, sentinel: object) -> None:
        self._s = sentinel
        self._con: "Console" = getattr(sentinel, "console", None)
        if self._con is None:
            from rich.console import Console as _Console
            self._con = _Console()
        self._log = getattr(sentinel, "log", None)

        # Parámetros de hardware desde sentinel.rf cuando esté presente
        rf_cfg = getattr(getattr(sentinel, "rf", None), "cfg", None)
        hw = getattr(rf_cfg, "hardware", None)
        self._gain = float(getattr(hw, "gain_db",        49.6))
        self._rate = int(getattr(hw, "sample_rate",    2_000_000))
        self._ppm = int(getattr(hw, "ppm_correction", 0))
        self._idx = int(getattr(hw, "device_index",   0))

        # Coordenadas del receptor (tomadas de sentinel.geo si existe)
        geo = getattr(sentinel, "geo", None)
        pos = getattr(geo,     "position", None)
        self._rx_lat = float(getattr(pos, "lat", 0.0))
        self._rx_lon = float(getattr(pos, "lon", 0.0))

    # Helpers privados
    def _info(self, msg: str) -> None:
        self._con.print(f"[cyan][{self._MODULE}][/cyan] {msg}")
        if self._log:
            self._log.info(msg, self._MODULE)

    def _warn(self, msg: str) -> None:
        self._con.print(f"[yellow][!][{self._MODULE}] {msg}[/yellow]")
        if self._log:
            self._log.warning(msg, self._MODULE)

    def _err(self, msg: str) -> None:
        self._con.print(f"[bold red][✗][{self._MODULE}] {msg}[/bold red]")
        if self._log:
            self._log.error(msg, self._MODULE)

    # API pública
    def menu(self) -> None:
        from rich.prompt import Prompt
        from rich.panel import Panel

        while True:
            self._con.print(Panel(
                "[1] Monitor en vivo (RTL-SDR)\n"
                "[2] Demo sin hardware\n"
                "[3] Configurar receptor (lat/lon/gain)\n"
                "[0] Volver",
                title=f"[bold cyan]✈  {self._MODULE}[/bold cyan]",
                border_style="cyan",
            ))
            opcion = Prompt.ask(
                "[bold cyan]ADS-B[/bold cyan]",
                choices=["0", "1", "2", "3"],
                default="2",
                console=self._con,
            )
            if opcion == "0":
                break
            elif opcion == "1":
                self._iniciar_rtlsdr()
            elif opcion == "2":
                self._iniciar_demo()
            elif opcion == "3":
                self._configurar()

    def _iniciar_rtlsdr(self) -> None:
        if not _PYMODES_OK:
            self._err("pyModeS no instalado. Ejecuta: pip install pyModeS")
            return
        self._info(
            f"Iniciando captura RTL-SDR — "
            f"1090 MHz  gain={self._gain} dB  sr={self._rate/1e6:.1f} MSPS"
        )
        try:
            source = rtlsdr_source(
                1_090_000_000, self._rate, self._gain, self._ppm, self._idx
            )
        except Exception as exc:
            self._err(f"RTL-SDR no disponible: {exc}")
            self._warn("Iniciando modo demo como alternativa…")
            self._iniciar_demo()
            return
        ADSBPipeline(
            source,
            sr=self._rate,
            rx_lat=self._rx_lat,
            rx_lon=self._rx_lon,
            console=self._con,
        ).run()

    def _iniciar_demo(self) -> None:
        self._info("Modo demo ADS-B (sin hardware SDR)")
        run_demo(self._rx_lat, self._rx_lon, self._con)

    def _configurar(self) -> None:
        from rich.prompt import Prompt
        try:
            self._rx_lat = float(Prompt.ask(
                "Latitud del receptor", default=str(self._rx_lat), console=self._con
            ))
            self._rx_lon = float(Prompt.ask(
                "Longitud del receptor", default=str(self._rx_lon), console=self._con
            ))
            self._gain = float(Prompt.ask(
                "Ganancia RTL-SDR (dB)", default=str(self._gain), console=self._con
            ))
            self._info(
                f"Receptor configurado — "
                f"lat={self._rx_lat:.4f}° lon={self._rx_lon:.4f}° "
                f"gain={self._gain} dB"
            )
        except ValueError as exc:
            self._err(f"Valor inválido: {exc}")
