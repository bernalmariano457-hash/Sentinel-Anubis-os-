from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import numpy as np

from modules.rf.rf_config import HardwareConfig

log = logging.getLogger(__name__)

_MULTIPATH_ATTENUATION: Final[float] = 0.3
_MULTIPATH_DELAY_S: Final[float] = 2e-6
_WFM_DEVIATION_HZ: Final[float] = 75_000.0
_WFM_STEREO_PILOT_HZ: Final[float] = 19_000.0
_AM_MODULATION_INDEX: Final[float] = 0.8
_NOISE_EPSILON: Final[float] = 1e-10
_PULSED_PERIOD_S: Final[float] = 1e-3
_PULSED_WIDTH_S: Final[float] = 50e-6
_IMPEDANCE_OHMS: Final[float] = 50.0
_SIGMF_DATATYPE: Final[str] = "cf32_le"
_SIGMF_VERSION: Final[str] = "1.0.0"
_SIGMF_LEGACY_FREQ_KEY: Final[str] = "frecuencia_hz"
_IQ_FILE_EXTENSIONS: Final[frozenset[str]] = frozenset({".sigmf-data", ".cf32", ".iq"})
_DEFAULT_SAMPLES_PER_READ: Final[int] = 524_288


def _dbm_to_amplitude(power_dbm: float) -> float:
    power_w = 10.0 ** ((power_dbm - 30.0) / 10.0)
    return math.sqrt(2.0 * power_w * _IMPEDANCE_OHMS)


@dataclass
class SyntheticSignal:
    freq_offset:   float = 0.0
    power_dbm:     float = -60.0
    mode:          str   = "tone"
    bw_hz:         float = 12_500.0
    audio_freq:    float = 1_000.0
    doppler_hz_s:  float = 0.0
    freq_drift_hz: float = 0.0

    def __post_init__(self) -> None:
        self._amplitude: float = _dbm_to_amplitude(self.power_dbm)

    @property
    def amplitude(self) -> float:
        return self._amplitude


def _meta_path_for(data_path: Path) -> Path:
    name = data_path.name
    for ext in (".sigmf-data", ".cf32", ".iq"):
        if name.endswith(ext):
            return data_path.with_name(name[: -len(ext)] + ".sigmf-meta")
    return data_path.with_suffix(".sigmf-meta")


def _load_sigmf_meta(meta_path: Path) -> tuple[int | None, float]:
    try:
        with meta_path.open(encoding="utf-8") as fh:
            meta: dict = json.load(fh)
        if "global" in meta:
            raw_sr = meta["global"].get("core:sample_rate")
            freq   = float(
                meta.get("captures", [{}])[0].get("core:frequency", 0.0)
            )
        else:
            raw_sr = meta.get("sample_rate")
            freq   = float(meta.get(_SIGMF_LEGACY_FREQ_KEY, 0.0))
        sample_rate = int(raw_sr) if raw_sr is not None else None
        return sample_rate, freq
    except Exception as exc:
        log.debug("Could not read metadata %s: %s", meta_path.name, exc)
        return None, 0.0


def _build_instantaneous_frequency_carrier(
    sig: SyntheticSignal,
    time_axis: np.ndarray,
) -> np.ndarray:
    f_inst = (
        sig.freq_offset
        + sig.freq_drift_hz * time_axis
        + 0.5 * sig.doppler_hz_s * time_axis ** 2
    )
    return np.exp(2j * np.pi * f_inst * time_axis)


def _apply_multipath(
    iq: np.ndarray,
    delay_samples: int,
) -> np.ndarray:
    if delay_samples <= 0 or delay_samples >= len(iq):
        return iq
    delayed = np.empty_like(iq)
    delayed[:delay_samples] = 0
    delayed[delay_samples:] = iq[:-delay_samples]
    return iq + delayed * _MULTIPATH_ATTENUATION


def _modulate_tone(
    amp: float,
    carrier: np.ndarray,
) -> np.ndarray:
    return amp * carrier


def _modulate_nfm(
    sig: SyntheticSignal,
    amp: float,
    carrier: np.ndarray,
    time_axis: np.ndarray,
    sample_rate: int,
) -> np.ndarray:
    deviation = min(sig.bw_hz / 2.0, 5_000.0)
    audio = np.cos(2.0 * np.pi * sig.audio_freq * time_axis)
    phase = 2.0 * np.pi * deviation * np.cumsum(audio) / sample_rate
    return amp * np.exp(1j * phase) * carrier


