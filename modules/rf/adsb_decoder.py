from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from math import acos, atan2, cos, degrees, floor, hypot, pi, radians, sin, sqrt
from typing import Final, Literal, Optional

import numpy as np

IcaoHex = str
CprFormat = Literal[0, 1]

DEFAULT_SAMPLE_RATE_HZ: Final[int] = 2_000_000

PREAMBLE_HIGH_PULSES_US: Final[tuple[float, ...]] = (0.0, 1.0, 3.5, 4.5)
PREAMBLE_DURATION_US: Final[float] = 8.0

SHORT_FRAME_BITS: Final[int] = 56
LONG_FRAME_BITS: Final[int] = 112
LONG_FRAME_DF_MASK: Final[int] = 0x10

SUPPORTED_DOWNLINK_FORMATS: Final[frozenset[int]] = frozenset({0, 4, 5, 11, 16, 17, 18, 20, 21})
EXTENDED_SQUITTER_DOWNLINK_FORMATS: Final[frozenset[int]] = frozenset({17, 18})

CPR_MAX_AGE_S: Final[float] = 10.0
STALE_TIMEOUT_S: Final[float] = 60.0
TCAS_RA_HOLD_S: Final[float] = 4.0
TRAIL_HISTORY_LEN: Final[int] = 30
RATE_WINDOW_S: Final[int] = 90
KNOWN_ICAO_TTL_S: Final[float] = 300.0
KNOWN_ICAO_PRUNE_THRESHOLD: Final[int] = 4096
NZ: Final[int] = 15

EMERGENCY_SQUAWK_CODES: Final[frozenset[str]] = frozenset({"7500", "7600", "7700"})

ICAO_COUNTRY_BANDS: Final[tuple[tuple[int, int, str], ...]] = (
    (0x0C0000, 0x0FFFFF, "FR"), (0x380000, 0x38FFFF, "DK"),
    (0x3C0000, 0x3FFFFF, "DE"), (0x400000, 0x43FFFF, "ES"),
    (0x480000, 0x48FFFF, "NL"), (0x4CA000, 0x4CAFFF, "IE"),
    (0x500000, 0x5003FF, "BE"), (0x700000, 0x71FFFF, "MX"),
    (0x7C0000, 0x7FFFFF, "AU"), (0x800000, 0x83FFFF, "IN"),
    (0xA00000, 0xAFFFFF, "US"), (0xC00000, 0xC3FFFF, "CA"),
    (0xE00000, 0xE3FFFF, "AR"),
)

AIS_CHARSET: Final[str] = "@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_ !\"#$%&'()*+,-./0123456789:;<=>?"

_CRC24_POLY: Final[int] = 0xFFF409


def _build_crc24_lut() -> tuple[int, ...]:
    table = [0] * 256
    for byte_val in range(256):
        remainder = byte_val << 16
        for _ in range(8):
            remainder <<= 1
            if remainder & 0x1000000:
                remainder ^= _CRC24_POLY
        table[byte_val] = remainder & 0xFFFFFF
    return tuple(table)


_CRC24_LUT: Final[tuple[int, ...]] = _build_crc24_lut()


def crc24(payload: bytes) -> int:
    crc = 0
    for byte_val in payload:
        crc = _CRC24_LUT[(crc >> 16) ^ byte_val] ^ ((crc & 0xFFFF) << 8)
    return crc & 0xFFFFFF


def is_crc_valid(raw_frame: bytes) -> bool:
    return crc24(raw_frame[:-3]) == int.from_bytes(raw_frame[-3:], "big")


def crc24_syndrome(raw_frame: bytes) -> int:
    return crc24(raw_frame[:-3]) ^ int.from_bytes(raw_frame[-3:], "big")


def extract_downlink_format(raw_frame: bytes) -> int:
    return raw_frame[0] >> 3


def extract_capability(raw_frame: bytes) -> int:
    return raw_frame[0] & 0x07


