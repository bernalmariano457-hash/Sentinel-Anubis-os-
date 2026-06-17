from __future__ import annotations

import logging
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from math import acos, atan2, cos, degrees, floor, pi, radians, sin, sqrt
from typing import TYPE_CHECKING, Final, Literal, Optional, Sequence

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

log: logging.Logger = logging.getLogger("sentinel.rf.adsb")

try:
    from pyModeS.message import Message as _PMMessage
    from pyModeS.position import (
        airborne_position_pair as _pm_pair,
        airborne_position_with_ref as _pm_ref,
    )
    _PYMODES_OK: bool = True
except ImportError:
    _PYMODES_OK = False
    _PMMessage = None
    _pm_pair = None
    _pm_ref = None


IcaoHex = str
CprFormat = Literal[0, 1]

CPR_MAX_AGE_S: Final[float] = 10.0
STALE_TIMEOUT_S: Final[float] = 60.0
TRAIL_HISTORY_LEN: Final[int] = 30
RATE_WINDOW_S: Final[int] = 90
NZ: Final[int] = 15

SQUAWK_EMERGENCY_MAP: Final[dict[str, tuple[str, str]]] = {
    "7500": ("HIJACK", "bold white on red"),
    "7600": ("RADIO",  "bold yellow on dark_red"),
    "7700": ("MAYDAY", "bold white on dark_red"),
}

ICAO_COUNTRY_BANDS: Final[list[tuple[int, int, str]]] = [
    (0x0C0000, 0x0FFFFF, "FR"), (0x380000, 0x38FFFF, "DK"),
    (0x3C0000, 0x3FFFFF, "DE"), (0x400000, 0x43FFFF, "ES"),
    (0x480000, 0x48FFFF, "NL"), (0x4CA000, 0x4CAFFF, "IE"),
    (0x500000, 0x5003FF, "BE"), (0x700000, 0x71FFFF, "MX"),
    (0x7C0000, 0x7FFFFF, "AU"), (0x800000, 0x83FFFF, "IN"),
    (0xA00000, 0xAFFFFF, "US"), (0xC00000, 0xC3FFFF, "CA"),
    (0xE00000, 0xE3FFFF, "AR"),
]

_CRC24_POLY: Final[int] = 0xFFF409
_CRC24_LUT: Final[list[int]] = [0] * 256


def _build_crc24_lut() -> None:
    for byte_val in range(256):
        remainder = byte_val << 16
        for _ in range(8):
            remainder <<= 1
            if remainder & 0x1000000:
                remainder ^= _CRC24_POLY
        _CRC24_LUT[byte_val] = remainder & 0xFFFFFF


_build_crc24_lut()


def crc24_lut(payload: bytes) -> int:
    crc = 0
    for b in payload:
        crc = _CRC24_LUT[(crc >> 16) ^ b] ^ ((crc & 0xFFFF) << 8)
    return crc & 0xFFFFFF


def is_crc_valid(raw_frame: bytes) -> bool:
    return crc24_lut(raw_frame[:-3]) == int.from_bytes(raw_frame[-3:], "big")


def extract_icao_from_df17(raw_frame: bytes) -> str:
    return ((raw_frame[1] << 16) | (raw_frame[2] << 8) | raw_frame[3]).to_bytes(3, "big").hex().upper()


def extract_downlink_format(raw_frame: bytes) -> int:
    return (raw_frame[0] & 0xF8) >> 3


def extract_type_code(raw_frame: bytes) -> int:
    return (raw_frame[4] & 0xF8) >> 3


def extract_cpr_lat_raw(raw_frame: bytes) -> int:
    return ((raw_frame[6] & 0x03) << 15) | (raw_frame[7] << 7) | (raw_frame[8] >> 1)


def extract_cpr_lon_raw(raw_frame: bytes) -> int:
    return ((raw_frame[8] & 0x01) << 16) | (raw_frame[9] << 8) | raw_frame[10]


def extract_cpr_format_bit(raw_frame: bytes) -> CprFormat:
    return 1 if (raw_frame[6] & 0x04) else 0