def _modulate_wfm(
    amp: float,
    carrier: np.ndarray,
    time_axis: np.ndarray,
    sample_rate: int,
) -> np.ndarray:
    audio = (
        0.5 * np.cos(2.0 * np.pi * 1_000.0 * time_axis)
        + 0.3 * np.cos(2.0 * np.pi * 3_000.0 * time_axis)
        + 0.2 * np.cos(2.0 * np.pi * 5_000.0 * time_axis)
        + 0.1 * np.cos(2.0 * np.pi * _WFM_STEREO_PILOT_HZ * time_axis)
    )
    phase = 2.0 * np.pi * _WFM_DEVIATION_HZ * np.cumsum(audio) / sample_rate
    return amp * np.exp(1j * phase) * carrier


def _modulate_am(
    sig: SyntheticSignal,
    amp: float,
    carrier: np.ndarray,
    time_axis: np.ndarray,
) -> np.ndarray:
    audio = np.cos(2.0 * np.pi * sig.audio_freq * time_axis)
    return amp * (1.0 + _AM_MODULATION_INDEX * audio) * carrier


def _modulate_dsb(
    sig: SyntheticSignal,
    amp: float,
    carrier: np.ndarray,
    time_axis: np.ndarray,
) -> np.ndarray:
    audio = np.cos(2.0 * np.pi * sig.audio_freq * time_axis)
    return amp * audio * carrier