def extract_icao_aa(raw_frame: bytes) -> IcaoHex:
    return raw_frame[1:4].hex().upper()


def extract_type_code(raw_frame: bytes) -> int:
    return raw_frame[4] >> 3


def extract_subtype(raw_frame: bytes, type_code: int) -> int:
    if type_code == 29:
        return (raw_frame[4] & 0x06) >> 1
    return raw_frame[4] & 0x07


def extract_cpr_format_bit(raw_frame: bytes) -> CprFormat:
    return 1 if raw_frame[6] & 0x04 else 0


def extract_cpr_lat_raw(raw_frame: bytes) -> int:
    return ((raw_frame[6] & 0x03) << 15) | (raw_frame[7] << 7) | (raw_frame[8] >> 1)


def extract_cpr_lon_raw(raw_frame: bytes) -> int:
    return ((raw_frame[8] & 0x01) << 16) | (raw_frame[9] << 8) | raw_frame[10]


def extract_ac12_field(raw_frame: bytes) -> int:
    return ((raw_frame[5] << 4) | (raw_frame[6] >> 4)) & 0x0FFF


def extract_ac13_field(raw_frame: bytes) -> int:
    return ((raw_frame[2] << 8) | raw_frame[3]) & 0x1FFF


def _gillham_remap(gillham_field: int) -> int:
    remapped = 0
    if gillham_field & 0x1000:
        remapped |= 0x0010
    if gillham_field & 0x0800:
        remapped |= 0x1000
    if gillham_field & 0x0400:
        remapped |= 0x0020
    if gillham_field & 0x0200:
        remapped |= 0x2000
    if gillham_field & 0x0100:
        remapped |= 0x0040
    if gillham_field & 0x0080:
        remapped |= 0x4000
    if gillham_field & 0x0020:
        remapped |= 0x0100
    if gillham_field & 0x0010:
        remapped |= 0x0001
    if gillham_field & 0x0008:
        remapped |= 0x0200
    if gillham_field & 0x0004:
        remapped |= 0x0002
    if gillham_field & 0x0002:
        remapped |= 0x0400
    if gillham_field & 0x0001:
        remapped |= 0x0004
    return remapped


def decode_ac12_altitude_ft(ac12_field: int) -> Optional[float]:
    if ac12_field == 0:
        return None
    if ac12_field & 0x10:
        n = ((ac12_field & 0x0FE0) >> 1) | (ac12_field & 0x000F)
        return float(n * 25 - 1000)
    return None


def decode_ac13_altitude_ft(ac13_field: int) -> Optional[float]:
    if ac13_field == 0:
        return None
    if ac13_field & 0x0040:
        return None
    if ac13_field & 0x0010:
        n = ((ac13_field & 0x1F80) >> 2) | ((ac13_field & 0x0020) >> 1) | (ac13_field & 0x000F)
        return float(n * 25 - 1000)
    return None


def decode_squawk(id13_field: int) -> Optional[str]:
    if id13_field == 0:
        return None
    return f"{_gillham_remap(id13_field):04X}"


def is_emergency_squawk(squawk: Optional[str]) -> bool:
    return squawk in EMERGENCY_SQUAWK_CODES if squawk else False


def decode_callsign(raw_frame: bytes) -> Optional[str]:
    chars1 = (raw_frame[5] << 16) | (raw_frame[6] << 8) | raw_frame[7]
    chars2 = (raw_frame[8] << 16) | (raw_frame[9] << 8) | raw_frame[10]
    if chars1 == 0 and chars2 == 0:
        return None
    indices = (
        (chars1 >> 18) & 0x3F, (chars1 >> 12) & 0x3F, (chars1 >> 6) & 0x3F, chars1 & 0x3F,
        (chars2 >> 18) & 0x3F, (chars2 >> 12) & 0x3F, (chars2 >> 6) & 0x3F, chars2 & 0x3F,
    )
    callsign = "".join(AIS_CHARSET[idx] for idx in indices).rstrip(" @")
    return callsign or None


