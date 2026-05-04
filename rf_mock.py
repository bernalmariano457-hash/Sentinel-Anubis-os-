import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from rf_config import HardwareConfig

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# SEÑAL SINTÉTICA
# ════════════════════════════════════════════════════════════════════

@dataclass
class SyntheticSignal:
    """
    Definición de una señal RF sintética a inyectar en el mock.

    Args:
        freq_offset: desplazamiento en Hz respecto a la freq sintonizada
        power_dbm:   potencia de la señal en dBm
        mode:        modulación: tone | nfm | wfm | am | noise
        bw_hz:       ancho de banda de la señal (Hz)
        audio_freq:  frecuencia del tono de audio interno (Hz)
    """
    freq_offset: float = 0.0
    power_dbm:   float = -60.0
    mode:        str = "tone"
    bw_hz:       float = 12_500.0
    audio_freq:  float = 1_000.0

    @property
    def amplitude(self) -> float:
        """Amplitud lineal desde dBm (referencia 50Ω)."""
        power_w = 10 ** ((self.power_dbm - 30) / 10)  # dBm → W
        return float(np.sqrt(2 * power_w * 50))         # tensión pico


# ════════════════════════════════════════════════════════════════════
# GENERADOR DE MUESTRAS IQ
# ════════════════════════════════════════════════════════════════════

