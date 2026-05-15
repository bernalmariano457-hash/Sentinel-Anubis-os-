from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone


import numpy as np

from modules.rf.rf_config import DspConfig
from modules.rf.bands import identify_band

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# TIPOS DE DATOS
# ════════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    freq_mhz:   float
    potencia:   float
    snr_db:     float
    bw_khz:     float
    piso_dbm:   float
    banda:      dict | None
    timestamp:  str
    kurtosis:   float = 0.0
    mod_hint:   str   = field(default="", init=True)

    def __post_init__(self) -> None:
        if not self.mod_hint:
            self.mod_hint = self._estimar_mod()

    def _estimar_mod(self) -> str:
        if self.bw_khz < 0.5:
            return "CW"
        if self.bw_khz < 5:
            return "NFM/CW"
        if self.bw_khz < 12:
            return "NFM"
        if self.bw_khz < 20:
            return "AM"
        if self.bw_khz < 35:
            return "WFM"
        if self.bw_khz < 200:
            return "WFM/DATA"
        return "DATA/WIDEBAND"

    def to_dict(self) -> dict:
        return {
            "freq_mhz": self.freq_mhz,
            "potencia":  self.potencia,
            "snr_db":    self.snr_db,
            "bw_khz":    self.bw_khz,
            "piso_dbm":  self.piso_dbm,
            "kurtosis":  round(self.kurtosis, 3),
            "mod_hint":  self.mod_hint,
            "banda":     self.banda["nombre"] if self.banda else "—",
            "timestamp": self.timestamp,
        }


# ════════════════════════════════════════════════════════════════════
# MOTOR DSP
# ════════════════════════════════════════════════════════════════════

