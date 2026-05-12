from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from modules.rf.rf_config import HardwareConfig

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# SEÑAL SINTÉTICA
# ════════════════════════════════════════════════════════════════════

@dataclass
class SyntheticSignal:
    freq_offset:   float = 0.0
    power_dbm:     float = -60.0
    mode:          str   = "tone"
    bw_hz:         float = 12_500.0
    audio_freq:    float = 1_000.0
    doppler_hz_s:  float = 0.0
    freq_drift_hz: float = 0.0

    @property
    def amplitude(self) -> float:
        power_w = 10 ** ((self.power_dbm - 30) / 10)
        return float(np.sqrt(2 * power_w * 50))


# ════════════════════════════════════════════════════════════════════
# GENERADOR DE MUESTRAS IQ
# ════════════════════════════════════════════════════════════════════

def generate_iq(sample_rate: int, n_samples: int,
                signals: list[SyntheticSignal],
                noise_floor_dbm: float = -100.0,
                t_offset_s: float = 0.0) -> np.ndarray:
    t   = np.arange(n_samples, dtype=np.float64) / sample_rate + t_offset_s
    out = np.zeros(n_samples, dtype=np.complex64)

    noise_power = 10 ** ((noise_floor_dbm - 30) / 10) / 50
    noise_amp   = float(np.sqrt(noise_power / 2))
    rng         = np.random.default_rng()
    out += (noise_amp * rng.standard_normal(n_samples)
            + 1j * noise_amp * rng.standard_normal(n_samples)).astype(np.complex64)

    for sig in signals:
        amp   = sig.amplitude
        mode  = sig.mode.lower()

        # Frecuencia instantánea con drift y Doppler lineales
        f_inst = (sig.freq_offset
                  + sig.freq_drift_hz * t
                  + 0.5 * sig.doppler_hz_s * t ** 2)
        carrier = np.exp(2j * np.pi * f_inst * t)

        if mode == "tone":
            iq = amp * carrier

        elif mode == "nfm":
            dev   = min(sig.bw_hz / 2, 5_000)
            audio = np.cos(2 * np.pi * sig.audio_freq * t)
            phase = 2 * np.pi * dev * np.cumsum(audio) / sample_rate
            iq    = amp * np.exp(1j * phase) * carrier

        elif mode == "wfm":
            dev   = 75_000
            audio = (
                0.5 * np.cos(2 * np.pi * 1_000 * t)
                + 0.3 * np.cos(2 * np.pi * 3_000 * t)
                + 0.2 * np.cos(2 * np.pi * 5_000 * t)
            )
            # Piloto estéreo 19 kHz
            audio += 0.1 * np.cos(2 * np.pi * 19_000 * t)
            phase = 2 * np.pi * dev * np.cumsum(audio) / sample_rate
            iq    = amp * np.exp(1j * phase) * carrier

        elif mode == "am":
            m     = 0.8
            audio = np.cos(2 * np.pi * sig.audio_freq * t)
            iq    = amp * (1 + m * audio) * carrier

        elif mode == "dsb":
            audio = np.cos(2 * np.pi * sig.audio_freq * t)
            iq    = amp * audio * carrier

        elif mode == "noise":
            n_sig   = (rng.standard_normal(n_samples)
                       + 1j * rng.standard_normal(n_samples)).astype(np.complex64)
            n_fft   = len(n_sig)
            bins_bw = int(sig.bw_hz / (sample_rate / n_fft))
            N       = np.fft.fftshift(np.fft.fft(n_sig))
            mid     = n_fft // 2
            mask    = np.zeros(n_fft)
            mask[mid - bins_bw // 2: mid + bins_bw // 2] = 1
            n_sig   = np.fft.ifft(np.fft.ifftshift(N * mask))
            std     = np.std(n_sig)
            iq      = amp * (n_sig / (std + 1e-10)) * carrier

        elif mode == "pulsed":
            # Radar / señal pulsada — burst 50µs cada 1ms
            pulse_period = int(sample_rate * 0.001)
            pulse_width  = int(sample_rate * 50e-6)
            envelope     = np.zeros(n_samples)
            for start in range(0, n_samples, pulse_period):
                envelope[start:start + pulse_width] = 1.0
            iq = amp * envelope * carrier

        else:
            iq = amp * carrier

        # Multitrayecto: reflejo atenuado y retardado 2µs
        delay_samples = int(sample_rate * 2e-6)
        if delay_samples > 0 and delay_samples < n_samples:
            multipath    = np.zeros(n_samples, dtype=np.complex64)
            multipath[delay_samples:] = iq[:-delay_samples] * 0.3
            iq = iq + multipath

        out += iq.astype(np.complex64)

    return out


# ════════════════════════════════════════════════════════════════════
# MOCK SDR MANAGER
# ════════════════════════════════════════════════════════════════════

class MockSDRManager:

    def __init__(self, sample_rate: int = 2_048_000,
                 noise_floor_dbm: float = -100.0):
        self.sample_rate    = sample_rate
        self.noise_floor    = noise_floor_dbm
        self._signals:      list[SyntheticSignal] = []
        self._iq_data:      Optional[np.ndarray]  = None
        self._iq_pos:       int   = 0
        self._current_freq: float = 0.0
        self._t_offset:     float = 0.0

        self.cfg     = HardwareConfig(sample_rate=sample_rate)
        self.hw_type = "MockSDR"
        self.hw_info = {
            "driver":      "mock",
            "sample_rate": sample_rate,
            "note":        "Hardware simulado para tests y desarrollo",
        }
        self.available = True
        log.info("MockSDR iniciado — SR=%.3f MHz", sample_rate / 1e6)

    @classmethod
    def from_file(cls, path: str,
                  sample_rate: int = 2_048_000) -> "MockSDRManager":
        p    = Path(path)
        mock = cls(sample_rate=sample_rate)

        meta_path = Path(
            str(p)
            .replace(".sigmf-data", ".sigmf-meta")
            .replace(".cf32", ".sigmf-meta")
            .replace(".iq", ".json")
        )
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                if "global" in meta:
                    cap_sr   = meta["global"].get("core:sample_rate")
                    cap_freq = meta.get("captures", [{}])[0].get(
                        "core:frequency", 0
                    )
                else:
                    cap_sr   = meta.get("sample_rate")
                    cap_freq = meta.get("frecuencia_hz", 0)
                if cap_sr:
                    mock.sample_rate = int(cap_sr)
                mock._current_freq = float(cap_freq)
                log.debug("Metadata: SR=%d freq=%.3fMHz",
                          mock.sample_rate, cap_freq / 1e6)
            except Exception as e:
                log.debug("No se pudo leer metadata: %s", e)

        suffix = p.suffix.lower()
        if suffix in (".sigmf-data", ".cf32", ".iq"):
            raw = np.fromfile(str(p), dtype=np.float32)
            mock._iq_data = (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
        else:
            mock._iq_data = np.fromfile(str(p), dtype=np.complex64)

        log.info("MockSDR cargo %d muestras desde %s",
                 len(mock._iq_data), p.name)
        return mock

    def add_signal(self, sig: SyntheticSignal):
        self._signals.append(sig)
        log.debug(
            "MockSDR: señal añadida offset=%.1fkHz pwr=%.0fdBm modo=%s",
            sig.freq_offset / 1e3, sig.power_dbm, sig.mode,
        )

    def capture(self, freq_hz: float,
                n_samples: Optional[int] = None) -> np.ndarray:
        if n_samples is None:
            n_samples = getattr(self.cfg, "samples_per_read", 524_288)

        self._current_freq = freq_hz
        time.sleep(0.005)

        if self._iq_data is not None:
            avail = len(self._iq_data) - self._iq_pos
            if avail < n_samples:
                self._iq_pos = 0
            chunk       = self._iq_data[self._iq_pos: self._iq_pos + n_samples]
            self._iq_pos += n_samples
            return chunk

        iq = generate_iq(
            sample_rate     = self.sample_rate,
            n_samples       = n_samples,
            signals         = self._signals,
            noise_floor_dbm = self.noise_floor,
            t_offset_s      = self._t_offset,
        )
        self._t_offset += n_samples / self.sample_rate
        return iq

    def set_gain(self, gain_db: float):
        self.cfg.gain_db = gain_db

    def set_ppm(self, ppm: int):
        self.cfg.ppm_correction = ppm

    def connect(self, **_) -> bool:
        return True

    def close(self):
        log.debug("MockSDR cerrado")


# ════════════════════════════════════════════════════════════════════
# GENERADOR DE FIXTURES SIGMF
# ════════════════════════════════════════════════════════════════════

def generate_fixture(path: str, freq_hz: float, sample_rate: int,
                     duration_s: float, signals: list[SyntheticSignal],
                     noise_dbm: float = -100.0) -> Path:
    n_samples = int(sample_rate * duration_s)
    iq        = generate_iq(sample_rate, n_samples, signals, noise_dbm)

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Datos en formato interleaved float32 (SigMF cf32_le)
    interleaved = np.empty(n_samples * 2, dtype=np.float32)
    interleaved[0::2] = iq.real
    interleaved[1::2] = iq.imag
    interleaved.tofile(str(out_path))

    from datetime import timezone as _tz
    meta_path = Path(
        str(out_path)
        .replace(".cf32", ".sigmf-meta")
        .replace(".sigmf-data", ".sigmf-meta")
    )
    meta = {
        "global": {
            "core:datatype":    "cf32_le",
            "core:sample_rate": sample_rate,
            "core:version":     "1.0.0",
            "core:description": f"Test fixture — {duration_s}s",
            "core:date":        datetime.now(_tz.utc).isoformat(),
        },
        "captures": [{
            "core:sample_start": 0,
            "core:frequency":    freq_hz,
            "core:datetime":     datetime.now(_tz.utc).isoformat(),
        }],
        "annotations": [
            {
                "core:sample_start":    0,
                "core:sample_count":    n_samples,
                "core:freq_lower_edge": freq_hz - sample_rate / 2,
                "core:freq_upper_edge": freq_hz + sample_rate / 2,
                "core:comment":
                    f"{sig.mode} @ {(freq_hz + sig.freq_offset) / 1e6:.3f} MHz",
            }
            for sig in signals
        ],
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    log.info(
        "Fixture: %s (%d muestras, %.1f MB)",
        out_path.name, n_samples, out_path.stat().st_size / 1e6,
    )
    return out_path


# Importación diferida de datetime para generate_fixture
from datetime import datetime
