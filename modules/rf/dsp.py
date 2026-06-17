from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Final, NamedTuple

import numpy as np
import numpy.typing as npt
from scipy.signal import windows as sp_windows

from modules.rf.rf_config import DspConfig
from modules.rf.bands import identify_band

log = logging.getLogger(__name__)

PowerArray: Final = npt.NDArray[np.float32]
IQArray:    Final = npt.NDArray[np.complex64]

_MOD_BREAKPOINTS: Final[npt.NDArray[np.float64]] = np.array(
    [0.5, 5.0, 12.0, 20.0, 35.0, 200.0], dtype=np.float64
)
_MOD_LABELS: Final[tuple[str, ...]] = (
    "CW", "NFM/CW", "NFM", "AM", "WFM", "WFM/DATA", "DATA/WIDEBAND"
)

_WINDOW_CORRECTION: Final[dict[str, float]] = {
    "blackman": 7.66,
    "hann":     6.02,
    "hamming":  5.37,
    "flattop":  13.33,
}

_FLATTOP_COEFFS: Final[npt.NDArray[np.float64]] = np.array(
    [0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368],
    dtype=np.float64,
)


class Signal:
    __slots__ = (
        "freq_mhz", "potencia", "snr_db", "bw_khz",
        "piso_dbm", "banda", "timestamp", "kurtosis", "mod_hint",
    )

    def __init__(
        self,
        freq_mhz:  float,
        potencia:  float,
        snr_db:    float,
        bw_khz:    float,
        piso_dbm:  float,
        banda:     dict | None,
        timestamp: str,
        kurtosis:  float = 0.0,
        mod_hint:  str   = "",
    ) -> None:
        self.freq_mhz  = freq_mhz
        self.potencia  = potencia
        self.snr_db    = snr_db
        self.bw_khz    = bw_khz
        self.piso_dbm  = piso_dbm
        self.banda     = banda
        self.timestamp = timestamp
        self.kurtosis  = kurtosis
        self.mod_hint  = mod_hint if mod_hint else _classify_modulation(bw_khz)

    def to_dict(self) -> dict:
        return {
            "freq_mhz": self.freq_mhz,
            "potencia":  self.potencia,
            "snr_db":    self.snr_db,
            "bw_khz":    self.bw_khz,
            "piso_dbm":  self.piso_dbm,
            "kurtosis":  round(self.kurtosis, 3),
            "mod_hint":  self.mod_hint,
            "banda":     self.banda["nombre"] if self.banda else "\u2014",
            "timestamp": self.timestamp,
        }


def _classify_modulation(bw_khz: float) -> str:
    return _MOD_LABELS[int(np.searchsorted(_MOD_BREAKPOINTS, bw_khz, side="right"))]


def _build_window(n: int, name: str) -> npt.NDArray[np.float32]:
    if name == "blackman":
        return sp_windows.blackman(n).astype(np.float32)
    if name == "hann":
        return sp_windows.hann(n).astype(np.float32)
    if name == "hamming":
        return sp_windows.hamming(n).astype(np.float32)
    if name == "flattop":
        k = np.arange(n, dtype=np.float64)
        phase = 2.0 * np.pi * k / (n - 1)
        signs = np.array([1.0, -1.0, 1.0, -1.0, 1.0], dtype=np.float64)
        harmonics = np.cos(np.outer(np.arange(5, dtype=np.float64), phase))
        return ((_FLATTOP_COEFFS * signs) @ harmonics).astype(np.float32)
    log.warning("unknown window '%s' — falling back to Blackman", name)
    return sp_windows.blackman(n).astype(np.float32)


