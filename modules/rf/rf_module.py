from __future__ import annotations

import csv
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── numpy ────────────────────────────────────────────────────────────
try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False
    np = None  # type: ignore

# ── config.py ────────────────────────────────────────────────────────
try:
    from core.config import Config as RFConfig, DemodConfig, DspConfig
    _RF_CONFIG_OK = True
except ImportError:
    _RF_CONFIG_OK = False
    RFConfig = None  # type: ignore

# ── logger.py ────────────────────────────────────────────────────────
try:
    from core.logger import get_logger as _rf_get_logger, setup_logger as _rf_setup_logger
    _RF_LOGGER_OK = True
except ImportError:
    _RF_LOGGER_OK = False

    def _rf_get_logger(name): return logging.getLogger(
        name)       # type: ignore
    def _rf_setup_logger(
        **kw): return logging.getLogger("rfscanner")  # type: ignore

# ── bands.py ─────────────────────────────────────────────────────────
try:
    from .bands import BANDAS_RF, COLORES_TIPO, bands_in_range, identify_band, tactical_bands
    _BANDS_OK = True
except ImportError:
    _BANDS_OK = False
    BANDAS_RF = []
    COLORES_TIPO = {}
    def identify_band(freq_mhz): return None        # type: ignore
    def bands_in_range(a, b): return []             # type: ignore
    def tactical_bands(): return []                 # type: ignore

# ── dsp.py ───────────────────────────────────────────────────────────
try:
    from .dsp import DSPEngine, Signal as RFSignal
    _DSP_OK = True
except ImportError:
    _DSP_OK = False
    DSPEngine = None    # type: ignore
    RFSignal = None    # type: ignore

# ── rf_demod.py ──────────────────────────────────────────────────────
try:
    from .rf_demod import Demodulator
    _DEMOD_OK = True
except ImportError:
    _DEMOD_OK = False
    Demodulator = None  # type: ignore

# ── rf_mock.py ───────────────────────────────────────────────────────
try:
    from .rf_mock import MockSDRManager, SyntheticSignal, generate_fixture
    _MOCK_OK = True
except ImportError:
    _MOCK_OK = False
    MockSDRManager = None  # type: ignore
    SyntheticSignal = None  # type: ignore
    generate_fixture = None  # type: ignore

# ── rf_database.py ───────────────────────────────────────────────────
try:
    from .rf_database import RFDatabase
    _RFDB_OK = True
except ImportError:
    _RFDB_OK = False
    RFDatabase = None   # type: ignore

# ── RFScanner.py ─────────────────────────────────────────────────────
try:
    from .RFScanner import RFScanner, MotorDSP, Renderizador, ConfigSDR, BANDAS
    _RFSCANNER_OK = True
except ImportError:
    _RFSCANNER_OK = False
    RFScanner = None  # type: ignore
    MotorDSP = None  # type: ignore
    Renderizador = None  # type: ignore
    ConfigSDR = None  # type: ignore
    BANDAS = []


