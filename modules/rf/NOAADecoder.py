from __future__ import annotations

import logging
import time
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

log = logging.getLogger("sentinel.rf.noaa")

# ── Dependencias opcionales ───────────────────────────────────────────
_SCIPY_OK = False
try:
    from scipy.signal import butter, sosfilt, hilbert, resample_poly
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

# ── Frecuencias NOAA ──────────────────────────────────────────────────
NOAA_SATELLITES = {
    "NOAA-19": 137_100_000,
    "NOAA-18": 137_912_500,
    "NOAA-15": 137_620_000,
}

# ── Constantes APT ────────────────────────────────────────────────────
APT_AUDIO_RATE   = 11_025   # Hz
APT_LINE_RATE    = 4        # líneas/segundo
APT_PIXELS_LINE  = 2080     # píxeles/línea (ambos canales)
APT_SYNC_FREQ    = 2400     # Hz — portadora de sync
APT_SYNC_PULSES  = 39       # pulsos por palabra sync
APT_SAMPLES_LINE = APT_AUDIO_RATE // APT_LINE_RATE

# Patrón Sync-A (39 bits)
APT_SYNC_A_WORD = [0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1,
                   0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1,
                   0, 0, 1, 1, 0, 0, 1]

# Posiciones de imagen dentro de la línea de 2080 px:
#   Sync-A(39) + Space-A(47) + Image-A(909) + Telemetry-A(45)
#   Sync-B(39) + Space-B(47) + Image-B(909) + Telemetry-B(45)
APT_IMG_A_START = 86
APT_IMG_A_END   = 995
APT_IMG_B_START = 1126
APT_IMG_B_END   = 2035

_UNICODE_BLOCKS = " ░▒▓█"


# ══════════════════════════════════════════════════════════════════════
# APTSyncEngine
# ══════════════════════════════════════════════════════════════════════

class APTSyncEngine:

    def __init__(self, audio_rate: int = APT_AUDIO_RATE):
        self.audio_rate   = audio_rate
        self.samples_line = audio_rate // APT_LINE_RATE
        self._sync_template = self._build_sync_template()
        log.debug("APTSyncEngine SR=%d SPL=%d template=%d",
                  audio_rate, self.samples_line, len(self._sync_template))

    def find_sync_positions(self, audio: np.ndarray) -> list[int]:
        if len(audio) < self.samples_line * 2:
            return []

        am   = self._am_demod_2400(audio)
        corr = np.correlate(am, self._sync_template, mode="valid")
        if len(corr) == 0:
            return []

        norm = np.max(np.abs(corr))
        if norm < 1e-9:
            return []
        corr = corr / norm

        threshold = float(np.mean(corr) + 2.0 * np.std(corr))
        threshold = max(threshold, 0.35)
        min_sep   = int(self.samples_line * 0.8)
        positions = self._find_peaks(corr, threshold, min_sep)

        log.debug("sync: %d líneas threshold=%.3f", len(positions), threshold)
        return positions

    def split_lines(self, audio: np.ndarray,
                    positions: list[int]) -> list[np.ndarray]:
        lines = []
        for pos in positions:
            end = pos + self.samples_line
            if end <= len(audio):
                lines.append(audio[pos:end])
        return lines

    def _build_sync_template(self) -> np.ndarray:
        pulse_samples = self.audio_rate / APT_SYNC_FREQ
        total = int(pulse_samples * APT_SYNC_PULSES)
        t     = np.arange(total) / self.audio_rate
        tone  = np.sin(2 * math.pi * APT_SYNC_FREQ * t)
        env   = np.zeros(total)
        for i, bit in enumerate(APT_SYNC_A_WORD):
            s = int(i * pulse_samples)
            e = min(int((i + 1) * pulse_samples), total)
            env[s:e] = bit
        template = tone * env
        n = np.max(np.abs(template))
        return (template / n).astype(np.float32) if n > 0 else template.astype(np.float32)

    def _am_demod_2400(self, audio: np.ndarray) -> np.ndarray:
        if _SCIPY_OK:
            nyq  = self.audio_rate / 2
            low  = max(0.001, min((APT_SYNC_FREQ - 200) / nyq, 0.999))
            high = max(0.001, min((APT_SYNC_FREQ + 200) / nyq, 0.999))
            try:
                sos      = butter(4, [low, high], btype="bandpass", output="sos")
                filtered = sosfilt(sos, audio.astype(np.float64))
                return np.abs(hilbert(filtered)).astype(np.float32)
            except Exception as e:
                log.debug("hilbert falló: %s", e)
        rectified = np.abs(audio.astype(np.float32))
        kernel    = np.ones(int(self.audio_rate / APT_SYNC_FREQ), dtype=np.float32)
        kernel   /= len(kernel)
        return np.convolve(rectified, kernel, mode="same")

    @staticmethod
    def _find_peaks(arr: np.ndarray, threshold: float, min_sep: int) -> list[int]:
        peaks: list[int] = []
        last = -min_sep
        for i in range(len(arr)):
            if arr[i] >= threshold and (i - last) >= min_sep:
                w   = min_sep // 4
                seg = arr[max(0, i - w): i + w + 1]
                if arr[i] == np.max(seg):
                    peaks.append(i)
                    last = i
        return peaks


