from __future__ import annotations

import logging
import math
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Callable, Final, Protocol

import numpy as np

from modules.rf.rf_config import DemodConfig

log: Final = logging.getLogger("sentinel.rf.demod")

_IS_ANDROID: Final[bool] = (
    "com.termux" in os.environ.get("PREFIX", "")
    or os.path.exists("/data/data/com.termux")
)
_IS_LINUX: Final[bool] = sys.platform.startswith("linux") and not _IS_ANDROID

_WFM_DEEMPH_TAU: Final[float] = 75e-6
_NFM_DEEMPH_TAU: Final[float] = 25e-6
_NFM_SQUELCH_STD_FLOOR: Final[float] = 0.005
_SSB_FILTER_LENGTH: Final[int] = 127
_PYAUDIO_FRAMES_PER_BUFFER: Final[int] = 2048
_ANDROID_PLAYBACK_TIMEOUT_S: Final[int] = 30
_AGC_PEAK_FLOOR: Final[float] = 1e-9
_AGC_DEFAULT_ATTACK: Final[float] = 0.01
_AGC_DEFAULT_RELEASE: Final[float] = 0.001
_WAV_SAMPLE_WIDTH_BYTES: Final[int] = 2
_INT16_SCALE: Final[float] = 32767.0

_DeemphFn = Callable[[np.ndarray, float, float], np.ndarray]


def _resolve_pyaudio() -> bool:
    if not _IS_LINUX:
        return False
    try:
        import pyaudio as _pa
        return True
    except ImportError:
        return False


def _resolve_sounddevice() -> bool:
    try:
        import sounddevice as _sd
        return True
    except ImportError:
        return False


def _resolve_scipy_decimate() -> bool:
    try:
        from scipy.signal import decimate as _d
        return True
    except ImportError:
        return False


_PYAUDIO_AVAILABLE: Final[bool] = _resolve_pyaudio()
_SOUNDDEVICE_AVAILABLE: Final[bool] = _resolve_sounddevice()
_SCIPY_AVAILABLE: Final[bool] = _resolve_scipy_decimate()


def _build_deemph_fn() -> _DeemphFn:
    try:
        from numba import njit

        @njit(cache=True)
        def _deemph_numba(audio: np.ndarray, alpha: float, k: float) -> np.ndarray:
            out = np.empty_like(audio)
            y = 0.0
            for i in range(len(audio)):
                y = k * audio[i] + alpha * y
                out[i] = y
            return out

        log.debug("Deemphasis backend: numba (JIT compiled)")
        return _deemph_numba

    except ImportError:
        pass

    try:
        from scipy.signal import lfilter as _lfilter

        def _deemph_scipy(audio: np.ndarray, alpha: float, k: float) -> np.ndarray:
            b = np.array([k], dtype=np.float64)
            a = np.array([1.0, -alpha], dtype=np.float64)
            return _lfilter(b, a, audio.astype(np.float64)).astype(np.float32)

        log.debug("Deemphasis backend: scipy.signal.lfilter (IIR vectorized)")
        return _deemph_scipy

    except ImportError:
        pass

    def _deemph_pure(audio: np.ndarray, alpha: float, k: float) -> np.ndarray:
        out = np.empty(len(audio), dtype=np.float32)
        y = 0.0
        for i in range(len(audio)):
            y = k * audio[i] + alpha * y
            out[i] = y
        return out

    log.debug("Deemphasis backend: pure Python loop (fallback)")
    return _deemph_pure


_deemph_fn: Final[_DeemphFn] = _build_deemph_fn()


def _precompute_ssb_hilbert_filter() -> np.ndarray:
    n = _SSB_FILTER_LENGTH
    half = n // 2
    k = np.arange(-half, half + 1, dtype=np.float64)
    hilbert = np.zeros(n, dtype=np.float64)
    nonzero = k != 0
    hilbert[nonzero] = (1.0 - np.cos(np.pi * k[nonzero])) / \
        (np.pi * k[nonzero])
    window = np.blackman(n)
    hilbert *= window
    norm = np.sum(np.abs(hilbert))
    if norm > 0.0:
        hilbert /= norm / 2.0
    return hilbert.astype(np.float32)


_SSB_HILBERT_KERNEL: Final[np.ndarray] = _precompute_ssb_hilbert_filter()