class RFModuleIntegrado:
    WATERFALL_CHARS = " ·░▒▓█"
    DB_MIN = -110.0
    DB_MAX = -20.0
    WATERFALL_ANCHO = 64
    WATERFALL_ALTO = 14
    UMBRAL_MARGEN_DB = 12.0
    UMBRAL_ABS_DBM = -85.0
    PICOS_MAX = 20
    PROMEDIO_N = 3
    WATERFALL_ROWS = 15
    SAMPLES_N = 512 * 1024
    EXPORT_PATH = Path("data/evidence/rf")

    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.console = getattr(sentinel, "console", Console())
        self.log_s = getattr(sentinel, "log",     None)
        self.gp = getattr(sentinel, "gp",      None)

        self._log = _rf_get_logger("rfscanner.main")

        # Configuración RF
        self.cfg: Optional[RFConfig] = None
        if _RF_CONFIG_OK and RFConfig:
            try:
                self.cfg = RFConfig()
            except Exception as e:
                self._log.warning(f"Config RF: usando defaults — {e}")

        self.sample_rate = self.cfg.hardware.sample_rate if self.cfg else 2_048_000
        self.fft_size = self.cfg.dsp.fft_size if self.cfg else 2048
        self.gain = self.cfg.hardware.gain if self.cfg else 40.0

        # Subsistemas
        self._scanner:       Optional[RFScanner] = None
        self._mock:          Optional[MockSDRManager] = None
        self._dsp_avanzado:  Optional[DSPEngine] = None
        self._dsp_basico:    Optional[MotorDSP] = None
        self._demod:         Optional[Demodulator] = None
        self._db:            Optional[RFDatabase] = None
        self._render:        Optional[Renderizador] = None

        self.hw_nombre = "Sin inicializar"
        self.hw_disponible = False

        self._waterfall = deque(maxlen=self.WATERFALL_ROWS)
        self._senales_sesion:  list = []
        self._capturas_sesion = 0
        self._lock = threading.Lock()

        self._inicializar_subsistemas()

    # ── Inicialización ────────────────────────────────────────────────

    def _inicializar_subsistemas(self):
        self.EXPORT_PATH.mkdir(parents=True, exist_ok=True)
        Path("data/evidence/rf/iq").mkdir(parents=True, exist_ok=True)

        if _RF_LOGGER_OK:
            try:
                _rf_setup_logger(
                    level="INFO", log_file="data/logs/rfscanner.log")
            except Exception:
                pass

        if _DSP_OK and DSPEngine and _NP_OK:
            try:
                from core.config import DspConfig as _DC
                dsp_cfg = self.cfg.dsp if self.cfg else _DC()
                self._dsp_avanzado = DSPEngine(dsp_cfg, self.sample_rate)
            except Exception as e:
                self._log.warning(f"DSPEngine: {e}")

        if _RFSCANNER_OK and MotorDSP and _NP_OK:
            try:
                self._dsp_basico = MotorDSP(
                    fft_size=self.fft_size, ventana="blackman")
            except Exception as e:
                self._log.warning(f"MotorDSP: {e}")

        if _DEMOD_OK and Demodulator and _NP_OK:
            try:
                from core.config import DemodConfig as _DemodC
                demod_cfg = self.cfg.demod if self.cfg else _DemodC()
                self._demod = Demodulator(demod_cfg, self.sample_rate)
            except Exception as e:
                self._log.warning(f"Demodulator: {e}")

        if _RFDB_OK and RFDatabase:
            try:
                db_path = Path("data/evidence/rf/signals.db")
                self._db = RFDatabase(db_path)
            except Exception as e:
                self._log.warning(f"RFDatabase: {e}")

        if _RFSCANNER_OK and Renderizador:
            try:
                self._render = Renderizador(self.console)
            except Exception as e:
                self._log.warning(f"Renderizador: {e}")

        self._conectar_hardware()

    def _conectar_hardware(self):
        if _RFSCANNER_OK and RFScanner:
            try:
                self._scanner = RFScanner(self.sentinel)
                if self._scanner.sdr is not None:
                    self.hw_nombre = self._scanner.hw_nombre
                    self.hw_disponible = True
                    self._print(
                        f"[green][+] RF Hardware real — {self.hw_nombre}[/green]")
                    return
                self._scanner = None
            except Exception as e:
                self._log.warning(f"RFScanner HW: {e}")
                self._scanner = None

        if _MOCK_OK and MockSDRManager and _NP_OK:
            try:
                self._mock = MockSDRManager(
                    sample_rate=self.sample_rate, noise_floor_dbm=-100.0)
                if SyntheticSignal:
                    self._mock.add_signal(SyntheticSignal(
                        freq_offset=0,    power_dbm=-60, mode="nfm"))
                    self._mock.add_signal(SyntheticSignal(
                        freq_offset=50e3, power_dbm=-70, mode="wfm"))
                    self._mock.add_signal(SyntheticSignal(
                        freq_offset=-30e3, power_dbm=-75, mode="am"))
                self.hw_nombre = "MockSDR (sin hardware real)"
                self.hw_disponible = True
                self._print(
                    "[yellow][!] Sin hardware SDR real — usando MockSDR (señales sintéticas).[/yellow]\n"
                    "[dim]    Instala RTL-SDR: pip install pyrtlsdr[/dim]"
                )
                return
            except Exception as e:
                self._log.warning(f"MockSDR: {e}")

        self.hw_nombre = "SIN HARDWARE"
        self.hw_disponible = False
        self._print(
            "[red][!] No se pudo inicializar ningún backend RF.\n    Instala: pip install numpy pyrtlsdr rich[/red]")

    # ── Captura ───────────────────────────────────────────────────────

    def _capturar(self, freq_hz: float, n_samples: Optional[int] = None) -> Optional["np.ndarray"]:
        if not self.hw_disponible or not _NP_OK:
            return None
        n = n_samples or self.SAMPLES_N

        if self._scanner is not None:
            with self._lock:
                resultado = self._scanner._capturar(freq_hz)
                if resultado is not None:
                    self._capturas_sesion += 1
                return resultado

        if self._mock is not None:
            self._mock._current_freq = freq_hz
            try:
                muestras = self._mock.capture(freq_hz, n)
                self._capturas_sesion += 1
                return muestras
            except Exception as e:
                self._log.error(f"MockSDR captura: {e}")

        return None

    # ── Identificación de banda ───────────────────────────────────────

    def _identificar_banda(self, freq_mhz: float) -> Optional[dict]:
        if _BANDS_OK:
            return identify_band(freq_mhz)
        for fmin, fmax, nombre, tipo, desc, color in BANDAS:
            if fmin <= freq_mhz <= fmax:
                return {"nombre": nombre, "tipo": tipo, "desc": desc, "color": color}
        return None

    def _enriquecer_picos(self, picos: list) -> list:
        for p in picos:
            p["banda"] = self._identificar_banda(p["freq_mhz"])
        return picos

    # ── PSD + Picos ───────────────────────────────────────────────────

    def _calcular_psd_y_picos(self, muestras: "np.ndarray", freq_hz: float):
        if not _NP_OK:
            return None, None, []

        if self._dsp_avanzado is not None:
            try:
                freqs, psd = self._dsp_avanzado.compute_psd(muestras)
                signals = self._dsp_avanzado.detect_peaks(freqs, psd, freq_hz)
                picos = [
                    {
                        "freq_mhz": sig.freq_mhz,
                        "freq_hz":  sig.freq_mhz * 1e6,
                        "potencia": sig.potencia,
                        "snr_db":   sig.snr_db,
                        "bw_hz":    sig.bw_khz * 1e3,
                        "bw_khz":   sig.bw_khz,
                        "piso_dbm": sig.piso_dbm,
                        "mod_hint": sig.mod_hint,
                        "timestamp": sig.timestamp,
                    }
                    for sig in signals
                ]
                return freqs, psd, picos
            except Exception as e:
                self._log.warning(
                    f"DSPEngine avanzado: {e} — usando MotorDSP básico")

        if self._dsp_basico is not None:
            try:
                freqs, psd = self._dsp_basico.calcular_psd(
                    muestras, self.sample_rate)
                picos = self._dsp_basico.detectar_picos(
                    freqs, psd, freq_hz, self.sample_rate)
                for p in picos:
                    bw = p.get("bw_khz", 0)
                    p["mod_hint"] = ("NFM/CW" if bw < 5 else "NFM" if bw < 12
                                     else "AM" if bw < 20 else "WFM" if bw < 35
                                     else "WFM/DATA")
                return freqs, psd, picos
            except Exception as e:
                self._log.error(f"MotorDSP básico: {e}")

        return None, None, []

    # ── Persistencia ─────────────────────────────────────────────────

    def _guardar_en_db(self, picos: list, escaneo_id: Optional[int] = None):
        if self._db is None or not picos:
            return
        try:
            self._db.insertar_senales_bulk(picos, escaneo_id)
        except Exception as e:
            self._log.warning(f"DB insert: {e}")

    def _exportar_csv(self, picos: list, freq_mhz: float):
        self.EXPORT_PATH.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = self.EXPORT_PATH / f"scan_{freq_mhz:.3f}MHz_{ts}.csv"
        try:
            campos = ["freq_mhz", "potencia", "snr_db", "bw_khz",
                      "piso_dbm", "mod_hint", "banda", "timestamp"]
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=campos)
                w.writeheader()
                for p in picos:
                    row = {k: p.get(k, "") for k in campos}
                    row["banda"] = p["banda"]["nombre"] if p.get(
                        "banda") else "—"
                    w.writerow(row)
            self._print(f"[green][+] CSV exportado → {fn}[/green]")
        except OSError as e:
            self._log.error(f"CSV export: {e}")

    def _exportar_csv_barrido(self, resultados: list, freq_ini: float, freq_fin: float):
        self.EXPORT_PATH.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = self.EXPORT_PATH / \
            f"sweep_{freq_ini:.0f}-{freq_fin:.0f}MHz_{ts}.csv"
        try:
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(
                    f, fieldnames=["freq_mhz", "pot_max", "piso", "snr", "banda"])
                w.writeheader()
                for r in resultados:
                    w.writerow({
                        "freq_mhz": r["freq_mhz"], "pot_max": r["pot_max"],
                        "piso": r["piso"],          "snr":    r["snr"],
                        "banda": r["banda"]["nombre"] if r.get("banda") else "—",
                    })
            self._print(f"[green][+] Barrido CSV → {fn}[/green]")
        except OSError as e:
            self._log.error(f"CSV barrido: {e}")

    def _registrar_en_proyecto(self, freq_mhz: float, picos: list, duracion: float):
        if not self.gp or not picos:
            return
        try:
            self.gp.registrar_evidencia(
                "rf_scan",
                f"Escaneo RF {freq_mhz:.3f} MHz: {len(picos)} señales",
                {
                    "freq_mhz": freq_mhz, "duracion_s": round(duracion, 1),
                    "hardware": self.hw_nombre,
                    "señales": [
                        {"freq": p["freq_mhz"], "pot": p["potencia"],
                         "snr": p["snr_db"],    "bw":  p["bw_khz"],
                         "banda": p["banda"]["nombre"] if p.get("banda") else "—"}
                        for p in picos
                    ],
                }
            )
            for p in picos:
                if not p.get("banda") and p["snr_db"] > 20:
                    self.gp.registrar_hallazgo(
                        "MEDIO",
                        f"Señal no clasificada en {p['freq_mhz']:.4f} MHz",
                        f"Potencia: {p['potencia']:.1f} dBm  SNR: {p['snr_db']:.1f} dB  BW: {p['bw_khz']:.2f} kHz",
                        "Investigar origen. Podría ser dispositivo no autorizado o interferencia ilegal.",
                    )
        except Exception as e:
            self._log.warning(f"GestorProyectos RF: {e}")

    # ── Renderizado ──────────────────────────────────────────────────

    def _render_espectro(self, freqs_hz, psd_dbm, freq_centro_mhz: float, picos: list) -> Panel:
        if self._render is not None:
            try:
                return self._render.espectro(freqs_hz, psd_dbm, freq_centro_mhz,
                                             picos, self.sample_rate, self.hw_nombre)
            except Exception:
                pass
        return Panel(
            f"[green]FFT {len(psd_dbm)} pts @ {freq_centro_mhz:.3f} MHz — {len(picos)} pico(s)[/green]",
            title="ESPECTRO", border_style="green"
        )

    def _render_waterfall(self, freq_mhz: float) -> Panel:
        if self._render is not None and self._waterfall:
            try:
                return self._render.waterfall(self._waterfall, freq_mhz)
            except Exception:
                pass
        return Panel("[dim]Sin datos de waterfall.[/dim]", title="WATERFALL", border_style="dim green")

    def _render_tabla_picos(self, picos: list) -> Panel:
        if self._render is not None:
            try:
                return self._render.tabla_picos(picos)
            except Exception:
                pass
        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia", style="cyan",    min_width=15)
        tb.add_column("Potencia",   justify="right", min_width=11)
        tb.add_column("SNR",        justify="right", min_width=8)
        tb.add_column("BW",         justify="right", min_width=10)
        tb.add_column("Mod. est.",                   min_width=10)
        tb.add_column("Banda",                       min_width=18)
        for p in picos:
            banda = p.get("banda")
            b_str = f"[{banda['color']}]{banda['nombre']}[/{banda['color']}]" if banda else "—"
            potencia_txt = Text(
                f"{p['potencia']:.1f} dBm",
                style="bold red" if p["potencia"] > -
                50 else "yellow" if p["potencia"] > -70 else "green"
            )
            tb.add_row(f"{p['freq_mhz']:.4f} MHz", potencia_txt,
                       f"{p['snr_db']:.1f} dB", f"{p.get('bw_khz', 0):.2f} kHz",
                       p.get("mod_hint", "—"), b_str)
        return Panel(tb, title=f"[bold green]SEÑALES [{len(picos)}][/bold green]",
                     border_style="green", box=box.HEAVY_HEAD)

    def _render_resumen(self, freq_mhz: float, picos: list, duracion: float, iteraciones: int) -> Panel:
        if self._render is not None and hasattr(self._render, "resumen_escaneo"):
            try:
                return self._render.resumen_escaneo(freq_mhz, picos, duracion, self.hw_nombre, iteraciones)
            except Exception:
                pass
        snr_max = max((p["snr_db"] for p in picos), default=0)
        pot_max = max((p["potencia"] for p in picos), default=-999)
        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim green", justify="right", min_width=22)
        g.add_column(style="white")
        g.add_row("Frecuencia",         f"{freq_mhz:.4f} MHz")
        g.add_row("Hardware",           self.hw_nombre)
        g.add_row("Duración",           f"{duracion:.1f} s")
        g.add_row("Iteraciones FFT",    str(iteraciones))
        g.add_row("Señales detectadas", str(len(picos)))
        g.add_row("Potencia máxima",    f"{pot_max:.1f} dBm")
        g.add_row("SNR máximo",         f"{snr_max:.1f} dB")
        g.add_row("DSP Engine",
                  "Avanzado (CFAR)" if self._dsp_avanzado else "Básico (MotorDSP)")
        g.add_row("Base de datos",
                  "SQLite activa" if self._db else "Sin persistencia")
        return Panel(g, title="[bold green]RESUMEN DEL ESCANEO[/bold green]", border_style="green")

    # ── API Pública ───────────────────────────────────────────────────

    def escanear_frecuencia(self, freq_mhz: float, duracion: int = 10):
        if not self.hw_disponible:
            self._print(
                "[red][!] RF no disponible. Verifica hardware o instalación.[/red]")
            return
        if not _NP_OK:
            self._print("[red][!] numpy no instalado: pip install numpy[/red]")
            return

        freq_hz = freq_mhz * 1e6
        banda = self._identificar_banda(freq_mhz)

        self._print()
        if banda:
            col = banda.get("color", "white")
            self._print(
                f"[bold green][RF] Sintonizando {freq_mhz:.4f} MHz — [{col}]{banda['nombre']}[/{col}]  [dim]{banda.get('desc', '')}[/dim][/bold green]")
        else:
            self._print(
                f"[bold green][RF] Sintonizando {freq_mhz:.4f} MHz — Banda no clasificada[/bold green]")

        self._print(
            f"[dim]  HW: {self.hw_nombre}  |  BW: {self.sample_rate/1e6:.3f} MHz  |  FFT: {self.fft_size} pts  |  Duración: {duracion}s  |  Ctrl+C para detener[/dim]\n")
        time.sleep(0.4)

        escaneo_id: Optional[int] = None
        if self._db:
            try:
                escaneo_id = self._db.iniciar_escaneo(
                    freq_mhz, self.hw_nombre, int(self.sample_rate), self.fft_size)
            except Exception:
                pass

        inicio = time.time()
        iteracion = 0
        todos_picos: list = []

        try:
            while time.time() - inicio < duracion:
                capturas_psd = []
                muestras_last = None

                for _ in range(self.PROMEDIO_N):
                    muestras = self._capturar(freq_hz)
                    if muestras is None:
                        self._print("[red][!] Fallo de captura.[/red]")
                        return
                    muestras_last = muestras
                    if self._dsp_basico:
                        try:
                            _, psd = self._dsp_basico.calcular_psd(
                                muestras, self.sample_rate)
                            capturas_psd.append(psd)
                        except Exception:
                            pass

                if muestras_last is None:
                    break

                freqs, psd, picos = self._calcular_psd_y_picos(
                    muestras_last, freq_hz)

                if capturas_psd and self._dsp_basico and len(capturas_psd) > 1:
                    try:
                        psd = self._dsp_basico.promediar_capturas(capturas_psd)
                    except Exception:
                        pass

                picos = self._enriquecer_picos(picos)
                todos_picos.extend(picos)
                self._senales_sesion.extend(picos)

                if psd is not None:
                    self._waterfall.appendleft(psd.copy())

                if self._demod is not None and picos and muestras_last is not None:
                    try:
                        audio = self._demod.demodulate(muestras_last)
                        if audio is not None:
                            self._demod.play(audio)
                    except Exception:
                        pass

                os.system("cls" if os.name == "nt" else "clear")
                if freqs is not None and psd is not None:
                    self.console.print(self._render_espectro(
                        freqs, psd, freq_mhz, picos))
                self.console.print(self._render_waterfall(freq_mhz))
                self.console.print(self._render_tabla_picos(picos))

                elapsed = time.time() - inicio
                self.console.print(
                    f"[dim]  Iter {iteracion+1}  |  {elapsed:.1f}s/{duracion}s  |  "
                    f"Picos: {len(picos)}  |  Total sesión: {len(self._senales_sesion)}  |  "
                    f"Capturas: {self._capturas_sesion}[/dim]"
                )
                iteracion += 1

        except KeyboardInterrupt:
            self._print("\n[yellow][!] Escaneo interrumpido.[/yellow]")

        duracion_real = time.time() - inicio

        if self._demod:
            try:
                self._demod.stop_audio()
            except Exception:
                pass

        self.console.print()
        self.console.print(self._render_resumen(
            freq_mhz, todos_picos, duracion_real, iteracion))

        if todos_picos:
            self._guardar_en_db(todos_picos, escaneo_id)
            self._exportar_csv(todos_picos, freq_mhz)

        if self._db and escaneo_id:
            try:
                self._db.finalizar_escaneo(escaneo_id, duracion_real)
            except Exception:
                pass

        self._registrar_en_proyecto(freq_mhz, todos_picos, duracion_real)

        if self.log_s:
            self.log_s.info(
                f"Escaneo RF {freq_mhz:.3f} MHz: {len(todos_picos)} señales en {duracion_real:.0f}s", "RFScanner")

    def barrido_espectro(self, freq_ini_mhz: float, freq_fin_mhz: float, paso_mhz: float = 1.0):
        if not self.hw_disponible or not _NP_OK:
            self._print("[red][!] RF no disponible.[/red]")
            return

        freqs = np.arange(freq_ini_mhz, freq_fin_mhz + paso_mhz, paso_mhz)
        self._print(
            f"\n[bold green][RF] Barrido: {freq_ini_mhz:.1f} → {freq_fin_mhz:.1f} MHz  (paso: {paso_mhz:.2f} MHz  |  {len(freqs)} puntos)[/bold green]\n")

        resultados = []
        try:
            for i, freq in enumerate(freqs):
                muestras = self._capturar(float(freq) * 1e6)
                if muestras is None:
                    break

                _, psd, _ = self._calcular_psd_y_picos(
                    muestras, float(freq) * 1e6)
                if psd is None:
                    continue

                piso = self._dsp_basico.estimar_piso_ruido(
                    psd) if self._dsp_basico else float(np.median(psd))
                pot_max = float(np.max(psd))
                snr = pot_max - piso
                banda = self._identificar_banda(float(freq))

                resultados.append({"freq_mhz": round(float(freq), 3), "pot_max": round(pot_max, 1),
                                   "piso": round(piso, 1), "snr": round(snr, 1), "banda": banda})

                pct = int((i + 1) / len(freqs) * 50)
                barra = "█" * pct + "─" * (50 - pct)
                print(
                    f"\r  [{barra}] {freq:.2f} MHz  {pot_max:.1f}dBm  SNR:{snr:.1f}dB  {banda['nombre'] if banda else '—':<20}", end="")

        except KeyboardInterrupt:
            self._print("\n[yellow][!] Barrido interrumpido.[/yellow]")

        print()
        self.console.print()

        if resultados:
            if self._render and hasattr(self._render, "mapa_barrido"):
                try:
                    self.console.print(self._render.mapa_barrido(resultados))
                except Exception:
                    self._mostrar_mapa_barrido_basico(resultados)
            else:
                self._mostrar_mapa_barrido_basico(resultados)

            self._exportar_csv_barrido(resultados, freq_ini_mhz, freq_fin_mhz)

            if self._db:
                try:
                    self._db.insertar_barrido(
                        freq_ini_mhz, freq_fin_mhz, paso_mhz, self.hw_nombre, resultados)
                except Exception:
                    pass

            if self.gp:
                try:
                    self.gp.registrar_evidencia("rf_sweep", f"Barrido RF {freq_ini_mhz:.0f}–{freq_fin_mhz:.0f} MHz",
                                                {"ini": freq_ini_mhz, "fin": freq_fin_mhz, "paso": paso_mhz,
                                                 "puntos": len(resultados), "hw": self.hw_nombre})
                except Exception:
                    pass

    def _mostrar_mapa_barrido_basico(self, resultados: list):
        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia", style="cyan",    min_width=14)
        tb.add_column("Actividad",                   min_width=18)
        tb.add_column("Pot. máx",   justify="right", min_width=11)
        tb.add_column("SNR",        justify="right", min_width=8)
        tb.add_column("Banda",                       min_width=18)
        for r in sorted(resultados, key=lambda x: x["snr"], reverse=True)[:25]:
            nivel = int(min(r["snr"] / 35 * 16, 16))
            barra = "█" * nivel + "·" * (16 - nivel)
            sty = "bold red" if r["snr"] > 25 else "yellow" if r["snr"] > 15 else "green" if r["snr"] > 8 else "dim"
            banda_n = "—"
            if r.get("banda"):
                col = r["banda"].get("color", "white")
                banda_n = f"[{col}]{r['banda']['nombre']}[/{col}]"
            tb.add_row(f"{r['freq_mhz']:.3f} MHz", Text(barra, style=sty),
                       f"{r['pot_max']:.1f} dBm", f"{r['snr']:.1f} dB", banda_n)
        self.console.print(Panel(tb, title="[bold green]MAPA DE ACTIVIDAD RF[/bold green]",
                                 border_style="green", box=box.HEAVY_HEAD))

    def escaneo_bandas_conocidas(self):
        if not self.hw_disponible or not _NP_OK:
            self._print("[red][!] RF no disponible.[/red]")
            return

        bandas_a_escanear = (
            [(fmin, fmax, nombre, tipo, desc, "white")
             for fmin, fmax, nombre, tipo, desc, _ in BANDAS_RF]
            if _BANDS_OK and BANDAS_RF else list(BANDAS)
        )
        self._print(
            f"\n[bold green][RF] Escaneo de {len(bandas_a_escanear)} bandas...[/bold green]\n")
        resultados = []

        for fmin, fmax, nombre, tipo, desc, color in bandas_a_escanear:
            freq = (fmin + fmax) / 2.0
            if freq < 24 or freq > 1766:
                continue
            muestras = self._capturar(freq * 1e6)
            if muestras is None:
                break

            _, psd, _ = self._calcular_psd_y_picos(muestras, freq * 1e6)
            if psd is None:
                continue

            piso = float(np.median(psd))
            pot_max = float(np.max(psd))
            snr = pot_max - piso

            resultados.append({"freq_mhz": round(freq, 3), "pot_max": round(pot_max, 1),
                               "piso": round(piso, 1),    "snr":     round(snr, 1),
                               "banda": {"nombre": nombre, "tipo": tipo, "desc": desc, "color": color}})
            print(
                f"\r  {nombre:<25} {freq:>8.2f} MHz  {pot_max:>6.1f} dBm  SNR: {snr:>5.1f} dB", end="")

        print()
        self.console.print()
        if resultados:
            self._mostrar_mapa_barrido_basico(resultados)

    def configurar_ganancia(self, ganancia):
        if self._scanner:
            self._scanner.configurar_ganancia(ganancia)
        elif self._mock:
            self._mock.set_gain(ganancia)
            self._print(f"[green][+] MockSDR ganancia={ganancia}dB[/green]")
        else:
            self._print("[red][!] Sin hardware para configurar.[/red]")

    def estado(self):
        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim green", justify="right", min_width=24)
        g.add_column(style="white")
        g.add_row("Hardware",             self.hw_nombre)
        g.add_row("Disponible",
                  "[green]Sí[/green]" if self.hw_disponible else "[red]No[/red]")
        g.add_row("Sample rate",          f"{self.sample_rate/1e6:.3f} MHz")
        g.add_row("Ganancia",             f"{self.gain} dB")
        g.add_row("FFT size",             str(self.fft_size))
        g.add_row("DSP Engine",
                  "[green]Avanzado (CFAR)[/green]" if self._dsp_avanzado else "[yellow]Básico[/yellow]")
        g.add_row("Demodulador",
                  "[green]Activo[/green]" if self._demod else "[dim]No disponible[/dim]")
        g.add_row("Base de datos SQLite",
                  "[green]Activa[/green]" if self._db else "[dim]No disponible[/dim]")
        g.add_row("Bandas en DB",         str(len(BANDAS_RF) or len(BANDAS)))
        g.add_row("Señales sesión",       str(len(self._senales_sesion)))
        g.add_row("Capturas totales",     str(self._capturas_sesion))
        g.add_row("Bandas tácticas",      str(
            len(tactical_bands())) if _BANDS_OK else "—")
        g.add_row("numpy",
                  "[green]OK[/green]" if _NP_OK else "[red]NO[/red]")
        g.add_row("Config TOML",
                  "[green]OK[/green]" if _RF_CONFIG_OK else "[yellow]Sin TOML (defaults)[/yellow]")
        self.console.print(Panel(
            g, title="[bold green]ESTADO RF SCANNER[/bold green]", border_style="green"))

    def db_consultar(self, freq_min=None, freq_max=None, snr_min=None, horas=None):
        if not self._db:
            self._print("[red][!] Base de datos RF no disponible.[/red]")
            return
        try:
            resultados = self._db.consultar_senales(
                freq_min=freq_min, freq_max=freq_max, snr_min=snr_min, horas=horas)
            if not resultados:
                self._print(
                    "[dim]Sin señales almacenadas con esos criterios.[/dim]")
                return
            tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                       show_edge=False, expand=True)
            tb.add_column("Timestamp",  style="dim",  min_width=19)
            tb.add_column("Frecuencia", style="cyan", min_width=14)
            tb.add_column("Potencia",   justify="right", min_width=11)
            tb.add_column("SNR",        justify="right", min_width=8)
            tb.add_column("BW",         justify="right", min_width=10)
            tb.add_column("Banda",      min_width=16)
            for r in resultados:
                tb.add_row(r.get("timestamp", "")[:19], f"{r.get('freq_mhz', 0):.4f} MHz",
                           f"{r.get('potencia', 0):.1f} dBm", f"{r.get('snr_db', 0):.1f} dB",
                           f"{r.get('bw_khz', 0):.2f} kHz", r.get("banda") or "—")
            self.console.print(Panel(
                tb, title=f"[bold green]DB RF — {len(resultados)} señales[/bold green]", border_style="green"))
        except Exception as e:
            self._print(f"[red][!] Error en consulta DB: {e}[/red]")

    def db_estadisticas(self):
        if not self._db:
            self._print("[red][!] Base de datos RF no disponible.[/red]")
            return
        try:
            stats = self._db.estadisticas()
            g = Table.grid(padding=(0, 3))
            g.add_column(style="dim green", justify="right", min_width=22)
            g.add_column(style="white")
            for k, v in stats.items():
                g.add_row(k.replace("_", " ").title(),
                          str(v) if v is not None else "—")
            self.console.print(Panel(
                g, title="[bold green]ESTADÍSTICAS DB RF[/bold green]", border_style="green"))
        except Exception as e:
            self._print(f"[red][!] Error estadísticas: {e}[/red]")

    def menu(self):
        self.console.print()
        self.console.print(Panel(
            f"[bold green]RF SCANNER — {self.hw_nombre}[/bold green]\n\n"
            "[green][1][/green] Escanear frecuencia específica\n"
            "[green][2][/green] Barrido de espectro (rango)\n"
            "[green][3][/green] Escaneo de bandas conocidas\n"
            "[green][4][/green] Ajustar ganancia\n"
            "[green][5][/green] Ver señales de esta sesión\n"
            "[green][6][/green] Estado del hardware y módulos\n"
            "[green][7][/green] Consultar base de datos RF\n"
            "[green][8][/green] Estadísticas DB\n"
            "[green][9][/green] Bandas tácticas (alto riesgo)",
            border_style="green", title="[bold green]RF SCANNER v2.2[/bold green]",
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
                self.barrido_espectro(float(ini_s), float(
                    fin_s), float(paso_s) if paso_s else 1.0)
            except ValueError:
                self._print("[red][!] Valores inválidos.[/red]")

        elif opt == "3":
            self.escaneo_bandas_conocidas()
        elif opt == "4":
            gan_s = self.console.input(
                "[bold cyan][?] Ganancia dB (0-49, 'auto'): [/bold cyan]").strip()
            self.configurar_ganancia("auto" if gan_s.lower(
            ) == "auto" else float(gan_s) if gan_s else 40)
        elif opt == "5":
            self.console.print(self._render_tabla_picos(
                self._senales_sesion[-50:])) if self._senales_sesion else self._print("[dim]Sin señales en esta sesión.[/dim]")
        elif opt == "6":
            self.estado()
        elif opt == "7":
            freq_s = self.console.input(
                "[bold cyan][?] Frecuencia mínima MHz (Enter=todas): [/bold cyan]").strip()
            snr_s = self.console.input(
                "[bold cyan][?] SNR mínimo dB [0]: [/bold cyan]").strip()
            hs_s = self.console.input(
                "[bold cyan][?] Últimas N horas (Enter=todas): [/bold cyan]").strip()
            self.db_consultar(freq_min=float(freq_s) if freq_s else None,
                              snr_min=float(snr_s) if snr_s else None,
                              horas=int(hs_s) if hs_s else None)
        elif opt == "8":
            self.db_estadisticas()
        elif opt == "9":
            bandas = tactical_bands() if _BANDS_OK else []
            if not bandas:
                self._print("[dim]Sin bandas tácticas definidas.[/dim]")
                return
            tb = Table(box=box.SIMPLE_HEAD, header_style="bold red",
                       show_edge=False, expand=True)
            tb.add_column("Nombre",      min_width=18)
            tb.add_column("Tipo",        min_width=10)
            tb.add_column("Freq. min",   justify="right", min_width=10)
            tb.add_column("Freq. max",   justify="right", min_width=10)
            tb.add_column("Descripción", style="dim",     min_width=30)
            for b in bandas:
                col = b.get("color", "red")
                tb.add_row(f"[{col}]{b['nombre']}[/{col}]", b["tipo"],
                           f"{b['freq_min']:.1f} MHz", f"{b['freq_max']:.1f} MHz", b.get("desc", ""))
            self.console.print(
                Panel(tb, title="[bold red]BANDAS TÁCTICAS[/bold red]", border_style="red"))

    def cerrar(self):
        for obj, metodo in [
            (self._scanner, "cerrar"), (self._mock, "close"),
            (self._demod, "stop_audio"), (self._db, "cerrar"),
        ]:
            if obj:
                try:
                    getattr(obj, metodo)()
                except Exception:
                    pass
        self._log.info("Módulo RF cerrado correctamente")

    def _print(self, msg: str = ""):
        if self.console:
            self.console.print(msg)
        else:
            import re as _re
            print(_re.sub(r"\[.*?\]", "", msg))
