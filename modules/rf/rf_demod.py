from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from modules.rf.rf_config import DemodConfig

log = logging.getLogger("sentinel.rf.demod")

_IS_ANDROID = (
    "com.termux" in os.environ.get("PREFIX", "")
    or os.path.exists("/data/data/com.termux")
)
_IS_LINUX = sys.platform.startswith("linux") and not _IS_ANDROID

_PYAUDIO_OK = False
if _IS_LINUX:
    try:
        import pyaudio
        _PYAUDIO_OK = True
    except ImportError:
        pass

_SOUNDDEVICE_OK = False
try:
    import sounddevice as sd
    _SOUNDDEVICE_OK = True
except ImportError:
    pass

_SCIPY_OK = False
try:
    from scipy.signal import decimate as _scipy_decimate, butter, sosfilt
    _SCIPY_OK = True
except ImportError:
    pass

# Numba acelera el filtro de de-énfasis 10-15x en hardware real
_NUMBA_OK = False
try:
    from numba import njit as _njit
    _NUMBA_OK = True

    @_njit(cache=True)
    def _deemph_loop(audio: np.ndarray, alpha: float, k: float) -> np.ndarray:
        out = np.empty_like(audio)
        y   = 0.0
        for i in range(len(audio)):
            y      = k * audio[i] + alpha * y
            out[i] = y
        return out

except ImportError:
    def _deemph_loop(audio: np.ndarray, alpha: float, k: float) -> np.ndarray:
        out = np.empty_like(audio)
        y   = 0.0
        for i in range(len(audio)):
            y      = k * audio[i] + alpha * y
            out[i] = y
        return out

# DEMODULADOR