def _decimate_audio(audio: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1:
        return audio
    if _SCIPY_AVAILABLE:
        try:
            from scipy.signal import decimate as _scipy_decimate
            return _scipy_decimate(audio, factor, zero_phase=True).astype(np.float32)
        except Exception as exc:
            log.debug("scipy decimate failed (%s) — falling back to slicing", exc)
    return audio[::factor]


def _apply_deemphasis(audio: np.ndarray, tau: float, sample_rate: int) -> np.ndarray:
    if tau <= 0.0:
        return audio
    alpha = math.exp(-1.0 / (sample_rate * tau))
    k = 1.0 - alpha
    return _deemph_fn(audio.astype(np.float32), alpha, k)


def _apply_soft_agc(
    audio: np.ndarray,
    current_gain: float,
    attack: float = _AGC_DEFAULT_ATTACK,
    release: float = _AGC_DEFAULT_RELEASE,
) -> tuple[np.ndarray, float]:
    peak = float(np.max(np.abs(audio)))
    if peak < _AGC_PEAK_FLOOR:
        return audio, current_gain
    target_gain = 1.0 / peak
    blend_alpha = attack if target_gain < current_gain else release
    new_gain = current_gain * (1.0 - blend_alpha) + target_gain * blend_alpha
    return (audio * new_gain).astype(np.float32), new_gain


def _fm_phase_discriminator(
    iq: np.ndarray,
    prev_phase: float,
) -> tuple[np.ndarray, float]:
    prev_samples = np.empty(len(iq), dtype=np.complex64)
    prev_samples[0] = np.exp(1j * prev_phase)
    prev_samples[1:] = iq[:-1]
    instantaneous_freq = np.angle(
        iq * np.conj(prev_samples)).astype(np.float32)
    next_prev_phase = float(np.angle(iq[-1]))
    return instantaneous_freq, next_prev_phase


def _encode_pcm16(audio: np.ndarray) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * _INT16_SCALE).astype(np.int16).tobytes()


def _write_wav_file(dest: Path, pcm16: bytes, sample_rate: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(_WAV_SAMPLE_WIDTH_BYTES)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16)


class AudioBackend(Protocol):
    def play(self, audio: np.ndarray, sample_rate: int) -> bool: ...
    def stop(self) -> None: ...


class _SounddeviceBackend:
    def play(self, audio: np.ndarray, sample_rate: int) -> bool:
        import sounddevice as sd
        try:
            sd.play(audio.astype(np.float32), sample_rate)
            sd.wait()
            return True
        except Exception as exc:
            log.error("sounddevice playback error: %s", exc)
            return False

    def stop(self) -> None:
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass


class _PyAudioBackend:
    def __init__(self) -> None:
        self._pa: object | None = None
        self._stream: object | None = None

    def play(self, audio: np.ndarray, sample_rate: int) -> bool:
        import pyaudio
        try:
            pcm_bytes = _encode_pcm16(audio)
            if self._pa is None:
                self._pa = pyaudio.PyAudio()
                self._stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=sample_rate,
                    output=True,
                    frames_per_buffer=_PYAUDIO_FRAMES_PER_BUFFER,
                )
            self._stream.write(pcm_bytes)
            return True
        except Exception as exc:
            log.error("pyaudio playback error: %s", exc)
            return False

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None


class _AndroidBackend:
    def play(self, audio: np.ndarray, sample_rate: int) -> bool:
        tmp_path = Path(tempfile.mktemp(suffix=".wav"))
        try:
            _write_wav_file(tmp_path, _encode_pcm16(audio), sample_rate)
            result = subprocess.run(
                ["termux-media-player", "play", str(tmp_path)],
                timeout=_ANDROID_PLAYBACK_TIMEOUT_S,
                capture_output=True,
            )
            if result.returncode != 0:
                log.warning(
                    "termux-media-player failed (rc=%d). Install: pkg install termux-api",
                    result.returncode,
                )
                return False
            return True
        except FileNotFoundError:
            log.warning(
                "termux-media-player not found. Install: pkg install termux-api")
            return False
        except Exception as exc:
            log.error("Android audio playback error: %s", exc)
            return False
        finally:
            tmp_path.unlink(missing_ok=True)

    def stop(self) -> None:
        pass


class _NullBackend:
    def play(self, audio: np.ndarray, sample_rate: int) -> bool:
        log.warning("No audio backend available. Audio output suppressed.")
        return False

    def stop(self) -> None:
        pass


def _select_audio_backend() -> AudioBackend:
    if _IS_ANDROID:
        return _AndroidBackend()
    if _SOUNDDEVICE_AVAILABLE:
        return _SounddeviceBackend()
    if _PYAUDIO_AVAILABLE:
        return _PyAudioBackend()
    return _NullBackend()