def extract_gillham_altitude_ft(raw_frame: bytes) -> Optional[float]:
    raw13 = ((raw_frame[5] << 4) | (raw_frame[6] >> 4)) & 0x1FFF
    q_bit = (raw13 >> 4) & 1
    if q_bit:
        n = ((raw13 & 0x1F80) >> 2) | (raw13 & 0x3F)
        return float(n * 25 - 1000)
    return None


_EARTH_RADIUS_KM: Final[float] = 6_371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi * 0.5) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda * 0.5) ** 2
    return _EARTH_RADIUS_KM * 2.0 * atan2(sqrt(a), sqrt(1.0 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlambda = radians(lon2 - lon1)
    y = sin(dlambda) * cos(radians(lat2))
    x = cos(radians(lat1)) * sin(radians(lat2)) - sin(radians(lat1)) * cos(radians(lat2)) * cos(dlambda)
    return (degrees(atan2(y, x)) + 360.0) % 360.0


def icao_country_code(icao_hex: IcaoHex) -> str:
    icao_int = int(icao_hex, 16)
    for lo, hi, cc in ICAO_COUNTRY_BANDS:
        if lo <= icao_int <= hi:
            return cc
    return "--"


_COMPASS_ARROW: Final[str] = "^ ne> se v sw< nw"[::2]


def compass_arrow(heading_deg: float) -> str:
    return _COMPASS_ARROW[round(heading_deg / 45.0) % 8]


def _cpr_nl(lat: float) -> int:
    lat_abs = abs(lat)
    if lat_abs == 0.0:
        return 59
    if lat_abs >= 87.0:
        return 1
    a = 1.0 - cos(pi / (2.0 * NZ))
    b = cos(radians(lat_abs)) ** 2
    if b == 0.0:
        return 1
    c = a / b
    if c > 1.0:
        return 1
    return max(1, int(floor(2.0 * pi / acos(1.0 - c))))


def decode_cpr_global_position(
    even_lat_raw: int,
    even_lon_raw: int,
    odd_lat_raw: int,
    odd_lon_raw: int,
    even_is_newer: bool,
) -> Optional[tuple[float, float]]:
    dlat_even = 360.0 / (4 * NZ)
    dlat_odd  = 360.0 / (4 * NZ - 1)

    lat_cpr_even = even_lat_raw / 131072.0
    lat_cpr_odd  = odd_lat_raw  / 131072.0
    lon_cpr_even = even_lon_raw / 131072.0
    lon_cpr_odd  = odd_lon_raw  / 131072.0

    j = floor(59.0 * lat_cpr_even - 60.0 * lat_cpr_odd + 0.5)

    lat_even = dlat_even * ((j % 60) + lat_cpr_even)
    lat_odd  = dlat_odd  * ((j % 59) + lat_cpr_odd)

    if lat_even >= 270.0:
        lat_even -= 360.0
    if lat_odd >= 270.0:
        lat_odd  -= 360.0

    nl_even = _cpr_nl(lat_even)
    nl_odd  = _cpr_nl(lat_odd)
    if nl_even != nl_odd:
        return None

    lat = lat_even if even_is_newer else lat_odd
    nl  = nl_even

    if even_is_newer:
        ni   = max(nl, 1)
        dlon = 360.0 / ni
        m    = floor(lon_cpr_even * (nl - 1) - lon_cpr_odd * nl + 0.5)
        lon  = dlon * ((m % ni) + lon_cpr_even)
    else:
        ni   = max(nl - 1, 1)
        dlon = 360.0 / ni
        m    = floor(lon_cpr_even * (nl - 1) - lon_cpr_odd * nl + 0.5)
        lon  = dlon * ((m % ni) + lon_cpr_odd)

    if lon >= 180.0:
        lon -= 360.0

    return (lat, lon)


def decode_cpr_local_position(
    cpr_fmt: CprFormat,
    cpr_lat_raw: int,
    cpr_lon_raw: int,
    ref_lat: float,
    ref_lon: float,
) -> Optional[tuple[float, float]]:
    dlat = 360.0 / (4 * NZ) if cpr_fmt == 0 else 360.0 / (4 * NZ - 1)
    lat_cpr = cpr_lat_raw / 131072.0
    lon_cpr = cpr_lon_raw / 131072.0

    j   = floor(ref_lat / dlat) + floor(0.5 + ((ref_lat % dlat) / dlat) - lat_cpr)
    lat = dlat * (j + lat_cpr)

    nl    = _cpr_nl(lat)
    ni    = max(nl - cpr_fmt, 1)
    dlon  = 360.0 / ni
    m     = floor(ref_lon / dlon) + floor(0.5 + ((ref_lon % dlon) / dlon) - lon_cpr)
    lon   = dlon * (m + lon_cpr)

    return (lat, lon)


@dataclass(slots=True)
class CprFrame:
    lat_raw:    int
    lon_raw:    int
    fmt:        CprFormat
    altitude_ft: Optional[float]
    timestamp_s: float


@dataclass
class AircraftState:
    icao:           IcaoHex
    callsign:       Optional[str] = None
    latitude:       Optional[float] = None
    longitude:      Optional[float] = None
    altitude_ft:    Optional[float] = None
    groundspeed_kt: Optional[float] = None
    track_deg:      Optional[float] = None
    vertical_rate:  Optional[float] = None
    squawk:         Optional[str] = None
    tcas_ra_active: bool = False
    msg_count:      int = 0
    pos_msg_count:  int = 0
    last_seen_s:    float = field(default_factory=time.monotonic)
    position_trail: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=TRAIL_HISTORY_LEN), repr=False
    )
    _cpr_even:      Optional[CprFrame] = field(default=None, repr=False)
    _cpr_odd:       Optional[CprFrame] = field(default=None, repr=False)
    _gs_ema:        Optional[float] = field(default=None, repr=False)
    _track_ema:     Optional[float] = field(default=None, repr=False)
    _vr_ema:        Optional[float] = field(default=None, repr=False)

    _EMA_ALPHA: float = field(default=0.25, init=False, repr=False)

    def _apply_ema(self, prev: Optional[float], sample: float) -> float:
        return sample if prev is None else self._EMA_ALPHA * sample + (1.0 - self._EMA_ALPHA) * prev

    def update_velocity_ema(
        self,
        groundspeed_kt: Optional[float],
        track_deg: Optional[float],
        vertical_rate: Optional[float],
    ) -> None:
        if groundspeed_kt is not None:
            self._gs_ema = self._apply_ema(self._gs_ema, groundspeed_kt)
            self.groundspeed_kt = self._gs_ema
        if track_deg is not None:
            self._track_ema = self._apply_ema(self._track_ema, track_deg)
            self.track_deg = self._track_ema
        if vertical_rate is not None:
            self._vr_ema = self._apply_ema(self._vr_ema, vertical_rate)
            self.vertical_rate = self._vr_ema

    def absorb_cpr_frame(self, frame: CprFrame) -> bool:
        if frame.fmt == 0:
            self._cpr_even, peer_frame, even_is_newer = frame, self._cpr_odd, True
        else:
            self._cpr_odd, peer_frame, even_is_newer = frame, self._cpr_even, False

        if peer_frame is None or abs(frame.timestamp_s - peer_frame.timestamp_s) > CPR_MAX_AGE_S:
            return False

        resolved_alt = frame.altitude_ft or (peer_frame.altitude_ft if peer_frame else None)

        if self.latitude is not None and self.longitude is not None:
            result = decode_cpr_local_position(
                frame.fmt, frame.lat_raw, frame.lon_raw,
                self.latitude, self.longitude,
            )
            if result is not None:
                self._commit_position(result[0], result[1], resolved_alt)
                return True

        if self._cpr_even is None or self._cpr_odd is None:
            return False

        result = decode_cpr_global_position(
            self._cpr_even.lat_raw, self._cpr_even.lon_raw,
            self._cpr_odd.lat_raw,  self._cpr_odd.lon_raw,
            even_is_newer=even_is_newer,
        )
        if result is None:
            return False

        self._commit_position(result[0], result[1], resolved_alt)
        return True

    def _commit_position(self, lat: float, lon: float, alt: Optional[float]) -> None:
        self.latitude  = lat
        self.longitude = lon
        if alt is not None:
            self.altitude_ft = alt
        self.position_trail.append((lat, lon))
        self.pos_msg_count += 1

    @property
    def age_s(self) -> float:
        return time.monotonic() - self.last_seen_s

    @property
    def is_stale(self) -> bool:
        return self.age_s > STALE_TIMEOUT_S