def _modulate_noise(
    amp: float,
    carrier: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    n_samples = len(carrier)
    noise = (
        rng.standard_normal(n_samples) + 1j * rng.standard_normal(n_samples)
    ).astype(np.complex64)
    std = np.std(noise)
    return amp * (noise / (std + _NOISE_EPSILON)) * carrier


def _modulate_pulsed(
    amp: float,
    carrier: np.ndarray,
    sample_rate: int,
) -> np.ndarray:
    n_samples    = len(carrier)
    pulse_period = int(sample_rate * _PULSED_PERIOD_S)
    pulse_width  = int(sample_rate * _PULSED_WIDTH_S)
    envelope     = np.zeros(n_samples, dtype=np.float32)
    starts       = np.arange(0, n_samples, pulse_period)
    ends         = np.minimum(starts + pulse_width, n_samples)
    for s, e in zip(starts, ends):
        envelope[s:e] = 1.0
    return amp * envelope * carrier


def _generate_signal_iq(
    sig: SyntheticSignal,
    time_axis: np.ndarray,
    sample_rate: int,
    rng: np.random.Generator,
) -> np.ndarray:
    amp     = sig.amplitude
    mode    = sig.mode.lower()
    carrier = _build_instantaneous_frequency_carrier(sig, time_axis)

    dispatch: dict[str, np.ndarray] = {
        "tone":   _modulate_tone(amp, carrier),
        "am":     _modulate_am(sig, amp, carrier, time_axis),
        "dsb":    _modulate_dsb(sig, amp, carrier, time_axis),
        "nfm":    _modulate_nfm(sig, amp, carrier, time_axis, sample_rate),
        "wfm":    _modulate_wfm(amp, carrier, time_axis, sample_rate),
        "noise":  _modulate_noise(amp, carrier, rng),
        "pulsed": _modulate_pulsed(amp, carrier, sample_rate),
    }
    iq = dispatch.get(mode, _modulate_tone(amp, carrier))

    delay_samples = int(sample_rate * _MULTIPATH_DELAY_S)
    return _apply_multipath(iq, delay_samples)


def generate_iq(
    sample_rate: int,
    n_samples: int,
    signals: list[SyntheticSignal],
    noise_floor_dbm: float = -100.0,
    t_offset_s: float = 0.0,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    resolved_rng = rng if rng is not None else np.random.default_rng()
    time_axis    = np.arange(n_samples, dtype=np.float64) / sample_rate + t_offset_s

    noise_power = 10.0 ** ((noise_floor_dbm - 30.0) / 10.0) / _IMPEDANCE_OHMS
    noise_amp   = math.sqrt(noise_power / 2.0)
    out = (
        noise_amp * resolved_rng.standard_normal(n_samples)
        + 1j * noise_amp * resolved_rng.standard_normal(n_samples)
    ).astype(np.complex64)

    for sig in signals:
        out += _generate_signal_iq(sig, time_axis, sample_rate, resolved_rng).astype(
            np.complex64
        )

    return out


def _load_iq_from_file(path: Path) -> np.ndarray:
    if path.suffix.lower() in _IQ_FILE_EXTENSIONS:
        raw = np.fromfile(str(path), dtype=np.float32)
        return (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
    return np.fromfile(str(path), dtype=np.complex64)


class MockSDRManager:

    def __init__(
        self,
        sample_rate: int = 2_048_000,
        noise_floor_dbm: float = -100.0,
    ) -> None:
        self.sample_rate:   int   = sample_rate
        self.noise_floor:   float = noise_floor_dbm
        self._signals:      list[SyntheticSignal] = []
        self._iq_data:      np.ndarray | None = None
        self._iq_pos:       int   = 0
        self._current_freq: float = 0.0
        self._t_offset:     float = 0.0
        self.cfg     = HardwareConfig(sample_rate=sample_rate)
        self.hw_type = "MockSDR"
        self.hw_info: dict[str, object] = {
            "driver":      "mock",
            "sample_rate": sample_rate,
            "note":        "Simulated hardware for tests and development",
        }
        self.available = True
        log.info("MockSDR started — SR=%.3f MHz", sample_rate / 1e6)

    @classmethod
    def from_file(
        cls,
        path: str,
        sample_rate: int = 2_048_000,
    ) -> MockSDRManager:
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"IQ file not found: {resolved}")

        mock = cls(sample_rate=sample_rate)
        meta_path = _meta_path_for(resolved)

        if meta_path.exists():
            loaded_sr, freq = _load_sigmf_meta(meta_path)
            if loaded_sr is not None:
                mock.sample_rate = loaded_sr
            mock._current_freq = freq
            log.debug(
                "Metadata loaded: SR=%d freq=%.3f MHz",
                mock.sample_rate,
                freq / 1e6,
            )

        mock._iq_data = _load_iq_from_file(resolved)
        log.info(
            "MockSDR loaded %d samples from %s",
            len(mock._iq_data),
            resolved.name,
        )
        return mock

    def add_signal(self, sig: SyntheticSignal) -> None:
        self._signals.append(sig)
        log.debug(
            "MockSDR: signal added offset=%.1f kHz pwr=%.0f dBm mode=%s",
            sig.freq_offset / 1e3,
            sig.power_dbm,
            sig.mode,
        )

    def capture(
        self,
        freq_hz: float,
        n_samples: int | None = None,
        t_offset: float | None = None,
    ) -> np.ndarray:
        resolved_n = n_samples if n_samples is not None else (
            getattr(self.cfg, "samples_per_read", _DEFAULT_SAMPLES_PER_READ)
        )
        self._current_freq = freq_hz

        if self._iq_data is not None:
            return self._read_from_file_buffer(resolved_n)

        effective_t_offset = t_offset if t_offset is not None else self._t_offset
        iq = generate_iq(
            sample_rate=self.sample_rate,
            n_samples=resolved_n,
            signals=self._signals,
            noise_floor_dbm=self.noise_floor,
            t_offset_s=effective_t_offset,
        )
        self._t_offset += resolved_n / self.sample_rate
        return iq

    def _read_from_file_buffer(self, n_samples: int) -> np.ndarray:
        assert self._iq_data is not None
        available = len(self._iq_data) - self._iq_pos
        if available < n_samples:
            self._iq_pos = 0
        chunk = self._iq_data[self._iq_pos: self._iq_pos + n_samples]
        self._iq_pos += n_samples
        return chunk

    def set_gain(self, gain_db: float) -> None:
        self.cfg.gain_db = gain_db

    def set_ppm(self, ppm: int) -> None:
        self.cfg.ppm_correction = ppm

    def set_agc(self, enable: bool = True) -> None:
        self.cfg.agc = enable
        log.debug("MockSDR: AGC %s", "enabled" if enable else "disabled")

    def connect(self, **_: object) -> bool:
        return True

    def close(self) -> None:
        log.debug("MockSDR closed")


def generate_fixture(
    path: str,
    freq_hz: float,
    sample_rate: int,
    duration_s: float,
    signals: list[SyntheticSignal],
    noise_dbm: float = -100.0,
) -> Path:
    n_samples = int(sample_rate * duration_s)
    iq = generate_iq(sample_rate, n_samples, signals, noise_dbm)

    out_path = Path(path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    iq.view(np.float32).tofile(str(out_path))

    now = datetime.now(timezone.utc).isoformat()
    meta: dict = {
        "global": {
            "core:datatype":    _SIGMF_DATATYPE,
            "core:sample_rate": sample_rate,
            "core:version":     _SIGMF_VERSION,
            "core:description": f"Test fixture — {duration_s}s",
            "core:date":        now,
        },
        "captures": [{
            "core:sample_start": 0,
            "core:frequency":    freq_hz,
            "core:datetime":     now,
        }],
        "annotations": [
            {
                "core:sample_start":    0,
                "core:sample_count":    n_samples,
                "core:freq_lower_edge": freq_hz - sample_rate / 2.0,
                "core:freq_upper_edge": freq_hz + sample_rate / 2.0,
                "core:comment": (
                    f"{sig.mode} @ {(freq_hz + sig.freq_offset) / 1e6:.3f} MHz"
                ),
            }
            for sig in signals
        ],
    }
    meta_path = _meta_path_for(out_path)
    with meta_path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)

    log.info(
        "Fixture: %s (%d samples, %.1f MB)",
        out_path.name,
        n_samples,
        out_path.stat().st_size / 1e6,
    )
    return out_path
