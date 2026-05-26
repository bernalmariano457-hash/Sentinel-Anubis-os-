from __future__ import annotations

import logging
import math
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np
from rich.console import Console
from rich.prompt import Prompt

from rf_source import Source, SourceFactory

log = logging.getLogger("sentinel.rf.noaa")

_SCIPY_OK = False
try:
    from scipy.signal import (
        butter, sosfilt, sosfiltfilt, hilbert,
        resample_poly, firwin, lfilter,
    )
    _SCIPY_OK = True
except ImportError:
    pass

_PILLOW_OK = False
try:
    from PIL import Image
    _PILLOW_OK = True
except ImportError:
    pass

_APT3_OK = False
try:
    import apt3
    _APT3_OK = True
except ImportError:
    pass

NOAA_SATELLITES: dict[str, int] = {
    "NOAA-19": 137_100_000,
    "NOAA-18": 137_912_500,
    "NOAA-15": 137_620_000,
}

APT_AUDIO_RATE   = 11_025
APT_LINE_RATE    = 4
APT_PIXELS_LINE  = 2080
APT_SYNC_FREQ    = 2400.0
APT_SAMPLES_LINE = APT_AUDIO_RATE // APT_LINE_RATE

_A_IMG_S, _A_IMG_E = 86,  995
_B_IMG_S, _B_IMG_E = 1126, 2035

_SYNC_A = np.array(
    [0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,
     0,0,1,1,0,0,1,1,0,0,1,1,0,0,1,1,
     0,0,1,1,0,0,1],
    dtype=np.float32,
)

_BLOCKS = " ░▒▓█"

_CELESTRAK_TLE = "https://celestrak.org/NORAD/elements/gp.php?GROUP=noaa&FORMAT=tle"

_TLE_FALLBACK: dict[str, tuple[str, str]] = {
    "NOAA-19": (
        "1 33591U 09005A   24001.50000000  .00000050  00000-0  50000-4 0  9990",
        "2 33591  99.1000 100.0000 0013000  50.0000 310.0000 14.12000000 00001",
    ),
    "NOAA-18": (
        "1 28654U 05018A   24001.50000000  .00000050  00000-0  50000-4 0  9990",
        "2 28654  99.0000  95.0000 0013000  55.0000 305.0000 14.11000000 00001",
    ),
    "NOAA-15": (
        "1 25338U 98030A   24001.50000000  .00000050  00000-0  50000-4 0  9990",
        "2 25338  98.7000 110.0000 0010000  60.0000 300.0000 14.25000000 00001",
    ),
}


class AFC:
    def __init__(
        self,
        sample_rate:  int,
        center_freq:  float,
        alpha:        float = 0.05,
    ) -> None:
        self.sample_rate   = sample_rate
        self.center_freq   = center_freq
        self.alpha         = alpha
        self._offset_hz    = 0.0
        self._sample_offset: int = 0

    def estimate_offset(self, iq: np.ndarray) -> float:
        n    = min(len(iq), 8192)
        spec = np.abs(np.fft.fftshift(np.fft.fft(iq[:n] * np.blackman(n))))
        freq = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / self.sample_rate))
        mask = np.abs(freq) < 5000
        peak = float(freq[mask][np.argmax(spec[mask])])
        self._offset_hz = (1 - self.alpha) * self._offset_hz + self.alpha * peak
        return self._offset_hz

    def correct(self, iq: np.ndarray) -> np.ndarray:
        n = len(iq)
        if abs(self._offset_hz) < 5.0:
            self._sample_offset += n
            return iq
        # NCO phase-continuous across chunks: use cumulative sample offset
        # so the rotator phase never jumps at chunk boundaries.
        t = (np.arange(n, dtype=np.float64) + self._sample_offset) / self.sample_rate
        self._sample_offset += n
        rot = np.exp(
            1j * 2.0 * math.pi * (-self._offset_hz) * t
        ).astype(np.complex64)
        return (iq * rot).astype(np.complex64)