class Demodulator:
    def __init__(self, cfg: DemodConfig, sample_rate: int) -> None:
        self._cfg = cfg
        self._sample_rate = sample_rate
        self._prev_phase: float = 0.0
        self._agc_gain: float = 1.0

        self._decimation_factor: int = max(
            1, int(sample_rate / cfg.audio_rate))
        self._audio_output_rate: int = sample_rate // self._decimation_factor

        self._audio_backend: AudioBackend = _select_audio_backend()

        self._demod_dispatch: dict[str, Callable[[np.ndarray], np.ndarray | None]] = {
            "wfm": self._demod_wfm,
            "nfm": self._demod_nfm,
            "am":  self._demod_am,
            "usb": lambda iq: self._demod_ssb(iq, upper=True),
            "lsb": lambda iq: self._demod_ssb(iq, upper=False),
        }

        log.debug(
            "Demodulator init: mode=%s  SR_in=%.3fMHz  SR_out=%dHz  decimation=1/%d  backend=%s",
            cfg.mode,
            sample_rate / 1e6,
            self._audio_output_rate,
            self._decimation_factor,
            type(self._audio_backend).__name__,
        )

    @property
    def audio_rate_actual(self) -> int:
        return self._audio_output_rate

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def demodulate(self, iq: np.ndarray) -> np.ndarray | None:
        if len(iq) == 0:
            return None
        mode = self._cfg.mode.lower()
        if mode == "none":
            return None
        handler = self._demod_dispatch.get(mode)
        if handler is None:
            log.warning("Unknown demodulation mode: %s", mode)
            return None
        return handler(iq)

    def play(self, audio: np.ndarray) -> bool:
        if audio is None or len(audio) == 0:
            return False
        return self._audio_backend.play(audio, self._audio_output_rate)

    def save_wav(self, audio: np.ndarray, path: str | Path) -> Path:
        dest = Path(path)
        pcm16 = _encode_pcm16(audio)
        _write_wav_file(dest, pcm16, self._audio_output_rate)
        log.info("WAV saved: %s (%.1fs)", dest,
                 len(audio) / self._audio_output_rate)
        return dest

    def stop_audio(self) -> None:
        self._audio_backend.stop()

    def _demod_wfm(self, iq: np.ndarray) -> np.ndarray:
        instantaneous_freq, self._prev_phase = _fm_phase_discriminator(
            iq, self._prev_phase)
        deemphasized = _apply_deemphasis(
            instantaneous_freq, _WFM_DEEMPH_TAU, self._sample_rate)
        decimated = _decimate_audio(deemphasized, self._decimation_factor)
        agc_out, self._agc_gain = _apply_soft_agc(decimated, self._agc_gain)
        return np.clip(agc_out * self._cfg.volume, -1.0, 1.0)

    def _demod_nfm(self, iq: np.ndarray) -> np.ndarray:
        instantaneous_freq, self._prev_phase = _fm_phase_discriminator(
            iq, self._prev_phase)
        deemphasized = _apply_deemphasis(
            instantaneous_freq, _NFM_DEEMPH_TAU, self._sample_rate)
        phase_deviation = float(np.std(deemphasized))
        if phase_deviation < _NFM_SQUELCH_STD_FLOOR:
            return np.zeros(len(iq) // self._decimation_factor, dtype=np.float32)
        decimated = _decimate_audio(deemphasized, self._decimation_factor)
        agc_out, self._agc_gain = _apply_soft_agc(decimated, self._agc_gain)
        return np.clip(agc_out * self._cfg.volume, -1.0, 1.0)

    def _demod_am(self, iq: np.ndarray) -> np.ndarray:
        envelope = np.abs(iq).astype(np.float32)
        envelope -= np.mean(envelope)
        decimated = _decimate_audio(envelope, self._decimation_factor)
        agc_out, self._agc_gain = _apply_soft_agc(decimated, self._agc_gain)
        return np.clip(agc_out * self._cfg.volume, -1.0, 1.0)

    def _demod_ssb(self, iq: np.ndarray, upper: bool) -> np.ndarray:
        real_part = iq.real.astype(np.float32)
        analytic_imag = np.convolve(
            real_part, _SSB_HILBERT_KERNEL, mode="same")
        audio = real_part + analytic_imag if upper else real_part - analytic_imag
        decimated = _decimate_audio(audio, self._decimation_factor)
        agc_out, self._agc_gain = _apply_soft_agc(decimated, self._agc_gain)
        return np.clip(agc_out * self._cfg.volume, -1.0, 1.0)

    def __enter__(self) -> Demodulator:
        return self

    def __exit__(self, *_: object) -> None:
        self.stop_audio()

    def __del__(self) -> None:
        try:
            self.stop_audio()
        except Exception:
            pass