class DSPEngine:

    _WINDOW_CORRECTION = {
        "blackman": 7.66,
        "hann":     6.02,
        "hamming":  5.37,
        "flattop":  13.33,
    }

    def __init__(self, cfg: DspConfig, sample_rate: int) -> None:
        self.cfg         = cfg
        self.sample_rate = sample_rate
        self._window     = self._build_window(cfg.fft_size, cfg.window)
        self._win_correction = self._WINDOW_CORRECTION.get(cfg.window, 6.02)
        self._win_norm   = float(np.sum(self._window ** 2))
        self._freq_axis  = np.fft.fftshift(
            np.fft.fftfreq(cfg.fft_size, d=1.0 / sample_rate)
        ).astype(np.float32)

        log.debug(
            "DSPEngine listo — FFT=%d ventana=%s SR=%.3fMHz resolucion=%.1fHz",
            cfg.fft_size, cfg.window,
            sample_rate / 1e6,
            sample_rate / cfg.fft_size,
        )

    # ── Construcción de ventana ──────────────────────────────────────

    @staticmethod
    def _build_window(n: int, name: str) -> np.ndarray:
        if name == "blackman":
            return np.blackman(n).astype(np.float32)
        if name == "hann":
            return np.hanning(n).astype(np.float32)
        if name == "hamming":
            return np.hamming(n).astype(np.float32)
        if name == "flattop":
            a = [0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368]
            k = np.arange(n, dtype=np.float32)
            w = np.zeros(n, dtype=np.float32)
            for i, ai in enumerate(a):
                w += ai * np.cos(2 * np.pi * i * k / (n - 1)) * ((-1) ** i)
            return w
        log.warning("Ventana '%s' desconocida — usando Blackman", name)
        return np.blackman(n).astype(np.float32)

    # ── PSD con promediado de Welch ──────────────────────────────────

    def compute_psd(self, samples: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        fft_size = self.cfg.fft_size
        samples  = np.asarray(samples, dtype=np.complex64)
        n_blocks = len(samples) // fft_size

        if n_blocks < 1:
            samples  = np.pad(samples, (0, fft_size - len(samples)))
            n_blocks = 1

        acum = np.zeros(fft_size, dtype=np.float64)
        for i in range(n_blocks):
            bloque   = samples[i * fft_size:(i + 1) * fft_size]
            spectrum = np.fft.fftshift(
                np.fft.fft(bloque * self._window, n=fft_size)
            )
            acum += np.abs(spectrum) ** 2

        psd  = acum / n_blocks
        psd /= (self._win_norm * self.sample_rate)
        psd  = np.maximum(psd, 1e-20)
        psd_dbm = (10.0 * np.log10(psd) + 30.0 + self._win_correction).astype(np.float32)

        if self.cfg.dc_spike_remove:
            mid = fft_size // 2
            if 3 < mid < fft_size - 4:
                # Interpolación cúbica para remover pico DC suavemente
                psd_dbm[mid - 1] = (psd_dbm[mid - 3] + psd_dbm[mid + 1]) / 2.0
                psd_dbm[mid]     = (psd_dbm[mid - 2] + psd_dbm[mid + 2]) / 2.0
                psd_dbm[mid + 1] = (psd_dbm[mid - 1] + psd_dbm[mid + 3]) / 2.0

        return self._freq_axis.copy(), psd_dbm

    # ── OS-CFAR (Order Statistics) ───────────────────────────────────

    def detect_peaks(self, freqs: np.ndarray, psd: np.ndarray,
                     center_freq_hz: float) -> list[Signal]:
        n        = len(psd)
        guard    = self.cfg.cfar_guard
        ref_win  = self.cfg.cfar_ref
        thr_snr  = self.cfg.snr_threshold
        margin   = ref_win + guard
        k_os     = int(ref_win * 2 * 0.75)

        signals: list[Signal] = []
        i = margin

        while i < n - margin:
            left_ref  = psd[max(0, i - margin) : max(0, i - guard)]
            right_ref = psd[min(n, i + guard + 1) : min(n, i + margin + 1)]
            ref_cells = np.concatenate([left_ref, right_ref])

            if len(ref_cells) < 4:
                i += 1
                continue

            ref_sorted  = np.sort(ref_cells)
            k_idx       = min(k_os, len(ref_sorted) - 1)
            noise_floor = float(ref_sorted[k_idx])
            threshold   = noise_floor + thr_snr

            is_peak = (
                psd[i] > threshold
                and psd[i] > psd[i - 1]
                and psd[i] > psd[i + 1]
                and psd[i] > psd[max(0, i - 2)]
                and psd[i] > psd[min(n - 1, i + 2)]
            )

            if is_peak:
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

                skip = max(3, int(bw_hz / (self.sample_rate / n)) // 2 + guard)
                i   += skip
            else:
                i += 1

        return signals

    # ── Ancho de banda -3dB ──────────────────────────────────────────

    def _measure_bw_3db(self, psd: np.ndarray, idx: int,
                        freqs: np.ndarray) -> float:
        level = float(psd[idx]) - 3.0
        n     = len(psd)
        left  = idx
        right = idx

        while left > 0 and float(psd[left]) > level:
            left -= 1
        while right < n - 1 and float(psd[right]) > level:
            right += 1

        bw      = abs(float(freqs[right]) - float(freqs[left]))
        bin_res = self.sample_rate / self.cfg.fft_size
        return max(bw, bin_res)

    # ── Curtosis espectral ───────────────────────────────────────────

    def _spectral_kurtosis(self, psd: np.ndarray, idx: int,
                           window: int = 8) -> float:
        lo  = max(0, idx - window)
        hi  = min(len(psd), idx + window + 1)
        seg = psd[lo:hi].astype(np.float64)

        if len(seg) < 4:
            return 0.0

        mu  = np.mean(seg)
        std = np.std(seg)
        if std < 1e-9:
            return 0.0

        return round(float(np.mean(((seg - mu) / std) ** 4)) - 3.0, 3)

    # ── Piso de ruido (percentil 40%) ───────────────────────────────

    def noise_floor(self, psd: np.ndarray) -> float:
        sorted_psd = np.sort(psd)
        n_noise    = max(1, int(len(sorted_psd) * 0.4))
        return float(np.median(sorted_psd[:n_noise]))

    # ── Propiedades ──────────────────────────────────────────────────

    @property
    def freq_resolution_hz(self) -> float:
        return self.sample_rate / self.cfg.fft_size

    @property
    def freq_resolution_khz(self) -> float:
        return self.freq_resolution_hz / 1e3