# ══════════════════════════════════════════════════════════════════════
# APTImageDecoder
# ══════════════════════════════════════════════════════════════════════

class APTImageDecoder:

    def __init__(self, audio_rate: int = APT_AUDIO_RATE):
        self.audio_rate   = audio_rate
        self.samples_line = audio_rate // APT_LINE_RATE

    def decode_line(self, line_audio: np.ndarray) -> np.ndarray | None:
        if len(line_audio) < self.samples_line // 2:
            return None
        if len(line_audio) != self.samples_line:
            line_audio = self._resample(line_audio, self.samples_line)
        return self._am_to_pixels(line_audio)

    def extract_image_channels(self, pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return pixels[APT_IMG_A_START:APT_IMG_A_END], pixels[APT_IMG_B_START:APT_IMG_B_END]

    def _am_to_pixels(self, audio: np.ndarray) -> np.ndarray:
        if _SCIPY_OK:
            try:
                env = np.abs(hilbert(audio.astype(np.float64))).astype(np.float32)
            except Exception:
                env = np.abs(audio.astype(np.float32))
        else:
            env = np.abs(audio.astype(np.float32))

        pixels  = self._resample(env, APT_PIXELS_LINE)
        mn, mx  = float(np.min(pixels)), float(np.max(pixels))
        if mx - mn < 1e-6:
            return np.zeros(APT_PIXELS_LINE, dtype=np.uint8)
        pixels = (pixels - mn) / (mx - mn) * 255.0
        return np.clip(pixels, 0, 255).astype(np.uint8)

    @staticmethod
    def _resample(arr: np.ndarray, target: int) -> np.ndarray:
        if len(arr) == target:
            return arr
        if _SCIPY_OK:
            from math import gcd
            g    = gcd(len(arr), target)
            up   = target // g
            down = len(arr) // g
            if max(up, down) <= 1000:
                try:
                    return resample_poly(arr.astype(np.float32), up, down)
                except Exception:
                    pass
        x_old = np.linspace(0, 1, len(arr))
        x_new = np.linspace(0, 1, target)
        return np.interp(x_new, x_old, arr.astype(np.float32)).astype(np.float32)


# ══════════════════════════════════════════════════════════════════════
# APTTerminalRenderer
# ══════════════════════════════════════════════════════════════════════

class APTTerminalRenderer:

    def __init__(self, console, max_cols: int = 80, max_rows: int = 40):
        self.console  = console
        self.max_cols = max_cols
        self.max_rows = max_rows

    def render(self, image_a: np.ndarray, image_b: np.ndarray | None = None) -> None:
        self.console.rule("[bold cyan]NOAA APT — Canal A (Visible/IR)[/bold cyan]")
        self._render_channel(image_a, label="A")
        if image_b is not None and len(image_b) > 0:
            self.console.rule("[bold yellow]NOAA APT — Canal B (IR Térmico)[/bold yellow]")
            self._render_channel(image_b, label="B")

    def _render_channel(self, img: np.ndarray, label: str) -> None:
        from rich.text import Text

        if img.ndim != 2 or img.shape[0] == 0:
            self.console.print(f"[dim]Canal {label}: sin datos[/dim]")
            return

        h, w     = img.shape
        scale_x  = max(1, w // self.max_cols)
        scale_y  = max(1, h // self.max_rows)
        rows_out = min(h // scale_y, self.max_rows)
        cols_out = min(w // scale_x, self.max_cols)

        for row_i in range(rows_out):
            y    = row_i * scale_y
            line = Text()
            for col_i in range(cols_out):
                x     = col_i * scale_x
                val   = int(img[y, x])
                block = _UNICODE_BLOCKS[min(4, val * 5 // 256)]
                color = f"#{val:02x}{val:02x}{int(val * 0.85):02x}"
                line.append(block, style=color)
            self.console.print(line)

        self.console.print(
            f"[dim]  Canal {label}: {w}×{h} px → terminal {cols_out}×{rows_out}[/dim]"
        )


# ══════════════════════════════════════════════════════════════════════
# NOAASatellitePass
# ══════════════════════════════════════════════════════════════════════

class NOAASatellitePass:
    # TLEs de referencia — actualizar desde celestrak.org
    NOAA_TLE: dict[str, tuple[str, str]] = {
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

    @classmethod
    def proximos_pases(cls, lat: float, lon: float,
                       alt_m: float = 0.0, n: int = 3) -> list[dict]:
        try:
            from sgp4.api import Satrec, jday
        except ImportError:
            return [{"error": "Instala sgp4: pip install sgp4 --break-system-packages"}]

        now    = datetime.now(timezone.utc)
        passes = []

        for sat_name, (tle1, tle2) in cls.NOAA_TLE.items():
            try:
                sat = Satrec.twoline2rv(tle1, tle2)
            except Exception:
                continue
            for minutes in range(0, 1440):
                t  = now.timestamp() + minutes * 60
                dt = datetime.fromtimestamp(t, tz=timezone.utc)
                jd, fr = jday(dt.year, dt.month, dt.day,
                              dt.hour, dt.minute, dt.second)
                e, r, _ = sat.sgp4(jd, fr)
                if e != 0:
                    continue
                elev = cls._elevation(r, lat, lon, alt_m)
                if elev > 5.0:
                    passes.append({
                        "satellite": sat_name,
                        "freq_mhz":  NOAA_SATELLITES[sat_name] / 1e6,
                        "time_utc":  dt.strftime("%H:%M UTC"),
                        "elevation": round(elev, 1),
                        "timestamp": t,
                    })
                    break

        passes.sort(key=lambda x: x.get("timestamp", 9e99))
        return passes[:n]

    @staticmethod
    def _elevation(r_eci: list, lat_deg: float, lon_deg: float, alt_m: float) -> float:
        try:
            lat = math.radians(lat_deg)
            lon = math.radians(lon_deg)
            Re  = 6371.0 + alt_m / 1000.0
            obs = np.array([
                Re * math.cos(lat) * math.cos(lon),
                Re * math.cos(lat) * math.sin(lon),
                Re * math.sin(lat),
            ])
            diff = np.array(r_eci) - obs
            dist = float(np.linalg.norm(diff))
            if dist < 1e-6:
                return 0.0
            up = obs / np.linalg.norm(obs)
            return math.degrees(math.asin(float(np.dot(diff / dist, up))))
        except Exception:
            return 0.0


# ══════════════════════════════════════════════════════════════════════
# NOAADecoder
# ══════════════════════════════════════════════════════════════════════

class NOAADecoder:

    def __init__(self, sentinel):
        self.s        = sentinel
        self.console  = getattr(sentinel, "console", None)
        self._sync    = APTSyncEngine(APT_AUDIO_RATE)
        self._img_dec = APTImageDecoder(APT_AUDIO_RATE)
        self._render  = APTTerminalRenderer(self.console)

    def menu(self) -> None:
        self.console.print()
        self.console.print("[bold cyan]╔══════════════════════════════════════╗[/bold cyan]")
        self.console.print("[bold cyan]║   NOAA APT — Imágenes Satelitales    ║[/bold cyan]")
        self.console.print("[bold cyan]╚══════════════════════════════════════╝[/bold cyan]")
        self.console.print()
        self.console.print("[bold]Satélites disponibles:[/bold]")

        opts = list(NOAA_SATELLITES.items())
        for i, (name, freq_hz) in enumerate(opts, 1):
            self.console.print(f"  [cyan][{i}][/cyan] {name}  [dim]{freq_hz/1e6:.3f} MHz[/dim]")
        self.console.print(
            "  [cyan][4][/cyan] Frecuencia manual\n"
            "  [cyan][5][/cyan] Ver próximos pases\n"
            "  [cyan][0][/cyan] Salir\n"
        )

        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()

        if opt == "0":
            return
        elif opt == "5":
            self._mostrar_pases()
            return
        elif opt == "4":
            freq_str = self.console.input("[bold cyan][?] Frecuencia MHz: [/bold cyan]").strip()
            try:
                freq_hz  = float(freq_str) * 1e6
                sat_name = "NOAA-CUSTOM"
            except ValueError:
                self.console.print("[red][!] Frecuencia inválida.[/red]")
                return
        elif opt in ("1", "2", "3"):
            sat_name, freq_hz = opts[int(opt) - 1]
        else:
            self.console.print("[red][!] Opción inválida.[/red]")
            return

        dur_s = self.console.input(
            "[bold cyan][?] Duración captura (segundos, default 120): [/bold cyan]"
        ).strip()
        try:
            duracion = max(10, min(int(dur_s) if dur_s else 120, 900))
        except ValueError:
            duracion = 120

        guardar = self.console.input(
            "[bold cyan][?] ¿Guardar PNG? (S/n): [/bold cyan]"
        ).strip().lower() != "n"

        self.decode(freq_hz, duracion, sat_name=sat_name, guardar_png=guardar)

    def decode(self, freq_hz: float, duracion: int = 120,
               sat_name: str = "NOAA", guardar_png: bool = True) -> Path | None:
        freq_mhz = freq_hz / 1e6
        self.console.print(
            f"\n[bold green][NOAA] Sintonizando {freq_mhz:.3f} MHz — {sat_name}[/bold green]"
        )
        self.console.print(
            f"[dim]  Duración: {duracion}s · APT 4 líneas/s · 2080 px/línea[/dim]\n"
            "[dim]  Ctrl+C para detener y procesar lo capturado[/dim]\n"
        )

        audio_buffer: list[np.ndarray] = []

        try:
            from modules.rf.rf_demod import Demodulator
            from modules.rf.rf_config import DemodConfig

            cfg   = DemodConfig(mode="wfm", audio_rate=APT_AUDIO_RATE, volume=1.0)
            demod = Demodulator(cfg, sample_rate=2_048_000)
            inicio = time.time()

            with self.console.status(
                f"[bold cyan]Recibiendo APT ({sat_name})…[/bold cyan]",
                spinner="satellite",
            ) as status:
                while (time.time() - inicio) < duracion:
                    muestras = self.s.rf._capturar(freq_hz)
                    if muestras is None:
                        time.sleep(0.1)
                        continue
                    audio = demod.demodulate(muestras)
                    if audio is not None and len(audio) > 0:
                        audio_buffer.append(audio)
                    elapsed      = time.time() - inicio
                    pct          = min(100, int(elapsed / duracion * 100))
                    lineas_aprox = int(elapsed * APT_LINE_RATE)
                    status.update(
                        f"[bold cyan]APT {sat_name} · {pct}% · ~{lineas_aprox} líneas[/bold cyan]"
                    )

        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Captura interrumpida — procesando buffer…[/yellow]")
        except Exception as e:
            self.console.print(f"[red][!] Error de captura: {e}[/red]")
            log.exception("Error durante captura NOAA")

        if not audio_buffer:
            self.console.print("[red][!] Sin audio capturado.[/red]")
            return None

        audio_total = np.concatenate(audio_buffer)
        audio_11k   = self._ensure_apt_rate(audio_total, demod.audio_rate_actual)

        self.console.print(
            f"[dim]  Buffer: {len(audio_total)/demod.audio_rate_actual:.1f}s "
            f"→ {len(audio_11k)/APT_AUDIO_RATE:.1f}s @ {APT_AUDIO_RATE} Hz[/dim]"
        )

        if _APT3_OK:
            return self._decode_apt3(audio_11k, sat_name, guardar_png)
        return self._decode_nativo(audio_11k, sat_name, guardar_png)

    def _decode_apt3(self, audio: np.ndarray, sat_name: str, guardar_png: bool) -> Path | None:
        self.console.print("[dim]  Usando apt3 para decodificación…[/dim]")
        try:
            img_data = apt3.decode(audio.astype(np.float32))
            ch_a = np.array(img_data.channel_a, dtype=np.uint8)
            ch_b = np.array(img_data.channel_b, dtype=np.uint8)
            self.console.print(
                f"[green][+] apt3: {ch_a.shape[1]}×{ch_a.shape[0]} px Canal A  "
                f"{ch_b.shape[1]}×{ch_b.shape[0]} px Canal B[/green]"
            )
            self._render.render(ch_a, ch_b)
            if guardar_png and _PILLOW_OK:
                return self._guardar_png(ch_a, ch_b, sat_name)
        except Exception as e:
            self.console.print(f"[yellow][!] apt3 falló ({e}), usando decodificador nativo…[/yellow]")
            return self._decode_nativo(audio, sat_name, guardar_png)
        return None

    def _decode_nativo(self, audio: np.ndarray, sat_name: str, guardar_png: bool) -> Path | None:
        self.console.print("[dim]  Decodificador nativo APT…[/dim]")

        with self.console.status("[cyan]Buscando pulsos de sincronismo…[/cyan]"):
            positions = self._sync.find_sync_positions(audio)

        if not positions:
            self.console.print(
                "[yellow][!] No se detectaron pulsos de sync APT.\n"
                "    Verifica señal, antena, frecuencia o pase activo.[/yellow]"
            )
            return self._decode_bruto(audio, sat_name, guardar_png)

        lines_audio = self._sync.split_lines(audio, positions)
        self.console.print(f"[green][+] {len(lines_audio)} líneas APT sincronizadas[/green]")

        rows_a: list[np.ndarray] = []
        rows_b: list[np.ndarray] = []

        with self.console.status("[cyan]Decodificando líneas…[/cyan]"):
            for line in lines_audio:
                pixels = self._img_dec.decode_line(line)
                if pixels is None:
                    continue
                ch_a, ch_b = self._img_dec.extract_image_channels(pixels)
                rows_a.append(ch_a)
                rows_b.append(ch_b)

        if not rows_a:
            self.console.print("[red][!] No se pudo decodificar ninguna línea.[/red]")
            return None

        img_a = self._stretch_contrast(np.array(rows_a, dtype=np.uint8))
        img_b = self._stretch_contrast(np.array(rows_b, dtype=np.uint8))

        self.console.print(
            f"[green][+] Imagen: {img_a.shape[1]}×{img_a.shape[0]} px (A)  "
            f"{img_b.shape[1]}×{img_b.shape[0]} px (B)[/green]"
        )
        self._render.render(img_a, img_b)

        if guardar_png and _PILLOW_OK:
            return self._guardar_png(img_a, img_b, sat_name)
        if guardar_png and not _PILLOW_OK:
            self.console.print(
                "[yellow][!] Pillow no disponible: pip install Pillow --break-system-packages[/yellow]"
            )
        return None

    def _decode_bruto(self, audio: np.ndarray, sat_name: str, guardar_png: bool) -> Path | None:
        self.console.print("[dim]  Modo bruto (sin sync)…[/dim]")
        rows_a: list[np.ndarray] = []
        rows_b: list[np.ndarray] = []

        offset = 0
        while offset + APT_SAMPLES_LINE <= len(audio):
            pixels = self._img_dec.decode_line(audio[offset: offset + APT_SAMPLES_LINE])
            if pixels is not None:
                ch_a, ch_b = self._img_dec.extract_image_channels(pixels)
                rows_a.append(ch_a)
                rows_b.append(ch_b)
            offset += APT_SAMPLES_LINE

        if not rows_a:
            self.console.print("[red][!] Sin datos para imagen bruta.[/red]")
            return None

        img_a = self._stretch_contrast(np.array(rows_a, dtype=np.uint8))
        img_b = self._stretch_contrast(np.array(rows_b, dtype=np.uint8))

        self.console.print(
            f"[yellow]  Modo bruto: {img_a.shape[0]} líneas (imagen puede estar desplazada)[/yellow]"
        )
        self._render.render(img_a, img_b)

        if guardar_png and _PILLOW_OK:
            return self._guardar_png(img_a, img_b, sat_name)
        return None

    def _guardar_png(self, img_a: np.ndarray, img_b: np.ndarray, sat_name: str) -> Path | None:
        try:
            ts        = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            safe_name = sat_name.replace(" ", "_").replace("-", "_")
            out_dir   = Path("data/evidence/rf/noaa")
            out_dir.mkdir(parents=True, exist_ok=True)

            path_a = out_dir / f"NOAA_APT_{safe_name}_A_{ts}.png"
            path_b = out_dir / f"NOAA_APT_{safe_name}_B_{ts}.png"
            Image.fromarray(img_a, mode="L").save(str(path_a))
            Image.fromarray(img_b, mode="L").save(str(path_b))

            if img_a.shape[0] == img_b.shape[0]:
                path_comp = out_dir / f"NOAA_APT_{safe_name}_composite_{ts}.png"
                Image.fromarray(np.hstack([img_a, img_b]), mode="L").save(str(path_comp))
                self.console.print(
                    f"[green][+] PNG guardados:\n"
                    f"    {path_a}\n    {path_b}\n    {path_comp} (compuesto)[/green]"
                )
                return path_comp

            self.console.print(f"[green][+] PNG: {path_a}  |  {path_b}[/green]")
            return path_a

        except Exception as e:
            self.console.print(f"[red][!] Error guardando PNG: {e}[/red]")
            log.exception("Error guardando PNG NOAA")
            return None

    def _mostrar_pases(self) -> None:
        from rich.table import Table
        from rich import box

        lat_s = self.console.input("[bold cyan][?] Latitud (ej. 21.5): [/bold cyan]").strip()
        lon_s = self.console.input("[bold cyan][?] Longitud (ej. -104.9): [/bold cyan]").strip()

        try:
            lat = float(lat_s)
            lon = float(lon_s)
        except ValueError:
            self.console.print("[red][!] Coordenadas inválidas.[/red]")
            return

        with self.console.status("[cyan]Calculando pases…[/cyan]"):
            passes = NOAASatellitePass.proximos_pases(lat, lon)

        if not passes:
            self.console.print("[yellow]Sin pases calculados.[/yellow]")
            return

        if "error" in passes[0]:
            self.console.print(
                f"[yellow][!] {passes[0]['error']}[/yellow]\n"
                "[dim]Para pases exactos: pip install sgp4 --break-system-packages[/dim]\n"
            )
            self.console.print("[bold]Frecuencias NOAA:[/bold]")
            for name, freq_hz in NOAA_SATELLITES.items():
                self.console.print(f"  {name}: [cyan]{freq_hz/1e6:.3f} MHz[/cyan]")
            return

        table = Table(title="Próximos Pases NOAA", box=box.ROUNDED)
        table.add_column("Satélite",  style="cyan")
        table.add_column("Hora UTC",  style="yellow")
        table.add_column("Elevación", style="green")
        table.add_column("Freq MHz",  style="white")

        for p in passes:
            table.add_row(p["satellite"], p["time_utc"], f"{p['elevation']}°", f"{p['freq_mhz']:.3f}")

        self.console.print(table)

    @staticmethod
    def _ensure_apt_rate(audio: np.ndarray, current_rate: int) -> np.ndarray:
        if current_rate == APT_AUDIO_RATE:
            return audio
        if _SCIPY_OK:
            from math import gcd
            g    = gcd(current_rate, APT_AUDIO_RATE)
            up   = APT_AUDIO_RATE // g
            down = current_rate   // g
            if max(up, down) <= 500:
                try:
                    return resample_poly(audio.astype(np.float32), up, down).astype(np.float32)
                except Exception:
                    pass
        n_out = int(len(audio) * APT_AUDIO_RATE / current_rate)
        return np.interp(
            np.linspace(0, 1, n_out),
            np.linspace(0, 1, len(audio)),
            audio.astype(np.float64),
        ).astype(np.float32)

    @staticmethod
    def _stretch_contrast(img: np.ndarray, low_pct: float = 2.0, high_pct: float = 98.0) -> np.ndarray:
        if img.size == 0:
            return img
        lo = float(np.percentile(img, low_pct))
        hi = float(np.percentile(img, high_pct))
        if hi - lo < 1.0:
            return img
        return np.clip((img.astype(np.float32) - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
