from __future__ import annotations

import logging
import logging.handlers
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from modules.rf.bands import BANDAS_RF, COLORES_TIPO, identify_band, tactical_bands
from modules.rf.dsp import DSPEngine, Signal
from modules.rf.rf_config import RFConfig, load_config
from modules.rf.rf_database import RFDatabase
from modules.rf.rf_demod import Demodulator
from modules.rf.rf_recorder import RFRecorder
from modules.rf.rf_storage import CSVExporter, SigMFWriter, SignalDB

log = logging.getLogger("sentinel.rf.scanner")

_WF_CHARS = " ·░▒▓█"
_RTL_FREQ_MIN = 24.0
_RTL_FREQ_MAX = 1766.0

# DC SPIKE REMOVER

class DCRemover:
    def remove(self, psd: np.ndarray, n_bins: int = 5) -> np.ndarray:
        result = psd.copy()
        cx = len(psd) // 2
        lo = max(0, cx - n_bins)
        hi = min(len(psd), cx + n_bins + 1)
        if lo > 0 and hi < len(psd):
            result[lo:hi] = np.interp(
                np.arange(lo, hi),
                [lo - 1, hi],
                [psd[lo - 1], psd[hi]],
            )
        return result

# PEAK HOLD + PROMEDIO ACUMULADO

class PeakHoldBuffer:
    def __init__(self, avg_frames: int = 8) -> None:
        self._avg_frames = avg_frames
        self._frames: deque[np.ndarray] = deque(maxlen=avg_frames)
        self._hold: np.ndarray | None = None

    def update(self, psd: np.ndarray) -> None:
        self._frames.append(psd)
        self._hold = (
            np.maximum(self._hold, psd)
            if self._hold is not None and self._hold.shape == psd.shape
            else psd.copy()
        )

    def peak_hold(self) -> np.ndarray | None:
        return self._hold

    def average(self) -> np.ndarray | None:
        if not self._frames:
            return None
        return np.mean(np.stack(self._frames), axis=0)

    def reset(self) -> None:
        self._frames.clear()
        self._hold = None

# SIGNAL PERSISTENCE TRACKER — filtra falsos positivos

@dataclass
class _FreqTrack:
    detecciones: int = 0
    ausencias:   int = 0
    primera_vez: float = field(default_factory=time.monotonic)
    ultima_vez:  float = field(default_factory=time.monotonic)
    potencias:   deque = field(default_factory=lambda: deque(maxlen=20))

    def activo(self) -> bool:
        return self.detecciones > 0

    def duty_cycle(self, total_frames: int) -> float:
        if total_frames == 0:
            return 0.0
        return min(1.0, self.detecciones / total_frames)

    def potencia_media(self) -> float:
        return float(np.mean(self.potencias)) if self.potencias else -999.0

class SignalTracker:
    BIN_KHZ = 5.0    # resolución de agrupación de frecuencias
    MIN_FRAMES = 2      # mínimo de frames consecutivos para reportar
    DECAY_FRAMES = 5      # frames sin señal antes de eliminar

    def __init__(self) -> None:
        self._tracks:      dict[int, _FreqTrack] = {}
        self._consec:      dict[int, int] = defaultdict(int)
        self._total_frames = 0

    def _freq_bin(self, freq_mhz: float) -> int:
        return round(freq_mhz * 1000 / self.BIN_KHZ)

    def update(self, picos: list[Signal]) -> list[Signal]:
        self._total_frames += 1
        vistos: set[int] = set()

        for s in picos:
            b = self._freq_bin(s.freq_mhz)
            vistos.add(b)
            if b not in self._tracks:
                self._tracks[b] = _FreqTrack(primera_vez=time.monotonic())
            t = self._tracks[b]
            t.detecciones += 1
            t.ausencias = 0
            t.ultima_vez = time.monotonic()
            t.potencias.append(s.potencia)
            self._consec[b] += 1

        for b in list(self._tracks.keys()):
            if b not in vistos:
                self._tracks[b].ausencias += 1
                self._consec[b] = 0
                if self._tracks[b].ausencias > self.DECAY_FRAMES:
                    del self._tracks[b]
                    self._consec.pop(b, None)

        return [
            s for s in picos
            if self._consec[self._freq_bin(s.freq_mhz)] >= self.MIN_FRAMES
        ]

    def duty_cycle(self, freq_mhz: float) -> float:
        b = self._freq_bin(freq_mhz)
        t = self._tracks.get(b)
        return t.duty_cycle(self._total_frames) if t else 0.0

    def tiempo_activo(self, freq_mhz: float) -> float:
        b = self._freq_bin(freq_mhz)
        t = self._tracks.get(b)
        return time.monotonic() - t.primera_vez if t else 0.0

    def reset(self) -> None:
        self._tracks.clear()
        self._consec.clear()
        self._total_frames = 0

# AGC — CONTROL AUTOMÁTICO DE GANANCIA

class AGCController:
    SAT_THRESHOLD = -5.0    # dBm — señal saturando
    WEAK_THRESHOLD = -85.0   # dBm — señal demasiado débil
    STEP_UP = 5.0     # dB de subida
    STEP_DOWN = 10.0    # dB de bajada (más agresivo para evitar saturación)
    GAIN_MIN = 0.0
    GAIN_MAX = 49.6
    COOLDOWN_S = 2.0     # segundos entre ajustes

    def __init__(self) -> None:
        self._last_adjust = 0.0
        self._current = 30.0

    def step(
        self, psd_dbm: np.ndarray, backend: Any, cfg_gain: float
    ) -> float | None:
        if time.monotonic() - self._last_adjust < self.COOLDOWN_S:
            return None

        peak = float(np.percentile(psd_dbm, 99))

        if peak > self.SAT_THRESHOLD:
            nueva = max(self.GAIN_MIN, self._current - self.STEP_DOWN)
            reason = f"saturación ({peak:.0f} dBm) → ↓ {self.STEP_DOWN:.0f} dB"
        elif peak < self.WEAK_THRESHOLD:
            nueva = min(self.GAIN_MAX, self._current + self.STEP_UP)
            reason = f"señal débil ({peak:.0f} dBm) → ↑ {self.STEP_UP:.0f} dB"
        else:
            return None

        if abs(nueva - self._current) < 0.5:
            return None

        try:
            backend.set_gain(nueva)
            self._current = nueva
            self._last_adjust = time.monotonic()
            log.info("AGC: %s  nueva_ganancia=%.1f dB", reason, nueva)
            return nueva
        except Exception as exc:
            log.warning("AGC set_gain: %s", exc)
            return None

# RENDERIZADOR