class FlightStateRegistry:
    def __init__(self, rx_lat: float = 0.0, rx_lon: float = 0.0) -> None:
        self._aircraft_db: dict[IcaoHex, AircraftState] = {}
        self._rx_position: tuple[float, float] = (rx_lat, rx_lon)
        self._total_msg_count: int = 0
        self._position_fix_count: int = 0
        self._crc_error_count: int = 0
        self._session_start_s: float = time.monotonic()
        self._rate_sample_buf: deque[float] = deque(maxlen=RATE_WINDOW_S)
        self._rate_last_sample_s: float = time.monotonic()

    def ingest_decoded(self, decoded: dict, timestamp_s: Optional[float] = None) -> None:
        if not decoded.get("crc_valid", True):
            self._crc_error_count += 1
            return

        icao = decoded.get("icao", "").upper()
        if not icao:
            return

        self._total_msg_count += 1
        self._advance_rate_sample()

        t = timestamp_s or time.monotonic()
        ac = self._aircraft_db.setdefault(icao, AircraftState(icao=icao, last_seen_s=t))
        ac.last_seen_s = t
        ac.msg_count += 1

        bds = decoded.get("bds", "")
        df  = decoded.get("df", 0)

        if bds == "0,8":
            cs = decoded.get("callsign", "").strip()
            if cs:
                ac.callsign = cs

        elif bds == "0,5" and "cpr_lat" in decoded:
            frame = CprFrame(
                lat_raw    = decoded["cpr_lat"],
                lon_raw    = decoded["cpr_lon"],
                fmt        = decoded["cpr_format"],
                altitude_ft= decoded.get("altitude"),
                timestamp_s= t,
            )
            if ac.absorb_cpr_frame(frame):
                self._position_fix_count += 1

        elif bds == "0,9":
            ac.update_velocity_ema(
                groundspeed_kt = decoded.get("groundspeed"),
                track_deg      = decoded.get("track"),
                vertical_rate  = decoded.get("vertical_rate"),
            )

        if decoded.get("altitude") is not None:
            ac.altitude_ft = decoded["altitude"]
        if decoded.get("squawk"):
            ac.squawk = str(decoded["squawk"])
        if df in (16, 17):
            ac.tcas_ra_active = bool(decoded.get("ra_active", False))

    def ingest_hex_frame(self, hex_str: str, timestamp_s: Optional[float] = None) -> None:
        if not _PYMODES_OK:
            return
        try:
            self.ingest_decoded(_PMMessage(hex_str.upper()).decode(), timestamp_s)
        except Exception:
            pass

    def _advance_rate_sample(self) -> None:
        now = time.monotonic()
        if now - self._rate_last_sample_s >= 1.0:
            self._rate_sample_buf.append(self._total_msg_count)
            self._rate_last_sample_s = now

    def active_aircraft(self) -> list[AircraftState]:
        return sorted(
            (ac for ac in self._aircraft_db.values() if not ac.is_stale),
            key=lambda a: a.last_seen_s,
            reverse=True,
        )

    def distance_to_aircraft_km(self, ac: AircraftState) -> Optional[float]:
        if ac.latitude is None or self._rx_position == (0.0, 0.0):
            return None
        return haversine_km(*self._rx_position, ac.latitude, ac.longitude)

    def bearing_to_aircraft_deg(self, ac: AircraftState) -> Optional[float]:
        if ac.latitude is None:
            return None
        return bearing_deg(*self._rx_position, ac.latitude, ac.longitude)

    def messages_per_second(self) -> float:
        buf = list(self._rate_sample_buf)
        if len(buf) >= 2:
            return float(buf[-1] - buf[-2])
        return self._total_msg_count / max(1.0, self.session_uptime_s())

    def session_uptime_s(self) -> float:
        return max(1.0, time.monotonic() - self._session_start_s)

    def sparkline(self, width: int = 20) -> str:
        _SPARK_CHARS = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
        buf = list(self._rate_sample_buf)
        if len(buf) < 2:
            return " " * width
        rates = [max(0, buf[i] - buf[i - 1]) for i in range(1, len(buf))]
        peak = max(rates) or 1
        return "".join(_SPARK_CHARS[min(8, int(v / peak * 8))] for v in rates[-width:])

    @property
    def total_messages(self) -> int:
        return self._total_msg_count

    @property
    def total_position_fixes(self) -> int:
        return self._position_fix_count

    @property
    def total_crc_errors(self) -> int:
        return self._crc_error_count


