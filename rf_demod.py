import logging
import math
import struct
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from rf_config import DemodConfig

log = logging.getLogger(__name__)

# ── pyaudio es opcional ──────────────────────────────────────────────
try:
    import pyaudio
    _PYAUDIO_OK = True
except ImportError:
    _PYAUDIO_OK = False


class Demodulator:
    """
    Demodulador de señales RF.

    Todos los métodos son pure functions sobre arrays numpy.
    El estado (fase FM) se guarda entre llamadas para continuidad.
    """

    def __init__(self, cfg: DemodConfig, sample_rate: int):
        self.cfg = cfg
        self.sample_rate = sample_rate
        self._prev_phase = 0.0   # estado para FM
        self._pa_stream = None
        self._pa = None

        # Relación de decimación
        self.decimation = max(1, int(sample_rate / cfg.audio_rate))
        self.audio_rate_actual = sample_rate // self.decimation

        log.debug(
            f"Demodulator — modo={cfg.mode} "
            f"SR_in={sample_rate} "
            f"SR_out={self.audio_rate_actual} "
            f"decimación=1/{self.decimation}"
        )

    def demodulate(self, iq: np.ndarray) -> Optional[np.ndarray]:
        """
        Demodula muestras IQ según el modo configurado.

        Args:
            iq: array complex64 de muestras IQ

        Returns:
            Audio float32 normalizado [-1, 1], o None si mode="none".
        """
        mode = self.cfg.mode.lower()

        if mode == "none":
            return None
        elif mode == "wfm":
            return self._demod_wfm(iq)
        elif mode == "nfm":
            return self._demod_nfm(iq)
        elif mode == "am":
            return self._demod_am(iq)
        elif mode == "usb":
            return self._demod_ssb(iq, upper=True)
        elif mode == "lsb":
            return self._demod_ssb(iq, upper=False)
        else:
            log.warning(f"Modo de demodulación desconocido: {mode}")
            return None

    # ── Demoduladores ────────────────────────────────────────────────

    def _demod_wfm(self, iq: np.ndarray) -> np.ndarray:
        """
        Wide FM — Radio FM comercial (200 kHz BW, audio 15 kHz).
        Proceso: discriminador de fase → de-énfasis 75µs → decimar.
        """
        # Discriminador FM por diferencia de fase
        audio = self._fm_discriminator(iq)

        # De-énfasis 75µs (estándar broadcast FM)
        audio = self._deemphasis(audio, tau=75e-6)

        # Decimación
        audio = audio[::self.decimation]
        return self._normalize(audio) * self.cfg.volume

    def _demod_nfm(self, iq: np.ndarray) -> np.ndarray:
        """
        Narrow FM — PMR, radio amateur, servicios de emergencia.
        De-énfasis 25µs (NBFM estándar).
        """
        audio = self._fm_discriminator(iq)
        audio = self._deemphasis(audio, tau=25e-6)
        audio = audio[::self.decimation]
        return self._normalize(audio) * self.cfg.volume

    def _demod_am(self, iq: np.ndarray) -> np.ndarray:
        """
        AM (detección de envolvente) — aviación ATC, AM broadcast.
        """
        # Envolvente = módulo de la señal compleja
        envolvente = np.abs(iq)
        # Eliminar DC (componente continua de la portadora)
        envolvente -= np.mean(envolvente)
        audio = envolvente[::self.decimation]
        return self._normalize(audio) * self.cfg.volume

    def _demod_ssb(self, iq: np.ndarray, upper: bool = True) -> np.ndarray:
        """
        SSB — USB (upper sideband) o LSB (lower sideband).
        Usado en HF amateur, aeronáutico HF, militar.
        Implementado con filtro de Hilbert aproximado.
        """
        # Tomar solo la parte real (proyección de la señal compleja)
        real_part = iq.real

        # Filtro Hilbert via ventana — aproximación suficiente para audio
        n = 63  # longitud del filtro impar
        k = np.arange(-(n//2), n//2 + 1)
        h = np.sinc(k) * np.blackman(n + 1)
        h /= np.sum(h)
        # Derivada del filtro paso de banda — aproxima la transformada de Hilbert
        hilbert = np.zeros(n + 1)
        mask = k != 0
        hilbert[mask] = (1 - np.cos(np.pi * k[mask])) / (np.pi * k[mask])
        hilbert = hilbert * np.blackman(n + 1)
        hilbert /= np.sum(np.abs(hilbert)) / 2

        analytic_imag = np.convolve(real_part, hilbert, mode="same")

        if upper:
            audio = real_part + analytic_imag  # USB: f > 0
        else:
            audio = real_part - analytic_imag  # LSB: f < 0

        audio = audio[::self.decimation]
        return self._normalize(audio) * self.cfg.volume

    # ── DSP helpers ──────────────────────────────────────────────────

    def _fm_discriminator(self, iq: np.ndarray) -> np.ndarray:
        """
        Discriminador FM por diferencia de fase instantánea.
        audio[n] = angle(iq[n] * conj(iq[n-1]))

        Más estable que atan2(Q/I) derivado porque evita
        discontinuidades en ±π.
        """
        # Producto con muestra anterior conjugada
        delayed = np.empty_like(iq)
        delayed[0] = iq[0] * np.exp(1j * self._prev_phase).conj()
        delayed[1:] = iq[1:] * np.conj(iq[:-1])

        # Guardar la fase de la última muestra para la siguiente llamada
        self._prev_phase = float(np.angle(iq[-1]))

        return np.angle(delayed)

    def _deemphasis(self, audio: np.ndarray, tau: float) -> np.ndarray:
        """
        Filtro de de-énfasis RC de primer orden.
        H(z) = (1-α) / (1 - α·z⁻¹), α = exp(-1/(SR·τ))
        """
        alpha = math.exp(-1.0 / (self.sample_rate * tau))
        out = np.empty_like(audio)
        y = 0.0
        k = 1.0 - alpha
        for i, x in enumerate(audio):
            y = k * x + alpha * y
            out[i] = y
        return out

    @staticmethod
    def _normalize(audio: np.ndarray) -> np.ndarray:
        """Normaliza a [-1, 1] evitando división por cero."""
        peak = np.max(np.abs(audio))
        if peak < 1e-9:
            return audio
        return audio / peak

    # ── Salida de audio ──────────────────────────────────────────────

    def play(self, audio: np.ndarray):
        """
        Reproduce audio en tiempo real con pyaudio.
        Requiere: pip install pyaudio
        En uConsole: apt install python3-pyaudio portaudio19-dev
        """
        if not _PYAUDIO_OK:
            log.warning(
                "pyaudio no disponible. "
                "Instala: sudo apt install python3-pyaudio portaudio19-dev"
            )
            return

        data = (audio.astype(np.float32) * 32767).astype(np.int16).tobytes()

        if self._pa is None:
            self._pa = pyaudio.PyAudio()
            self._pa_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.audio_rate_actual,
                output=True,
                frames_per_buffer=1024,
            )

        if self._pa_stream:
            self._pa_stream.write(data)

    def stop_audio(self):
        """Cierra el stream de pyaudio."""
        if self._pa_stream:
            try:
                self._pa_stream.stop_stream()
                self._pa_stream.close()
            except Exception:
                pass
            self._pa_stream = None

        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def save_wav(self, audio: np.ndarray, path: str):
        """Guarda audio en archivo WAV 16-bit mono."""
        data = (audio.astype(np.float32) * 32767).astype(np.int16)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)   # 16-bit
            wf.setframerate(self.audio_rate_actual)
            wf.writeframes(data.tobytes())
        log.info(f"Audio guardado → {path}")

    def __del__(self):
        self.stop_audio()