class Demodulator:

    def __init__(self, cfg: DemodConfig, sample_rate: int) -> None:
        self.cfg         = cfg
        self.sample_rate = sample_rate
        self._prev_phase = 0.0
        self._pa_stream  = None
        self._pa         = None
        self._agc_gain   = 1.0      # ganancia AGC suave para nivel consistente

        self.decimation       = max(1, int(sample_rate / cfg.audio_rate))
        self.audio_rate_actual = sample_rate // self.decimation

        backend = (
            "numba" if _NUMBA_OK
            else "sounddevice" if _SOUNDDEVICE_OK
            else "pyaudio" if _PYAUDIO_OK
            else "WAV/stderr"
        )
        log.debug(
            "Demodulator — modo=%s SR_in=%.3fMHz SR_out=%dHz "
            "decimacion=1/%d backend=%s",
            cfg.mode, sample_rate / 1e6,
            self.audio_rate_actual, self.decimation, backend,
        )

    # API pública
    def demodulate(self, iq: np.ndarray) -> np.ndarray | None:
        mode = self.cfg.mode.lower()
        if mode == "none":
            return None
        if mode == "wfm":
            return self._demod_wfm(iq)
        if mode == "nfm":
            return self._demod_nfm(iq)
        if mode == "am":
            return self._demod_am(iq)
        if mode == "usb":
            return self._demod_ssb(iq, upper=True)
        if mode == "lsb":
            return self._demod_ssb(iq, upper=False)
        log.warning("Modo de demodulacion desconocido: %s", mode)
        return None

    def play(self, audio: np.ndarray) -> bool:
        if audio is None or len(audio) == 0:
            return False
        if _IS_ANDROID:
            return self._play_android(audio)
        if _SOUNDDEVICE_OK:
            return self._play_sounddevice(audio)
        if _PYAUDIO_OK:
            return self._play_pyaudio(audio)
        log.warning("Sin backend de audio disponible.")
        return False

    def save_wav(self, audio: np.ndarray, path: str) -> Path:
        data = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dest), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.audio_rate_actual)
            wf.writeframes(data.tobytes())
        log.info("WAV guardado: %s (%.1fs)", dest,
                 len(audio) / self.audio_rate_actual)
        return dest

    def stop_audio(self) -> None:
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

    # Demoduladores
    def _demod_wfm(self, iq: np.ndarray) -> np.ndarray:
        audio = self._fm_discriminator(iq)
        audio = self._deemphasis(audio, tau=75e-6)
        audio = self._decimar(audio)
        audio = self._soft_agc(audio)
        return np.clip(audio * self.cfg.volume, -1.0, 1.0)

    def _demod_nfm(self, iq: np.ndarray) -> np.ndarray:
        audio = self._fm_discriminator(iq)
        audio = self._deemphasis(audio, tau=25e-6)
        # Squelch basado en desviación de fase: silencia portadora sin modulación
        dev = float(np.std(audio))
        if dev < 0.005:
            return np.zeros(len(audio) // self.decimation, dtype=np.float32)
        audio = self._decimar(audio)
        audio = self._soft_agc(audio)
        return np.clip(audio * self.cfg.volume, -1.0, 1.0)

    def _demod_am(self, iq: np.ndarray) -> np.ndarray:
        envolvente = np.abs(iq).astype(np.float32)
        envolvente -= np.mean(envolvente)
        audio = self._decimar(envolvente)
        audio = self._soft_agc(audio)
        return np.clip(audio * self.cfg.volume, -1.0, 1.0)

    def _demod_ssb(self, iq: np.ndarray, upper: bool = True) -> np.ndarray:
        real_part = iq.real.astype(np.float32)
        n = 127
        k = np.arange(-(n // 2), n // 2 + 1, dtype=np.float32)

        hilbert = np.zeros(n + 1, dtype=np.float32)
        mask    = k != 0
        hilbert[mask] = (1 - np.cos(np.pi * k[mask])) / (np.pi * k[mask])
        window  = np.blackman(n + 1).astype(np.float32)
        hilbert *= window
        norm    = np.sum(np.abs(hilbert))
        if norm > 0:
            hilbert /= norm / 2.0

        analytic_imag = np.convolve(real_part, hilbert, mode="same")
        audio = (real_part + analytic_imag) if upper else (real_part - analytic_imag)
        audio = self._decimar(audio)
        audio = self._soft_agc(audio)
        return np.clip(audio * self.cfg.volume, -1.0, 1.0)

    # DSP helpers
    def _fm_discriminator(self, iq: np.ndarray) -> np.ndarray:
        prev    = np.empty(len(iq), dtype=np.complex64)
        prev[0] = np.exp(1j * self._prev_phase)
        prev[1:] = iq[:-1]
        self._prev_phase = float(np.angle(iq[-1]))
        return np.angle(iq * np.conj(prev)).astype(np.float32)

    def _deemphasis(self, audio: np.ndarray, tau: float) -> np.ndarray:
        if tau <= 0:
            return audio
        alpha = math.exp(-1.0 / (self.sample_rate * tau))
        k     = 1.0 - alpha
        return _deemph_loop(audio.astype(np.float32), alpha, k)

    def _decimar(self, audio: np.ndarray) -> np.ndarray:
        if self.decimation <= 1:
            return audio
        if _SCIPY_OK:
            try:
                return _scipy_decimate(
                    audio, self.decimation, zero_phase=True
                ).astype(np.float32)
            except Exception:
                pass
        return audio[::self.decimation]

    def _soft_agc(self, audio: np.ndarray,
                  attack: float = 0.01, release: float = 0.001) -> np.ndarray:
        peak = float(np.max(np.abs(audio)))
        if peak < 1e-9:
            return audio
        target_gain = 1.0 / peak
        # Seguimiento suave de ganancia para evitar clics
        alpha = attack if target_gain < self._agc_gain else release
        self._agc_gain = self._agc_gain * (1 - alpha) + target_gain * alpha
        return (audio * self._agc_gain).astype(np.float32)

    @staticmethod
    def _normalize(audio: np.ndarray) -> np.ndarray:
        peak = np.max(np.abs(audio))
        return audio / peak if peak > 1e-9 else audio

    # Backends de audio
    def _play_android(self, audio: np.ndarray) -> bool:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            self.save_wav(audio, tmp.name)
            result = subprocess.run(
                ["termux-media-player", "play", tmp.name],
                timeout=30, capture_output=True,
            )
            if result.returncode != 0:
                log.warning(
                    "termux-media-player fallo. "
                    "Instala: pkg install termux-api — WAV: %s", tmp.name
                )
                return False
            return True
        except FileNotFoundError:
            log.warning(
                "termux-media-player no encontrado. "
                "Instala: pkg install termux-api — WAV: %s", tmp.name
            )
            return False
        except Exception as e:
            log.error("Error reproduciendo en Android: %s", e)
            return False
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except Exception:
                pass

    def _play_sounddevice(self, audio: np.ndarray) -> bool:
        try:
            sd.play(audio.astype(np.float32), self.audio_rate_actual)
            sd.wait()
            return True
        except Exception as e:
            log.error("sounddevice error: %s", e)
            return False

    def _play_pyaudio(self, audio: np.ndarray) -> bool:
        try:
            data = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
            if self._pa is None:
                self._pa        = pyaudio.PyAudio()
                self._pa_stream = self._pa.open(
                    format=pyaudio.paInt16, channels=1,
                    rate=self.audio_rate_actual, output=True,
                    frames_per_buffer=2048,
                )
            self._pa_stream.write(data)
            return True
        except Exception as e:
            log.error("pyaudio error: %s", e)
            return False

    def __del__(self) -> None:
        self.stop_audio()