def demodulate_iq_to_mode_s_frames(raw_iq: np.ndarray, sample_rate_hz: int = 2_000_000) -> list[bytes]:
    samples_per_us = sample_rate_hz // 1_000_000
    preamble_samples = 8 * samples_per_us

    i_samples = raw_iq[0::2].astype(np.float32) - 127.5
    q_samples = raw_iq[1::2].astype(np.float32) - 127.5
    amplitude = np.hypot(i_samples, q_samples)

    median_amp = np.median(amplitude)
    mad = np.median(np.abs(amplitude - median_amp))
    noise_floor = mad * 1.4826
    detection_threshold = max(noise_floor * 3.5, 20.0)

    n_samples = len(amplitude)
    correlation_len = n_samples - preamble_samples - 112 * samples_per_us - 4
    if correlation_len <= 0:
        return []

    preamble_score = np.zeros(correlation_len, np.float32)
    for hi_us_offset in (0, 1, 3, 4):
        start = hi_us_offset * samples_per_us
        preamble_score += amplitude[start: start + correlation_len]
    for lo_us_offset in (2, 5, 6, 8):
        end = lo_us_offset * samples_per_us + correlation_len
        if end <= n_samples:
            start = lo_us_offset * samples_per_us
            preamble_score -= amplitude[start:end] * 0.5

    decoded_frames: list[bytes] = []
    cursor = 0
    while cursor < correlation_len - 1:
        if preamble_score[cursor] < detection_threshold * 3:
            cursor += 1
            continue

        search_lo = max(0, cursor - 1)
        search_hi = min(correlation_len, cursor + 2)
        cursor = search_lo + int(np.argmax(preamble_score[search_lo:search_hi]))

        payload_start = cursor + preamble_samples
        payload_segment = amplitude[payload_start: payload_start + 112 * samples_per_us]
        if len(payload_segment) < 112 * samples_per_us:
            break

        symbol_power = payload_segment.reshape(112, samples_per_us).mean(axis=1)
        mid_threshold = (symbol_power.max() + symbol_power.min()) * 0.5
        bit_sequence = (symbol_power > mid_threshold).astype(np.uint8)

        df_val = int.from_bytes(np.packbits(bit_sequence[:8]).tobytes()[:1], "big") >> 3
        frame_bit_len = 112 if df_val >= 16 else 56
        raw_frame = np.packbits(bit_sequence[:frame_bit_len]).tobytes()[: frame_bit_len // 8]

        if is_crc_valid(raw_frame):
            decoded_frames.append(raw_frame)

        cursor += preamble_samples + frame_bit_len * samples_per_us

    return decoded_frames


_ALT_COLOR_BANDS: Final[tuple[tuple[int, str], ...]] = (
    (10_000, "bright_green"),
    (18_000, "green"),
    (28_000, "yellow"),
    (36_000, "bright_yellow"),
    (99_999, "bright_cyan"),
)


def _altitude_color(altitude_ft: Optional[float]) -> str:
    if altitude_ft is None:
        return "dim white"
    for limit, color in _ALT_COLOR_BANDS:
        if altitude_ft < limit:
            return color
    return "bright_cyan"


def _format_optional(value: Optional[float], fmt: str = ".0f") -> str:
    return f"{value:{fmt}}" if value is not None else "[dim]\u00b7[/dim]"


def _format_vertical_rate(vr: Optional[float]) -> str:
    if vr is None:
        return "[dim]\u00b7[/dim]"
    sym   = "\u2191" if vr > 64 else "\u2193" if vr < -64 else "\u2192"
    color = "green" if vr > 64 else "red" if vr < -64 else "dim"
    return f"[{color}]{sym}{abs(vr):.0f}[/{color}]"


def _format_squawk(squawk: Optional[str]) -> str:
    if squawk is None:
        return "[dim]\u00b7[/dim]"
    if squawk in SQUAWK_EMERGENCY_MAP:
        label, style = SQUAWK_EMERGENCY_MAP[squawk]
        return f"[{style}] {squawk} {label} [/{style}]"
    return f"[yellow]{squawk}[/yellow]"


def _format_age_bar(age_s: float, width: int = 6) -> str:
    ratio  = min(1.0, age_s / STALE_TIMEOUT_S)
    filled = round(ratio * width)
    bar    = "\u2588" * filled + "\u2591" * (width - filled)
    color  = "green" if ratio < 0.33 else "yellow" if ratio < 0.66 else "red"
    return f"[{color}]{bar}[/{color}]"


def _build_aircraft_table(registry: FlightStateRegistry) -> Table:
    t = Table(
        show_header  = True,
        header_style = "bold grey82",
        border_style = "grey27",
        box          = box.SIMPLE_HEAD,
        row_styles   = ["", "on grey7"],
        expand       = True,
        show_edge    = False,
        padding      = (0, 1),
    )
    column_defs = [
        ("",       dict(width=4,  no_wrap=True)),
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
    for col_name, col_kw in column_defs:
        t.add_column(col_name, **col_kw)

    for ac in registry.active_aircraft():
        alt_color  = _altitude_color(ac.altitude_ft)
        row_style  = "on dark_red" if ac.tcas_ra_active else ("dim" if ac.age_s > 30 else "")
        dist_km    = registry.distance_to_aircraft_km(ac)
        brg_deg    = registry.bearing_to_aircraft_deg(ac)
        country_cc = icao_country_code(ac.icao)

        hdg_str = (
            f"{_format_optional(ac.track_deg, '.0f')} "
            f"{compass_arrow(ac.track_deg) if ac.track_deg is not None else ''}"
        )
        t.add_row(
            country_cc,
            ac.icao,
            ac.callsign or "[dim]\u00b7[/dim]",
            _format_optional(ac.latitude,  "+.4f") if ac.latitude  is not None else "[dim]\u00b7[/dim]",
            _format_optional(ac.longitude, "+.4f") if ac.longitude is not None else "[dim]\u00b7[/dim]",
            f"[{alt_color}]{_format_optional(ac.altitude_ft)}[/{alt_color}]",
            _format_optional(ac.groundspeed_kt),
            hdg_str,
            _format_vertical_rate(ac.vertical_rate),
            _format_squawk(ac.squawk),
            f"{dist_km:.0f}" if dist_km is not None else "[dim]\u00b7[/dim]",
            f"{compass_arrow(brg_deg)} {brg_deg:.0f}\u00b0" if brg_deg is not None else "[dim]\u00b7[/dim]",
            str(ac.msg_count),
            _format_age_bar(ac.age_s),
            style=row_style,
        )
    return t


def _build_stats_panel(registry: FlightStateRegistry) -> Panel:
    n_active = len(registry.active_aircraft())
    spark    = registry.sparkline(18)
    body = Text.assemble(
        ("Aviones  ", "dim"), (f"{n_active:>4}\n",                       "bold bright_white"),
        ("Msgs     ", "dim"), (f"{registry.total_messages:>4}\n",        "white"),
        ("Pos.     ", "dim"), (f"{registry.total_position_fixes:>4}\n",  "bright_green"),
        ("CRC err  ", "dim"), (f"{registry.total_crc_errors:>4}\n",      "bright_red"),
        ("msg/s    ", "dim"), (f"{registry.messages_per_second():>4.1f}\n", "bright_yellow"),
        ("Uptime   ", "dim"), (f"{registry.session_uptime_s():>4.0f}s\n\n", "dim"),
        (spark,               "bright_blue"),
    )
    return Panel(body, title="[dim]Stats[/dim]", border_style="grey27", padding=(0, 1))


def _build_tui_layout(registry: FlightStateRegistry) -> Layout:
    n_active = len(registry.active_aircraft())
    header   = Text(
        f"  ADS-B  1090 MHz  {n_active} aviones  Mode S",
        style="bold white on grey15",
        justify="center",
    )
    root = Layout()
    root.split_column(Layout(name="header", size=1), Layout(name="body"))
    root["body"].split_row(
        Layout(name="table", ratio=5),
        Layout(name="stats", minimum_size=22),
    )
    root["header"].update(header)
    root["table"].update(_build_aircraft_table(registry))
    root["stats"].update(_build_stats_panel(registry))
    return root


class ADSBPipeline:
    def __init__(
        self,
        sdr_source:  Source,
        sample_rate: int = 2_000_000,
        refresh_hz:  int = 4,
        rx_lat:      float = 0.0,
        rx_lon:      float = 0.0,
        console:     Optional["Console"] = None,
    ) -> None:
        from rich.console import Console as _Console
        self._sdr_source   = sdr_source
        self._sample_rate  = sample_rate
        self._refresh_hz   = refresh_hz
        self.registry      = FlightStateRegistry(rx_lat, rx_lon)
        self._console      = console or _Console()

    def ingest_hex_frame(self, hex_str: str, timestamp_s: Optional[float] = None) -> None:
        self.registry.ingest_hex_frame(hex_str, timestamp_s)

    def _consume_iq_chunk(self, iq_bytes: bytes) -> None:
        raw_samples = np.frombuffer(iq_bytes, dtype=np.uint8)
        timestamp_s = time.monotonic()
        if not _PYMODES_OK:
            return
        for raw_frame in demodulate_iq_to_mode_s_frames(raw_samples, self._sample_rate):
            try:
                self.registry.ingest_decoded(
                    _PMMessage(raw_frame.hex().upper()).decode(),
                    timestamp_s,
                )
            except Exception:
                pass

    def run(self) -> None:
        if not _PYMODES_OK:
            self._console.print("[bold red]pyModeS no instalado. pip install pyModeS[/bold red]")
            return
        with Live(
            _build_tui_layout(self.registry),
            console=self._console,
            refresh_per_second=self._refresh_hz,
            screen=True,
        ) as live:
            try:
                while True:
                    chunk = self._sdr_source()
                    if chunk:
                        self._consume_iq_chunk(chunk)
                    live.update(_build_tui_layout(self.registry))
                    time.sleep(1.0 / self._refresh_hz)
            except KeyboardInterrupt:
                pass


_DEMO_HEX_FRAMES: Final[list[str]] = [
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
    console: Optional["Console"] = None,
) -> None:
    from rich.console import Console as _Console
    con = console or _Console()
    if not _PYMODES_OK:
        con.print("[bold red]pyModeS no instalado. pip install pyModeS[/bold red]")
        return
    registry = FlightStateRegistry(rx_lat, rx_lon)
    idx      = 0
    with Live(
        _build_tui_layout(registry),
        console=con,
        refresh_per_second=4,
        screen=True,
    ) as live:
        try:
            while True:
                registry.ingest_hex_frame(_DEMO_HEX_FRAMES[idx % len(_DEMO_HEX_FRAMES)])
                idx += 1
                live.update(_build_tui_layout(registry))
                time.sleep(0.3)
        except KeyboardInterrupt:
            pass


class AircraftMonitor:
    _MODULE_LABEL: Final[str] = "ADS-B"

    def __init__(self, sentinel: object) -> None:
        self._sentinel = sentinel
        self._console: "Console" = getattr(sentinel, "console", None)
        if self._console is None:
            from rich.console import Console as _Console
            self._console = _Console()
        self._sentinel_log = getattr(sentinel, "log", None)

        rf_cfg  = getattr(getattr(sentinel, "rf", None), "cfg", None)
        hw_cfg  = getattr(rf_cfg, "hardware", None)
        self._gain_db:      float = float(getattr(hw_cfg, "gain_db",        49.6))
        self._sample_rate:  int   = int(getattr(hw_cfg,   "sample_rate",    2_000_000))
        self._ppm_corr:     int   = int(getattr(hw_cfg,   "ppm_correction", 0))
        self._device_index: int   = int(getattr(hw_cfg,   "device_index",   0))

        geo_ref  = getattr(sentinel, "geo", None)
        pos_ref  = getattr(geo_ref,  "position", None)
        self._rx_lat: float = float(getattr(pos_ref, "lat", 0.0))
        self._rx_lon: float = float(getattr(pos_ref, "lon", 0.0))

    def _log_info(self, msg: str) -> None:
        self._console.print(f"[cyan][{self._MODULE_LABEL}][/cyan] {msg}")
        if self._sentinel_log:
            self._sentinel_log.info(msg, self._MODULE_LABEL)

    def _log_warn(self, msg: str) -> None:
        self._console.print(f"[yellow][!][{self._MODULE_LABEL}] {msg}[/yellow]")
        if self._sentinel_log:
            self._sentinel_log.warning(msg, self._MODULE_LABEL)

    def _log_error(self, msg: str) -> None:
        self._console.print(f"[bold red][x][{self._MODULE_LABEL}] {msg}[/bold red]")
        if self._sentinel_log:
            self._sentinel_log.error(msg, self._MODULE_LABEL)

    def menu(self) -> None:
        from rich.prompt import Prompt

        while True:
            self._console.print(Panel(
                "[1] Monitor en vivo (RTL-SDR)\n"
                "[2] Demo sin hardware\n"
                "[3] Configurar receptor (lat/lon/gain)\n"
                "[0] Volver",
                title=f"[bold cyan]{self._MODULE_LABEL}[/bold cyan]",
                border_style="cyan",
            ))
            choice = Prompt.ask(
                f"[bold cyan]{self._MODULE_LABEL}[/bold cyan]",
                choices=["0", "1", "2", "3"],
                default="2",
                console=self._console,
            )
            if choice == "0":
                break
            elif choice == "1":
                self._start_rtlsdr()
            elif choice == "2":
                self._start_demo()
            elif choice == "3":
                self._configure_receiver()

    def _start_rtlsdr(self) -> None:
        if not _PYMODES_OK:
            self._log_error("pyModeS no instalado. Ejecuta: pip install pyModeS")
            return
        self._log_info(
            f"Iniciando captura RTL-SDR  "
            f"1090 MHz  gain={self._gain_db} dB  sr={self._sample_rate / 1e6:.1f} MSPS"
        )
        try:
            sdr_source = rtlsdr_source(
                1_090_000_000, self._sample_rate, self._gain_db,
                self._ppm_corr, self._device_index,
            )
        except Exception as exc:
            self._log_error(f"RTL-SDR no disponible: {exc}")
            self._log_warn("Iniciando modo demo como alternativa.")
            self._start_demo()
            return
        ADSBPipeline(
            sdr_source,
            sample_rate = self._sample_rate,
            rx_lat      = self._rx_lat,
            rx_lon      = self._rx_lon,
            console     = self._console,
        ).run()

    def _start_demo(self) -> None:
        self._log_info("Modo demo ADS-B (sin hardware SDR)")
        run_demo(self._rx_lat, self._rx_lon, self._console)

    def _configure_receiver(self) -> None:
        from rich.prompt import Prompt
        try:
            self._rx_lat = float(Prompt.ask(
                "Latitud del receptor", default=str(self._rx_lat), console=self._console
            ))
            self._rx_lon = float(Prompt.ask(
                "Longitud del receptor", default=str(self._rx_lon), console=self._console
            ))
            self._gain_db = float(Prompt.ask(
                "Ganancia RTL-SDR (dB)", default=str(self._gain_db), console=self._console
            ))
            self._log_info(
                f"Receptor configurado  "
                f"lat={self._rx_lat:.4f}  lon={self._rx_lon:.4f}  gain={self._gain_db} dB"
            )
        except ValueError as exc:
            self._log_error(f"Valor invalido: {exc}")