class Renderizador:

    def __init__(self, console: Console, cfg: RFConfig) -> None:
        self.console = console
        self.cfg = cfg

    # Espectro con peak hold y promedio
    def espectro(
        self,
        freqs_hz:       np.ndarray,
        psd_dbm:        np.ndarray,
        freq_centro_mhz: float,
        picos:          list[Signal],
        sample_rate:    float,
        hw:             str,
        peak_hold:      np.ndarray | None = None,
        avg_psd:        np.ndarray | None = None,
    ) -> Panel:
        disp = self.cfg.display
        ancho = disp.spectrum_width
        alto = disp.spectrum_height
        db_min = disp.dbm_floor
        db_max = disp.dbm_ceil

        idx = np.linspace(0, len(psd_dbm) - 1, ancho).astype(int)
        psd_d = psd_dbm[idx]
        ph_d = peak_hold[idx] if peak_hold is not None and peak_hold.shape == psd_dbm.shape else None
        av_d = avg_psd[idx] if avg_psd is not None and avg_psd.shape == psd_dbm.shape else None

        def _y(val: float) -> int:
            return int(np.clip((val - db_min) / (db_max - db_min) * alto, 0, alto))

        alturas = [_y(v) for v in psd_d]
        ph_ys = [_y(v) for v in ph_d] if ph_d is not None else None
        av_ys = [_y(v) for v in av_d] if av_d is not None else None
        piso = float(np.median(psd_dbm))
        umbral_y = _y(piso + self.cfg.dsp.snr_threshold)
        texto = Text()

        for fila in range(alto, -1, -1):
            db_label = db_min + (fila / alto) * (db_max - db_min)
            texto.append(f"{db_label:>6.0f} │", style="dim green")

            for col, h in enumerate(alturas):
                ph_y = ph_ys[col] if ph_ys else None
                av_y = av_ys[col] if av_ys else None

                if h >= fila:
                    ratio = h / alto
                    if ratio >= 0.85:
                        style = "bold red"
                    elif ratio >= 0.65:
                        style = "red"
                    elif ratio >= 0.45:
                        style = "yellow"
                    elif ratio >= 0.25:
                        style = "green"
                    else:
                        style = "dim green"
                    texto.append("█", style=style)
                elif ph_y is not None and ph_y == fila:
                    texto.append("▔", style="cyan")
                elif av_y is not None and av_y == fila:
                    texto.append("─", style="dim cyan")
                elif fila == umbral_y:
                    texto.append("─", style="dim red")
                else:
                    texto.append(" ")

            texto.append("\n")

        bw_mhz = sample_rate / 1e6
        freq_ini = freq_centro_mhz - bw_mhz / 2
        freq_fin = freq_centro_mhz + bw_mhz / 2
        pad_l = max(0, ancho // 2 - 9)
        pad_r = max(0, ancho // 2 - 11)

        texto.append("       └" + "─" * ancho + "\n", style="dim green")
        texto.append(
            f"  {freq_ini:.3f}" + " " * pad_l
            + f"{freq_centro_mhz:.3f} [centro]" + " " * pad_r
            + f"{freq_fin:.3f} MHz\n",
            style="dim green",
        )
        if ph_ys:
            texto.append("  [dim cyan]▔[/dim cyan] peak-hold  ", style="dim")
        if av_ys:
            texto.append("  [dim cyan]─[/dim cyan] promedio  ", style="dim")
        if picos:
            texto.append(
                f"  [dim red]▲ umbral={piso:.0f}+{self.cfg.dsp.snr_threshold:.0f}"
                f"={piso + self.cfg.dsp.snr_threshold:.0f} dBm[/dim red]"
            )

        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        return Panel(
            texto,
            title=(f"[bold green]ESPECTRO RF — {freq_centro_mhz:.4f} MHz"
                   f"[/bold green]  [dim]{hw}[/dim]  [dim]{ts}[/dim]"),
            border_style="green",
            box=box.HEAVY_HEAD,
        )

    # Waterfall
    def waterfall(self, historial: deque, freq_centro_mhz: float) -> Panel:
        if not historial:
            return Panel("[dim]Sin datos.[/dim]",
                         title="WATERFALL", border_style="dim green")

        ancho = self.cfg.display.spectrum_width
        db_min = self.cfg.display.dbm_floor
        db_max = self.cfg.display.dbm_ceil
        texto = Text()

        for i, psd in enumerate(historial):
            idx = np.linspace(0, len(psd) - 1, ancho).astype(int)
            fila = psd[idx]
            age = i / max(len(historial) - 1, 1)
            texto.append("  ")
            for val in fila:
                v = float(np.clip((val - db_min) / (db_max - db_min), 0, 1))
                char = _WF_CHARS[int(v * (len(_WF_CHARS) - 1))]
                if v > 0.75:
                    style = "bold red" if age < 0.3 else "red"
                elif v > 0.50:
                    style = "yellow" if age < 0.3 else "dark_orange"
                elif v > 0.25:
                    style = "green" if age < 0.3 else "dark_green"
                else:
                    style = "dim"
                texto.append(char, style=style)
            texto.append("\n")

        return Panel(
            texto,
            title=(f"[bold green]WATERFALL — {freq_centro_mhz:.3f} MHz"
                   f"[/bold green]  [dim]{len(historial)} capturas[/dim]"),
            border_style="dim green",
            box=box.SIMPLE,
        )

    # Tabla de señales con duty cycle
    def tabla_picos(
        self,
        picos:   list[Signal],
        tracker: SignalTracker | None = None,
    ) -> Panel:
        if not picos:
            return Panel(
                "[dim]No se detectaron señales sobre el umbral.[/dim]",
                title="[green]SEÑALES DETECTADAS[/green]",
                border_style="dim green",
            )

        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia",  style="cyan",  min_width=15, no_wrap=True)
        tb.add_column("Potencia",    justify="right", min_width=11)
        tb.add_column("SNR",         justify="right", min_width=8)
        tb.add_column("BW",          justify="right", min_width=10)
        tb.add_column("Mod.",        min_width=10)
        tb.add_column("Duty",        justify="right", min_width=7)
        tb.add_column("t activo",    justify="right", min_width=9)
        tb.add_column("Banda",       min_width=16)

        for s in picos:
            if s.potencia > -50:
                pot_style = "bold red"
            elif s.potencia > -70:
                pot_style = "yellow"
            else:
                pot_style = "green"

            if s.banda:
                col = s.banda.get("color", "dim")
                b_str = f"[{col}]{s.banda['nombre']}[/{col}]"
            else:
                b_str = "—"

            if tracker:
                dc = tracker.duty_cycle(s.freq_mhz)
                ta = tracker.tiempo_activo(s.freq_mhz)
                dc_s = f"{dc*100:.0f}%"
                ta_s = f"{ta:.0f}s"
            else:
                dc_s = ta_s = "—"

            tb.add_row(
                f"{s.freq_mhz:.4f} MHz",
                Text(f"{s.potencia:.1f} dBm", style=pot_style),
                f"{s.snr_db:.1f} dB",
                f"{s.bw_khz:.2f} kHz",
                s.mod_hint or "—",
                dc_s,
                ta_s,
                b_str,
            )

        return Panel(
            tb,
            title=f"[bold green]SEÑALES DETECTADAS  [{len(picos)}][/bold green]",
            border_style="green",
            box=box.HEAVY_HEAD,
        )

    # Panel de stats en tiempo real
    def panel_stats(
        self,
        freq_mhz:   float,
        iteracion:  int,
        duracion:   int,
        elapsed:    float,
        n_picos:    int,
        n_sesion:   int,
        capturas:   int,
        piso:       float,
        ganancia:   float,
        agc_activo: bool,
    ) -> Panel:
        pct = min(1.0, elapsed / duracion)
        bw = 24
        done = int(pct * bw)
        bar = "█" * done + "░" * (bw - done)

        g = Table.grid(padding=(0, 2))
        g.add_column(style="dim green", justify="right", min_width=14)
        g.add_column(style="white",     min_width=14)

        g.add_row("Frecuencia",  f"{freq_mhz:.4f} MHz")
        g.add_row("Progreso",    f"[green][{bar}][/green] {pct*100:.0f}%")
        g.add_row("Tiempo",      f"{elapsed:.1f}s / {duracion}s")
        g.add_row("Iteración",   str(iteracion))
        g.add_row("Capturas",    str(capturas))
        g.add_row("Señales",     f"[yellow]{n_picos}[/yellow]")
        g.add_row("Sesión tot.", str(n_sesion))
        g.add_row("Piso RF",     f"{piso:.1f} dBm")
        g.add_row("Ganancia",    (
            f"[cyan]{ganancia:.1f} dB [AGC][/cyan]"
            if agc_activo else f"{ganancia:.1f} dB"
        ))

        return Panel(g, title="[bold green]ESCANEO[/bold green]",
                     border_style="green", box=box.ROUNDED)

    # Mapa de barrido con ocupación
    def mapa_barrido(self, resultados: list[dict[str, Any]]) -> Panel:
        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia",  style="cyan",  min_width=14, no_wrap=True)
        tb.add_column("Actividad",   min_width=22)
        tb.add_column("Pot. máx",    justify="right", min_width=10)
        tb.add_column("SNR",         justify="right", min_width=8)
        tb.add_column("Piso RF",     justify="right", min_width=10)
        tb.add_column("Ocup. %",     justify="right", min_width=8)
        tb.add_column("Banda",       min_width=18)

        for r in sorted(resultados, key=lambda x: x["snr"], reverse=True)[:35]:
            nivel = int(np.clip(r["snr"] / 35 * 22, 0, 22))
            barra = "█" * nivel + "·" * (22 - nivel)
            if r["snr"] > 25:
                sty = "bold red"
            elif r["snr"] > 15:
                sty = "yellow"
            elif r["snr"] > 8:
                sty = "green"
            else:
                sty = "dim"

            banda = r.get("banda")
            b_str = (
                f"[{banda['color']}]{banda['nombre']}[/{banda['color']}]"
                if banda else "—"
            )
            ocup = r.get("ocupacion_pct", 0)

            tb.add_row(
                f"{r['freq_mhz']:.3f} MHz",
                Text(barra, style=sty),
                Text(f"{r['pot_max']:.1f} dBm", style=sty),
                f"{r['snr']:.1f} dB",
                f"{r['piso']:.1f} dBm",
                f"{ocup:.0f}%",
                b_str,
            )

        return Panel(tb, title="[bold green]MAPA DE ACTIVIDAD RF[/bold green]",
                     border_style="green", box=box.HEAVY_HEAD)

    # Resumen de escaneo enriquecido
    def resumen_escaneo(
        self,
        freq_mhz:   float,
        picos:      list[Signal],
        duracion:   float,
        hw:         str,
        iteraciones: int,
        tracker:    SignalTracker | None = None,
        agc_ajustes: int = 0,
    ) -> Panel:
        snr_max = max((s.snr_db for s in picos), default=0.0)
        pot_max = max((s.potencia for s in picos), default=-999.0)
        bw_med = sum(s.bw_khz for s in picos) / len(picos) if picos else 0.0
        bandas = {s.banda["nombre"] for s in picos if s.banda}

        dc_max = 0.0
        if tracker and picos:
            dc_max = max(tracker.duty_cycle(s.freq_mhz) for s in picos)

        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim green", justify="right", min_width=22)
        g.add_column(style="white")
        g.add_row("Frecuencia",         f"{freq_mhz:.4f} MHz")
        g.add_row("Hardware",           hw)
        g.add_row("Duración real",      f"{duracion:.1f} s")
        g.add_row("Iteraciones FFT",    str(iteraciones))
        g.add_row("Señales persistentes", str(len(picos)))
        g.add_row("Potencia máxima",    f"{pot_max:.1f} dBm")
        g.add_row("SNR máximo",         f"{snr_max:.1f} dB")
        g.add_row("BW promedio",        f"{bw_med:.2f} kHz")
        g.add_row("Duty cycle máx.",    f"{dc_max*100:.0f}%")
        g.add_row("Ajustes AGC",        str(agc_ajustes))
        g.add_row("Bandas",             ", ".join(bandas) if bandas else "—")

        return Panel(g, title="[bold green]RESUMEN[/bold green]",
                     border_style="green")

# RF SCANNER — orquestador principal

class RFScanner:

    def __init__(self, sentinel: Any, config_path: str | None = None) -> None:
        self.sentinel = sentinel
        self.console: Console = getattr(sentinel, "console", Console())
        self.gp = getattr(sentinel, "gp",      None)

        self.cfg: RFConfig = load_config(config_path)

        self.dsp = DSPEngine(self.cfg.dsp, self.cfg.hardware.sample_rate)
        self.render = Renderizador(self.console, self.cfg)
        self.db = RFDatabase(self.cfg.storage.db_path)
        self.signal_db = SignalDB(self.cfg.storage)
        self.csv = CSVExporter(self.cfg.storage)
        self.sigmf = SigMFWriter(self.cfg.storage)
        self.recorder = RFRecorder(self)
        self._demod:   Demodulator | None = None

        self._backend: Any = None
        self._lock = threading.Lock()

        self._waterfall:       deque = deque(
            maxlen=self.cfg.display.waterfall_rows)
        self._senales_sesion:  deque = deque(maxlen=5_000)
        self._capturas_sesion: int = 0

        self._dc_remover = DCRemover()
        self._peak_hold = PeakHoldBuffer(avg_frames=8)
        self._tracker = SignalTracker()
        self._agc = AGCController()
        self._agc_activo = False
        self._agc_ajustes = 0

        self._setup_logging()
        self._conectar_hardware()

    # Logging
    def _setup_logging(self) -> None:
        lc = self.cfg.logging
        root = logging.getLogger("sentinel.rf")
        if root.handlers:
            return
        root.setLevel(getattr(logging, lc.level.upper(), logging.INFO))
        Path(lc.file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            lc.file,
            maxBytes=lc.max_mb * 1_048_576,
            backupCount=lc.backup_count,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        ))
        root.addHandler(fh)

    # Hardware
    def _conectar_hardware(self) -> None:
        from modules.rf.rf_source import open_backend
        hw = self.cfg.hardware
        self._backend = open_backend(
            freq_hz=hw.sample_rate,
            sample_rate=hw.sample_rate,
            gain=hw.gain_db,
            ppm=hw.ppm_correction,
            device_index=hw.device_index,
        )
        self.hw_nombre = self._backend.hw_name
        self._agc._current = hw.gain_db
        if hw.bias_tee:
            try:
                self._backend._sdr.set_bias_tee(True)
            except Exception:
                log.debug("bias_tee no soportado")
        self._print(
            f"[green][+] RF backend: {self.hw_nombre}[/green]"
            if "Mock" not in self.hw_nombre
            else f"[yellow][!] Sin hardware SDR físico — {self.hw_nombre}[/yellow]\n"
            "[dim]    pip install pyrtlsdr  |  https://www.rtl-sdr.com/[/dim]"
        )
        log.info("RF backend: %s", self.hw_nombre)

    # Propiedades
    @property
    def sample_rate(self) -> int:
        return self.cfg.hardware.sample_rate

    @property
    def hw_disponible(self) -> bool:
        return self._backend is not None

    @property
    def _hw_disponible(self) -> bool:
        return self._backend is not None

    # Configuración en caliente
    def configurar_ganancia(self, ganancia: object) -> None:
        if not self._hw_disponible:
            self._print("[red][!] Sin hardware conectado.[/red]")
            return
        try:
            val = "auto" if str(ganancia).lower(
            ) == "auto" else float(ganancia)
            self._backend.set_gain(val)
            if val != "auto":
                self.cfg.hardware.gain_db = float(val)
                self._agc._current = float(val)
            self._print(f"[green][+] Ganancia → {ganancia} dB[/green]")
            log.info("Ganancia ajustada a %s dB", ganancia)
        except Exception as exc:
            self._print(f"[red][!] Error ajustando ganancia: {exc}[/red]")

    def activar_agc(self, activar: bool = True) -> None:
        self._agc_activo = activar
        estado = "[green]activado[/green]" if activar else "[yellow]desactivado[/yellow]"
        self._print(f"[cyan][RF] AGC {estado}[/cyan]")

    def cargar_iq_archivo(self, path: str) -> None:
        from modules.rf.rf_source import file_backend
        self._backend = file_backend(path, loop=True)
        self.hw_nombre = self._backend.hw_name
        self._print(f"[cyan][RF] IQ cargado desde: {path}[/cyan]")

    def configurar_tcp(self, host: str, port: int = 1234, gain: int = 400) -> None:
        from modules.rf.rf_source import tcp_backend
        try:
            self._backend = tcp_backend(
                host, port,
                freq_hz=self.cfg.hardware.sample_rate,
                sample_rate=self.cfg.hardware.sample_rate,
                gain=gain,
            )
            self.hw_nombre = self._backend.hw_name
            self._print(
                f"[green][+] rtl_tcp conectado — {self.hw_nombre}[/green]")
        except Exception as exc:
            self._print(f"[red][!] TCP error: {exc}[/red]")

    def agregar_senal_mock(
        self,
        freq_offset_hz: float,
        power_dbm:      float = -60.0,
        mode:           str = "tone",
        bw_hz:          float = 12_500.0,
    ) -> None:
        from modules.rf.rf_source import _MockBackend
        from modules.rf.rf_mock import SyntheticSignal
        if not isinstance(self._backend, _MockBackend):
            from modules.rf.rf_source import mock_backend
            self._backend = mock_backend(self.cfg.hardware.sample_rate)
            self.hw_nombre = self._backend.hw_name
        self._backend._mock.add_signal(SyntheticSignal(
            freq_offset=freq_offset_hz, power_dbm=power_dbm,
            mode=mode, bw_hz=bw_hz,
        ))

    # Captura IQ
    def _capturar(self, freq_hz: float) -> np.ndarray | None:
        if not self._hw_disponible:
            self._print("[red][!] Sin hardware SDR disponible.[/red]")
            return None
        with self._lock:
            try:
                self._backend.tune(freq_hz)
                iq = self._backend.read_raw(self.cfg.dsp.samples_per_read)
                if iq is not None:
                    self._capturas_sesion += 1
                return iq
            except Exception as exc:
                self._print(
                    f"[red][!] Captura @ {freq_hz/1e6:.3f} MHz: {exc}[/red]")
                log.error("Captura IQ @ %.3f MHz: %s", freq_hz / 1e6, exc)
                return None

    def _verificar_rango_rtl(self, freq_mhz: float) -> bool:
        from modules.rf.rf_source import _RTLSDRBackend
        if isinstance(self._backend, _RTLSDRBackend):
            if not (_RTL_FREQ_MIN <= freq_mhz <= _RTL_FREQ_MAX):
                self._print(
                    f"[yellow][!] {freq_mhz:.3f} MHz fuera de rango RTL-SDR. Omitida.[/yellow]"
                )
                return False
        return True

    def _get_demod(self) -> Demodulator:
        if self._demod is None:
            self._demod = Demodulator(self.cfg.demod, self.sample_rate)
        return self._demod

    # Pipeline DSP — captura → suprimir DC → PSD → peaks
    def _procesar_muestra(
        self, freq_hz: float
    ) -> tuple[np.ndarray, np.ndarray, list[Signal], float] | None:
        muestras = self._capturar(freq_hz)
        if muestras is None:
            return None

        freqs_hz, psd_raw = self.dsp.compute_psd(muestras)
        psd_dbm = self._dc_remover.remove(psd_raw)
        self._peak_hold.update(psd_dbm)
        picos_raw = self.dsp.detect_peaks(freqs_hz, psd_dbm, freq_hz)
        picos = self._tracker.update(picos_raw)
        piso = float(np.median(psd_dbm))

        return freqs_hz, psd_dbm, picos, piso

    # API PÚBLICA

    def escanear_frecuencia(self, freq_mhz: float, duracion: int = 10) -> None:
        if not self._hw_disponible:
            self._print("[red][!] Sin hardware SDR disponible.[/red]")
            return

        freq_hz = freq_mhz * 1e6
        banda = identify_band(freq_mhz)

        self._peak_hold.reset()
        self._tracker.reset()
        self._agc_ajustes = 0

        self._print()
        if banda:
            col = banda.get("color", "white")
            self._print(
                f"[bold green][RF] {freq_mhz:.4f} MHz — "
                f"[{col}]{banda['nombre']}[/{col}]  "
                f"[dim]{banda['desc']}[/dim][/bold green]"
            )
        else:
            self._print(
                f"[bold green][RF] {freq_mhz:.4f} MHz — Sin clasificar[/bold green]")

        self._print(
            f"[dim]  HW: {self.hw_nombre}  BW: {self.sample_rate/1e6:.3f} MHz  "
            f"FFT: {self.cfg.dsp.fft_size}pts  Res: {self.dsp.freq_resolution_khz:.2f} kHz/bin  "
            f"AGC: {'ON' if self._agc_activo else 'OFF'}  Ctrl+C para detener[/dim]\n"
        )

        escaneo_id = self.db.iniciar_escaneo(
            freq_mhz=freq_mhz, hardware=self.hw_nombre,
            sample_rate=self.sample_rate, fft_size=self.cfg.dsp.fft_size,
        )
        self.signal_db.open_session(
            hw_type=self.hw_nombre, sample_rate=self.sample_rate,
            notes=f"escanear {freq_mhz:.4f} MHz {duracion}s",
        )

        inicio = time.monotonic()
        iteracion = 0
        todos_picos:  list[Signal] = []
        demod = self._get_demod() if self.cfg.demod.mode != "none" else None
        piso_actual = -99.0
        picos_actuales: list[Signal] = []
        freqs_hz = psd_dbm = np.array([])

        def _build_view() -> Group:
            return Group(
                self.render.espectro(
                    freqs_hz, psd_dbm, freq_mhz, picos_actuales,
                    self.sample_rate, self.hw_nombre,
                    peak_hold=self._peak_hold.peak_hold(),
                    avg_psd=self._peak_hold.average(),
                ),
                self.render.waterfall(self._waterfall, freq_mhz),
                self.render.tabla_picos(picos_actuales, self._tracker),
                self.render.panel_stats(
                    freq_mhz, iteracion, duracion,
                    time.monotonic() - inicio,
                    len(picos_actuales), len(self._senales_sesion),
                    self._capturas_sesion, piso_actual,
                    self._agc._current, self._agc_activo,
                ),
            )

        try:
            with Live(
                console=self.console,
                refresh_per_second=4,
                screen=False,
            ) as live:
                while time.monotonic() - inicio < duracion:
                    resultado = self._procesar_muestra(freq_hz)
                    if resultado is None:
                        break

                    freqs_hz, psd_dbm, picos_actuales, piso_actual = resultado

                    todos_picos.extend(picos_actuales)
                    self._senales_sesion.extend(picos_actuales)
                    self._waterfall.appendleft(psd_dbm.copy())

                    if picos_actuales:
                        self._guardar_senales_db(picos_actuales, escaneo_id)

                    if self._agc_activo:
                        nueva = self._agc.step(psd_dbm, self._backend,
                                               self.cfg.hardware.gain_db)
                        if nueva is not None:
                            self._agc_ajustes += 1

                    if demod:
                        try:
                            audio = demod.demodulate(
                                self._capturar(freq_hz) or np.array([])
                            )
                            if audio is not None and len(audio) > 0:
                                if (not picos_actuales or
                                        picos_actuales[0].snr_db >= self.cfg.demod.squelch_db):
                                    demod.play(audio)
                                if self.cfg.demod.save_audio:
                                    ts_a = datetime.now(
                                        timezone.utc).strftime("%H%M%S")
                                    demod.save_wav(
                                        audio,
                                        str(self.cfg.storage.iq_path /
                                            f"audio_{freq_mhz:.3f}MHz_{ts_a}.wav")
                                    )
                        except Exception as exc:
                            log.debug("Demod: %s", exc)

                    live.update(_build_view())
                    iteracion += 1

        except KeyboardInterrupt:
            self._print("\n[yellow][!] Escaneo interrumpido.[/yellow]")

        duracion_real = time.monotonic() - inicio
        self.db.finalizar_escaneo(escaneo_id, duracion_real)
        self.signal_db.close_session()

        self.console.print()
        self.console.print(self.render.resumen_escaneo(
            freq_mhz, todos_picos, duracion_real,
            self.hw_nombre, iteracion,
            self._tracker, self._agc_ajustes,
        ))

        if todos_picos:
            self._exportar_csv_picos(todos_picos, freq_mhz)
        self._registrar_evidencia(freq_mhz, todos_picos, duracion_real)

        if self.cfg.storage.db_retention_days > 0:
            self.db.limpiar_antiguas(self.cfg.storage.db_retention_days)
            self.signal_db.purge_old(self.cfg.storage.db_retention_days)

        log.info("Escaneo %.3f MHz — %d señales en %.0fs  hw=%s",
                 freq_mhz, len(todos_picos), duracion_real, self.hw_nombre)

    def barrido_espectro(
        self,
        freq_ini_mhz: float,
        freq_fin_mhz: float,
        paso_mhz:     float = 1.0,
    ) -> None:
        if not self._hw_disponible:
            self._print("[red][!] Sin hardware SDR disponible.[/red]")
            return

        freqs = np.arange(freq_ini_mhz, freq_fin_mhz +
                          paso_mhz * 0.5, paso_mhz)
        self._print(
            f"\n[bold green][RF] Barrido: "
            f"{freq_ini_mhz:.1f} → {freq_fin_mhz:.1f} MHz  "
            f"paso={paso_mhz:.3f} MHz  {len(freqs)} puntos[/bold green]\n"
        )

        resultados: list[dict[str, Any]] = []
        ocup_muestras: dict[float, list[float]] = defaultdict(list)

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Barriendo...", total=len(freqs))

            try:
                for freq in freqs:
                    if not self._verificar_rango_rtl(float(freq)):
                        progress.advance(task)
                        continue

                    resultado = self._procesar_muestra(float(freq) * 1e6)
                    if resultado is None:
                        break

                    _, psd_dbm, _, _ = resultado
                    piso = float(np.median(psd_dbm))
                    pot_max = float(np.max(psd_dbm))
                    snr = pot_max - piso
                    banda = identify_band(float(freq))

                    for _ in range(3):
                        r2 = self._procesar_muestra(float(freq) * 1e6)
                        if r2:
                            _, p2, _, _ = r2
                            ocup_muestras[round(float(freq), 3)].append(
                                float(np.max(p2)) - piso)

                    muestras_ocup = ocup_muestras.get(
                        round(float(freq), 3), [])
                    ocup_pct = (
                        sum(1 for v in muestras_ocup if v >=
                            self.cfg.dsp.snr_threshold)
                        / len(muestras_ocup) * 100
                        if muestras_ocup else 0.0
                    )

                    resultados.append({
                        "freq_mhz":      round(float(freq), 3),
                        "pot_max":       round(pot_max, 1),
                        "piso":          round(piso, 1),
                        "snr":           round(snr, 1),
                        "banda":         banda,
                        "ocupacion_pct": round(ocup_pct, 1),
                    })

                    b_nom = banda["nombre"] if banda else "—"
                    progress.update(
                        task,
                        advance=1,
                        description=f"[bold green]{freq:.2f} MHz  {snr:+.0f} dB SNR  {b_nom[:18]}",
                    )

            except KeyboardInterrupt:
                self._print("\n[yellow][!] Barrido interrumpido.[/yellow]")

        if resultados:
            self.console.print(self.render.mapa_barrido(resultados))
            self._exportar_csv_barrido(resultados, freq_ini_mhz, freq_fin_mhz)
            self.db.insertar_barrido(
                freq_ini=freq_ini_mhz, freq_fin=freq_fin_mhz,
                paso_mhz=paso_mhz, hardware=self.hw_nombre,
                resultados=resultados,
            )
            activas = sum(1 for r in resultados
                          if r["snr"] >= self.cfg.dsp.snr_threshold)
            self.signal_db.insert_sweep(
                freq_ini=freq_ini_mhz, freq_fin=freq_fin_mhz,
                paso=paso_mhz, puntos=len(resultados), activas=activas,
            )
            if self.gp:
                try:
                    self.gp.registrar_evidencia(
                        "rf_sweep",
                        f"Barrido RF {freq_ini_mhz:.0f}–{freq_fin_mhz:.0f} MHz: "
                        f"{len(resultados)} puntos",
                        {"ini_mhz": freq_ini_mhz, "fin_mhz": freq_fin_mhz,
                         "paso_mhz": paso_mhz, "puntos": len(resultados),
                         "hardware": self.hw_nombre},
                    )
                except Exception as exc:
                    log.warning("gp barrido: %s", exc)

        log.info("Barrido %.1f–%.1f MHz paso=%.3f — %d puntos hw=%s",
                 freq_ini_mhz, freq_fin_mhz, paso_mhz,
                 len(resultados), self.hw_nombre)

    def escaneo_bandas_conocidas(self) -> None:
        if not self._hw_disponible:
            self._print("[red][!] Sin hardware SDR disponible.[/red]")
            return

        todas = [
            {
                "nombre": n, "tipo": t, "desc": d,
                "color": COLORES_TIPO.get(t, "dim"),
                "freq_min": fmin, "freq_max": fmax,
            }
            for fmin, fmax, n, t, d, _ in BANDAS_RF
        ]

        self._print(
            f"\n[bold green][RF] Escaneo de {len(todas)} bandas conocidas...[/bold green]\n"
        )
        resultados: list[dict[str, Any]] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold green]{task.description}"),
            BarColumn(bar_width=44),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Escaneando bandas...", total=len(todas))
            try:
                for b in todas:
                    freq = (b["freq_min"] + b["freq_max"]) / 2.0
                    if not self._verificar_rango_rtl(freq):
                        progress.advance(task)
                        continue

                    resultado = self._procesar_muestra(freq * 1e6)
                    if resultado is None:
                        break

                    _, psd_dbm, _, _ = resultado
                    piso = float(np.median(psd_dbm))
                    pot_max = float(np.max(psd_dbm))
                    snr = pot_max - piso

                    resultados.append({
                        "freq_mhz":      round(freq, 3),
                        "pot_max":       round(pot_max, 1),
                        "piso":          round(piso, 1),
                        "snr":           round(snr, 1),
                        "banda":         b,
                        "ocupacion_pct": 0.0,
                    })
                    progress.update(
                        task, advance=1,
                        description=f"[bold green]{b['nombre'][:26]:<26} {freq:>9.3f} MHz",
                    )

            except KeyboardInterrupt:
                self._print(
                    "\n[yellow][!] Escaneo de bandas interrumpido.[/yellow]")

        if resultados:
            self.console.print(self.render.mapa_barrido(resultados))
            self._exportar_csv_barrido(resultados, 0.0, 0.0)
            if self.gp:
                try:
                    self.gp.registrar_evidencia(
                        "rf_bands_scan",
                        f"Escaneo bandas: {len(resultados)} mediciones",
                        {"hardware": self.hw_nombre,
                            "bandas": len(resultados)},
                    )
                except Exception as exc:
                    log.warning("gp bandas: %s", exc)

        log.info("Escaneo bandas: %d mediciones hw=%s",
                 len(resultados), self.hw_nombre)

    # Consultas DB
    def estadisticas_db(self) -> None:
        stats = self.db.estadisticas()
        st2 = self.signal_db.stats()
        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim green", justify="right", min_width=22)
        g.add_column(style="white")
        g.add_row("[bold]RFDatabase[/bold]", "")
        for k, v in stats.items():
            g.add_row(k.replace("_", " ").title(),
                      str(v) if v is not None else "—")
        g.add_row("", "")
        g.add_row("[bold]SignalDB[/bold]", "")
        for k, v in st2.items():
            g.add_row(k.replace("_", " ").title(),
                      str(v) if v is not None else "—")
        self.console.print(Panel(g, title="[bold green]ESTADÍSTICAS DB[/bold green]",
                                 border_style="green"))

    def top_senales(self, n: int = 10) -> None:
        rows = self.db.top_senales(n)
        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia", style="cyan",  min_width=14)
        tb.add_column("Potencia",   justify="right", min_width=11)
        tb.add_column("SNR",        justify="right", min_width=8)
        tb.add_column("BW",         justify="right", min_width=9)
        tb.add_column("Mod.",       min_width=10)
        tb.add_column("Banda",      min_width=16)
        tb.add_column("Timestamp",  style="dim", min_width=22)
        for r in rows:
            tb.add_row(
                f"{r['freq_mhz']:.4f} MHz",
                f"{r['potencia']:.1f} dBm",
                f"{r['snr_db']:.1f} dB",
                f"{r.get('bw_khz', 0):.2f} kHz",
                r.get("mod_hint") or "—",
                r.get("banda") or "—",
                r.get("timestamp", "")[:19],
            )
        self.console.print(Panel(tb,
                                 title=f"[bold green]TOP {n} SEÑALES[/bold green]",
                                 border_style="green"))

    def frecuencias_activas(self, snr_min: float = 10.0, horas: int = 24) -> None:
        rows = self.db.frecuencias_activas(snr_min=snr_min, horas=horas)
        if not rows:
            self._print(
                f"[dim]Sin frecuencias activas en las últimas {horas}h "
                f"con SNR ≥ {snr_min} dB.[/dim]"
            )
            return
        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia",   style="cyan",  min_width=14)
        tb.add_column("Detecciones",  justify="right", min_width=12)
        tb.add_column("SNR máx",      justify="right", min_width=9)
        tb.add_column("Pot. media",   justify="right", min_width=11)
        tb.add_column("Banda",        min_width=16)
        for r in rows:
            tb.add_row(
                f"{r['freq_mhz']:.3f} MHz",
                str(r["detecciones"]),
                f"{r['snr_max']:.1f} dB",
                f"{r.get('pot_media', 0):.1f} dBm",
                r.get("banda") or "—",
            )
        self.console.print(Panel(tb,
                                 title=(f"[bold green]FRECUENCIAS ACTIVAS "
                                        f"(últimas {horas}h  SNR≥{snr_min}dB)[/bold green]"),
                                 border_style="green"))

    # Grabación / Reproducción IQ
    def grabar_iq(self, freq_mhz: float, duracion: int = 10,
                  formato: str = "sigmf") -> None:
        if not self._hw_disponible:
            self._print("[red][!] Sin hardware SDR disponible.[/red]")
            return

        freq_hz = freq_mhz * 1e6

        if formato == "sigmf":
            recording = self.sigmf.open(
                freq_hz=freq_hz, sample_rate=self.sample_rate,
                hw_type=self.hw_nombre,
                notes=f"Grabacion campo {freq_mhz:.3f} MHz",
            )
            self._print(
                f"[bold cyan][RF] Grabando {freq_mhz:.3f} MHz · "
                f"{duracion}s · SigMF streaming[/bold cyan]"
            )
            inicio = time.monotonic()
            muestras_total = 0

            with Progress(
                SpinnerColumn(),
                BarColumn(bar_width=30),
                TextColumn("[bold cyan]{task.description}"),
                TimeElapsedColumn(),
                console=self.console,
                transient=True,
            ) as progress:
                task = progress.add_task(
                    f"Grabando {freq_mhz:.3f} MHz", total=duracion)
                with recording:
                    while time.monotonic() - inicio < duracion:
                        bloque = self._capturar(freq_hz)
                        if bloque is None:
                            break
                        recording.write(bloque)
                        muestras_total += len(bloque)
                        elapsed = time.monotonic() - inicio
                        size_mb = recording.data_path.stat().st_size / 1e6
                        progress.update(
                            task, completed=elapsed,
                            description=f"{freq_mhz:.3f} MHz  "
                            f"{muestras_total:,} muestras  "
                            f"{size_mb:.1f} MB",
                        )

            size_mb = recording.data_path.stat().st_size / 1e6
            dur_real = muestras_total / self.sample_rate
            self.signal_db.register_iq(
                freq_mhz=freq_mhz, duration_s=dur_real,
                sample_rate=self.sample_rate, hw_type=self.hw_nombre,
                filename=str(recording.data_path), size_mb=round(size_mb, 2),
            )
            self._print(
                f"[green][+] IQ grabado → {recording.data_path.name}  "
                f"({dur_real:.1f}s  {size_mb:.1f} MB)[/green]"
            )
            log.info("IQ grabado: %s  %.1fs  %.1fMB",
                     recording.data_path.name, dur_real, size_mb)
        else:
            self.recorder.grabar(
                freq_mhz=freq_mhz,
                duracion_seg=duracion,
                sample_rate=self.sample_rate,
                formato=formato,
            )

    def reproducir_iq(self, archivo: str, modo: str = "wfm") -> None:
        self.recorder.reproducir(
            archivo, modo=modo, sample_rate=self.sample_rate)

    # Estado
    def estado(self) -> None:
        stats = self.db.estadisticas()
        st2 = self.signal_db.stats()
        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim green", justify="right", min_width=24)
        g.add_column(style="white")
        g.add_row("Hardware",           self.hw_nombre)
        g.add_row("Backend tipo",       type(
            self._backend).__name__ if self._backend else "N/A")
        g.add_row("Sample rate",        f"{self.sample_rate/1e6:.3f} MHz")
        g.add_row("Ganancia",           f"{self._agc._current:.1f} dB")
        g.add_row("AGC",
                  "[green]ON[/green]" if self._agc_activo else "[dim]OFF[/dim]")
        g.add_row("PPM corrección",     str(self.cfg.hardware.ppm_correction))
        g.add_row("Tamaño FFT",         str(self.cfg.dsp.fft_size))
        g.add_row("Ventana DSP",        self.cfg.dsp.window)
        g.add_row("SNR umbral",         f"{self.cfg.dsp.snr_threshold} dB")
        g.add_row("Resolución",
                  f"{self.dsp.freq_resolution_khz:.2f} kHz/bin")
        g.add_row("Persistencia mín.",  f"{SignalTracker.MIN_FRAMES} frames")
        g.add_row("Modo demod",         self.cfg.demod.mode)
        g.add_row("DB path",            str(self.cfg.storage.db_path))
        g.add_row("Capturas sesión",    str(self._capturas_sesion))
        g.add_row("Señales sesión",     str(len(self._senales_sesion)))
        g.add_row("─" * 22,             "─" * 18)
        g.add_row("Señales DB total",   str(stats.get("total_senales", 0)))
        g.add_row("Escaneos DB",        str(stats.get("escaneos", 0)))
        g.add_row("Sesiones SignalDB",  str(st2.get("sessions", 0)))
        g.add_row("Grabaciones IQ",     str(st2.get("iq_files", 0)))
        g.add_row("Tamaño DB",          f"{st2.get('db_size_mb', 0):.2f} MB")
        self.console.print(Panel(g, title="[bold green]ESTADO RF SCANNER[/bold green]",
                                 border_style="green"))

    # Menú interactivo
    def menu(self) -> None:
        self.console.print()
        self.console.print(Panel(
            "[bold green]RF SCANNER — " + self.hw_nombre + "[/bold green]\n\n"
            " [green][1][/green]  Escanear frecuencia específica\n"
            " [green][2][/green]  Barrido de espectro (rango)\n"
            " [green][3][/green]  Escaneo de bandas conocidas\n"
            " [green][4][/green]  Ajustar ganancia\n"
            " [green][5][/green]  Activar / desactivar AGC\n"
            " [green][6][/green]  Ver señales de esta sesión\n"
            " [green][7][/green]  Estado del hardware\n"
            " [green][8][/green]  Grabar IQ\n"
            " [green][9][/green]  Reproducir IQ\n"
            " [green][10][/green] Frecuencias activas (DB)\n"
            " [green][11][/green] Top señales (DB)",
            border_style="green",
            title="[bold green]RF SCANNER[/bold green]",
        ))

        opt = self.console.input(
            "[bold green][?] Opción: [/bold green]").strip()

        if opt == "1":
            freq_s = self.console.input(
                "[bold cyan][?] Frecuencia (MHz): [/bold cyan]").strip()
            dur_s = self.console.input(
                "[bold cyan][?] Duración segundos [10]: [/bold cyan]").strip()
            try:
                self.escanear_frecuencia(
                    float(freq_s), int(dur_s) if dur_s else 10)
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "2":
            ini_s = self.console.input(
                "[bold cyan][?] Freq. inicial (MHz): [/bold cyan]").strip()
            fin_s = self.console.input(
                "[bold cyan][?] Freq. final (MHz): [/bold cyan]").strip()
            paso_s = self.console.input(
                "[bold cyan][?] Paso MHz [1.0]: [/bold cyan]").strip()
            try:
                self.barrido_espectro(float(ini_s), float(fin_s),
                                      float(paso_s) if paso_s else 1.0)
            except ValueError:
                self._print("[red][!] Valores inválidos.[/red]")

        elif opt == "3":
            self.escaneo_bandas_conocidas()

        elif opt == "4":
            gan_s = self.console.input(
                "[bold cyan][?] Ganancia dB (0-49.6, 'auto'): [/bold cyan]"
            ).strip()
            try:
                self.configurar_ganancia(
                    "auto" if gan_s.lower() == "auto" else float(gan_s)
                )
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "5":
            self.activar_agc(not self._agc_activo)

        elif opt == "6":
            self.console.print(
                self.render.tabla_picos(
                    list(self._senales_sesion)[-50:], self._tracker)
            )

        elif opt == "7":
            self.estado()

        elif opt == "8":
            freq_s = self.console.input(
                "[bold cyan][?] Frecuencia a grabar (MHz): [/bold cyan]").strip()
            dur_s = self.console.input(
                "[bold cyan][?] Duración segundos [10]: [/bold cyan]").strip()
            fmt_s = self.console.input(
                "[bold cyan][?] Formato (sigmf/raw) [sigmf]: [/bold cyan]").strip() or "sigmf"
            try:
                self.grabar_iq(float(freq_s), int(
                    dur_s) if dur_s else 10, fmt_s)
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "9":
            arch = self.console.input(
                "[bold cyan][?] Archivo IQ (ruta): [/bold cyan]").strip()
            modo = self.console.input(
                "[bold cyan][?] Modo demod (wfm/nfm/am/usb/lsb) [wfm]: [/bold cyan]").strip() or "wfm"
            self.reproducir_iq(arch, modo)

        elif opt == "10":
            snr_s = self.console.input(
                "[bold cyan][?] SNR mínimo dB [10]: [/bold cyan]").strip()
            hrs_s = self.console.input(
                "[bold cyan][?] Horas hacia atrás [24]: [/bold cyan]").strip()
            try:
                self.frecuencias_activas(
                    snr_min=float(snr_s) if snr_s else 10.0,
                    horas=int(hrs_s) if hrs_s else 24,
                )
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        elif opt == "11":
            n_s = self.console.input(
                "[bold cyan][?] Cuántas señales [10]: [/bold cyan]").strip()
            try:
                self.top_senales(int(n_s) if n_s else 10)
            except ValueError:
                self._print("[red][!] Valor inválido.[/red]")

        else:
            self._print("[yellow][!] Opción no reconocida.[/yellow]")

    # Internos
    def _guardar_senales_db(self, senales: list[Signal], escaneo_id: int) -> None:
        rows = [dict(s.to_dict(), banda=s.banda) for s in senales]
        self.db.insertar_senales_bulk(rows, escaneo_id)
        self.signal_db.insert_signals_batch(senales)

    def _exportar_csv_picos(self, picos: list[Signal], freq_mhz: float) -> None:
        try:
            fn = self.csv.export_signals(picos, freq_mhz, self.hw_nombre)
            self._print(f"[green][+] CSV → {fn}[/green]")
        except OSError as exc:
            self._print(f"[red][!] Error CSV: {exc}[/red]")

    def _exportar_csv_barrido(self, resultados: list[dict], freq_ini: float, freq_fin: float) -> None:
        try:
            fn = self.csv.export_sweep(resultados, freq_ini, freq_fin)
            self._print(f"[green][+] CSV barrido → {fn}[/green]")
        except OSError as exc:
            self._print(f"[red][!] Error CSV: {exc}[/red]")

    def _registrar_evidencia(self, freq_mhz: float,
                             picos: list[Signal], duracion: float) -> None:
        if not self.gp or not picos:
            return
        try:
            self.gp.registrar_evidencia(
                "rf_scan",
                f"Escaneo RF {freq_mhz:.3f} MHz: {len(picos)} señales",
                {
                    "freq_mhz":   freq_mhz,
                    "duracion_s": round(duracion, 1),
                    "hardware":   self.hw_nombre,
                    "senales":    [s.to_dict() for s in picos],
                },
            )
            for s in picos:
                if not s.banda and s.snr_db > 20:
                    self.gp.registrar_hallazgo(
                        "MEDIO",
                        f"Señal no clasificada en {s.freq_mhz:.3f} MHz",
                        f"Potencia: {s.potencia:.1f} dBm  SNR: {s.snr_db:.1f} dB  "
                        f"BW: {s.bw_khz:.2f} kHz  "
                        f"Duty: {self._tracker.duty_cycle(s.freq_mhz)*100:.0f}%",
                        "Investigar origen. Posible dispositivo ilícito.",
                    )
        except Exception as exc:
            log.warning("registrar_evidencia: %s", exc)

    # Ciclo de vida
    def cerrar(self) -> None:
        if self._demod:
            try:
                self._demod.stop_audio()
            except Exception:
                pass
        if self._backend is not None:
            try:
                self._backend.close()
                self._print("[green][+] SDR desconectado.[/green]")
                log.info("RF backend cerrado")
            except Exception as exc:
                self._print(f"[yellow][!] Error cerrando RF: {exc}[/yellow]")
            finally:
                self._backend = None
        for db in (self.signal_db, self.db):
            try:
                getattr(db, "close_session", lambda: None)()
                getattr(db, "cerrar", lambda: None)()
            except Exception:
                pass

    def __enter__(self) -> RFScanner:
        return self

    def __exit__(self, *_) -> None:
        self.cerrar()

    def _print(self, msg: str = "") -> None:
        if self.console:
            self.console.print(msg)
        else:
            import re
            print(re.sub(r"\[/?[^\]]*\]", "", msg))
