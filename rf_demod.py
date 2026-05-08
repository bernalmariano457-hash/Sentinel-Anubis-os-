from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from rf_config import DemodConfig

log = logging.getLogger("sentinel.rf.demod")

# ── Detección de plataforma ───────────────────────────────────────
_IS_ANDROID = "com.termux" in os.environ.get("PREFIX", "") or \
              os.path.exists("/data/data/com.termux")
_IS_LINUX = sys.platform.startswith("linux") and not _IS_ANDROID

# ── pyaudio (Linux / uConsole) ────────────────────────────────────
_PYAUDIO_OK = False
if _IS_LINUX:
    try:
        import pyaudio
        _PYAUDIO_OK = True
    except ImportError:
        pass

# ── sounddevice (alternativa multiplataforma) ─────────────────────
_SOUNDDEVICE_OK = False
try:
    import sounddevice as sd
    _SOUNDDEVICE_OK = True
except ImportError:
    pass

# ── scipy para decimación de calidad ─────────────────────────────
_SCIPY_OK = False
try:
    from scipy.signal import decimate as _scipy_decimate
    _SCIPY_OK = True
except ImportError:
    pass


# ══════════════════════════════════════════════════════════════════
# DEMODULADOR
# ══════════════════════════════════════════════════════════════════

class Demodulator:
    """
    Demodulador de señales RF para APEX SENTINEL.

    Todos los modos operan sobre arrays numpy (IQ complex64).
    El estado de fase se conserva entre llamadas para continuidad de audio.

    Uso:
        cfg = DemodConfig(mode="wfm", audio_rate=48000, volume=0.8)
        demod = Demodulator(cfg, sample_rate=2_048_000)

        audio = demod.demodulate(iq_samples)
        demod.play(audio)              # reproducción directa
        demod.save_wav(audio, "fm.wav") # guardar a archivo
    """

    def __init__(self, cfg: DemodConfig, sample_rate: int):
        self.cfg = cfg
        self.sample_rate = sample_rate
        self._prev_phase = 0.0
        self._pa_stream = None
        self._pa = None

        # Relación de decimación
        self.decimation = max(1, int(sample_rate / cfg.audio_rate))
        self.audio_rate_actual = sample_rate // self.decimation

        log.debug(
            f"Demodulator init — modo={cfg.mode} "
            f"SR_in={sample_rate/1e6:.3f}MHz "
            f"SR_out={self.audio_rate_actual}Hz "
            f"decimación=1/{self.decimation}"
        )

        # Avisar qué backend de audio está disponible
        if _IS_ANDROID:
            log.info("Plataforma Android: audio vía termux-media-player o WAV")
        elif _SOUNDDEVICE_OK:
            log.info("Audio backend: sounddevice")
        elif _PYAUDIO_OK:
            log.info("Audio backend: pyaudio")
        else:
            log.warning(
                "Sin backend de audio. "
                "En uConsole: sudo apt install python3-pyaudio portaudio19-dev | "
                "pip install sounddevice"
            )

    # ── API pública ────────────────────────────────────────────────

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
            log.warning(f"Modo desconocido: {mode}")
            return None

    def play(self, audio: np.ndarray) -> bool:
        """
        Reproduce audio usando el mejor backend disponible.

        En Android usa termux-media-player (guarda WAV temporal).
        En Linux usa sounddevice o pyaudio.

        Retorna True si pudo reproducir.
        """
        if audio is None or len(audio) == 0:
            return False

        if _IS_ANDROID:
            return self._play_android(audio)
        elif _SOUNDDEVICE_OK:
            return self._play_sounddevice(audio)
        elif _PYAUDIO_OK:
            return self._play_pyaudio(audio)
        else:
            log.warning("Sin backend de audio disponible.")
            return False

    def save_wav(self, audio: np.ndarray, path: str) -> Path:
        """Guarda audio en archivo WAV 16-bit mono."""
        data = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dest), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.audio_rate_actual)
            wf.writeframes(data.tobytes())
        log.info(
            f"Audio WAV guardado: {dest} ({len(audio)/self.audio_rate_actual:.1f}s)")
        return dest

    def stop_audio(self):
        """Cierra streams de audio activos."""
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

    # ── Demoduladores ──────────────────────────────────────────────

    def _demod_wfm(self, iq: np.ndarray) -> np.ndarray:
        """Wide FM — Radio FM comercial (200 kHz BW, de-énfasis 75µs)."""
        audio = self._fm_discriminator(iq)
        audio = self._deemphasis_vectorized(audio, tau=75e-6)
        audio = self._decimar(audio)
        return self._normalize(audio) * self.cfg.volume

    def _demod_nfm(self, iq: np.ndarray) -> np.ndarray:
        """Narrow FM — PMR, radio amateur, emergencias (de-énfasis 25µs)."""
        audio = self._fm_discriminator(iq)
        audio = self._deemphasis_vectorized(audio, tau=25e-6)
        audio = self._decimar(audio)
        return self._normalize(audio) * self.cfg.volume

    def _demod_am(self, iq: np.ndarray) -> np.ndarray:
        """AM por detección de envolvente — aviación ATC, AM broadcast."""
        envolvente = np.abs(iq)
        envolvente -= np.mean(envolvente)   # eliminar DC
        audio = self._decimar(envolvente)
        return self._normalize(audio) * self.cfg.volume

    def _demod_ssb(self, iq: np.ndarray, upper: bool = True) -> np.ndarray:
        """
        SSB — USB (upper) o LSB (lower).
        HF amateur, aeronáutico HF, militar.
        """
        real_part = iq.real
        n = 63
        k = np.arange(-(n // 2), n // 2 + 1, dtype=float)

        # Filtro Hilbert aproximado con ventana Blackman
        hilbert = np.zeros(n + 1)
        mask = k != 0
        hilbert[mask] = (1 - np.cos(np.pi * k[mask])) / (np.pi * k[mask])
        hilbert *= np.blackman(n + 1)
        norm = np.sum(np.abs(hilbert))
        if norm > 0:
            hilbert /= norm / 2

        analytic_imag = np.convolve(real_part, hilbert, mode="same")
        audio = (real_part + analytic_imag) if upper else (real_part - analytic_imag)
        audio = self._decimar(audio)
        return self._normalize(audio) * self.cfg.volume

    # ── DSP helpers ────────────────────────────────────────────────

    def _fm_discriminator(self, iq: np.ndarray) -> np.ndarray:
        """
        Discriminador FM por diferencia de fase instantánea.
        audio[n] = angle(iq[n] * conj(iq[n-1]))
        Conserva estado de fase entre llamadas para continuidad.
        """
        prev = np.empty(len(iq), dtype=complex)
        prev[0] = np.exp(1j * self._prev_phase)
        prev[1:] = iq[:-1]
        self._prev_phase = float(np.angle(iq[-1]))
        return np.angle(iq * np.conj(prev))

    def _deemphasis_vectorized(self, audio: np.ndarray, tau: float) -> np.ndarray:
        """
        Filtro de de-énfasis RC vectorizado (mucho más rápido que el loop Python).
        H(z) = (1-α) / (1 - α·z⁻¹),  α = exp(-1 / (SR·τ))
        """
        alpha = math.exp(-1.0 / (self.sample_rate * tau))
        k = 1.0 - alpha
        out = np.empty_like(audio)
        y = 0.0
        # Numba podría acelerar esto más — por ahora es suficiente para RT
        for i in range(len(audio)):
            y = k * audio[i] + alpha * y
            out[i] = y
        return out

    def _decimar(self, audio: np.ndarray) -> np.ndarray:
        """Decimación con antialiasing si scipy disponible, si no simple slicing."""
        if _SCIPY_OK and self.decimation > 1:
            try:
                return _scipy_decimate(audio, self.decimation, zero_phase=True)
            except Exception:
                pass
        return audio[::self.decimation]

    @staticmethod
    def _normalize(audio: np.ndarray) -> np.ndarray:
        """Normaliza a [-1, 1] evitando división por cero."""
        peak = np.max(np.abs(audio))
        return audio / peak if peak > 1e-9 else audio

    # ── Backends de audio ──────────────────────────────────────────

    def _play_android(self, audio: np.ndarray) -> bool:
        """
        Reproducción en Android/Termux mediante termux-media-player.
        Guarda WAV temporal, lo reproduce y lo elimina.
        Requiere: pkg install termux-api
        """
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            self.save_wav(audio, tmp.name)
            result = subprocess.run(
                ["termux-media-player", "play", tmp.name],
                timeout=30,
                capture_output=True,
            )
            if result.returncode != 0:
                log.warning(
                    "termux-media-player falló. "
                    "Instala: pkg install termux-api — "
                    f"El archivo WAV está en: {tmp.name}"
                )
                return False
            return True
        except FileNotFoundError:
            log.warning(
                "termux-media-player no encontrado. "
                "Instala: pkg install termux-api\n"
                f"Audio guardado en: {tmp.name}"
            )
            return False
        except Exception as e:
            log.error(f"Error reproduciendo en Android: {e}")
            return False
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except Exception:
                pass

    def _play_sounddevice(self, audio: np.ndarray) -> bool:
        """Reproducción con sounddevice (multiplataforma)."""
        try:
            sd.play(audio.astype(np.float32), self.audio_rate_actual)
            sd.wait()
            return True
        except Exception as e:
            log.error(f"sounddevice error: {e}")
            return False

    def _play_pyaudio(self, audio: np.ndarray) -> bool:
        """Reproducción con pyaudio (Linux nativo)."""
        try:
            data = (np.clip(audio, -1.0, 1.0) *
                    32767).astype(np.int16).tobytes()
            if self._pa is None:
                self._pa = pyaudio.PyAudio()
                self._pa_stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self.audio_rate_actual,
                    output=True,
                    frames_per_buffer=1024,
                )
            self._pa_stream.write(data)
            return True
        except Exception as e:
            log.error(f"pyaudio error: {e}")
            return False

    def __del__(self):
        self.stop_audio()