class DSPEngine:

    def __init__(self, cfg: DspConfig, sample_rate: int) -> None:
        self.cfg              = cfg
        self.sample_rate      = sample_rate
        self._window          = _build_window(cfg.fft_size, cfg.window)
        self._win_correction  = _WINDOW_CORRECTION.get(cfg.window, 6.02)
        self._win_norm        = float(np.sum(self._window ** 2))
        self._freq_axis: PowerArray = np.fft.fftshift(
            np.fft.fftfreq(cfg.fft_size, d=1.0 / sample_rate)
        ).astype(np.float32)
        self._bin_hz          = sample_rate / cfg.fft_size

        log.debug(
            "DSPEngine ready — FFT=%d window=%s SR=%.3fMHz resolution=%.1fHz",
            cfg.fft_size, cfg.window,
            sample_rate / 1e6,
            self._bin_hz,
        )

    def compute_psd(self, samples: IQArray) -> tuple[PowerArray, PowerArray]:
        fft_size = self.cfg.fft_size
        samples  = np.asarray(samples, dtype=np.complex64)

        if len(samples) < fft_size:
            samples = np.pad(samples, (0, fft_size - len(samples)))

        n_blocks = len(samples) // fft_size
        trimmed  = samples[: n_blocks * fft_size].reshape(n_blocks, fft_size)
        windowed = trimmed * self._window.astype(np.float32)
        spectra  = np.fft.fft(windowed, n=fft_size, axis=1)
        psd      = np.fft.fftshift(
            (np.abs(spectra) ** 2).mean(axis=0) / (self._win_norm * self.sample_rate)
        )
        np.maximum(psd, 1e-20, out=psd)
        psd_dbm = (10.0 * np.log10(psd) + 30.0 + self._win_correction).astype(np.float32)

        if self.cfg.dc_spike_remove:
            mid = fft_size // 2
            if 3 < mid < fft_size - 4:
                left_anchor  = (psd_dbm[mid - 3] + psd_dbm[mid + 1]) * 0.5
                center_fill  = (psd_dbm[mid - 2] + psd_dbm[mid + 2]) * 0.5
                right_anchor = (left_anchor       + psd_dbm[mid + 3]) * 0.5
                psd_dbm[mid - 1] = left_anchor
                psd_dbm[mid]     = center_fill
                psd_dbm[mid + 1] = right_anchor

        return self._freq_axis.copy(), psd_dbm

    def detect_peaks(
        self,
        freqs:          PowerArray,
        psd:            PowerArray,
        center_freq_hz: float,
    ) -> list[Signal]:
        n       = len(psd)
        guard   = self.cfg.cfar_guard
        ref_win = self.cfg.cfar_ref
        margin  = ref_win + guard
        k_os    = int(ref_win * 2 * 0.75)

        local_max_mask = (
            (psd[2:-2] > psd[0:-4])
            & (psd[2:-2] > psd[1:-3])
            & (psd[2:-2] > psd[3:-1])
            & (psd[2:-2] > psd[4:])
        )
        candidate_indices = np.where(local_max_mask)[0] + 2
        candidate_indices = candidate_indices[
            (candidate_indices >= margin) & (candidate_indices < n - margin)
        ]

        signals: list[Signal] = []
        last_skip_end: int = 0

        for ci in candidate_indices:
            i = int(ci)
            if i < last_skip_end:
                continue

            left_ref  = psd[i - margin : i - guard]
            right_ref = psd[i + guard + 1 : i + margin + 1]
            ref_cells = np.concatenate([left_ref, right_ref])

            if len(ref_cells) < 4:
                continue

            k_idx       = min(k_os, len(ref_cells) - 1)
            noise_floor = float(np.partition(ref_cells, k_idx)[k_idx])
            threshold   = noise_floor + self.cfg.snr_threshold

            if psd[i] <= threshold:
                continue

            freq_abs_mhz = (center_freq_hz + float(freqs[i])) / 1e6
            snr_db       = float(psd[i]) - noise_floor
            bw_hz        = self._measure_bw_3db(psd, i, freqs)
            kurt         = self._spectral_kurtosis(psd, i)

            signals.append(Signal(
                freq_mhz  = round(freq_abs_mhz, 4),
                potencia  = round(float(psd[i]), 2),
                snr_db    = round(snr_db, 2),
                bw_khz    = round(bw_hz / 1e3, 2),
                piso_dbm  = round(noise_floor, 2),
                kurtosis  = kurt,
                banda     = identify_band(freq_abs_mhz),
                timestamp = datetime.now(timezone.utc).isoformat(),
            ))

            skip = max(3, int(bw_hz / self._bin_hz) // 2 + guard)
            last_skip_end = i + skip

        return signals

    def _measure_bw_3db(self, psd: PowerArray, idx: int, freqs: PowerArray) -> float:
        level          = float(psd[idx]) - 3.0
        below_mask     = psd < level

        left_candidates  = np.where(below_mask[:idx])[0]
        right_candidates = np.where(below_mask[idx:])[0]

        left_bin  = int(left_candidates[-1])  if left_candidates.size  else 0
        right_bin = int(right_candidates[0]) + idx if right_candidates.size else len(psd) - 1

        bw = abs(float(freqs[right_bin]) - float(freqs[left_bin]))
        return max(bw, self._bin_hz)

    def _spectral_kurtosis(self, psd: PowerArray, idx: int, half_win: int = 8) -> float:
        lo  = max(0, idx - half_win)
        hi  = min(len(psd), idx + half_win + 1)
        seg = psd[lo:hi].astype(np.float64)

        if seg.size < 4:
            return 0.0

        mu  = seg.mean()
        std = seg.std()
        if std < 1e-9:
            return 0.0

        normalized = (seg - mu) / std
        np.multiply(normalized, normalized, out=normalized)
        np.multiply(normalized, normalized, out=normalized)
        return round(float(normalized.mean()) - 3.0, 3)

    def noise_floor(self, psd: PowerArray) -> float:
        n_noise = max(1, int(len(psd) * 0.4))
        return float(np.median(np.partition(psd, n_noise - 1)[:n_noise]))

    @property
    def freq_resolution_hz(self) -> float:
        return self._bin_hz

    @property
    def freq_resolution_khz(self) -> float:
        return self._bin_hz / 1e3