@dataclass(slots=True)
class VelocityInfo:
    groundspeed_kt: Optional[float] = None
    track_deg: Optional[float] = None
    vertical_rate_fpm: Optional[float] = None


def decode_velocity(raw_frame: bytes, subtype: int) -> VelocityInfo:
    info = VelocityInfo()
    vr_raw = ((raw_frame[8] & 0x07) << 6) | (raw_frame[9] >> 2)
    if vr_raw:
        vertical_rate = float((vr_raw - 1) * 64)
        if raw_frame[8] & 0x08:
            vertical_rate = -vertical_rate
        info.vertical_rate_fpm = vertical_rate

    if subtype in (1, 2):
        unit_scale = 4 if subtype == 2 else 1
        ew_raw = ((raw_frame[5] & 0x03) << 8) | raw_frame[6]
        ns_raw = ((raw_frame[7] & 0x7F) << 3) | (raw_frame[8] >> 5)
        ew_vel = float((ew_raw - 1) * unit_scale) if ew_raw else 0.0
        ns_vel = float((ns_raw - 1) * unit_scale) if ns_raw else 0.0
        if raw_frame[5] & 0x04:
            ew_vel = -ew_vel
        if raw_frame[7] & 0x80:
            ns_vel = -ns_vel
        if ew_raw and ns_raw:
            speed = hypot(ew_vel, ns_vel)
            info.groundspeed_kt = speed
            if speed > 0.0:
                heading = degrees(atan2(ew_vel, ns_vel))
                info.track_deg = heading + 360.0 if heading < 0.0 else heading
    elif subtype in (3, 4):
        unit_scale = 4 if subtype == 4 else 1
        airspeed_raw = ((raw_frame[7] & 0x7F) << 3) | (raw_frame[8] >> 5)
        if airspeed_raw:
            info.groundspeed_kt = float((airspeed_raw - 1) * unit_scale)
        if raw_frame[5] & 0x04:
            info.track_deg = (((raw_frame[5] & 0x03) << 8) | raw_frame[6]) * 45.0 / 128.0
    return info


@dataclass(slots=True)
class AircraftStatusInfo:
    squawk: Optional[str] = None
    tcas_ra_active: bool = False


def decode_aircraft_status(raw_frame: bytes, subtype: int) -> AircraftStatusInfo:
    info = AircraftStatusInfo()
    if subtype == 1:
        id13_field = ((raw_frame[5] << 8) | raw_frame[6]) & 0x1FFF
        info.squawk = decode_squawk(id13_field)
    elif subtype == 2:
        info.tcas_ra_active = True
    return info


@dataclass(slots=True)
class CprFrame:
    lat_raw: int
    lon_raw: int
    fmt: CprFormat
    altitude_ft: Optional[float]
    timestamp_s: float


@dataclass(slots=True)
class ModeSFrame:
    downlink_format: int
    icao: Optional[IcaoHex] = None
    icao_verified: bool = False
    callsign: Optional[str] = None
    cpr: Optional[CprFrame] = None
    altitude_ft: Optional[float] = None
    squawk: Optional[str] = None
    groundspeed_kt: Optional[float] = None
    track_deg: Optional[float] = None
    vertical_rate_fpm: Optional[float] = None
    tcas_ra_active: bool = False


