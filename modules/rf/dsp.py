import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np

from modules.rf.rf_config import DspConfig
from modules.rf.bands import identify_band

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# TIPOS DE DATOS
# ════════════════════════════════════════════════════════════════════

@dataclass
class Signal:
    """Señal detectada con todos los parámetros medidos."""
    freq_mhz:   float
    potencia:   float    # dBm
    snr_db:     float
    bw_khz:     float    # ancho de banda -3dB
    piso_dbm:   float    # piso de ruido local
    banda:      Optional[dict]
    timestamp:  str

    @property
    def mod_hint(self) -> str:
        """Estimación de modulación por ancho de banda."""
        if self.bw_khz < 5:
            return "NFM/CW"
        if self.bw_khz < 12:
            return "NFM"
        if self.bw_khz < 20:
            return "AM"
        if self.bw_khz < 35:
            return "WFM"
        return "WFM/DATA"

    def to_dict(self) -> dict:
        return {
            "freq_mhz": self.freq_mhz,
            "potencia":  self.potencia,
            "snr_db":    self.snr_db,
            "bw_khz":    self.bw_khz,
            "piso_dbm":  self.piso_dbm,
            "mod_hint":  self.mod_hint,
            "banda":     self.banda["nombre"] if self.banda else "—",
            "timestamp": self.timestamp,
        }


# ════════════════════════════════════════════════════════════════════
# MOTOR DSP
# ════════════════════════════════════════════════════════════════════