class SyncPLL:
    def __init__(self, audio_rate: int = APT_AUDIO_RATE) -> None:
        self.audio_rate = audio_rate
        self._omega0    = 2 * math.pi * APT_SYNC_FREQ / audio_rate
        bw              = 50.0 / audio_rate
        self._kp        = 4 * bw * math.sqrt(2)
        self._ki        = 4 * bw ** 2
        self._phase     = 0.0
        self._freq      = self._omega0
        self._integr    = 0.0

    def track(self, audio: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        n       = len(audio)
        env_out = np.zeros(n, dtype=np.float32)
        ph_out  = np.zeros(n, dtype=np.float32)

        phase = self._phase
        freq  = self._freq
        integ = self._integr

        for i in range(n):
            ref_i =  math.cos(phase)
            ref_q = -math.sin(phase)
            s     = float(audio[i])

            in_phase = s * ref_i
            quad     = s * ref_q

            err    = math.atan2(quad, in_phase + 1e-12)
            integ += self._ki * err
            freq   = self._omega0 + self._kp * err + integ
            freq   = max(self._omega0 * 0.8, min(freq, self._omega0 * 1.2))
            phase += freq
            if phase > math.pi:
                phase -= 2 * math.pi

            env_out[i] = abs(in_phase)
            ph_out[i]  = phase

        self._phase  = phase
        self._freq   = freq
        self._integr = integ
        return env_out, ph_out

    def find_line_starts(self, audio: np.ndarray) -> List[int]:
        # Fast path: scipy AM envelope is faster and equally robust for NOAA SNR.
        # The Python PLL loop remains as fallback when scipy is unavailable.
        if _SCIPY_OK:
            env = _am_envelope(audio, self.audio_rate)
        else:
            env, _ = self.track(audio)

        if _SCIPY_OK:
            try:
                sos = butter(
                    4, 20.0 / (self.audio_rate / 2), btype="low", output="sos"
                )
                env = sosfilt(sos, env).astype(np.float32)
            except Exception:
                pass

        threshold = float(np.mean(env) + np.std(env) * 0.5)
        binary    = (env > threshold).astype(np.float32)
        corr      = np.correlate(binary, _SYNC_A, mode="valid")
        mx        = float(np.max(np.abs(corr)) + 1e-12)
        corr     /= mx
        thr       = max(float(np.mean(corr) + 2.0 * np.std(corr)), 0.45)
        min_sep   = int(APT_SAMPLES_LINE * 0.8)
        return _find_peaks_fast(corr, thr, min_sep)


def _find_peaks_fast(
    arr: np.ndarray, threshold: float, min_sep: int
) -> List[int]:
    peaks: List[int] = []
    last  = -min_sep
    w     = min_sep // 4
    for i in range(len(arr)):
        if arr[i] >= threshold and (i - last) >= min_sep:
            seg = arr[max(0, i - w): i + w + 1]
            if arr[i] >= float(np.max(seg)):
                peaks.append(i)
                last = i
    return peaks


def _resample_2stage(
    arr: np.ndarray, src_rate: int, dst_rate: int
) -> np.ndarray:
    if src_rate == dst_rate:
        return arr.astype(np.float32)

    if not _SCIPY_OK:
        n = int(len(arr) * dst_rate / src_rate)
        return np.interp(
            np.linspace(0, 1, n),
            np.linspace(0, 1, len(arr)),
            arr.astype(np.float64),
        ).astype(np.float32)

    from math import gcd
    g    = gcd(src_rate, dst_rate)
    up   = dst_rate // g
    down = src_rate // g

    if max(up, down) <= 500:
        try:
            return resample_poly(
                arr.astype(np.float32), up, down
            ).astype(np.float32)
        except Exception:
            pass

    dec = src_rate // dst_rate
    if dec > 1:
        n_taps  = min(511, 8 * dec + 1)
        n_taps  = n_taps if n_taps % 2 == 1 else n_taps + 1
        cutoff  = 0.9 / dec
        try:
            fir      = firwin(n_taps, cutoff, window=("kaiser", 8.0))
            arr      = lfilter(fir, 1.0, arr.astype(np.float32))[::dec]
            src_rate = src_rate // dec
        except Exception:
            arr      = arr[::dec].astype(np.float32)
            src_rate = src_rate // dec

    if src_rate != dst_rate:
        g    = gcd(src_rate, dst_rate)
        up   = dst_rate // g
        down = src_rate // g
        if max(up, down) <= 500:
            try:
                return resample_poly(
                    arr.astype(np.float32), up, down
                ).astype(np.float32)
            except Exception:
                pass
        n = int(len(arr) * dst_rate / src_rate)
        return np.interp(
            np.linspace(0, 1, n),
            np.linspace(0, 1, len(arr)),
            arr.astype(np.float64),
        ).astype(np.float32)
    return arr.astype(np.float32)


def _am_envelope(audio: np.ndarray, audio_rate: int) -> np.ndarray:
    if not _SCIPY_OK:
        return np.abs(audio.astype(np.float32))
    nyq = audio_rate / 2.0
    try:
        lo  = max(0.01, (APT_SYNC_FREQ - 1200) / nyq)
        hi  = min(0.99, (APT_SYNC_FREQ + 1200) / nyq)
        sos = butter(6, [lo, hi], btype="bandpass", output="sos")
        bp  = sosfiltfilt(sos, audio.astype(np.float64))
        env = np.abs(hilbert(bp)).astype(np.float32)
        lp  = butter(4, min(0.99, 2080.0 / nyq), btype="low", output="sos")
        return sosfiltfilt(lp, env).astype(np.float32)
    except Exception as e:
        log.debug("am_envelope scipy error: %s", e)
        return np.abs(audio.astype(np.float32))


def _stretch_contrast(
    img: np.ndarray, p_lo: float = 1.0, p_hi: float = 99.0
) -> np.ndarray:
    if img.size == 0:
        return img
    lo = float(np.percentile(img, p_lo))
    hi = float(np.percentile(img, p_hi))
    if hi - lo < 1.0:
        return img
    return np.clip(
        (img.astype(np.float32) - lo) / (hi - lo) * 255.0, 0, 255
    ).astype(np.uint8)


def _block_average(img: np.ndarray, cols: int, rows: int) -> np.ndarray:
    h, w      = img.shape
    bh        = max(1, h // rows)
    bw        = max(1, w // cols)
    rows_out  = h // bh
    cols_out  = w // bw
    cropped   = img[: rows_out * bh, : cols_out * bw]
    return cropped.reshape(rows_out, bh, cols_out, bw).mean(axis=(1, 3)).astype(np.uint8)


class APTLineDecoder:
    def __init__(self, audio_rate: int = APT_AUDIO_RATE) -> None:
        self.audio_rate   = audio_rate
        self.samples_line = audio_rate // APT_LINE_RATE

    def decode(self, line_audio: np.ndarray) -> Optional[np.ndarray]:
        if len(line_audio) < self.samples_line // 2:
            return None
        if len(line_audio) != self.samples_line:
            line_audio = _resample_2stage(
                line_audio, len(line_audio), self.samples_line
            )
        env    = _am_envelope(line_audio, self.audio_rate)
        pixels = _resample_2stage(env, self.samples_line, APT_PIXELS_LINE)
        mn, mx = float(np.min(pixels)), float(np.max(pixels))
        if mx - mn < 1e-6:
            return np.zeros(APT_PIXELS_LINE, dtype=np.uint8)
        return np.clip(
            (pixels - mn) / (mx - mn) * 255.0, 0, 255
        ).astype(np.uint8)

    def channels(
        self, px: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        return px[_A_IMG_S:_A_IMG_E], px[_B_IMG_S:_B_IMG_E]


class TerminalRenderer:
    def __init__(
        self, console: Console, max_cols: int = 80, max_rows: int = 36
    ) -> None:
        self.console  = console
        self.max_cols = max_cols
        self.max_rows = max_rows

    def render(
        self,
        img_a: np.ndarray,
        img_b: Optional[np.ndarray] = None,
    ) -> None:
        from rich.text import Text
        self.console.rule("[bold cyan]Canal A — Visible / IR[/bold cyan]")
        self._draw(img_a, "A", thermal=False)
        if img_b is not None and img_b.size > 0:
            self.console.rule("[bold yellow]Canal B — IR Térmico 10.8 µm[/bold yellow]")
            self._draw(img_b, "B", thermal=True)

    def _draw(
        self, img: np.ndarray, label: str, thermal: bool = False
    ) -> None:
        from rich.text import Text
        if img.ndim != 2 or img.shape[0] == 0:
            self.console.print(f"[dim]Canal {label}: sin datos[/dim]")
            return
        thumb = _block_average(img, self.max_cols, self.max_rows)
        h, w  = thumb.shape
        for row in range(h):
            line = Text()
            for col in range(w):
                v     = int(thumb[row, col])
                block = _BLOCKS[min(4, v * 5 // 256)]
                if thermal:
                    if v < 64:
                        r, g, b = 0, 0, v * 2
                    elif v < 128:
                        r, g, b = 0, (v - 64) * 4, 128 + (v - 64)
                    elif v < 192:
                        r, g, b = (v - 128) * 4, 255, 255
                    else:
                        r, g, b = 255, 255, 255
                else:
                    r = g = b = v
                line.append(
                    block,
                    style=f"#{min(r,255):02x}{min(g,255):02x}{min(b,255):02x}",
                )
            self.console.print(line)
        self.console.print(
            f"[dim]  Canal {label}: {img.shape[1]}×{img.shape[0]} px "
            f"→ {w}×{h} terminal[/dim]"
        )


class TLEManager:
    _cache:    dict[str, tuple[str, str]] = {}
    _cache_ts: float = 0.0
    _TTL       = 3600 * 6

    @classmethod
    def get_tle(cls, sat_name: str) -> Optional[Tuple[str, str]]:
        if (time.time() - cls._cache_ts) > cls._TTL or not cls._cache:
            cls._refresh()
        return cls._cache.get(sat_name) or _TLE_FALLBACK.get(sat_name)

    @classmethod
    def _refresh(cls) -> None:
        try:
            req = urllib.request.Request(
                _CELESTRAK_TLE,
                headers={"User-Agent": "SentinelNOAA/2.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                lines = resp.read().decode().strip().splitlines()
            i = 0
            while i + 2 < len(lines):
                name = lines[i].strip()
                tle1 = lines[i + 1].strip()
                tle2 = lines[i + 2].strip()
                if tle1.startswith("1 ") and tle2.startswith("2 "):
                    cls._cache[name] = (tle1, tle2)
                i += 3
            cls._cache_ts = time.time()
            log.debug("TLE actualizados: %d satélites", len(cls._cache))
        except Exception as e:
            log.debug("TLE refresh error (%s) — usando fallback", e)
            cls._cache.update(_TLE_FALLBACK)
            cls._cache_ts = time.time()


class PassCalculator:
    @staticmethod
    def next_passes(
        lat: float, lon: float,
        alt_m: float = 0.0,
        n: int = 5,
        horizon_deg: float = 5.0,
    ) -> List[dict]:
        try:
            from sgp4.api import Satrec, jday
        except ImportError:
            return [{"error": "pip install sgp4 --break-system-packages"}]

        now    = datetime.now(timezone.utc)
        passes: List[dict] = []

        for sat_name in NOAA_SATELLITES:
            tle = TLEManager.get_tle(sat_name)
            if not tle:
                continue
            try:
                sat = Satrec.twoline2rv(tle[0], tle[1])
            except Exception:
                continue

            in_pass    = False
            pass_start = 0.0
            max_elev   = 0.0

            for step_s in range(0, 86400, 30):
                t  = now.timestamp() + step_s
                dt = datetime.fromtimestamp(t, tz=timezone.utc)
                jd, fr = jday(
                    dt.year, dt.month, dt.day,
                    dt.hour, dt.minute, dt.second + dt.microsecond / 1e6,
                )
                e, r, _ = sat.sgp4(jd, fr)
                if e != 0:
                    continue
                elev = PassCalculator._elev(r, lat, lon, alt_m, jd + fr)

                if elev > horizon_deg and not in_pass:
                    in_pass    = True
                    pass_start = t
                    max_elev   = elev
                elif elev > horizon_deg and in_pass:
                    max_elev = max(max_elev, elev)
                elif elev <= horizon_deg and in_pass:
                    in_pass = False
                    dt_start = datetime.fromtimestamp(pass_start, tz=timezone.utc)
                    passes.append({
                        "satellite":  sat_name,
                        "freq_mhz":   NOAA_SATELLITES[sat_name] / 1e6,
                        "start_utc":  dt_start.strftime("%H:%M:%S UTC"),
                        "max_elev":   round(max_elev, 1),
                        "timestamp":  pass_start,
                        "duration_s": int(t - pass_start),
                    })
                    break

        passes.sort(key=lambda x: x.get("timestamp", 9e99))
        return passes[:n]

    @staticmethod
    def _elev(
        r_eci: list,
        lat_deg: float, lon_deg: float,
        alt_m: float,
        jd_full: float = 0.0,
    ) -> float:
        try:
            lat = math.radians(lat_deg)
            lon = math.radians(lon_deg)
            Re  = 6371.0 + alt_m / 1000.0
            obs = np.array([
                Re * math.cos(lat) * math.cos(lon),
                Re * math.cos(lat) * math.sin(lon),
                Re * math.sin(lat),
            ])
            gmst = math.fmod(
                math.radians(
                    280.46061837 + 360.98564736629 * (jd_full - 2451545.0)
                ),
                2 * math.pi,
            )
            cg, sg = math.cos(gmst), math.sin(gmst)
            obs_eci = np.array([
                obs[0] * cg - obs[1] * sg,
                obs[0] * sg + obs[1] * cg,
                obs[2],
            ])
            diff = np.array(r_eci) - obs_eci
            dist = float(np.linalg.norm(diff))
            if dist < 1e-6:
                return 0.0
            up = obs_eci / np.linalg.norm(obs_eci)
            return math.degrees(math.asin(float(np.dot(diff / dist, up))))
        except Exception:
            return 0.0


class NOAADecoder:
    def __init__(
        self,
        rf_factory: SourceFactory,
        console:    Console,
    ) -> None:
        self._rf_factory = rf_factory
        self.console     = console
        self._pll        = SyncPLL(APT_AUDIO_RATE)
        self._decoder    = APTLineDecoder(APT_AUDIO_RATE)
        self._render     = TerminalRenderer(console)

    def menu(self) -> None:
        self.console.print()
        self.console.print("[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
        self.console.print("[bold cyan]║   NOAA APT — Imágenes Satelitales    ║[/bold cyan]")
        self.console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]")
        self.console.print()

        opts = list(NOAA_SATELLITES.items())
        for i, (name, hz) in enumerate(opts, 1):
            self.console.print(
                f"  [cyan][{i}][/cyan] {name}  [dim]{hz/1e6:.3f} MHz[/dim]"
            )
        self.console.print(
            "  [cyan][4][/cyan] Frecuencia manual\n"
            "  [cyan][5][/cyan] Próximos pases (requiere sgp4)\n"
            "  [cyan][0][/cyan] Salir\n"
        )

        opt = Prompt.ask("[bold cyan] >[/bold cyan]").strip()

        if opt == "0":
            return
        if opt == "5":
            self._show_passes()
            return
        if opt == "4":
            s = Prompt.ask("[bold cyan][?] Frecuencia MHz[/bold cyan]").strip()
            try:
                freq_hz, sat_name = float(s) * 1e6, "NOAA-CUSTOM"
            except ValueError:
                self.console.print("[red][!] Frecuencia inválida.[/red]")
                return
        elif opt in ("1", "2", "3"):
            sat_name, freq_hz = opts[int(opt) - 1]
        else:
            self.console.print("[red][!] Opción inválida.[/red]")
            return

        dur_s = Prompt.ask(
            "[bold cyan][?] Duración en segundos[/bold cyan]", default="120"
        ).strip()
        try:
            duracion = max(10, min(int(dur_s) if dur_s else 120, 900))
        except ValueError:
            duracion = 120

        guardar = (
            Prompt.ask(
                "[bold cyan][?] ¿Guardar PNG?[/bold cyan]",
                choices=["s", "n"], default="s",
            ).strip().lower() != "n"
        )

        self.decode(freq_hz, duracion, sat_name=sat_name, save_png=guardar)

    def decode(
        self,
        freq_hz:  float,
        duration: int  = 120,
        sat_name: str  = "NOAA",
        save_png: bool = True,
        on_evidence: Optional[Callable[[str, dict], None]] = None,
    ) -> Optional[Path]:
        self.console.print(
            f"\n[bold green][NOAA] {sat_name}  {freq_hz/1e6:.3f} MHz  {duration}s[/bold green]\n"
            "[dim]  Pipeline: IQ → AFC → WFM → resample → PLL sync → AM demod → píxeles[/dim]\n"
            "[dim]  Ctrl+C detiene la captura y procesa el buffer acumulado[/dim]\n"
        )

        audio_buf:   List[np.ndarray] = []
        actual_rate: int              = APT_AUDIO_RATE

        try:
            from modules.rf.rf_demod  import Demodulator
            from modules.rf.rf_config import DemodConfig

            cfg         = DemodConfig(mode="wfm", audio_rate=APT_AUDIO_RATE, volume=1.0)
            demod       = Demodulator(cfg, sample_rate=2_048_000)
            actual_rate = demod.audio_rate_actual
            afc         = AFC(sample_rate=2_048_000, center_freq=freq_hz)
            source      = self._rf_factory(freq_hz, 2_048_000)
            t0          = time.time()

            with self.console.status(
                f"[bold cyan]Recibiendo APT {sat_name}…[/bold cyan]",
                spinner="satellite",
            ) as status:
                while (time.time() - t0) < duration:
                    iq = source()
                    if iq is None:
                        time.sleep(0.05)
                        continue

                    afc.estimate_offset(
                        np.frombuffer(iq, dtype=np.uint8).astype(np.float32)
                    )
                    iq_arr = np.frombuffer(iq, dtype=np.uint8).view(np.complex64)
                    iq_cor = afc.correct(iq_arr)

                    audio = demod.demodulate(iq_cor)
                    if audio is not None and len(audio) > 0:
                        audio_buf.append(audio)

                    elapsed = time.time() - t0
                    pct     = min(100, int(elapsed / duration * 100))
                    lines   = int(elapsed * APT_LINE_RATE)
                    status.update(
                        f"[bold cyan]APT {sat_name} · {pct}% · "
                        f"~{lines} líneas · AFC {afc._offset_hz:+.0f} Hz[/bold cyan]"
                    )

        except KeyboardInterrupt:
            self.console.print(
                "\n[yellow][!] Captura detenida — procesando buffer…[/yellow]"
            )
        except Exception as e:
            self.console.print(f"[red][!] Error de captura: {e}[/red]")
            log.exception("Error captura NOAA")

        if not audio_buf:
            self.console.print("[red][!] Buffer vacío — sin señal capturada.[/red]")
            return None

        audio_raw = np.concatenate(audio_buf)
        audio     = _resample_2stage(audio_raw, actual_rate, APT_AUDIO_RATE)

        self.console.print(
            f"[dim]  Buffer: {len(audio_raw)/actual_rate:.1f}s "
            f"→ {len(audio)/APT_AUDIO_RATE:.1f}s @ {APT_AUDIO_RATE} Hz[/dim]"
        )

        if _APT3_OK:
            result = self._decode_apt3(audio, sat_name, save_png, on_evidence)
            if result:
                return result

        return self._decode_native(audio, sat_name, save_png, on_evidence)

    def _decode_apt3(
        self,
        audio:       np.ndarray,
        sat_name:    str,
        save_png:    bool,
        on_evidence: Optional[Callable[[str, dict], None]],
    ) -> Optional[Path]:
        self.console.print("[dim]  Backend: apt3[/dim]")
        try:
            data = apt3.decode(audio.astype(np.float32))
            ch_a = np.array(data.channel_a, dtype=np.uint8)
            ch_b = np.array(data.channel_b, dtype=np.uint8)
            self.console.print(
                f"[green][+] apt3: A={ch_a.shape[1]}×{ch_a.shape[0]}  "
                f"B={ch_b.shape[1]}×{ch_b.shape[0]}[/green]"
            )
            self._render.render(ch_a, ch_b)
            if save_png and _PILLOW_OK:
                return self._save_png(ch_a, ch_b, sat_name, on_evidence)
        except Exception as e:
            self.console.print(
                f"[yellow][!] apt3: {e} — usando decodificador nativo[/yellow]"
            )
        return None

    def _decode_native(
        self,
        audio:       np.ndarray,
        sat_name:    str,
        save_png:    bool,
        on_evidence: Optional[Callable[[str, dict], None]],
    ) -> Optional[Path]:
        self.console.print("[dim]  Backend: nativo (PLL sync + AM demod)[/dim]")

        with self.console.status("[cyan]PLL — buscando pulsos de sync…[/cyan]"):
            positions = self._pll.find_line_starts(audio)

        if not positions:
            self.console.print(
                "[yellow][!] Sin sync — modo bruto (imagen puede estar desplazada)[/yellow]"
            )
            return self._decode_raw(audio, sat_name, save_png, on_evidence)

        line_segments = []
        for pos in positions:
            end = pos + APT_SAMPLES_LINE
            if end <= len(audio):
                line_segments.append(audio[pos:end])

        self.console.print(f"[green][+] {len(line_segments)} líneas sincronizadas[/green]")

        rows_a: List[np.ndarray] = []
        rows_b: List[np.ndarray] = []

        with self.console.status("[cyan]Decodificando líneas…[/cyan]"):
            for seg in line_segments:
                px = self._decoder.decode(seg)
                if px is None:
                    continue
                a, b = self._decoder.channels(px)
                rows_a.append(a)
                rows_b.append(b)

        if not rows_a:
            self.console.print("[red][!] No se decodificó ninguna línea.[/red]")
            return None

        img_a = _stretch_contrast(np.array(rows_a, dtype=np.uint8))
        img_b = _stretch_contrast(np.array(rows_b, dtype=np.uint8))

        self.console.print(
            f"[green][+] Imagen: A={img_a.shape[1]}×{img_a.shape[0]}  "
            f"B={img_b.shape[1]}×{img_b.shape[0]}[/green]"
        )
        self._render.render(img_a, img_b)

        if save_png and _PILLOW_OK:
            return self._save_png(img_a, img_b, sat_name, on_evidence)
        if save_png and not _PILLOW_OK:
            self.console.print(
                "[yellow][!] Pillow no disponible: "
                "pip install Pillow --break-system-packages[/yellow]"
            )
        return None

    def _decode_raw(
        self,
        audio:       np.ndarray,
        sat_name:    str,
        save_png:    bool,
        on_evidence: Optional[Callable[[str, dict], None]],
    ) -> Optional[Path]:
        rows_a: List[np.ndarray] = []
        rows_b: List[np.ndarray] = []
        off = 0
        while off + APT_SAMPLES_LINE <= len(audio):
            px = self._decoder.decode(audio[off: off + APT_SAMPLES_LINE])
            if px is not None:
                a, b = self._decoder.channels(px)
                rows_a.append(a)
                rows_b.append(b)
            off += APT_SAMPLES_LINE

        if not rows_a:
            self.console.print("[red][!] Sin datos en modo bruto.[/red]")
            return None

        img_a = _stretch_contrast(np.array(rows_a, dtype=np.uint8))
        img_b = _stretch_contrast(np.array(rows_b, dtype=np.uint8))

        self.console.print(f"[yellow]  Bruto: {img_a.shape[0]} líneas[/yellow]")
        self._render.render(img_a, img_b)
        if save_png and _PILLOW_OK:
            return self._save_png(img_a, img_b, sat_name, on_evidence)
        return None

    def _save_png(
        self,
        img_a:       np.ndarray,
        img_b:       np.ndarray,
        sat_name:    str,
        on_evidence: Optional[Callable[[str, dict], None]],
    ) -> Optional[Path]:
        try:
            ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            slug = sat_name.replace(" ", "_").replace("-", "_")
            out  = Path("data/evidence/rf/noaa")
            out.mkdir(parents=True, exist_ok=True)

            pa = out / f"NOAA_{slug}_A_{ts}.png"
            pb = out / f"NOAA_{slug}_B_{ts}.png"
            Image.fromarray(img_a, "L").save(str(pa))
            Image.fromarray(img_b, "L").save(str(pb))

            paths: List[str] = [str(pa), str(pb)]

            if img_a.shape[0] == img_b.shape[0]:
                pc  = out / f"NOAA_{slug}_composite_{ts}.png"
                rgb = np.zeros((*img_a.shape, 3), dtype=np.uint8)
                rgb[..., 0] = img_b
                rgb[..., 1] = img_a
                rgb[..., 2] = img_a
                Image.fromarray(rgb, "RGB").save(str(pc))
                paths.append(str(pc) + " (falso color)")

            self.console.print(
                "[green][+] PNG guardados:\n"
                + "".join(f"    {p}\n" for p in paths)
                + "[/green]"
            )

            if on_evidence is not None:
                on_evidence("noaa_imagen", {
                    "paths":     paths,
                    "canales":   2,
                    "satellite": sat_name,
                })

            return pa
        except Exception as e:
            self.console.print(f"[red][!] Error guardando PNG: {e}[/red]")
            log.exception("save_png")
            return None

    def _show_passes(self) -> None:
        from rich.table import Table
        from rich import box

        lat_s = Prompt.ask("[bold cyan][?] Latitud  (ej. 21.48)[/bold cyan]").strip()
        lon_s = Prompt.ask("[bold cyan][?] Longitud (ej. -104.89)[/bold cyan]").strip()
        try:
            lat, lon = float(lat_s), float(lon_s)
        except ValueError:
            self.console.print("[red][!] Coordenadas inválidas.[/red]")
            return

        with self.console.status("[cyan]Descargando TLEs y calculando pases…[/cyan]"):
            passes = PassCalculator.next_passes(lat, lon)

        if not passes:
            self.console.print("[yellow]Sin pases calculados.[/yellow]")
            return

        if "error" in passes[0]:
            self.console.print(f"[yellow][!] {passes[0]['error']}[/yellow]")
            for name, hz in NOAA_SATELLITES.items():
                self.console.print(f"  {name}  [cyan]{hz/1e6:.3f} MHz[/cyan]")
            return

        tbl = Table(title="Próximos Pases NOAA", box=box.ROUNDED)
        tbl.add_column("Satélite",   style="cyan",   no_wrap=True)
        tbl.add_column("Inicio UTC", style="yellow")
        tbl.add_column("Elevación",  style="green",  justify="right")
        tbl.add_column("Duración",   style="white",  justify="right")
        tbl.add_column("Freq MHz",   style="dim",    justify="right")

        for p in passes:
            tbl.add_row(
                p["satellite"],
                p["start_utc"],
                f"{p['max_elev']}°",
                f"{p['duration_s']}s",
                f"{p['freq_mhz']:.3f}",
            )
        self.console.print(tbl)