def decode_mode_s_frame(
    raw_frame: bytes,
    known_icao: Optional[set[IcaoHex]] = None,
    timestamp_s: Optional[float] = None,
) -> Optional[ModeSFrame]:
    if len(raw_frame) not in (SHORT_FRAME_BITS // 8, LONG_FRAME_BITS // 8):
        return None
    df = extract_downlink_format(raw_frame)
    if df not in SUPPORTED_DOWNLINK_FORMATS:
        return None

    ts = timestamp_s if timestamp_s is not None else time.monotonic()
    frame = ModeSFrame(downlink_format=df)

    if df in EXTENDED_SQUITTER_DOWNLINK_FORMATS:
        frame.icao = extract_icao_aa(raw_frame)
        frame.icao_verified = is_crc_valid(raw_frame)
        if not frame.icao_verified:
            return frame

        type_code = extract_type_code(raw_frame)
        subtype = extract_subtype(raw_frame, type_code)

        if 1 <= type_code <= 4:
            frame.callsign = decode_callsign(raw_frame)
        elif type_code == 0 or 9 <= type_code <= 18 or 20 <= type_code <= 22:
            frame.altitude_ft = decode_ac12_altitude_ft(extract_ac12_field(raw_frame))
            if type_code != 0:
                frame.cpr = CprFrame(
                    lat_raw=extract_cpr_lat_raw(raw_frame),
                    lon_raw=extract_cpr_lon_raw(raw_frame),
                    fmt=extract_cpr_format_bit(raw_frame),
                    altitude_ft=frame.altitude_ft,
                    timestamp_s=ts,
                )
        elif type_code == 19:
            velocity = decode_velocity(raw_frame, subtype)
            frame.groundspeed_kt = velocity.groundspeed_kt
            frame.track_deg = velocity.track_deg
            frame.vertical_rate_fpm = velocity.vertical_rate_fpm
        elif type_code == 28:
            status = decode_aircraft_status(raw_frame, subtype)
            frame.squawk = status.squawk
            frame.tcas_ra_active = status.tcas_ra_active
        return frame

    if df == 11:
        frame.icao = extract_icao_aa(raw_frame)
        syndrome = crc24_syndrome(raw_frame)
        frame.icao_verified = (syndrome & 0xFFFF80) == 0
        return frame

    syndrome = crc24_syndrome(raw_frame)
    candidate_icao = f"{syndrome:06X}"
    known = known_icao if known_icao is not None else frozenset()
    frame.icao_verified = candidate_icao in known
    if not frame.icao_verified:
        return frame
    frame.icao = candidate_icao
    if df in (0, 4, 16, 20):
        frame.altitude_ft = decode_ac13_altitude_ft(extract_ac13_field(raw_frame))
    elif df in (5, 21):
        frame.squawk = decode_squawk(extract_ac13_field(raw_frame))
    return frame


def _amplitude_from_iq(raw_iq: np.ndarray) -> np.ndarray:
    i_samples = raw_iq[0::2].astype(np.float32) - 127.5
    q_samples = raw_iq[1::2].astype(np.float32) - 127.5
    return np.hypot(i_samples, q_samples)


def _preamble_sample_offsets(samples_per_us: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    preamble_len = round(PREAMBLE_DURATION_US * samples_per_us)
    high = tuple(round(t * samples_per_us) for t in PREAMBLE_HIGH_PULSES_US)
    low = tuple(i for i in range(preamble_len) if i not in high)
    return high, low


def _preamble_correlation(
    amplitude: np.ndarray,
    samples_per_us: int,
    high_offsets: tuple[int, ...],
    low_offsets: tuple[int, ...],
) -> np.ndarray:
    preamble_len = round(PREAMBLE_DURATION_US * samples_per_us)
    max_frame_samples = LONG_FRAME_BITS * samples_per_us
    valid_len = amplitude.size - preamble_len - max_frame_samples
    if valid_len <= 0:
        return np.empty(0, dtype=np.float32)
    score = np.zeros(valid_len, dtype=np.float32)
    for offset in high_offsets:
        score += amplitude[offset: offset + valid_len]
    low_weight = len(high_offsets) / len(low_offsets)
    for offset in low_offsets:
        score -= amplitude[offset: offset + valid_len] * low_weight
    return score


def _cluster_peak_positions(candidates: np.ndarray, score: np.ndarray, cluster_gap: int) -> np.ndarray:
    breaks = np.flatnonzero(np.diff(candidates) > cluster_gap) + 1
    clusters = np.split(candidates, breaks)
    peaks = np.empty(len(clusters), dtype=candidates.dtype)
    for idx, cluster in enumerate(clusters):
        peaks[idx] = cluster[np.argmax(score[cluster])]
    return peaks


def _demodulate_symbols(payload_amplitude: np.ndarray, n_bits: int, samples_per_us: int) -> np.ndarray:
    symbols = payload_amplitude[: n_bits * samples_per_us].reshape(n_bits, samples_per_us)
    half = samples_per_us // 2
    early = symbols[:, :half].mean(axis=1)
    late = symbols[:, half:].mean(axis=1)
    return (early > late).astype(np.uint8)


def demodulate_iq_to_mode_s_frames(
    raw_iq: np.ndarray,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
) -> list[bytes]:
    samples_per_us = sample_rate_hz // 1_000_000
    if samples_per_us < 2:
        raise ValueError("La demodulacion PPM Manchester requiere al menos 2 muestras por microsegundo.")

    amplitude = _amplitude_from_iq(raw_iq)
    high_offsets, low_offsets = _preamble_sample_offsets(samples_per_us)
    preamble_len = round(PREAMBLE_DURATION_US * samples_per_us)
    score = _preamble_correlation(amplitude, samples_per_us, high_offsets, low_offsets)
    if score.size == 0:
        return []

    median_amp = float(np.median(amplitude))
    mad = float(np.median(np.abs(amplitude - median_amp)))
    noise_floor = mad * 1.4826
    per_pulse_threshold = max(noise_floor * 3.5, 20.0)
    score_threshold = per_pulse_threshold * len(high_offsets)

    raw_candidates = np.flatnonzero(score > score_threshold)
    if raw_candidates.size == 0:
        return []
    candidate_positions = _cluster_peak_positions(raw_candidates, score, preamble_len)

    frames: list[bytes] = []
    n_candidates = int(candidate_positions.size)
    i = 0
    while i < n_candidates:
        start = int(candidate_positions[i])
        refine_lo = max(0, start - 1)
        refine_hi = min(score.size, start + 2)
        start = refine_lo + int(np.argmax(score[refine_lo:refine_hi]))

        header_offset = start + preamble_len
        header_needed = 8 * samples_per_us
        if header_offset + header_needed > amplitude.size:
            break
        header_bits = _demodulate_symbols(amplitude[header_offset: header_offset + header_needed], 8, samples_per_us)
        downlink_format = int(np.packbits(header_bits)[0]) >> 3

        if downlink_format not in SUPPORTED_DOWNLINK_FORMATS:
            i += 1
            continue

        frame_bits = LONG_FRAME_BITS if downlink_format & LONG_FRAME_DF_MASK else SHORT_FRAME_BITS
        frame_needed = frame_bits * samples_per_us
        if header_offset + frame_needed > amplitude.size:
            break

        bit_sequence = _demodulate_symbols(amplitude[header_offset: header_offset + frame_needed], frame_bits, samples_per_us)
        raw_frame = np.packbits(bit_sequence).tobytes()

        if downlink_format in EXTENDED_SQUITTER_DOWNLINK_FORMATS or downlink_format == 11:
            if not is_crc_valid(raw_frame):
                i += 1
                continue

        frames.append(raw_frame)
        consumed_end = header_offset + frame_needed
        i += 1
        while i < n_candidates and candidate_positions[i] < consumed_end:
            i += 1

    return frames


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
    dlat_odd = 360.0 / (4 * NZ - 1)

    lat_cpr_even = even_lat_raw / 131072.0
    lat_cpr_odd = odd_lat_raw / 131072.0
    lon_cpr_even = even_lon_raw / 131072.0
    lon_cpr_odd = odd_lon_raw / 131072.0

    j = floor(59.0 * lat_cpr_even - 60.0 * lat_cpr_odd + 0.5)

    lat_even = dlat_even * ((j % 60) + lat_cpr_even)
    lat_odd = dlat_odd * ((j % 59) + lat_cpr_odd)

    if lat_even >= 270.0:
        lat_even -= 360.0
    if lat_odd >= 270.0:
        lat_odd -= 360.0

    nl_even = _cpr_nl(lat_even)
    nl_odd = _cpr_nl(lat_odd)
    if nl_even != nl_odd:
        return None

    lat = lat_even if even_is_newer else lat_odd
    nl = nl_even

    if even_is_newer:
        ni = max(nl, 1)
        dlon = 360.0 / ni
        m = floor(lon_cpr_even * (nl - 1) - lon_cpr_odd * nl + 0.5)
        lon = dlon * ((m % ni) + lon_cpr_even)
    else:
        ni = max(nl - 1, 1)
        dlon = 360.0 / ni
        m = floor(lon_cpr_even * (nl - 1) - lon_cpr_odd * nl + 0.5)
        lon = dlon * ((m % ni) + lon_cpr_odd)

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

    j = floor(ref_lat / dlat) + floor(0.5 + ((ref_lat % dlat) / dlat) - lat_cpr)
    lat = dlat * (j + lat_cpr)

    nl = _cpr_nl(lat)
    ni = max(nl - cpr_fmt, 1)
    dlon = 360.0 / ni
    m = floor(ref_lon / dlon) + floor(0.5 + ((ref_lon % dlon) / dlon) - lon_cpr)
    lon = dlon * (m + lon_cpr)

    return (lat, lon)


@dataclass
class AircraftState:
    icao: IcaoHex
    callsign: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_ft: Optional[float] = None
    groundspeed_kt: Optional[float] = None
    track_deg: Optional[float] = None
    vertical_rate: Optional[float] = None
    squawk: Optional[str] = None
    msg_count: int = 0
    pos_msg_count: int = 0
    last_seen_s: float = field(default_factory=time.monotonic)
    position_trail: deque[tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=TRAIL_HISTORY_LEN), repr=False
    )
    _cpr_even: Optional[CprFrame] = field(default=None, repr=False)
    _cpr_odd: Optional[CprFrame] = field(default=None, repr=False)
    _gs_ema: Optional[float] = field(default=None, repr=False)
    _track_ema: Optional[float] = field(default=None, repr=False)
    _vr_ema: Optional[float] = field(default=None, repr=False)
    _tcas_ra_last_s: Optional[float] = field(default=None, repr=False)

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

    def mark_tcas_ra(self, timestamp_s: float) -> None:
        self._tcas_ra_last_s = timestamp_s

    @property
    def tcas_ra_active(self) -> bool:
        if self._tcas_ra_last_s is None:
            return False
        return (time.monotonic() - self._tcas_ra_last_s) <= TCAS_RA_HOLD_S

    def absorb_cpr_frame(self, frame: CprFrame) -> bool:
        if frame.fmt == 0:
            self._cpr_even, peer_frame = frame, self._cpr_odd
        else:
            self._cpr_odd, peer_frame = frame, self._cpr_even

        if peer_frame is None or abs(frame.timestamp_s - peer_frame.timestamp_s) > CPR_MAX_AGE_S:
            return False

        resolved_alt = frame.altitude_ft or peer_frame.altitude_ft

        if self.latitude is not None and self.longitude is not None:
            result = decode_cpr_local_position(
                frame.fmt, frame.lat_raw, frame.lon_raw,
                self.latitude, self.longitude,
            )
            if result is not None:
                self._commit_position(result[0], result[1], resolved_alt)
                return True

        even_frame, odd_frame = self._cpr_even, self._cpr_odd
        if even_frame is None or odd_frame is None:
            return False

        result = decode_cpr_global_position(
            even_frame.lat_raw, even_frame.lon_raw,
            odd_frame.lat_raw, odd_frame.lon_raw,
            even_is_newer=even_frame.timestamp_s >= odd_frame.timestamp_s,
        )
        if result is None:
            return False

        self._commit_position(result[0], result[1], resolved_alt)
        return True

    def _commit_position(self, lat: float, lon: float, alt: Optional[float]) -> None:
        self.latitude = lat
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
        self._known_icao: dict[IcaoHex, float] = {}
        self._total_msg_count: int = 0
        self._position_fix_count: int = 0
        self._unverified_count: int = 0
        self._session_start_s: float = time.monotonic()
        self._rate_sample_buf: deque[int] = deque(maxlen=RATE_WINDOW_S)
        self._rate_last_sample_s: float = time.monotonic()

    def _remember_icao(self, icao: IcaoHex, timestamp_s: float) -> None:
        self._known_icao[icao] = timestamp_s
        if len(self._known_icao) > KNOWN_ICAO_PRUNE_THRESHOLD:
            cutoff = timestamp_s - KNOWN_ICAO_TTL_S
            for stale_icao in [k for k, seen in self._known_icao.items() if seen < cutoff]:
                del self._known_icao[stale_icao]

    def _known_icao_set(self, timestamp_s: float) -> set[IcaoHex]:
        cutoff = timestamp_s - KNOWN_ICAO_TTL_S
        return {icao for icao, seen in self._known_icao.items() if seen >= cutoff}

    def ingest_raw_frame(self, raw_frame: bytes, timestamp_s: Optional[float] = None) -> Optional[IcaoHex]:
        ts = timestamp_s if timestamp_s is not None else time.monotonic()
        frame = decode_mode_s_frame(raw_frame, self._known_icao_set(ts), ts)
        if frame is None:
            return None
        if not frame.icao_verified or frame.icao is None:
            self._unverified_count += 1
            return None

        self._remember_icao(frame.icao, ts)
        self._total_msg_count += 1
        self._advance_rate_sample()

        ac = self._aircraft_db.setdefault(frame.icao, AircraftState(icao=frame.icao, last_seen_s=ts))
        ac.last_seen_s = ts
        ac.msg_count += 1

        if frame.callsign:
            ac.callsign = frame.callsign
        if frame.cpr is not None and ac.absorb_cpr_frame(frame.cpr):
            self._position_fix_count += 1
        if frame.altitude_ft is not None:
            ac.altitude_ft = frame.altitude_ft
        if frame.squawk is not None:
            ac.squawk = frame.squawk
        if frame.groundspeed_kt is not None or frame.track_deg is not None or frame.vertical_rate_fpm is not None:
            ac.update_velocity_ema(frame.groundspeed_kt, frame.track_deg, frame.vertical_rate_fpm)
        if frame.tcas_ra_active:
            ac.mark_tcas_ra(ts)
        return frame.icao

    def ingest_hex_frame(self, hex_str: str, timestamp_s: Optional[float] = None) -> Optional[IcaoHex]:
        try:
            raw_frame = bytes.fromhex(hex_str.strip())
        except ValueError:
            return None
        return self.ingest_raw_frame(raw_frame, timestamp_s)

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
        spark_chars = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
        buf = list(self._rate_sample_buf)
        if len(buf) < 2:
            return " " * width
        rates = [max(0, buf[idx] - buf[idx - 1]) for idx in range(1, len(buf))]
        peak = max(rates) or 1
        return "".join(spark_chars[min(8, int(v / peak * 8))] for v in rates[-width:])

    @property
    def total_messages(self) -> int:
        return self._total_msg_count

    @property
    def total_position_fixes(self) -> int:
        return self._position_fix_count

    @property
    def total_unverified_frames(self) -> int:
        return self._unverified_count

    @property
    def rx_position(self) -> tuple[float, float]:
        return self._rx_position