class DSPEngine:
    """
    Motor de procesamiento de señal digital.
    Stateless — todos los métodos son pure functions sobre numpy arrays.
    """

    # Factores de corrección de potencia para cada ventana
    # (compensa la pérdida de ganancia introducida por la ventana)
    _WINDOW_CORRECTION = {
        "blackman": 7.66,
        "hann":     6.02,
        "hamming":  5.37,
        "flattop":  13.33,
    }

    def __init__(self, cfg: DspConfig, sample_rate: int):
        self.cfg = cfg
        self.sample_rate = sample_rate
        self._window = self._build_window(cfg.fft_size, cfg.window)
        self._win_correction = self._WINDOW_CORRECTION.get(cfg.window, 6.02)
        log.debug(
            f"DSPEngine — FFT={cfg.fft_size} "
            f"ventana={cfg.window} "
            f"SR={sample_rate/1e6:.3f} MHz"
        )

    # ── Construcción de ventana ──────────────────────────────────────

    @staticmethod
    def _build_window(n: int, name: str) -> np.ndarray:
        if name == "blackman":
            return np.blackman(n)
        if name == "hann":
            return np.hanning(n)
        if name == "hamming":
            return np.hamming(n)
        if name == "flattop":
            # Flat-top: mejor para medición de potencia absoluta
            a = [0.21557895, 0.41663158, 0.277263158, 0.083578947, 0.006947368]
            k = np.arange(n)
            w = np.zeros(n)
            for i, ai in enumerate(a):
                w += ai * np.cos(2 * np.pi * i * k / (n - 1)) * ((-1)**i)
            return w
        log.warning(f"Ventana desconocida '{name}', usando Blackman")
        return np.blackman(n)

    # ── PSD por método de Welch ──────────────────────────────────────

    def compute_psd(self, samples: np.ndarray
                    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Calcula PSD con promediado de Welch + corrección de ventana.

        Returns:
            freqs_hz: eje de frecuencias relativo al centro (Hz)
            psd_dbm:  potencia espectral en dBm
        """
        fft_size = self.cfg.fft_size
        n_blocks = len(samples) // fft_size

        if n_blocks < 1:
            log.warning(
                f"Muestras insuficientes ({len(samples)}) "
                f"para FFT de {fft_size} puntos. "
                "Usando una pasada."
            )
            samples = np.pad(samples, (0, fft_size - len(samples)))
            n_blocks = 1

        # ── Welch averaging ──────────────────────────────────────────
        acum = np.zeros(fft_size, dtype=np.float64)
        for i in range(n_blocks):
            bloque = samples[i * fft_size:(i + 1) * fft_size]
            fft_b = np.fft.fftshift(
                np.fft.fft(bloque * self._window, n=fft_size)
            )
            acum += np.abs(fft_b) ** 2

        psd = acum / n_blocks

        # ── Normalización ────────────────────────────────────────────
        # Factor de ventana para potencia absoluta correcta
        win_power = np.sum(self._window ** 2)
        psd /= (win_power * self.sample_rate)

        # Evitar log(0)
        psd = np.maximum(psd, 1e-20)

        # Convertir a dBm (referencia 1mW en 50Ω, incluyendo corrección)
        psd_dbm = 10.0 * np.log10(psd) + 30.0 + self._win_correction

        # ── Eliminación del spike DC ─────────────────────────────────
        if self.cfg.dc_spike_remove:
            mid = fft_size // 2
            # Interpolación lineal entre bins adyacentes
            if 1 < mid < fft_size - 2:
                psd_dbm[mid] = (psd_dbm[mid - 1] + psd_dbm[mid + 1]) / 2
                psd_dbm[mid - 1] = (psd_dbm[mid - 2] + psd_dbm[mid]) / 2
                psd_dbm[mid + 1] = (psd_dbm[mid] + psd_dbm[mid + 2]) / 2

        # ── Eje de frecuencias relativo al centro ─────────────────────
        freqs = np.fft.fftshift(
            np.fft.fftfreq(fft_size, d=1.0 / self.sample_rate)
        )

        return freqs, psd_dbm

    # ── Detección de picos CFAR ──────────────────────────────────────

    def detect_peaks(self, freqs: np.ndarray, psd: np.ndarray,
                     center_freq_hz: float) -> list[Signal]:
        """
        CA-CFAR (Cell-Averaging Constant False Alarm Rate).

        Para cada celda bajo test (CUT), estima el piso de ruido
        local como la mediana de las celdas de referencia a izquierda
        y derecha, excluyendo las celdas de guarda.
        """
        n = len(psd)
        guard = self.cfg.cfar_guard
        ref_win = self.cfg.cfar_ref
        thr_snr = self.cfg.snr_threshold
        margin = ref_win + guard

        signals: list[Signal] = []
        i = margin

        while i < n - margin:
            # Celdas de referencia (excluir guarda)
            left_ref = psd[max(0, i - margin):max(0, i - guard)]
            right_ref = psd[min(n, i + guard + 1):min(n, i + margin + 1)]
            ref_cells = np.concatenate([left_ref, right_ref])

            if len(ref_cells) == 0:
                i += 1
                continue

            # Piso de ruido local (mediana = robusto a picos aislados)
            noise_floor = float(np.median(ref_cells))
            threshold = noise_floor + thr_snr

            # Condición de pico: máximo local estricto sobre umbral
            is_peak = (
                psd[i] > threshold and
                psd[i] > psd[i - 1] and
                psd[i] > psd[i + 1] and
                psd[i] > psd[i - 2] and
                psd[i] > psd[i + 2]
            )

            if is_peak:
                freq_abs_hz = center_freq_hz + float(freqs[i])
                freq_abs_mhz = freq_abs_hz / 1e6
                snr_db = float(psd[i]) - noise_floor
                bw_hz = self._measure_bw_3db(psd, i, freqs)

                signals.append(Signal(
                    freq_mhz=round(freq_abs_mhz, 4),
                    potencia=round(float(psd[i]), 2),
                    snr_db=round(snr_db, 2),
                    bw_khz=round(bw_hz / 1e3, 2),
                    piso_dbm=round(noise_floor, 2),
                    banda=identify_band(freq_abs_mhz),
                    timestamp=datetime.now().isoformat(),
                ))

                # Avanzar el cursor más allá del pico
                skip = max(2, int(bw_hz / (self.sample_rate / n)) // 2 + guard)
                i += skip
            else:
                i += 1

        return signals

    # ── Medición BW -3dB ────────────────────────────────────────────

    def _measure_bw_3db(self, psd: np.ndarray, idx: int,
                        freqs: np.ndarray) -> float:
        """
        Calcula el ancho de banda a -3dB del pico en `idx`.
        Desciende desde el pico hacia cada lado hasta cruzar el
        umbral de 3dB. Mínimo: un bin FFT.
        """
        level = float(psd[idx]) - 3.0
        n = len(psd)

        left = idx
        while left > 0 and float(psd[left]) > level:
            left -= 1

        right = idx
        while right < n - 1 and float(psd[right]) > level:
            right += 1

        bw = abs(float(freqs[right]) - float(freqs[left]))
        bin_res = self.sample_rate / self.cfg.fft_size
        return max(bw, bin_res)

    # ── Estimación de piso de ruido global ──────────────────────────

    def noise_floor(self, psd: np.ndarray) -> float:
        """
        Piso de ruido robusto: mediana del 40% inferior del espectro.
        Excluye picos para no sesgar la estimación.
        """
        sorted_psd = np.sort(psd)
        n_noise = max(1, int(len(sorted_psd) * 0.4))
        return float(np.median(sorted_psd[:n_noise]))

    # ── Resolución frecuencial ───────────────────────────────────────

    @property
    def freq_resolution_hz(self) -> float:
        """Resolución frecuencial de un bin FFT en Hz."""
        return self.sample_rate / self.cfg.fft_size

    @property
    def freq_resolution_khz(self) -> float:
        return self.freq_resolution_hz / 1e3