def generate_iq(sample_rate: int, n_samples: int,
                signals: list[SyntheticSignal],
                noise_floor_dbm: float = -100.0) -> np.ndarray:
    """
    Genera muestras IQ sintéticas mezclando señales y ruido.

    Args:
        sample_rate:    frecuencia de muestreo en Hz
        n_samples:      número de muestras a generar
        signals:        lista de señales sintéticas a sumar
        noise_floor_dbm: nivel del piso de ruido

    Returns:
        Array complex64 con las muestras IQ
    """
    t = np.arange(n_samples, dtype=np.float64) / sample_rate
    out = np.zeros(n_samples, dtype=np.complex64)

    # ── Ruido de fondo ───────────────────────────────────────────────
    noise_power = 10 ** ((noise_floor_dbm - 30) / 10) / 50
    noise_amp = float(np.sqrt(noise_power / 2))
    out += (noise_amp * np.random.randn(n_samples) +
            1j * noise_amp * np.random.randn(n_samples)).astype(np.complex64)

    # ── Señales ──────────────────────────────────────────────────────
    for sig in signals:
        amp = sig.amplitude
        f_off = sig.freq_offset
        mode = sig.mode.lower()

        # Portadora de la señal en la frecuencia desplazada
        carrier = np.exp(2j * np.pi * f_off * t)

        if mode == "tone":
            # Tono puro sin modulación
            iq = amp * carrier

        elif mode == "nfm":
            # NFM: frecuencia máx = bw/2, devex = audio / bw
            dev = min(sig.bw_hz / 2, 5_000)  # desviación máx 5kHz NFM
            audio = np.cos(2 * np.pi * sig.audio_freq * t)
            phase = 2 * np.pi * dev * np.cumsum(audio) / sample_rate
            iq = amp * np.exp(1j * phase) * carrier

        elif mode == "wfm":
            # WFM: desviación 75kHz, audio compuesto simulado
            dev = 75_000
            audio = (0.5 * np.cos(2 * np.pi * 1_000 * t) +
                     0.3 * np.cos(2 * np.pi * 3_000 * t) +
                     0.2 * np.cos(2 * np.pi * 5_000 * t))
            phase = 2 * np.pi * dev * np.cumsum(audio) / sample_rate
            iq = amp * np.exp(1j * phase) * carrier

        elif mode == "am":
            # AM con índice de modulación 0.8
            m = 0.8
            audio = np.cos(2 * np.pi * sig.audio_freq * t)
            iq = amp * (1 + m * audio) * carrier

        elif mode == "noise":
            # Señal de ruido gaussiana (simula señales digitales wideband)
            n_sig = (np.random.randn(n_samples) +
                     1j * np.random.randn(n_samples)).astype(np.complex64)
            # Limitar BW via filtro rectangular en frecuencia
            n_fft = len(n_sig)
            bins_bw = int(sig.bw_hz / (sample_rate / n_fft))
            N = np.fft.fftshift(np.fft.fft(n_sig))
            mid = n_fft // 2
            mask = np.zeros(n_fft)
            mask[mid - bins_bw//2: mid + bins_bw//2] = 1
            n_sig = np.fft.ifft(np.fft.ifftshift(N * mask))
            iq = amp * (n_sig / (np.std(n_sig) + 1e-10)) * carrier

        else:
            iq = amp * carrier

        out += iq.astype(np.complex64)

    return out


# ════════════════════════════════════════════════════════════════════
# MOCK SDR MANAGER
# ════════════════════════════════════════════════════════════════════

class MockSDRManager:
    """
    Mock del SDRManager que no requiere hardware real.

    Compatible con la interfaz de SDRManager:
      - available → True
      - capture(freq_hz, n_samples) → array IQ
      - set_gain / set_ppm
      - close()

    Útil para:
      - Tests unitarios sin RTL-SDR
      - Desarrollo de la UI sin hardware
      - CI/CD en servidores sin USB
    """

    def __init__(self, sample_rate: int = 2_048_000,
                 noise_floor_dbm: float = -100.0):
        self.sample_rate = sample_rate
        self.noise_floor = noise_floor_dbm
        self._signals:      list[SyntheticSignal] = []
        self._iq_data:      Optional[np.ndarray] = None
        self._iq_pos:       int = 0
        self._current_freq: float = 0.0

        # Simular la interfaz de SDRManager
        self.cfg = HardwareConfig(sample_rate=sample_rate)
        self.hw_type = "MockSDR"
        self.hw_info = {
            "driver": "mock",
            "sample_rate": sample_rate,
            "note": "Hardware simulado para tests",
        }
        self.available = True
        log.info(f"MockSDR iniciado — SR={sample_rate/1e6:.3f} MHz")

    @classmethod
    def from_file(cls, path: str, sample_rate: int = 2_048_000) -> "MockSDRManager":
        """
        Crea un MockSDR que sirve muestras desde un archivo .cf32 o .sigmf-data.

        Args:
            path: ruta al archivo de muestras IQ float32 intercalado
            sample_rate: sample rate de las muestras
        """
        p = Path(path)
        mock = cls(sample_rate=sample_rate)

        # Intentar leer metadatos SigMF
        # Soportar .sigmf-data y .cf32
        meta_path = Path(
            str(p)
            .replace(".sigmf-data", ".sigmf-meta")
            .replace(".cf32", ".sigmf-meta")
        )
        if meta_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
            except (UnicodeDecodeError, json.JSONDecodeError):
                log.debug(f"No se pudo leer meta SigMF: {meta_path}")
            cap_sr = meta.get("global", {}).get("core:sample_rate")
            if cap_sr:
                mock.sample_rate = int(cap_sr)
            cap_freq = meta.get("captures", [{}])[0].get("core:frequency", 0)
            mock._current_freq = cap_freq
            log.debug(
                f"SigMF meta: SR={mock.sample_rate} freq={cap_freq/1e6:.3f} MHz")

        raw = np.fromfile(str(p), dtype=np.float32)
        mock._iq_data = raw[0::2] + 1j * raw[1::2]
        mock._iq_data = mock._iq_data.astype(np.complex64)
        log.info(
            f"MockSDR cargó {len(mock._iq_data):,} muestras "
            f"desde {p.name}"
        )
        return mock

    def add_signal(self, sig: SyntheticSignal):
        """Añade una señal sintética al generador."""
        self._signals.append(sig)
        log.debug(
            f"MockSDR: señal añadida "
            f"offset={sig.freq_offset/1e3:.1f} kHz  "
            f"pwr={sig.power_dbm} dBm  "
            f"modo={sig.mode}"
        )

    def capture(self, freq_hz: float,
                n_samples: Optional[int] = None) -> np.ndarray:
        """
        Retorna muestras IQ (desde fixture o generadas sintéticamente).
        Simula la latencia USB real con un sleep mínimo.
        """
        if n_samples is None:
            n_samples = self.cfg.samples_per_read

        self._current_freq = freq_hz
        time.sleep(0.01)  # simular latencia USB mínima

        # ── Servir desde fixture ─────────────────────────────────────
        if self._iq_data is not None:
            avail = len(self._iq_data) - self._iq_pos
            if avail < n_samples:
                # Wrap-around al inicio
                self._iq_pos = 0
                avail = len(self._iq_data)

            chunk = self._iq_data[self._iq_pos:self._iq_pos + n_samples]
            self._iq_pos += n_samples
            return chunk

        # ── Generar sintéticamente ───────────────────────────────────
        return generate_iq(
            sample_rate=self.sample_rate,
            n_samples=n_samples,
            signals=self._signals,
            noise_floor_dbm=self.noise_floor,
        )

    def set_gain(self, gain_db: float):
        self.cfg.gain_db = gain_db
        log.debug(f"MockSDR: ganancia={gain_db} dB")

    def set_ppm(self, ppm: int):
        self.cfg.ppm_correction = ppm
        log.debug(f"MockSDR: PPM={ppm}")

    def connect(self, **_) -> bool:
        return True

    def close(self):
        log.debug("MockSDR: cerrado")


# ════════════════════════════════════════════════════════════════════
# GENERADOR DE FIXTURES
# ════════════════════════════════════════════════════════════════════

def generate_fixture(path: str, freq_hz: float, sample_rate: int,
                     duration_s: float, signals: list[SyntheticSignal],
                     noise_dbm: float = -100.0):
    """
    Genera un archivo de fixture IQ (.cf32) para usar en tests.
    Incluye metadatos SigMF.

    Ejemplo:
        generate_fixture(
            "tests/fixtures/fm_broadcast.cf32",
            freq_hz=100e6,
            sample_rate=2_048_000,
            duration_s=5.0,
            signals=[SyntheticSignal(freq_offset=0, power_dbm=-50, mode="wfm")],
        )
    """
    n_samples = int(sample_rate * duration_s)
    iq = generate_iq(sample_rate, n_samples, signals, noise_dbm)

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Escribir datos
    iq.astype(np.complex64).tofile(str(out_path))

    # Escribir metadatos SigMF
    from datetime import datetime, timezone
    meta_path = Path(str(out_path).replace(".cf32", ".sigmf-meta")
                     .replace(".sigmf-data", ".sigmf-meta"))
    meta = {
        "global": {
            "core:datatype":    "cf32_le",
            "core:sample_rate": sample_rate,
            "core:version":     "1.0.0",
            "core:description": f"Test fixture — {duration_s}s",
        },
        "captures": [{
            "core:sample_start": 0,
            "core:frequency":    freq_hz,
            "core:datetime":     datetime.now(timezone.utc).isoformat(),
        }],
        "annotations": [
            {
                "core:sample_start":  0,
                "core:sample_count":  n_samples,
                "core:freq_lower_edge": freq_hz - sample_rate/2,
                "core:freq_upper_edge": freq_hz + sample_rate/2,
                "core:comment": f"{sig.mode} @ {(freq_hz + sig.freq_offset)/1e6:.3f} MHz"
            }
            for sig in signals
        ],
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    log.info(
        f"Fixture generada: {out_path.name} "
        f"({n_samples:,} muestras, {out_path.stat().st_size/1e6:.1f} MB)"
    )
    return out_path
