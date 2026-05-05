"""
╔══════════════════════════════════════════════════════════════════╗
║         APEX SENTINEL — ANUBIS OS  v2.2                          ║
║         Main integrado · Arquitectura profesional completa       ║
║                                                                  ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations
from rich.text import Text
from rich.table import Table
from rich.rule import Rule
from rich.prompt import Prompt
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.console import Console
from rich.columns import Columns
from rich.align import Align
from rich import box

import csv
import ipaddress
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Compatibilidad Windows ──────────────────────────────────────────
if sys.platform == "win32":
    _proj = os.path.abspath(os.path.dirname(__file__))
    os.add_dll_directory(_proj)

# ── Asegurar que el directorio del proyecto está en sys.path ───────
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── Rich ─────────────────────────────────────────────────────────────

# ── Autenticación ────────────────────────────────────────────────────
try:
    import bcrypt
    _BCRYPT_OK = True
except ImportError:
    _BCRYPT_OK = False

# ── Importaciones opcionales del sistema Sentinel ───────────────────


def _importar(modulo: str, clase: str):
    """Importa una clase de forma segura; retorna None si falla."""
    try:
        m = __import__(modulo, fromlist=[clase])
        return getattr(m, clase)
    except Exception as exc:
        logging.getLogger("sentinel").debug(
            f"[IMPORT] {clase} ({modulo}): {exc}")
        return None


try:
    from bootscreen import (
        ANUBIS_ART,
        COMANDOS_HELP,
        ESTILOS_LOG,
        MODULOS_BOOT,
        mostrar_ayuda,
        mostrar_banner,
        mostrar_bootloader,
    )
except ImportError:
    # Fallbacks mínimos para que el sistema arranque sin bootscreen
    ESTILOS_LOG = {
        "INFO":    ("cyan",   "ℹ"),
        "WARNING": ("yellow", "⚠"),
        "ERROR":   ("red",    "✖"),
        "SUCCESS": ("green",  "✔"),
        "AUDIT":   ("magenta", "🔍"),
        "DEBUG":   ("dim",    "·"),
    }
    MODULOS_BOOT = []
    ANUBIS_ART = ""
    COMANDOS_HELP = {}

    def mostrar_bootloader(console, nombre, version, iface):
        console.print(Panel(f"[bold green]{nombre} v{version}[/bold green]",
                            border_style="green"))

    def mostrar_banner(console, nombre, version, iface):
        console.print(Rule(f"[bold green]{nombre} v{version}[/bold green]"))

    def mostrar_ayuda(console, version, cmds):
        console.print(Panel("[dim]Sin ayuda disponible.[/dim]",
                            title="AYUDA", border_style="cyan"))

try:
    from auth import GestorAuth
except ImportError:
    class GestorAuth:  # type: ignore
        def __init__(self, *a, **kw): pass
        def solicitar_acceso(self) -> bool: return True


# ════════════════════════════════════════════════════════════════════
# IMPORTS RF — con fallbacks completos
# ════════════════════════════════════════════════════════════════════

# ── numpy (requerido por los módulos RF) ─────────────────────────────
try:
    import numpy as np
    _NP_OK = True
except ImportError:
    _NP_OK = False
    np = None  # type: ignore

# ── config.py ────────────────────────────────────────────────────────
try:
    from config import (
        Config as RFConfig,
        DemodConfig,
        DspConfig,
        HardwareConfig,
        StorageConfig,
    )
    _RF_CONFIG_OK = True
except ImportError:
    _RF_CONFIG_OK = False
    RFConfig = None  # type: ignore

# ── logger.py ────────────────────────────────────────────────────────
try:
    from logger import get_logger as _rf_get_logger, setup_logger as _rf_setup_logger
    _RF_LOGGER_OK = True
except ImportError:
    _RF_LOGGER_OK = False

    def _rf_get_logger(name):  # type: ignore
        return logging.getLogger(name)

    def _rf_setup_logger(**kw):  # type: ignore
        return logging.getLogger("rfscanner")

# ── bands.py ─────────────────────────────────────────────────────────
try:
    from bands import (
        BANDAS_RF,
        COLORES_TIPO,
        bands_in_range,
        identify_band,
        tactical_bands,
    )
    _BANDS_OK = True
except ImportError:
    _BANDS_OK = False
    BANDAS_RF = []
    COLORES_TIPO = {}
    def identify_band(freq_mhz): return None  # type: ignore
    def bands_in_range(a, b): return []  # type: ignore
    def tactical_bands(): return []  # type: ignore

# ── dsp.py ───────────────────────────────────────────────────────────
try:
    from dsp import DSPEngine, Signal as RFSignal
    _DSP_OK = True
except ImportError:
    _DSP_OK = False
    DSPEngine = None  # type: ignore
    RFSignal = None  # type: ignore

# ── rf_demod.py ──────────────────────────────────────────────────────
try:
    from rf_demod import Demodulator
    _DEMOD_OK = True
except ImportError:
    _DEMOD_OK = False
    Demodulator = None  # type: ignore

# ── rf_mock.py ───────────────────────────────────────────────────────
try:
    from rf_mock import MockSDRManager, SyntheticSignal, generate_fixture
    _MOCK_OK = True
except ImportError:
    _MOCK_OK = False
    MockSDRManager = None  # type: ignore
    SyntheticSignal = None  # type: ignore
    generate_fixture = None  # type: ignore

# ── rf_database.py ───────────────────────────────────────────────────
try:
    from rf_database import RFDatabase
    _RFDB_OK = True
except ImportError:
    _RFDB_OK = False
    RFDatabase = None  # type: ignore

# ── RFScanner hardware real ──────────────────────────────────────────
try:
    from RFScanner import RFScanner, MotorDSP, Renderizador, ConfigSDR, BANDAS
    _RFSCANNER_OK = True
except ImportError:
    _RFSCANNER_OK = False
    RFScanner = None  # type: ignore
    MotorDSP = None  # type: ignore
    Renderizador = None  # type: ignore
    ConfigSDR = None  # type: ignore
    BANDAS = []


# ════════════════════════════════════════════════════════════════════
# MÓDULO RF INTEGRADO — Fachada unificada
# ════════════════════════════════════════════════════════════════════

class RFModuleIntegrado:
    """
    Fachada única que integra todos los subsistemas RF:

      · Hardware real (RTL-SDR / HackRF via RFScanner.py)
      · Mock/simulación (rf_mock.py) cuando no hay hardware
      · Motor DSP avanzado (dsp.py) para análisis CFAR
      · Demodulación de audio (rf_demod.py)
      · Persistencia SQLite (rf_database.py)
      · Base de datos de bandas (bands.py)
      · Configuración TOML (config.py)

    Expone la misma API que el RFScanner original:
      rf.escanear_frecuencia(freq_mhz)
      rf.barrido_espectro(ini, fin, paso)
      rf.menu()
    """

    # ── Constantes de visualización ───────────────────────────────────
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

        # ── Logger RF propio ─────────────────────────────────────────
        self._log = _rf_get_logger("rfscanner.main")

        # ── Configuración RF ─────────────────────────────────────────
        self.cfg: Optional[RFConfig] = None
        if _RF_CONFIG_OK and RFConfig:
            try:
                self.cfg = RFConfig()
                self._log.debug("Config RF cargada")
            except Exception as e:
                self._log.warning(f"Config RF: usando defaults — {e}")

        # ── Parámetros de hardware ───────────────────────────────────
        self.sample_rate = (
            self.cfg.hardware.sample_rate
            if self.cfg else 2_048_000
        )
        self.fft_size = (
            self.cfg.dsp.fft_size
            if self.cfg else 2048
        )
        self.gain = (
            self.cfg.hardware.gain
            if self.cfg else 40.0
        )

        # ── Hardware SDR (real o mock) ───────────────────────────────
        self._scanner: Optional[RFScanner] = None  # scanner original
        self._mock:    Optional[MockSDRManager] = None
        self.hw_nombre = "Sin inicializar"
        self.hw_disponible = False

        # ── Motor DSP avanzado (dsp.py) ──────────────────────────────
        self._dsp_avanzado: Optional[DSPEngine] = None

        # ── Motor DSP básico (RFScanner.py integrado) ─────────────────
        self._dsp_basico: Optional[MotorDSP] = None

        # ── Demodulador (rf_demod.py) ────────────────────────────────
        self._demod: Optional[Demodulator] = None

        # ── Base de datos RF (rf_database.py) ───────────────────────
        self._db: Optional[RFDatabase] = None

        # ── Renderizador (RFScanner.py) ──────────────────────────────
        self._render: Optional[Renderizador] = None

        # ── Estado de sesión ─────────────────────────────────────────
        self._waterfall = deque(maxlen=self.WATERFALL_ROWS)
        self._senales_sesion: list = []
        self._capturas_sesion = 0
        self._lock = threading.Lock()

        # ── Inicializar todos los subsistemas ────────────────────────
        self._inicializar_subsistemas()

    # ── Inicialización ────────────────────────────────────────────────

    def _inicializar_subsistemas(self):
        """Inicializa los módulos RF en orden de dependencia."""

        # 1) Directorios
        self.EXPORT_PATH.mkdir(parents=True, exist_ok=True)
        iq_dir = Path("data/evidence/rf/iq")
        iq_dir.mkdir(parents=True, exist_ok=True)

        # 2) Logger RF
        if _RF_LOGGER_OK:
            try:
                _rf_setup_logger(
                    level="INFO",
                    log_file="data/logs/rfscanner.log",
                )
            except Exception:
                pass

        # 3) Motor DSP avanzado
        if _DSP_OK and DSPEngine and _NP_OK:
            try:
                from config import DspConfig as _DC
                dsp_cfg = self.cfg.dsp if self.cfg else _DC()
                self._dsp_avanzado = DSPEngine(dsp_cfg, self.sample_rate)
                self._log.debug("DSPEngine (avanzado) inicializado")
            except Exception as e:
                self._log.warning(f"DSPEngine: {e}")

        # 4) Motor DSP básico (MotorDSP de RFScanner.py)
        if _RFSCANNER_OK and MotorDSP and _NP_OK:
            try:
                self._dsp_basico = MotorDSP(
                    fft_size=self.fft_size,
                    ventana="blackman",
                )
                self._log.debug("MotorDSP (básico) inicializado")
            except Exception as e:
                self._log.warning(f"MotorDSP: {e}")

        # 5) Demodulador
        if _DEMOD_OK and Demodulator and _NP_OK:
            try:
                from config import DemodConfig as _DemodC
                demod_cfg = self.cfg.demod if self.cfg else _DemodC()
                self._demod = Demodulator(demod_cfg, self.sample_rate)
                self._log.debug(
                    f"Demodulator inicializado — modo={demod_cfg.mode}")
            except Exception as e:
                self._log.warning(f"Demodulator: {e}")

        # 6) Base de datos SQLite
        if _RFDB_OK and RFDatabase:
            try:
                db_path = Path("data/evidence/rf/signals.db")
                self._db = RFDatabase(db_path)
                self._log.debug(f"RFDatabase abierta en {db_path}")
            except Exception as e:
                self._log.warning(f"RFDatabase: {e}")

        # 7) Renderizador
        if _RFSCANNER_OK and Renderizador:
            try:
                self._render = Renderizador(self.console)
            except Exception as e:
                self._log.warning(f"Renderizador: {e}")

        # 8) Hardware real → mock si no hay
        self._conectar_hardware()

    def _conectar_hardware(self):
        """
        Intenta conectar hardware SDR real (RTL-SDR / HackRF).
        Si no hay hardware, activa el mock para desarrollo/tests.
        """
        # Intentar hardware real via RFScanner
        if _RFSCANNER_OK and RFScanner:
            try:
                self._scanner = RFScanner(self.sentinel)
                if self._scanner.sdr is not None:
                    self.hw_nombre = self._scanner.hw_nombre
                    self.hw_disponible = True
                    self._print(
                        f"[green][+] RF Hardware real — {self.hw_nombre}[/green]"
                    )
                    return
                else:
                    # Scanner instanciado pero sin HW
                    self._scanner = None
            except Exception as e:
                self._log.warning(f"RFScanner HW: {e}")
                self._scanner = None

        # Fallback: MockSDR
        if _MOCK_OK and MockSDRManager and _NP_OK:
            try:
                self._mock = MockSDRManager(
                    sample_rate=self.sample_rate,
                    noise_floor_dbm=-100.0,
                )
                # Añadir señales de demo
                if SyntheticSignal:
                    self._mock.add_signal(
                        SyntheticSignal(freq_offset=0,
                                        power_dbm=-60, mode="nfm")
                    )
                    self._mock.add_signal(
                        SyntheticSignal(freq_offset=50e3,
                                        power_dbm=-70, mode="wfm")
                    )
                    self._mock.add_signal(
                        SyntheticSignal(freq_offset=-30e3,
                                        power_dbm=-75, mode="am")
                    )
                self.hw_nombre = "MockSDR (sin hardware real)"
                self.hw_disponible = True
                self._print(
                    "[yellow][!] Sin hardware SDR real — usando MockSDR "
                    "(señales sintéticas).[/yellow]\n"
                    "[dim]    Instala RTL-SDR: pip install pyrtlsdr[/dim]"
                )
                return
            except Exception as e:
                self._log.warning(f"MockSDR: {e}")

        self.hw_nombre = "SIN HARDWARE"
        self.hw_disponible = False
        self._print(
            "[red][!] No se pudo inicializar ningún backend RF.\n"
            "    Instala: pip install numpy pyrtlsdr rich[/red]"
        )

    # ── Captura de muestras ──────────────────────────────────────────

    def _capturar(self, freq_hz: float,
                  n_samples: Optional[int] = None) -> Optional["np.ndarray"]:
        """
        Captura muestras IQ desde hardware real o mock.
        Siempre retorna complex64 o None.
        """
        if not self.hw_disponible or not _NP_OK:
            return None

        n = n_samples or self.SAMPLES_N

        # Hardware real via RFScanner
        if self._scanner is not None:
            with self._lock:
                resultado = self._scanner._capturar(freq_hz)
                if resultado is not None:
                    self._capturas_sesion += 1
                return resultado

        # MockSDR
        if self._mock is not None:
            self._mock._current_freq = freq_hz
            try:
                muestras = self._mock.capture(freq_hz, n)
                self._capturas_sesion += 1
                return muestras
            except Exception as e:
                self._log.error(f"MockSDR captura: {e}")

        return None

    # ── Identificación de banda (híbrida) ────────────────────────────

    def _identificar_banda(self, freq_mhz: float) -> Optional[dict]:
        """
        Usa bands.py si disponible, sino la lista interna de RFScanner.
        """
        if _BANDS_OK:
            return identify_band(freq_mhz)
        # Fallback a BANDAS internas de RFScanner.py
        for fmin, fmax, nombre, tipo, desc, color in BANDAS:
            if fmin <= freq_mhz <= fmax:
                return {"nombre": nombre, "tipo": tipo,
                        "desc": desc, "color": color}
        return None

    def _enriquecer_picos(self, picos: list) -> list:
        """Añade información de banda a cada pico."""
        for p in picos:
            p["banda"] = self._identificar_banda(p["freq_mhz"])
        return picos

    # ── Cálculo PSD + detección de picos ────────────────────────────

    def _calcular_psd_y_picos(
        self, muestras: "np.ndarray", freq_hz: float
    ) -> tuple[Optional["np.ndarray"], Optional["np.ndarray"], list]:
        """
        Calcula PSD y detecta picos. Usa DSPEngine avanzado si está
        disponible, sino el MotorDSP básico de RFScanner.
        Retorna (freqs_hz, psd_dbm, picos).
        """
        if not _NP_OK:
            return None, None, []

        # Motor DSP avanzado (dsp.py — CFAR bilateral)
        if self._dsp_avanzado is not None:
            try:
                freqs, psd = self._dsp_avanzado.compute_psd(muestras)
                signals = self._dsp_avanzado.detect_peaks(
                    freqs, psd, freq_hz
                )
                # Convertir Signal dataclass a dict
                picos = []
                for sig in signals:
                    picos.append({
                        "freq_mhz": sig.freq_mhz,
                        "freq_hz":  sig.freq_mhz * 1e6,
                        "potencia": sig.potencia,
                        "snr_db":   sig.snr_db,
                        "bw_hz":    sig.bw_khz * 1e3,
                        "bw_khz":   sig.bw_khz,
                        "piso_dbm": sig.piso_dbm,
                        "mod_hint": sig.mod_hint,
                        "timestamp": sig.timestamp,
                    })
                return freqs, psd, picos
            except Exception as e:
                self._log.warning(
                    f"DSPEngine avanzado: {e} — usando MotorDSP básico")

        # Fallback: MotorDSP básico (RFScanner.py)
        if self._dsp_basico is not None:
            try:
                freqs, psd = self._dsp_basico.calcular_psd(
                    muestras, self.sample_rate
                )
                picos = self._dsp_basico.detectar_picos(
                    freqs, psd, freq_hz, self.sample_rate
                )
                # Añadir mod_hint al formato dict básico
                for p in picos:
                    bw = p.get("bw_khz", 0)
                    if bw < 5:
                        p["mod_hint"] = "NFM/CW"
                    elif bw < 12:
                        p["mod_hint"] = "NFM"
                    elif bw < 20:
                        p["mod_hint"] = "AM"
                    elif bw < 35:
                        p["mod_hint"] = "WFM"
                    else:
                        p["mod_hint"] = "WFM/DATA"
                return freqs, psd, picos
            except Exception as e:
                self._log.error(f"MotorDSP básico: {e}")

        return None, None, []

    # ── Persistencia ─────────────────────────────────────────────────

    def _guardar_en_db(self, picos: list, escaneo_id: Optional[int] = None):
        """Persiste los picos detectados en SQLite."""
        if self._db is None or not picos:
            return
        try:
            self._db.insertar_senales_bulk(picos, escaneo_id)
        except Exception as e:
            self._log.warning(f"DB insert: {e}")

    def _exportar_csv(self, picos: list, freq_mhz: float):
        """Exporta picos a CSV en data/evidence/rf/."""
        self.EXPORT_PATH.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = self.EXPORT_PATH / f"scan_{freq_mhz:.3f}MHz_{ts}.csv"
        try:
            with open(fn, "w", newline="", encoding="utf-8") as f:
                campos = ["freq_mhz", "potencia", "snr_db", "bw_khz",
                          "piso_dbm", "mod_hint", "banda", "timestamp"]
                w = csv.DictWriter(f, fieldnames=campos)
                w.writeheader()
                for p in picos:
                    row = {k: p.get(k, "") for k in campos}
                    banda = p.get("banda")
                    row["banda"] = banda["nombre"] if banda else "—"
                    w.writerow(row)
            self._print(f"[green][+] CSV exportado → {fn}[/green]")
        except OSError as e:
            self._log.error(f"CSV export: {e}")

    def _exportar_csv_barrido(self, resultados: list,
                              freq_ini: float, freq_fin: float):
        """Exporta resultados de barrido a CSV."""
        self.EXPORT_PATH.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = self.EXPORT_PATH / \
            f"sweep_{freq_ini:.0f}-{freq_fin:.0f}MHz_{ts}.csv"
        try:
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "freq_mhz", "pot_max", "piso", "snr", "banda"
                ])
                w.writeheader()
                for r in resultados:
                    w.writerow({
                        "freq_mhz": r["freq_mhz"],
                        "pot_max":  r["pot_max"],
                        "piso":     r["piso"],
                        "snr":      r["snr"],
                        "banda":    (r["banda"]["nombre"]
                                     if r.get("banda") else "—"),
                    })
            self._print(f"[green][+] Barrido CSV → {fn}[/green]")
        except OSError as e:
            self._log.error(f"CSV barrido: {e}")

    def _registrar_en_proyecto(self, freq_mhz: float,
                               picos: list, duracion: float):
        """Registra evidencia y hallazgos en el GestorProyectos."""
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
                    "señales": [
                        {
                            "freq":  p["freq_mhz"],
                            "pot":   p["potencia"],
                            "snr":   p["snr_db"],
                            "bw":    p["bw_khz"],
                            "banda": (p["banda"]["nombre"]
                                      if p.get("banda") else "—"),
                        }
                        for p in picos
                    ],
                }
            )
            # Hallazgo para señales no clasificadas y fuertes
            for p in picos:
                if not p.get("banda") and p["snr_db"] > 20:
                    self.gp.registrar_hallazgo(
                        "MEDIO",
                        f"Señal no clasificada en {p['freq_mhz']:.4f} MHz",
                        f"Potencia: {p['potencia']:.1f} dBm  "
                        f"SNR: {p['snr_db']:.1f} dB  "
                        f"BW: {p['bw_khz']:.2f} kHz",
                        "Investigar origen. Podría ser dispositivo no autorizado "
                        "o interferencia ilegal.",
                    )
        except Exception as e:
            self._log.warning(f"GestorProyectos RF: {e}")

    # ── Renderizado ──────────────────────────────────────────────────

    def _render_espectro(self, freqs_hz: "np.ndarray",
                         psd_dbm: "np.ndarray",
                         freq_centro_mhz: float,
                         picos: list) -> Panel:
        """Delega al Renderizador de RFScanner si disponible."""
        if self._render is not None:
            try:
                return self._render.espectro(
                    freqs_hz, psd_dbm, freq_centro_mhz,
                    picos, self.sample_rate, self.hw_nombre
                )
            except Exception:
                pass
        # Fallback: panel básico
        return Panel(
            f"[green]FFT {len(psd_dbm)} pts @ {freq_centro_mhz:.3f} MHz — "
            f"{len(picos)} pico(s) detectado(s)[/green]",
            title="ESPECTRO", border_style="green"
        )

    def _render_waterfall(self, freq_mhz: float) -> Panel:
        if self._render is not None and self._waterfall:
            try:
                return self._render.waterfall(self._waterfall, freq_mhz)
            except Exception:
                pass
        return Panel("[dim]Sin datos de waterfall.[/dim]",
                     title="WATERFALL", border_style="dim green")

    def _render_tabla_picos(self, picos: list) -> Panel:
        if self._render is not None:
            try:
                return self._render.tabla_picos(picos)
            except Exception:
                pass
        # Fallback tabla básica
        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia",  style="cyan",  min_width=15)
        tb.add_column("Potencia",    justify="right", min_width=11)
        tb.add_column("SNR",         justify="right", min_width=8)
        tb.add_column("BW",          justify="right", min_width=10)
        tb.add_column("Mod. est.",   min_width=10)
        tb.add_column("Banda",       min_width=18)
        for p in picos:
            banda = p.get("banda")
            b_str = f"[{banda['color']}]{banda['nombre']}[/{banda['color']}]" \
                if banda else "—"
            potencia_txt = Text(f"{p['potencia']:.1f} dBm",
                                style="bold red" if p["potencia"] > -50
                                else "yellow" if p["potencia"] > -70
                                else "green")
            tb.add_row(
                f"{p['freq_mhz']:.4f} MHz",
                potencia_txt,
                f"{p['snr_db']:.1f} dB",
                f"{p.get('bw_khz', 0):.2f} kHz",
                p.get("mod_hint", "—"),
                b_str,
            )
        return Panel(tb,
                     title=f"[bold green]SEÑALES [{len(picos)}][/bold green]",
                     border_style="green",
                     box=box.HEAVY_HEAD)

    def _render_resumen(self, freq_mhz: float, picos: list,
                        duracion: float, iteraciones: int) -> Panel:
        if self._render is not None and hasattr(self._render, "resumen_escaneo"):
            try:
                return self._render.resumen_escaneo(
                    freq_mhz, picos, duracion, self.hw_nombre, iteraciones
                )
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
        g.add_row("DSP Engine",         "Avanzado (CFAR)"
                  if self._dsp_avanzado else "Básico (MotorDSP)")
        g.add_row("Base de datos",      "SQLite activa"
                  if self._db else "Sin persistencia")
        return Panel(g,
                     title="[bold green]RESUMEN DEL ESCANEO[/bold green]",
                     border_style="green")

    # ════════════════════════════════════════════════════════════════
    # API PÚBLICA
    # ════════════════════════════════════════════════════════════════

    def escanear_frecuencia(self, freq_mhz: float, duracion: int = 10):
        """
        Escanea una frecuencia con visualización en tiempo real.

        Proceso:
          1. Captura IQ desde hardware real o mock
          2. Promedia N capturas (reduce ruido)
          3. Calcula PSD con DSPEngine avanzado o MotorDSP básico
          4. Detecta picos con CFAR o umbral dinámico
          5. Identifica bandas (bands.py con fallback a BANDAS internas)
          6. Renderiza espectro + waterfall + tabla Rich
          7. Persiste en SQLite (rf_database.py)
          8. Exporta CSV y registra en proyecto
        """
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
                f"[bold green][RF] Sintonizando {freq_mhz:.4f} MHz — "
                f"[{col}]{banda['nombre']}[/{col}]  "
                f"[dim]{banda.get('desc', '')}[/dim][/bold green]"
            )
        else:
            self._print(
                f"[bold green][RF] Sintonizando {freq_mhz:.4f} MHz — "
                f"Banda no clasificada[/bold green]"
            )

        self._print(
            f"[dim]  HW: {self.hw_nombre}  |  "
            f"BW: {self.sample_rate/1e6:.3f} MHz  |  "
            f"FFT: {self.fft_size} pts  |  "
            f"Duración: {duracion}s  |  Ctrl+C para detener[/dim]\n"
        )
        time.sleep(0.4)

        # Registrar inicio de escaneo en DB
        escaneo_id: Optional[int] = None
        if self._db:
            try:
                escaneo_id = self._db.iniciar_escaneo(
                    freq_mhz, self.hw_nombre,
                    int(self.sample_rate), self.fft_size
                )
            except Exception:
                pass

        inicio = time.time()
        iteracion = 0
        todos_picos: list = []

        try:
            while time.time() - inicio < duracion:
                # ── Captura con promediado ──────────────────────────
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
                                muestras, self.sample_rate
                            )
                            capturas_psd.append(psd)
                        except Exception:
                            pass

                if muestras_last is None:
                    break

                # ── PSD + Picos ─────────────────────────────────────
                freqs, psd, picos = self._calcular_psd_y_picos(
                    muestras_last, freq_hz
                )

                # Promediado de capturas si disponible
                if capturas_psd and self._dsp_basico and len(capturas_psd) > 1:
                    try:
                        psd = self._dsp_basico.promediar_capturas(capturas_psd)
                    except Exception:
                        pass

                picos = self._enriquecer_picos(picos)
                todos_picos.extend(picos)
                self._senales_sesion.extend(picos)

                # ── Waterfall ───────────────────────────────────────
                if psd is not None:
                    self._waterfall.appendleft(psd.copy())

                # ── Demodulación (si está activa y hay pico) ────────
                if (self._demod is not None and picos and
                        muestras_last is not None):
                    try:
                        audio = self._demod.demodulate(muestras_last)
                        if audio is not None:
                            self._demod.play(audio)
                    except Exception:
                        pass

                # ── Renderizado ─────────────────────────────────────
                os.system("cls" if os.name == "nt" else "clear")
                if freqs is not None and psd is not None:
                    self.console.print(
                        self._render_espectro(freqs, psd, freq_mhz, picos)
                    )
                self.console.print(self._render_waterfall(freq_mhz))
                self.console.print(self._render_tabla_picos(picos))

                elapsed = time.time() - inicio
                self.console.print(
                    f"[dim]  Iter {iteracion+1}  |  "
                    f"{elapsed:.1f}s/{duracion}s  |  "
                    f"Picos: {len(picos)}  |  "
                    f"Total sesión: {len(self._senales_sesion)}  |  "
                    f"Capturas: {self._capturas_sesion}[/dim]"
                )
                iteracion += 1

        except KeyboardInterrupt:
            self._print("\n[yellow][!] Escaneo interrumpido.[/yellow]")

        duracion_real = time.time() - inicio

        # ── Demod: detener stream de audio ──────────────────────────
        if self._demod:
            try:
                self._demod.stop_audio()
            except Exception:
                pass

        # ── Resumen ─────────────────────────────────────────────────
        self.console.print()
        self.console.print(
            self._render_resumen(freq_mhz, todos_picos,
                                 duracion_real, iteracion)
        )

        # ── Persistencia ─────────────────────────────────────────────
        if todos_picos:
            self._guardar_en_db(todos_picos, escaneo_id)
            self._exportar_csv(todos_picos, freq_mhz)

        # Cerrar sesión en DB
        if self._db and escaneo_id:
            try:
                self._db.finalizar_escaneo(escaneo_id, duracion_real)
            except Exception:
                pass

        # Registrar en proyecto
        self._registrar_en_proyecto(freq_mhz, todos_picos, duracion_real)

        # Log sentinel
        if self.log_s:
            self.log_s.info(
                f"Escaneo RF {freq_mhz:.3f} MHz: "
                f"{len(todos_picos)} señales en {duracion_real:.0f}s",
                "RFScanner",
            )

    def barrido_espectro(self, freq_ini_mhz: float,
                         freq_fin_mhz: float,
                         paso_mhz: float = 1.0):
        """
        Barre un rango de frecuencias y genera mapa de actividad RF.
        Captura una muestra por frecuencia y reporta potencia máxima y SNR.
        """
        if not self.hw_disponible or not _NP_OK:
            self._print("[red][!] RF no disponible.[/red]")
            return

        freqs = np.arange(freq_ini_mhz, freq_fin_mhz + paso_mhz, paso_mhz)
        self._print(
            f"\n[bold green][RF] Barrido: "
            f"{freq_ini_mhz:.1f} → {freq_fin_mhz:.1f} MHz  "
            f"(paso: {paso_mhz:.2f} MHz  |  {len(freqs)} puntos)[/bold green]\n"
        )

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

                if self._dsp_basico:
                    piso = self._dsp_basico.estimar_piso_ruido(psd)
                else:
                    piso = float(np.median(psd))

                pot_max = float(np.max(psd))
                snr = pot_max - piso
                banda = self._identificar_banda(float(freq))

                resultados.append({
                    "freq_mhz": round(float(freq), 3),
                    "pot_max":  round(pot_max, 1),
                    "piso":     round(piso, 1),
                    "snr":      round(snr, 1),
                    "banda":    banda,
                })

                pct = int((i + 1) / len(freqs) * 50)
                barra = "█" * pct + "─" * (50 - pct)
                banda_n = banda["nombre"] if banda else "—"
                print(
                    f"\r  [{barra}] {freq:.2f} MHz  "
                    f"{pot_max:.1f}dBm  SNR:{snr:.1f}dB  {banda_n:<20}",
                    end="",
                )

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
                        freq_ini_mhz, freq_fin_mhz, paso_mhz,
                        self.hw_nombre, resultados
                    )
                except Exception:
                    pass

            if self.gp:
                try:
                    self.gp.registrar_evidencia(
                        "rf_sweep",
                        f"Barrido RF {freq_ini_mhz:.0f}–{freq_fin_mhz:.0f} MHz",
                        {"ini": freq_ini_mhz, "fin": freq_fin_mhz,
                         "paso": paso_mhz, "puntos": len(resultados),
                         "hw": self.hw_nombre}
                    )
                except Exception:
                    pass

    def _mostrar_mapa_barrido_basico(self, resultados: list):
        """Mapa de barrido básico sin Renderizador."""
        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia",  style="cyan",  min_width=14)
        tb.add_column("Actividad",   min_width=18)
        tb.add_column("Pot. máx",    justify="right", min_width=11)
        tb.add_column("SNR",         justify="right", min_width=8)
        tb.add_column("Banda",       min_width=18)

        for r in sorted(resultados, key=lambda x: x["snr"], reverse=True)[:25]:
            nivel = int(min(r["snr"] / 35 * 16, 16))
            barra = "█" * nivel + "·" * (16 - nivel)
            sty = ("bold red" if r["snr"] > 25 else
                   "yellow" if r["snr"] > 15 else
                   "green" if r["snr"] > 8 else "dim")
            banda_n = "—"
            if r.get("banda"):
                col = r["banda"].get("color", "white")
                banda_n = f"[{col}]{r['banda']['nombre']}[/{col}]"
            tb.add_row(
                f"{r['freq_mhz']:.3f} MHz",
                Text(barra, style=sty),
                f"{r['pot_max']:.1f} dBm",
                f"{r['snr']:.1f} dB",
                banda_n,
            )
        self.console.print(Panel(tb,
                                 title="[bold green]MAPA DE ACTIVIDAD RF[/bold green]",
                                 border_style="green",
                                 box=box.HEAVY_HEAD))

    def escaneo_bandas_conocidas(self):
        """Escanea rápidamente cada banda conocida y muestra actividad global."""
        if not self.hw_disponible or not _NP_OK:
            self._print("[red][!] RF no disponible.[/red]")
            return

        # Usar BANDAS_RF (bands.py) con fallback a BANDAS (RFScanner.py)
        bandas_a_escanear = []
        if _BANDS_OK and BANDAS_RF:
            for fmin, fmax, nombre, tipo, desc, peligro in BANDAS_RF:
                bandas_a_escanear.append(
                    (fmin, fmax, nombre, tipo, desc, "white"))
        else:
            bandas_a_escanear = list(BANDAS)

        self._print(
            f"\n[bold green][RF] Escaneo de {len(bandas_a_escanear)} bandas...[/bold green]\n"
        )
        resultados = []

        for fmin, fmax, nombre, tipo, desc, color in bandas_a_escanear:
            freq = (fmin + fmax) / 2.0
            # Límites RTL-SDR
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

            resultados.append({
                "freq_mhz": round(freq, 3),
                "pot_max":  round(pot_max, 1),
                "piso":     round(piso, 1),
                "snr":      round(snr, 1),
                "banda":    {"nombre": nombre, "tipo": tipo,
                             "desc": desc, "color": color},
            })
            print(
                f"\r  {nombre:<25} {freq:>8.2f} MHz  "
                f"{pot_max:>6.1f} dBm  SNR: {snr:>5.1f} dB",
                end="",
            )

        print()
        self.console.print()
        if resultados:
            self._mostrar_mapa_barrido_basico(resultados)

    def configurar_ganancia(self, ganancia):
        """Ajusta la ganancia del hardware SDR."""
        if self._scanner:
            self._scanner.configurar_ganancia(ganancia)
        elif self._mock:
            self._mock.set_gain(ganancia)
            self._print(f"[green][+] MockSDR ganancia={ganancia}dB[/green]")
        else:
            self._print("[red][!] Sin hardware para configurar.[/red]")

    def estado(self):
        """Muestra el estado completo del módulo RF."""
        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim green", justify="right", min_width=24)
        g.add_column(style="white")

        g.add_row("Hardware",             self.hw_nombre)
        g.add_row("Disponible",           "[green]Sí[/green]" if self.hw_disponible
                                          else "[red]No[/red]")
        g.add_row("Sample rate",          f"{self.sample_rate/1e6:.3f} MHz")
        g.add_row("Ganancia",             f"{self.gain} dB")
        g.add_row("FFT size",             str(self.fft_size))
        g.add_row("DSP Engine",           "[green]Avanzado (CFAR)[/green]"
                                          if self._dsp_avanzado
                                          else "[yellow]Básico[/yellow]")
        g.add_row("Demodulador",          "[green]Activo[/green]"
                                          if self._demod else "[dim]No disponible[/dim]")
        g.add_row("Base de datos SQLite", "[green]Activa[/green]"
                                          if self._db else "[dim]No disponible[/dim]")
        g.add_row("Bandas en DB",         str(len(BANDAS_RF) or len(BANDAS)))
        g.add_row("Señales sesión",       str(len(self._senales_sesion)))
        g.add_row("Capturas totales",     str(self._capturas_sesion))
        g.add_row("Bandas tácticas",      str(len(tactical_bands())) if _BANDS_OK
                  else "—")
        g.add_row("numpy",                "[green]OK[/green]" if _NP_OK
                                          else "[red]NO[/red]")
        g.add_row("Config TOML",          "[green]OK[/green]" if _RF_CONFIG_OK
                                          else "[yellow]Sin TOML (defaults)[/yellow]")

        self.console.print(Panel(g,
                                 title="[bold green]ESTADO RF SCANNER[/bold green]",
                                 border_style="green"))

    def db_consultar(self, freq_min: Optional[float] = None,
                     freq_max: Optional[float] = None,
                     snr_min: Optional[float] = None,
                     horas: Optional[int] = None):
        """Consulta la base de datos RF y muestra resultados."""
        if not self._db:
            self._print("[red][!] Base de datos RF no disponible.[/red]")
            return
        try:
            resultados = self._db.consultar_senales(
                freq_min=freq_min, freq_max=freq_max,
                snr_min=snr_min, horas=horas
            )
            if not resultados:
                self._print(
                    "[dim]Sin señales almacenadas con esos criterios.[/dim]")
                return
            tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                       show_edge=False, expand=True)
            tb.add_column("Timestamp",   style="dim",   min_width=19)
            tb.add_column("Frecuencia",  style="cyan",  min_width=14)
            tb.add_column("Potencia",    justify="right", min_width=11)
            tb.add_column("SNR",         justify="right", min_width=8)
            tb.add_column("BW",          justify="right", min_width=10)
            tb.add_column("Banda",       min_width=16)
            for r in resultados:
                tb.add_row(
                    r.get("timestamp", "")[:19],
                    f"{r.get('freq_mhz', 0):.4f} MHz",
                    f"{r.get('potencia', 0):.1f} dBm",
                    f"{r.get('snr_db', 0):.1f} dB",
                    f"{r.get('bw_khz', 0):.2f} kHz",
                    r.get("banda") or "—",
                )
            self.console.print(Panel(tb,
                                     title=f"[bold green]DB RF — {len(resultados)} señales[/bold green]",
                                     border_style="green"))
        except Exception as e:
            self._print(f"[red][!] Error en consulta DB: {e}[/red]")

    def db_estadisticas(self):
        """Muestra estadísticas de la base de datos RF."""
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
            self.console.print(Panel(g,
                                     title="[bold green]ESTADÍSTICAS DB RF[/bold green]",
                                     border_style="green"))
        except Exception as e:
            self._print(f"[red][!] Error estadísticas: {e}[/red]")

    def menu(self):
        """Menú interactivo completo del módulo RF."""
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
            border_style="green",
            title="[bold green]RF SCANNER v2.2[/bold green]",
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
                    float(freq_s), int(dur_s) if dur_s else 10
                )
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
                self.barrido_espectro(
                    float(ini_s), float(fin_s),
                    float(paso_s) if paso_s else 1.0
                )
            except ValueError:
                self._print("[red][!] Valores inválidos.[/red]")

        elif opt == "3":
            self.escaneo_bandas_conocidas()

        elif opt == "4":
            gan_s = self.console.input(
                "[bold cyan][?] Ganancia dB (0-49, 'auto'): [/bold cyan]"
            ).strip()
            if gan_s.lower() == "auto":
                self.configurar_ganancia("auto")
            else:
                try:
                    self.configurar_ganancia(float(gan_s))
                except ValueError:
                    self._print("[red][!] Valor inválido.[/red]")

        elif opt == "5":
            if self._senales_sesion:
                self.console.print(
                    self._render_tabla_picos(self._senales_sesion[-50:])
                )
            else:
                self._print("[dim]Sin señales en esta sesión.[/dim]")

        elif opt == "6":
            self.estado()

        elif opt == "7":
            freq_s = self.console.input(
                "[bold cyan][?] Frecuencia mínima MHz (Enter=todas): [/bold cyan]"
            ).strip()
            snr_s = self.console.input(
                "[bold cyan][?] SNR mínimo dB [0]: [/bold cyan]"
            ).strip()
            hs_s = self.console.input(
                "[bold cyan][?] Últimas N horas (Enter=todas): [/bold cyan]"
            ).strip()
            self.db_consultar(
                freq_min=float(freq_s) if freq_s else None,
                snr_min=float(snr_s) if snr_s else None,
                horas=int(hs_s) if hs_s else None,
            )

        elif opt == "8":
            self.db_estadisticas()

        elif opt == "9":
            bandas = tactical_bands() if _BANDS_OK else []
            if not bandas:
                self._print("[dim]Sin bandas tácticas definidas.[/dim]")
                return
            tb = Table(box=box.SIMPLE_HEAD, header_style="bold red",
                       show_edge=False, expand=True)
            tb.add_column("Nombre",     min_width=18)
            tb.add_column("Tipo",       min_width=10)
            tb.add_column("Freq. min",  justify="right", min_width=10)
            tb.add_column("Freq. max",  justify="right", min_width=10)
            tb.add_column("Descripción", style="dim", min_width=30)
            for b in bandas:
                col = b.get("color", "red")
                tb.add_row(
                    f"[{col}]{b['nombre']}[/{col}]",
                    b["tipo"],
                    f"{b['freq_min']:.1f} MHz",
                    f"{b['freq_max']:.1f} MHz",
                    b.get("desc", ""),
                )
            self.console.print(Panel(tb,
                                     title="[bold red]BANDAS TÁCTICAS[/bold red]",
                                     border_style="red"))

    def cerrar(self):
        """Libera todos los recursos del módulo RF."""
        if self._scanner:
            try:
                self._scanner.cerrar()
            except Exception:
                pass
        if self._mock:
            try:
                self._mock.close()
            except Exception:
                pass
        if self._demod:
            try:
                self._demod.stop_audio()
            except Exception:
                pass
        if self._db:
            try:
                self._db.cerrar()
            except Exception:
                pass
        self._log.info("Módulo RF cerrado correctamente")

    def _print(self, msg: str = ""):
        if self.console:
            self.console.print(msg)
        else:
            import re as _re
            print(_re.sub(r"\[.*?\]", "", msg))


# ════════════════════════════════════════════════════════════════════
# VALIDADORES
# ════════════════════════════════════════════════════════════════════

class Validador:
    MAX_INTENTOS = 3

    @staticmethod
    def es_ip(v: str) -> bool:
        try:
            ipaddress.ip_address(v)
            return True
        except ValueError:
            return False

    @staticmethod
    def es_rango_cidr(v: str) -> bool:
        try:
            ipaddress.ip_network(v, strict=False)
            return True
        except ValueError:
            return False

    @staticmethod
    def es_mac(v: str) -> bool:
        return bool(re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", v))

    @staticmethod
    def es_url(v: str) -> bool:
        return bool(re.match(
            r"^https?://[^\s/$.?#].[^\s]*$", v, re.IGNORECASE
        ))

    @staticmethod
    def es_frecuencia(v: str) -> bool:
        try:
            return 1.0 <= float(v) <= 6000.0
        except ValueError:
            return False

    @classmethod
    def pedir(cls, console, prompt: str, validador=None,
              error: str = "Valor inválido.", default=None,
              password: bool = False, intentos: Optional[int] = None):
        max_i = intentos or cls.MAX_INTENTOS
        prompt_fmt = f"\n[bold cyan]{prompt}[/bold cyan]"
        if default is not None:
            prompt_fmt += f" [dim](Enter = {default})[/dim]"
        prompt_fmt += ": "
        for i in range(max_i):
            try:
                if password:
                    valor = Prompt.ask(prompt_fmt, password=True)
                else:
                    valor = console.input(prompt_fmt).strip()
                if not valor and default is not None:
                    return default
                if validador is None or validador(valor):
                    return valor
                restantes = max_i - i - 1
                msg = f"  [red][!] {error}[/red]"
                if restantes > 0:
                    msg += f" [dim]({restantes} intento{'s' if restantes != 1 else ''} restante)[/dim]"
                console.print(msg)
            except KeyboardInterrupt:
                console.print("\n[yellow][!] Cancelado.[/yellow]")
                raise
        return default

    @classmethod
    def pedir_ip(cls, console, prompt: str = "[?] IP objetivo"):
        return cls.pedir(console, prompt, cls.es_ip, "IP inválida. Ej: 192.168.1.1")

    @classmethod
    def pedir_rango(cls, console, prompt: str = "[?] Rango de red",
                    default: str = "192.168.1.0/24"):
        return cls.pedir(console, prompt, cls.es_rango_cidr,
                         "CIDR inválido. Ej: 192.168.1.0/24", default=default)

    @classmethod
    def pedir_url(cls, console, prompt: str = "[?] URL objetivo"):
        return cls.pedir(console, prompt, cls.es_url,
                         "URL inválida. Debe empezar con http:// o https://")

    @classmethod
    def pedir_frecuencia(cls, console, prompt: str = "[?] Frecuencia (MHz)"):
        v = cls.pedir(console, prompt, cls.es_frecuencia,
                      "Frecuencia inválida. Rango: 1.0 - 6000.0 MHz")
        return float(v) if v else None

    @classmethod
    def pedir_segundos(cls, console, prompt: str = "[?] Duración (segundos)",
                       minimo: int = 1, maximo: int = 300,
                       default: int = 30) -> int:
        def validar(v):
            try:
                return minimo <= int(v) <= maximo
            except ValueError:
                return False
        v = cls.pedir(
            console, f"{prompt} [{minimo}-{maximo}]", validar,
            f"Número entre {minimo} y {maximo}.", default=str(default)
        )
        return int(v) if v else default


# ════════════════════════════════════════════════════════════════════
# SISTEMA DE LOGS SENTINEL
# ════════════════════════════════════════════════════════════════════

class LogSistema:
    def __init__(self, console: Console):
        self.console = console
        self._entradas = self._cargar()
        os.makedirs("data/logs", exist_ok=True)
        logging.basicConfig(
            filename="data/logs/sentinel.log",
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def _ts(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _cargar(self) -> list:
        try:
            with open("data/logs/historial.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _guardar(self):
        try:
            os.makedirs("data/logs", exist_ok=True)
            with open("data/logs/historial.json", "w", encoding="utf-8") as f:
                json.dump(self._entradas[-500:], f,
                          indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _log(self, nivel: str, mensaje: str, modulo: str = "Sistema"):
        entrada = {"timestamp": self._ts(), "nivel": nivel,
                   "modulo": modulo, "mensaje": mensaje}
        self._entradas.append(entrada)
        self._guardar()
        color, icono = ESTILOS_LOG.get(nivel, ("white", "·"))
        line = Text()
        line.append(entrada["timestamp"],      style="dim")
        line.append(" ")
        line.append(f"{icono} {nivel:<8}",     style=color)
        line.append(" ")
        line.append(f"{str(modulo):<18}",      style="cyan")
        line.append(" ")
        line.append(str(mensaje))
        self.console.print(line)
        getattr(logging, nivel.lower(), logging.info)(f"[{modulo}] {mensaje}")

    def info(self, msg, modulo="Sistema"):    self._log("INFO",    msg, modulo)
    def warning(self, msg, modulo="Sistema"): self._log("WARNING", msg, modulo)
    def error(self, msg, modulo="Sistema"):   self._log("ERROR",   msg, modulo)
    def success(self, msg, modulo="Sistema"): self._log("SUCCESS", msg, modulo)
    def audit(self, msg, modulo="Auditoría"): self._log("AUDIT",   msg, modulo)

    def mostrar_historial(self, ultimas: int = 50):
        entradas = self._entradas[-ultimas:]
        if not entradas:
            self.console.print(Panel("[dim]Sin registros.[/dim]",
                                     title="HISTORIAL", border_style="dim green"))
            return
        conteos = {}
        for e in self._entradas:
            conteos[e["nivel"]] = conteos.get(e["nivel"], 0) + 1

        resumen = Table.grid(padding=(0, 3))
        celdas = []
        for n, (c, ico) in ESTILOS_LOG.items():
            t = Text()
            t.append(f"{ico} {n}: {conteos.get(n, 0)}", style=c)
            celdas.append(t)
        resumen.add_row(*celdas)
        self.console.print(Panel(resumen, title="[bold]RESUMEN[/bold]",
                                 border_style="dim green", box=box.SIMPLE))

        tabla = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
                      show_edge=False, expand=True)
        tabla.add_column("Timestamp", style="dim",
                         min_width=19, no_wrap=True)
        tabla.add_column("Nivel",
                         min_width=10, no_wrap=True)
        tabla.add_column("Módulo",    style="cyan",  min_width=16)
        tabla.add_column("Mensaje",   style="white")
        for e in entradas:
            color, icono = ESTILOS_LOG.get(e["nivel"], ("white", "·"))
            nivel_txt = Text()
            nivel_txt.append(f"{icono} {e['nivel']}", style=color)
            tabla.add_row(e["timestamp"], nivel_txt,
                          str(e["modulo"]), str(e["mensaje"]))
        self.console.print(Panel(tabla,
                                 title=f"[bold]HISTORIAL — {len(entradas)} entradas[/bold]",
                                 border_style="green", box=box.HEAVY_EDGE))

    def verificar_y_limpiar(self, max_entradas: int = 500):
        if len(self._entradas) > max_entradas:
            self._entradas = self._entradas[-max_entradas:]
            self._guardar()


# ════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL APEX SENTINEL
# ════════════════════════════════════════════════════════════════════

class ApexSentinel:

    VERSION = "2.2"
    NOMBRE = "ApexSentinel"

    def __init__(self):
        for d in ["data/logs", "data/evidence", "data/evidence/rf",
                  "data/evidence/rf/iq", "plugins"]:
            os.makedirs(d, exist_ok=True)

        self.console = Console()
        self.config = self._cargar_config()
        self.nombre = self.config.get("sistema", {}).get("nombre", self.NOMBRE)
        self.version = self.config.get(
            "sistema", {}).get("version", self.VERSION)
        self.log = LogSistema(self.console)
        self.auth = GestorAuth(self.config, self.console, self.log)

        self._registrar_senales()
        self._cargar_modulos()

    # ── Señales OS ────────────────────────────────────────────────────

    def _registrar_senales(self):
        def _handler(signum, frame):
            nombre_sig = ("SIGINT" if signum == getattr(signal, "SIGINT", 2)
                          else "SIGTERM")
            self.console.print(
                f"\n[yellow][!] Señal {nombre_sig} — cerrando...[/yellow]"
            )
            self._cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, _handler)
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm is not None:
            signal.signal(sigterm, _handler)

    def _cleanup(self):
        try:
            if self.log:
                self.log.info("Sesión terminada.", "ApexSentinel")
            if getattr(self, "radar", None):
                self.radar.stop_sniffing()
            if getattr(self, "cola", None):
                self.cola.limpiar_completadas()
            if getattr(self, "gp", None) and self.gp.proyecto_activo:
                self.gp.cerrar_proyecto()
            # Cerrar módulo RF de forma segura
            if getattr(self, "rf", None):
                self.rf.cerrar()
        except Exception:
            pass

    # ── Configuración ────────────────────────────────────────────────

    def _cargar_config(self) -> dict:
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"sistema": {"nombre": "Sentinel", "version": self.VERSION,
                                "primer_arranque": True}}
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    # ── Carga de módulos ─────────────────────────────────────────────

    def _cargar_modulos(self):
        """
        Carga todos los módulos tácticos del sistema.
        El módulo RF ahora usa RFModuleIntegrado, que unifica
        hardware real, mock, DSP avanzado, demodulador y base de datos.
        """
        imports = [
            ("checker",      "SystemChecker",    "SystemChecker"),
            ("audit_engine", "AuditEngine",       "AuditEngine"),
            ("dict_manager", "DictionaryManager", "DictionaryManager"),
            ("hydra",        "HydraModule",       "HydraModule"),
            ("reportes",     "ReportManager",     "ReportManager"),
            ("stealth",      "StealthModule",     "Stealth"),
            ("locator",      "LocatorModule",     "LocatorModule"),
            ("exif",         "ExifAnalyzer",      "ExifAnalyzer"),
            ("geopreciose",  "GeoPrecise",        "GeoPrecise"),
            ("wifi_attack",  "WifiAttack",        "WifiAtack"),
            ("reader",       "ForensicReader",    "ForensicReader"),
            ("sniffer",      "TacticalSniffer",   "TacticalSniffer"),
            ("bt",           "BluetoothModule",   "bt_module"),
            ("sweep",        "SweepModule",       "SweepModule"),
            ("ducky",        "DuckyModule",       "DuckyModule"),
            ("adv_scanner",  "AdvancedScanner",   "AdvancedScanner"),
            ("mobile",       "MobileSentinel",    "MobileSentinel"),
            ("security",     "SecurityModule",    "Security"),
            ("network",      "NetworkModule",     "Network"),
            ("phishing",     "PhishingModule",    "PhishingModule"),
        ]

        for attr, clase, modulo in imports:
            Cls = _importar(modulo, clase)
            if Cls is None:
                setattr(self, attr, None)
                continue
            try:
                if clase in ("SystemChecker", "ReportManager", "DictionaryManager"):
                    setattr(self, attr, Cls())
                else:
                    setattr(self, attr, Cls(self))
            except Exception as e:
                self.log.warning(f"{clase} falló al iniciar: {e}", "Init")
                setattr(self, attr, None)

        # ── Radar / Geomap ───────────────────────────────────────────
        try:
            from RadarSentinel import RadarSentinel
            from GeomapSentinel import GeomapSentinel
            self.radar = RadarSentinel(interface="Wi-Fi")
            self.radar.start_sniffing()
            self.geomap = GeomapSentinel()
        except Exception as e:
            self.log.warning(f"Radar/Geomap: {e}", "Init")
            self.radar = self.geomap = None

        # ── EvilTwin ─────────────────────────────────────────────────
        try:
            from EvilTwinServer import iniciar_servidor
            self._evil_twin_server = iniciar_servidor
        except Exception:
            self._evil_twin_server = None

        # ── Extractor DB / WhatsApp ───────────────────────────────────
        self._db_extractor_cls = _importar("db_extractor", "DatabaseExtractor")
        self._wa_decryptor_cls = _importar("WADecryptor",  "WhatsAppDecryptor")

        # ── ForensicReader mejorado (instancia directa) ───────────────
        # El módulo ya está en self.reader vía _cargar_modulos(), pero
        # guardamos la clase para instanciar si el import genérico falló.
        _ForensicReader = _importar("ForensicReader", "ForensicReader")
        if _ForensicReader is not None and self.reader is None:
            try:
                self.reader = _ForensicReader(self)
            except Exception as e:
                self.log.warning(f"ForensicReader directo: {e}", "Init")

        # ── Scapy ────────────────────────────────────────────────────
        try:
            from scapy.all import ARP, Ether, srp
            self._ARP, self._Ether, self._srp = ARP, Ether, srp
        except Exception:
            self._ARP = self._Ether = self._srp = None

        # ── Módulos profesionales ─────────────────────────────────────
        try:
            from GestorProyectos import GestorProyectos
            self.gp = GestorProyectos()
        except Exception as e:
            self.log.warning(f"GestorProyectos: {e}", "Init")
            self.gp = None

        try:
            from MotorReportes import MotorReportes
            self.motor_rep = MotorReportes(self) if self.gp else None
        except Exception as e:
            self.log.warning(f"MotorReportes: {e}", "Init")
            self.motor_rep = None

        try:
            from OSINTEngine import OSINTEngine
            self.osint = OSINTEngine(self)
        except Exception as e:
            self.log.warning(f"OSINTEngine: {e}", "Init")
            self.osint = None

        try:
            from CVEMatcher import CVEMatcher
            self.cve = CVEMatcher(self)
        except Exception as e:
            self.log.warning(f"CVEMatcher: {e}", "Init")
            self.cve = None

        try:
            from ColaTareas import ColaTareas
            self.cola = ColaTareas()
        except Exception as e:
            self.log.warning(f"ColaTareas: {e}", "Init")
            self.cola = None

        try:
            from PluginSystem import GestorPlugins, crear_plugin_ejemplo
            self.plugins = GestorPlugins(self)
            crear_plugin_ejemplo()
            self.plugins.cargar_todos()
        except Exception as e:
            self.log.warning(f"PluginSystem: {e}", "Init")
            self.plugins = None

        # ── RF MODULE INTEGRADO ──────────────────────────────────────
        # Reemplaza el simple self.rf = RFScanner(self) del Main anterior.
        # Ahora unifica hardware real, mock, DSP avanzado,
        # demodulador, base de datos y bands.py.
        try:
            self.rf = RFModuleIntegrado(self)
            self.log.info(
                f"RF Module cargado — {self.rf.hw_nombre}", "Init"
            )
        except Exception as e:
            self.log.warning(f"RFModuleIntegrado: {e}", "Init")
            self.rf = None

    # ── Helpers generales ─────────────────────────────────────────────

    def _iface(self) -> str:
        return getattr(getattr(self, "bt", None), "iface", "wlan0mon")

    def _modulo_ok(self, nombre_attr: str) -> bool:
        m = getattr(self, nombre_attr, None)
        if m is None:
            self.console.print(
                f"[red][!] Módulo '{nombre_attr}' no disponible en este entorno.[/red]"
            )
            return False
        return True

    def animar_barra(self, tarea: str):
        print(f"\n{tarea}")
        largo = 20
        for i in range(largo + 1):
            pct = int((i / largo) * 100)
            print(f"\r[{'█'*i}{'-'*(largo-i)}] {pct}%", end="")
            time.sleep(0.05)
        print("\n[OK] Tarea completada.\n")

    def obtener_fabricante(self, mac: str) -> str:
        try:
            import requests
            r = requests.get(f"https://api.macvendors.com/{mac}", timeout=2)
            return r.text if r.status_code == 200 else "Desconocido"
        except Exception:
            return "Error"

    def mostrar_dashboard_exito(self, ip: str, servicio: str, credencial: str):
        tabla = Table(title="ACCESO OBTENIDO", show_header=True,
                      header_style="bold green")
        tabla.add_column("Objetivo",          style="cyan",
                         justify="center")
        tabla.add_column("Protocolo",         style="yellow",
                         justify="center")
        tabla.add_column("Credenciales (U:P)",
                         style="bold white", justify="center")
        tabla.add_row(ip, servicio.upper(), credencial)
        self.console.print("\n")
        self.console.print(Panel(tabla,
                                 title="[bold green]MISSION ACCOMPLISHED[/bold green]",
                                 border_style="bright_green", expand=False))
        self.log.audit(f"Acceso obtenido en {ip} vía {servicio}", "Hydra")
        if self.gp:
            self.gp.registrar_hallazgo(
                "CRITICO",
                f"Credenciales obtenidas en {ip}:{servicio}",
                f"Credenciales válidas: {credencial}",
                "Cambiar credenciales inmediatamente.",
            )

    def _limpiar(self):
        os.system("cls" if os.name == "nt" else "clear")

    def _run(self, cmd: list, timeout: int = 30,
             **kwargs) -> subprocess.CompletedProcess:
        """Wrapper sobre subprocess.run con timeout garantizado."""
        return subprocess.run(cmd, timeout=timeout, check=True, **kwargs)

    # ── Comandos ─────────────────────────────────────────────────────

    def _cmd_status(self):
        proy = (self.gp.proyecto_activo.nombre
                if self.gp and self.gp.proyecto_activo else "Ninguno")
        rf_estado = getattr(self.rf, "hw_nombre",
                            "No disponible") if self.rf else "No disponible"
        self.console.print(Panel(
            f"[cyan]Sistema:[/cyan]  {self.nombre}\n"
            f"[cyan]Versión:[/cyan]  {self.version}\n"
            f"[cyan]Estado:[/cyan]   [green]Operacional[/green]\n"
            f"[cyan]Hora:[/cyan]     {time.strftime('%H:%M:%S')}\n"
            f"[cyan]Iface:[/cyan]    {self._iface()}\n"
            f"[cyan]Proyecto:[/cyan] [green]{proy}[/green]\n"
            f"[cyan]RF HW:[/cyan]    {rf_estado}",
            title="STATUS", border_style="cyan"
        ))

    def _cmd_files(self):
        self.animar_barra("EXPLORANDO DIRECTORIO LOCAL...")
        tabla = Table(header_style="bold cyan",
                      box=box.SIMPLE_HEAD, show_edge=False)
        tabla.add_column("Nombre", style="white")
        tabla.add_column("Tamaño", style="yellow", justify="right")
        tabla.add_column("Tipo",   style="green",  justify="center")
        try:
            for f in sorted(os.listdir(".")):
                try:
                    tabla.add_row(f, f"{os.path.getsize(f):,} bytes",
                                  "DIR" if os.path.isdir(f) else "FILE")
                except OSError:
                    tabla.add_row(f, "N/A", "?")
            self.console.print(tabla)
        except Exception as e:
            self.log.error(f"files: {e}", "Sistema")

    def _cmd_scan(self):
        if self._ARP is None:
            self.console.print("[red][!] Scapy no disponible.[/red]")
            return
        rango = Validador.pedir_rango(self.console)
        if not rango:
            return
        self.animar_barra(f"ESCANEANDO HOSTS EN {rango}...")
        try:
            resultado = self._srp(
                self._Ether(dst="ff:ff:ff:ff:ff:ff") / self._ARP(pdst=rango),
                timeout=3, verbose=False
            )[0]
            tabla = Table(header_style="bold cyan",
                          box=box.SIMPLE_HEAD, show_edge=False)
            tabla.add_column("IP",         style="cyan",   min_width=15)
            tabla.add_column("MAC",        style="yellow", min_width=18)
            tabla.add_column("Fabricante", style="white")
            hosts = []
            for _, reci in resultado:
                fab = self.obtener_fabricante(reci.hwsrc)
                tabla.add_row(reci.psrc, reci.hwsrc, fab)
                hosts.append(
                    {"ip": reci.psrc, "mac": reci.hwsrc, "fabricante": fab})
            self.console.print(tabla)
            if self.gp:
                self.gp.registrar_evidencia(
                    "arp_scan",
                    f"Scan ARP en {rango}: {len(hosts)} hosts",
                    {"rango": rango, "hosts": hosts}
                )
            self.log.info(
                f"Scan ARP en {rango}: {len(resultado)} hosts", "NetworkScan")
        except Exception:
            self.console.print(
                "[red][!] Error de permisos. Ejecuta como root/administrador.[/red]"
            )

    def _cmd_portscan(self):
        objetivo = Validador.pedir_ip(
            self.console, f"\n{self.nombre} [TARGET IP]")
        if not objetivo:
            return
        self.animar_barra(f"AUDITANDO PUERTOS EN {objetivo}...")
        puertos = {21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
                   80: "HTTP", 443: "HTTPS", 445: "SMB", 3306: "MySQL",
                   5432: "PostgreSQL", 8080: "HTTP-Alt"}
        tabla = Table(header_style="bold red",
                      box=box.SIMPLE_HEAD, show_edge=False)
        tabla.add_column("Puerto",   style="cyan",   justify="center")
        tabla.add_column("Servicio", style="yellow")
        tabla.add_column("Estado",   justify="center")
        abiertos = []
        for puerto, servicio in puertos.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                if sock.connect_ex((objetivo, puerto)) == 0:
                    tabla.add_row(str(puerto), servicio,
                                  "[green]ABIERTO[/green]")
                    abiertos.append({"puerto": puerto, "servicio": servicio})
                sock.close()
            except socket.error:
                pass
        self.console.print(tabla)
        self.console.print(f"[dim]Puertos abiertos: {len(abiertos)}[/dim]")
        if self.gp and abiertos:
            self.gp.registrar_evidencia(
                "portscan",
                f"PortScan en {objetivo}: {len(abiertos)} puertos",
                {"ip": objetivo, "puertos": abiertos}
            )
        self.log.info(
            f"PortScan {objetivo}: {len(abiertos)} puertos abiertos", "PortScan")
        if abiertos and self.cve:
            if Prompt.ask("\n[?] ¿Cruzar con CVE?", choices=["s", "n"], default="s") == "s":
                self.cve.analizar_resultado_scan(
                    [{"nombre": a["servicio"], "version": ""}
                        for a in abiertos]
                )

    def _cmd_sweep(self):
        if not self._modulo_ok("sweep"):
            return
        rango = Validador.pedir_rango(self.console)
        self.sweep.escanear_perimetro(rango)

    def _cmd_sniff(self):
        if not self._modulo_ok("sniffer"):
            return
        filtro = self.console.input(
            "\n[bold cyan]  [?] Filtro (Enter para ninguno)[/bold cyan]: "
        ).strip()
        segundos = Validador.pedir_segundos(self.console, default=30)
        self.sniffer.iniciar_captura(filtro=filtro, duracion=segundos)

    def _cmd_advscan(self):
        if not self._modulo_ok("adv_scanner"):
            return
        ip = Validador.pedir_ip(self.console, "[?] IP del objetivo")
        if ip:
            self.adv_scanner.escanear_objetivo(ip)

    def _cmd_radar(self):
        if not self._modulo_ok("radar") or not self._modulo_ok("geomap"):
            return
        self._limpiar()
        self.geomap.abrir_mapa()
        try:
            while True:
                panel_radar = self.radar.render_radar()
                self.geomap.generar_mapa(self.radar.targets)
                self._limpiar()
                self.console.print(panel_radar)
                time.sleep(2)
        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Radar detenido.[/yellow]")

    def _cmd_audit(self):
        if not self._modulo_ok("hydra") or not self._modulo_ok("dict_manager"):
            return
        self.console.print(
            "\n[bold magenta]⚔  MÓDULO HYDRA INICIADO[/bold magenta]")
        target = Validador.pedir_ip(self.console, "[?] IP del objetivo")
        if not target:
            return
        servicio = Prompt.ask("[?] Servicio",
                              choices=["ssh", "ftp", "mysql",
                                       "http-get", "telnet"],
                              default="ssh")
        diccionario = self.dict_manager.obtener_ruta_diccionario(servicio)
        if Prompt.ask(f"¿Iniciar ataque con {diccionario}?",
                      choices=["s", "n"], default="n") == "s":
            resultado = self.hydra.ejecutar_ataque(
                target, servicio, "root", diccionario)
            if resultado:
                self.mostrar_dashboard_exito(target, servicio, resultado)

    def _cmd_vulnscan(self):
        if not self._modulo_ok("audit_engine"):
            return
        target = Validador.pedir_ip(self.console, "[?] IP a analizar")
        if not target:
            return
        resultado = self.audit_engine.escaneo_vulnerabilidades(target)
        self.console.print(Panel(resultado, title="RESULTADOS DE VULNERABILIDAD",
                                 border_style="red"))
        self.log.audit(f"Vulnscan en {target}", "AuditEngine")

    def _cmd_sqlcheck(self):
        if not self._modulo_ok("audit_engine"):
            return
        url = Validador.pedir_url(self.console, "[?] URL Objetivo")
        if not url:
            return
        resultado = self.audit_engine.auditoria_sql(url)
        self.console.print(
            Panel(resultado, title="INFORME SQLMAP", border_style="yellow"))

    def _cmd_wifi(self):
        if not self._modulo_ok("bt"):
            return
        self.console.print("\n[1] Beacon Spam  [2] Deauth Attack")
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        if opt == "1":
            prefijo = self.console.input(
                "[bold cyan]Prefijo SSID: [/bold cyan]").strip()
            self.bt.beacon_spam(prefijo)
        elif opt == "2":
            mac_vic = Validador.pedir(self.console, "MAC Víctima",
                                      Validador.es_mac, "MAC inválida. Ej: AA:BB:CC:DD:EE:FF")
            mac_ap = Validador.pedir(
                self.console, "MAC AP", Validador.es_mac, "MAC inválida.")
            if mac_vic and mac_ap:
                self.bt.deauth(mac_vic, mac_ap)

    def _cmd_eviltwin(self):
        if not self._modulo_ok("wifi_attack"):
            return
        if self._evil_twin_server is None:
            self.console.print("[red][!] EvilTwinServer no disponible.[/red]")
            return
        ssid = self.console.input("[bold cyan] [?] SSID: [/bold cyan]").strip()
        if not ssid:
            return
        self.wifi_attack.crear_gemelo_malvado(ssid, 6)
        threading.Thread(target=self._evil_twin_server, daemon=True).start()
        input("[!] Presiona Enter para detener...")
        self.wifi_attack.detener_ataques()

    # ── COMANDOS RF — Redirigen al módulo integrado ────────────────────

    def _cmd_rfscan(self):
        """
        Comando rfscan: escaneo de frecuencia con el módulo integrado.
        Usa RFModuleIntegrado que combina hardware real / mock /
        DSP avanzado / demodulador / SQLite / bands.py.
        """
        if not self._modulo_ok("rf"):
            return
        freq = Validador.pedir_frecuencia(self.console)
        if freq is not None:
            duracion = Validador.pedir_segundos(
                self.console, "[?] Duración (segundos)", 1, 300, 10
            )
            self.rf.escanear_frecuencia(freq, duracion)

    def _cmd_rfmenu(self):
        """Abre el menú completo del RF Scanner."""
        if not self._modulo_ok("rf"):
            return
        self.rf.menu()

    def _cmd_rfbarrido(self):
        """Barrido de espectro interactivo."""
        if not self._modulo_ok("rf"):
            return
        ini = Validador.pedir_frecuencia(
            self.console, "[?] Frecuencia inicial (MHz)")
        fin = Validador.pedir_frecuencia(
            self.console, "[?] Frecuencia final (MHz)")
        if ini is None or fin is None or ini >= fin:
            self.console.print("[red][!] Rango de frecuencias inválido.[/red]")
            return
        paso_s = self.console.input(
            "\n[bold cyan][?] Paso MHz [1.0]: [/bold cyan]"
        ).strip()
        try:
            paso = float(paso_s) if paso_s else 1.0
        except ValueError:
            paso = 1.0
        self.rf.barrido_espectro(ini, fin, paso)

    def _cmd_rfbandas(self):
        """Escaneo de todas las bandas conocidas."""
        if not self._modulo_ok("rf"):
            return
        self.rf.escaneo_bandas_conocidas()

    def _cmd_rfdb(self):
        """Consulta la base de datos RF."""
        if not self._modulo_ok("rf"):
            return
        self.rf.db_consultar()

    def _cmd_rfstats(self):
        """Estadísticas de la base de datos RF."""
        if not self._modulo_ok("rf"):
            return
        self.rf.db_estadisticas()

    def _cmd_rfestado(self):
        """Estado completo del módulo RF."""
        if not self._modulo_ok("rf"):
            return
        self.rf.estado()

    # ── Mobile ───────────────────────────────────────────────────────

    def _cmd_mobile(self):
        if not self._modulo_ok("mobile"):
            return
        self.console.print(
            "\n[1] Android Triage  [2] iOS Info  [3] Screenshot")
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        if opt == "1":
            self.mobile.triage_android()
        elif opt == "2":
            self.mobile.triage_ios()
        elif opt == "3":
            path = self.mobile.preparar_directorio("Android_Screen")
            self.console.print("[*] Tomando captura...")
            try:
                self._run(["adb", "shell", "screencap",
                          "-p", "/sdcard/s.png"], timeout=15)
                self._run(["adb", "pull", "/sdcard/s.png",
                          f"{path}/s.png"], timeout=15)
                self.console.print(
                    f"[green][+] Captura guardada en {path}/s.png[/green]")
                self.log.success(
                    f"Screenshot guardado en {path}/s.png", "MobileSentinel")
            except subprocess.TimeoutExpired:
                self.console.print(
                    "[red][!] ADB timeout. Verifica conexión.[/red]")
                self.log.error("ADB timeout screenshot", "MobileSentinel")
            except subprocess.CalledProcessError as e:
                self.console.print(
                    f"[red][!] Error ADB ({e.returncode}): {e}[/red]")
                self.log.error(f"Screenshot ADB: {e}", "MobileSentinel")
            except Exception as e:
                self.console.print(f"[red][!] Error inesperado ADB: {e}[/red]")

    def _cmd_mobile_deep(self):
        path = "./data/evidence/mobile/Deep_Extraction/"
        os.makedirs(path, exist_ok=True)

        self.console.print(
            "\n[1] Extraer WhatsApp Full  "
            "[2] Extraer Chrome History  "
            "[3] Descifrar crypt (WADecryptor)"
        )
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()

        if opt == "1":
            if self._db_extractor_cls is None:
                self.console.print(
                    "[red][!] DatabaseExtractor no disponible.[/red]")
                return
            extractor = self._db_extractor_cls()
            self.animar_barra("EXTRAYENDO DB Y LLAVE...")
            extractor.extraer_whatsapp(path)
            extractor.extraer_whatsapp_key(path)
            self.log.audit("Extracción WhatsApp completada", "MobileDeep")

        elif opt == "2":
            if self._db_extractor_cls is None:
                self.console.print(
                    "[red][!] DatabaseExtractor no disponible.[/red]")
                return
            extractor = self._db_extractor_cls()
            self.animar_barra("EXTRAYENDO HISTORIAL CHROME...")
            self.log.audit("Extracción Chrome completada", "MobileDeep")

        elif opt == "3":
            # ── Descifrado WADecryptor mejorado ───────────────────────
            if self._wa_decryptor_cls is None:
                self.console.print("[red][!] WADecryptor no disponible.[/red]")
                return

            crypt_file = self.console.input(
                "[bold cyan][?] Ruta archivo .crypt12/.crypt14/.crypt15: [/bold cyan]"
            ).strip().strip("'\"")
            key_file = self.console.input(
                "[bold cyan][?] Ruta archivo key: [/bold cyan]"
            ).strip().strip("'\"")

            if not crypt_file or not key_file:
                self.console.print("[red][!] Rutas inválidas.[/red]")
                return

            output_file = os.path.join(path, "whatsapp_decrypted.db")

            try:
                decryptor = self._wa_decryptor_cls(verbose=False)
                ok = decryptor.descifrar(crypt_file, key_file, output_file)
                if ok:
                    self.log.audit(
                        f"WA descifrado OK → {output_file}", "MobileDeep"
                    )
                    self.console.print(
                        f"[green][+] DB lista en: {output_file}[/green]\n"
                        "[dim]Usa el comando [bold white]view[/bold white] "
                        "para leerla.[/dim]"
                    )
                else:
                    self.log.error(
                        "WADecryptor: descifrado fallido", "MobileDeep")
            except Exception as e:
                self.console.print(f"[red][!] Error en descifrado: {e}[/red]")
                self.log.error(f"WADecryptor: {e}", "MobileDeep")

    def _cmd_view(self):
        if not self._modulo_ok("reader"):
            return
        ruta_base = "./data/evidence/mobile/Deep_Extraction/"

        self.console.print(
            "\n[bold cyan]VIEW — Lector Forense[/bold cyan]\n"
            "[1] WhatsApp (Android/iOS auto)\n"
            "[2] Chrome History\n"
            "[3] Firefox places.sqlite\n"
            "[4] Safari History.db\n"
            "[5] Registro de llamadas WA\n"
            "[6] Buscar mensajes eliminados\n"
            "[7] Top contactos + timeline de actividad\n"
            "[8] Buscar palabras clave en mensajes\n"
            "[9] Exportar reporte HTML completo"
        )
        opcion = self.console.input("[bold cyan] > [/bold cyan]").strip()

        if opcion == "1":
            db = self.console.input(
                f"[dim][Enter] = {ruta_base}whatsapp_decrypted.db > [/dim]"
            ).strip() or os.path.join(ruta_base, "whatsapp_decrypted.db")
            self.reader.leer_whatsapp_mensajes(db)

        elif opcion == "2":
            db = self.console.input(
                f"[dim][Enter] = {ruta_base}chrome_history.db > [/dim]"
            ).strip() or os.path.join(ruta_base, "chrome_history.db")
            self.reader.leer_historial_chrome(db)

        elif opcion == "3":
            db = self.console.input(
                f"[dim][Enter] = {ruta_base}places.sqlite > [/dim]"
            ).strip() or os.path.join(ruta_base, "places.sqlite")
            self.reader.leer_historial_firefox(db)

        elif opcion == "4":
            db = self.console.input(
                f"[dim][Enter] = {ruta_base}History.db > [/dim]"
            ).strip() or os.path.join(ruta_base, "History.db")
            self.reader.leer_historial_safari(db)

        elif opcion == "5":
            db = self.console.input(
                f"[dim][Enter] = {ruta_base}whatsapp_decrypted.db > [/dim]"
            ).strip() or os.path.join(ruta_base, "whatsapp_decrypted.db")
            llamadas = self.reader.leer_llamadas_android(db)
            self.reader.mostrar_llamadas(llamadas)

        elif opcion == "6":
            db = self.console.input(
                f"[dim][Enter] = {ruta_base}whatsapp_decrypted.db > [/dim]"
            ).strip() or os.path.join(ruta_base, "whatsapp_decrypted.db")
            eliminados = self.reader.leer_mensajes_eliminados(db)
            if eliminados:
                self.console.print(
                    f"[yellow][!] {len(eliminados)} registros potencialmente eliminados:[/yellow]"
                )
                for e in eliminados:
                    self.console.print(
                        f"  [{e['fecha_display']}] "
                        f"[bold]{e['contacto']}[/bold]: {e['texto_recuperado']}"
                    )
            else:
                self.console.print(
                    "[dim]Sin registros eliminados detectados.[/dim]")

        elif opcion == "7":
            db = self.console.input(
                f"[dim][Enter] = {ruta_base}whatsapp_decrypted.db > [/dim]"
            ).strip() or os.path.join(ruta_base, "whatsapp_decrypted.db")
            mensajes, _ = self.reader.leer_whatsapp_mensajes(db)
            if mensajes:
                stats = self.reader.analizar_frecuencia_contactos(mensajes)
                self.reader.mostrar_frecuencia_contactos(stats)
                tl = self.reader.analizar_timeline_horas(mensajes)
                self.reader.mostrar_timeline_horas(tl)

        elif opcion == "8":
            db = self.console.input(
                f"[dim][Enter] = {ruta_base}whatsapp_decrypted.db > [/dim]"
            ).strip() or os.path.join(ruta_base, "whatsapp_decrypted.db")
            kw_raw = self.console.input(
                "[bold cyan][?] Palabras clave (separadas por espacio): [/bold cyan]"
            ).strip()
            if not kw_raw:
                return
            keywords = kw_raw.split()
            mensajes, _ = self.reader.leer_whatsapp_mensajes(db)
            encontrados = self.reader.buscar_palabras_clave(mensajes, keywords)
            self.console.print(
                f"[yellow]{len(encontrados)} mensajes con: {keywords}[/yellow]"
            )
            for m in encontrados:
                self.console.print(
                    f"  [{m.fecha_iso}] [bold]{m.contacto}[/bold]: {m.texto}"
                )

        elif opcion == "9":
            db = self.console.input(
                f"[dim][Enter] = {ruta_base}whatsapp_decrypted.db > [/dim]"
            ).strip() or os.path.join(ruta_base, "whatsapp_decrypted.db")
            out_html = os.path.join(ruta_base, "reporte_forense.html")

            mensajes, resumen = self.reader.leer_whatsapp_mensajes(db)
            llamadas = self.reader.leer_llamadas_android(db)
            eliminados = self.reader.leer_mensajes_eliminados(db)
            frecuencia = self.reader.analizar_frecuencia_contactos(
                mensajes) if mensajes else None
            timeline = self.reader.analizar_timeline_horas(
                mensajes) if mensajes else None

            self.reader.exportar_html(
                out_html,
                mensajes=mensajes or None,
                resumen=resumen,
                llamadas=llamadas or None,
                eliminados=eliminados or None,
                frecuencia=frecuencia,
                timeline=timeline,
            )
            self.log.audit(
                f"Reporte HTML generado → {out_html}", "ForensicReader")

    def _cmd_locate(self):
        if not self._modulo_ok("locator"):
            return
        ip = Validador.pedir_ip(self.console, "IP objetivo")
        if ip:
            self.locator.rastrear_ip(ip)
            self.log.info(f"Locate en {ip}", "LocatorModule")

    def _cmd_locate_p(self):
        if not self._modulo_ok("adv_scanner") or not self._modulo_ok("geopreciose"):
            return
        redes = self.adv_scanner.obtener_redes_formateadas()
        self.geopreciose.triangular_posicion(redes)

    def _cmd_geofoto(self):
        if not self._modulo_ok("exif"):
            return
        ruta = self.console.input(
            "[bold cyan]Ruta de imagen: [/bold cyan]").strip()
        ruta = ruta.replace("'", "").replace('"', "")
        if ruta:
            self.exif.analizar_foto(ruta)

    def _cmd_phishing(self):
        self._limpiar()
        self.console.print(
            "[bold red][!][/bold red] Iniciando Suite de Phishing...")
        ruta_z = "./tools/zphisher/zphisher.sh"
        if not os.path.exists(ruta_z):
            self.console.print(
                "[red][!] zphisher no encontrado en ./tools/zphisher/[/red]\n"
                "[dim]  git clone https://github.com/htr-tech/zphisher.git tools/zphisher[/dim]"
            )
            return
        try:
            if sys.platform == "win32":
                bash_path = r"C:\Program Files\Git\bin\bash.exe"
                if not os.path.exists(bash_path):
                    self.console.print(
                        "[red][!] Git Bash no encontrado.[/red]")
                    return
                subprocess.run([bash_path, ruta_z], check=True)
            else:
                subprocess.run(["bash", ruta_z], check=True)
        except Exception as e:
            self.console.print(f"[red]Error al lanzar: {e}[/red]")
            self.log.error(f"Phishing: {e}", "PhishingModule")

    def _cmd_ducky(self):
        if not self._modulo_ok("ducky"):
            return
        self.ducky.ejecutar_payload()

    def _cmd_stealth(self):
        if not self._modulo_ok("stealth"):
            return
        self.stealth.verificar_identidad()

    def _cmd_panic(self):
        if not self._modulo_ok("stealth"):
            return
        self.stealth.activar_panico()

    def _cmd_netscan(self):
        self._cmd_scan()

    def _cmd_proyecto(self, args: list):
        if not self._modulo_ok("gp"):
            return
        sub = args[0] if args else ""
        acciones = {
            "nuevo":  self.gp.crear_proyecto,
            "cargar": self.gp.cargar_proyecto,
            "lista":  self.gp.listar_proyectos,
            "list":   self.gp.listar_proyectos,
            "estado": self.gp.mostrar_resumen,
            "cerrar": self.gp.cerrar_proyecto,
        }
        accion = acciones.get(sub)
        if accion:
            accion()
        else:
            self.console.print(
                "[dim]Subcomandos: [bold white]nuevo | cargar | lista | estado | cerrar[/bold white][/dim]"
            )

    def _cmd_reporte(self, args: list):
        if not self._modulo_ok("motor_rep"):
            return
        sub = args[0] if args else ""
        if sub == "resumen":
            self.motor_rep.generar_resumen_ejecutivo()
        elif sub == "timeline":
            self.motor_rep.generar_timeline()
        else:
            self.motor_rep.generar_reporte_completo()

    def _cmd_osint(self):
        if not self._modulo_ok("osint"):
            return
        self.osint.menu()

    def _cmd_cve(self):
        if not self._modulo_ok("cve"):
            return
        self.cve.busqueda_libre()

    def _cmd_jobs(self, args: list):
        if not self._modulo_ok("cola"):
            return
        sub = args[0] if args else ""
        if sub == "resultado" and len(args) > 1:
            self.cola.resultado(args[1])
        elif sub == "cancelar" and len(args) > 1:
            self.cola.cancelar(args[1])
        elif sub == "limpiar":
            self.cola.limpiar_completadas()
        else:
            self.cola.listar()

    def _cmd_plugins(self, args: list):
        if not self._modulo_ok("plugins"):
            return
        sub = args[0] if args else ""
        if sub == "reload":
            self.plugins.recargar()
        elif sub == "ayuda" and len(args) > 1:
            p = self.plugins._plugins.get(args[1])
            if p:
                self.console.print(Panel(p.ayuda(), border_style="green"))
            else:
                self.console.print(
                    f"[red][!] Plugin '{args[1]}' no encontrado.[/red]")
        else:
            self.plugins.listar()

    # ── Despachador ───────────────────────────────────────────────────

    def _despachar(self, entrada: str) -> bool:
        partes = entrada.strip().lower().split()
        if not partes:
            return True
        cmd = partes[0]
        args = partes[1:]

        # Subcomandos con args
        if cmd == "proyecto":
            self._cmd_proyecto(args)
            return True
        if cmd == "reporte":
            self._cmd_reporte(args)
            return True
        if cmd in ("job", "jobs"):
            self._cmd_jobs(args)
            return True
        if cmd in ("plugin", "plugins"):
            self._cmd_plugins(args)
            return True
        if cmd == "locate":
            (self._cmd_locate_p if "-p" in args else self._cmd_locate)()
            return True

        tabla = {
            # ── Generales ───────────────────────────────────────────
            "help": lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "?": lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "status":       self._cmd_status,
            "hora": lambda: self.console.print(
                f"[cyan]Hora:[/cyan] {time.strftime('%H:%M:%S')}"),
            "clear": lambda: mostrar_banner(
                self.console, self.nombre, self.version, self._iface()),
            "cls": lambda: mostrar_banner(
                self.console, self.nombre, self.version, self._iface()),
            "logs":         self.log.mostrar_historial,
            "files":        self._cmd_files,
            # ── Red ─────────────────────────────────────────────────
            "scan":         self._cmd_scan,
            "netscan":      self._cmd_netscan,
            "advscan":      self._cmd_advscan,
            "portscan":     self._cmd_portscan,
            "sweep":        self._cmd_sweep,
            "sniff":        self._cmd_sniff,
            "radar":        self._cmd_radar,
            "audit":        self._cmd_audit,
            "vulnscan":     self._cmd_vulnscan,
            "sqlcheck":     self._cmd_sqlcheck,
            # ── Wireless ─────────────────────────────────────────────
            "wifi":         self._cmd_wifi,
            "eviltwin":     self._cmd_eviltwin,
            "btjumper": lambda: (
                self.bt.iniciar_jumper() if self._modulo_ok("bt") else None
            ),
            # ── RF — comandos integrados ──────────────────────────────
            "rfscan":       self._cmd_rfscan,       # escaneo frecuencia
            "rfmenu":       self._cmd_rfmenu,       # menú completo RF
            "rfbarrido":    self._cmd_rfbarrido,    # barrido de espectro
            "rfbandas":     self._cmd_rfbandas,     # escaneo bandas conocidas
            "rfdb":         self._cmd_rfdb,         # consulta DB
            "rfstats":      self._cmd_rfstats,      # estadísticas DB
            "rfstatus":     self._cmd_rfestado,     # estado del módulo
            # ── Mobile ───────────────────────────────────────────────
            "mobile":       self._cmd_mobile,
            "mobile-deep":  self._cmd_mobile_deep,
            "view":         self._cmd_view,
            # ── OSINT / Geo ──────────────────────────────────────────
            "geofoto":      self._cmd_geofoto,
            "osint":        self._cmd_osint,
            "cve":          self._cmd_cve,
            # ── Ofensivo ─────────────────────────────────────────────
            "phishing":     self._cmd_phishing,
            "ducky":        self._cmd_ducky,
            # ── Stealth ──────────────────────────────────────────────
            "stealth":      self._cmd_stealth,
            "panic":        self._cmd_panic,
        }

        if cmd in tabla:
            tabla[cmd]()
            return True

        if self.plugins and self.plugins.tiene_comando(cmd):
            self.plugins.ejecutar_comando(cmd, args)
            return True

        return False

    # ── Bucle principal ───────────────────────────────────────────────

    def ejecutar(self):
        if not self.auth.solicitar_acceso():
            self.console.print(
                "[red][!] Acceso denegado. Sistema bloqueado.[/red]")
            self.log.warning(
                "Sistema bloqueado por intentos fallidos.", "GestorAuth")
            return

        mostrar_bootloader(self.console, self.nombre,
                           self.version, self._iface())

        self.console.print(
            "[bold blue][*] Diagnosticando dependencias...[/bold blue]")
        if self.checker:
            self.checker.verificar_dependencias()

        self.log.verificar_y_limpiar()

        if self.stealth:
            self.stealth.verificar_identidad()

        self.log.info("Sistema iniciado correctamente.", "ApexSentinel")

        # Mostrar estado del módulo RF al arrancar
        if self.rf:
            rf_status = (
                f"[green]{self.rf.hw_nombre}[/green]"
                if self.rf.hw_disponible
                else f"[yellow]{self.rf.hw_nombre}[/yellow]"
            )
            self.console.print(
                f"\n[dim][RF] Hardware: {rf_status}[/dim]"
            )

        if self.gp and not self.gp.proyecto_activo:
            self.console.print(
                "\n[dim][tip] Usa [bold white]proyecto nuevo[/bold white] "
                "para crear un workspace de operación.[/dim]\n"
            )

        while True:
            try:
                plab = ""
                if self.gp and self.gp.proyecto_activo:
                    from rich.markup import escape as _esc
                    plab = f"[{_esc(str(self.gp.proyecto_activo.nombre))}]"
                prompt_str = (
                    f"[bold green]AnubisOS[/bold green]"
                    f"[dim white]@[/dim white]"
                    f"[bold cyan]Sentinel[/bold cyan]"
                    f"[dim]{plab}[/dim]"
                    f"[bold white]~#[/bold white]"
                )
                entrada = Prompt.ask(prompt_str, default="").strip()
                if not entrada:
                    continue
                if entrada.lower() == "exit":
                    self.console.print(
                        "[yellow][!] Desconectando Sentinel...[/yellow]")
                    self.log.info(
                        "Sesión cerrada por el operador.", "ApexSentinel")
                    self._cleanup()
                    time.sleep(0.5)
                    break
                if not self._despachar(entrada):
                    self.console.print(
                        f"[yellow][?] Comando '[bold]{entrada}[/bold]' no reconocido. "
                        f"Escribe [bold white]help[/bold white] para ver opciones.[/yellow]"
                    )
            except EOFError:
                self._cleanup()
                break
            except Exception as e:
                self.console.print(f"[red][!] Error inesperado: {e}[/red]")
                self.log.error(str(e), "Bucle principal")


# ════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    for d in ["data/logs", "data/evidence", "data/evidence/rf",
              "data/evidence/rf/iq", "plugins"]:
        os.makedirs(d, exist_ok=True)

    sentinel = ApexSentinel()
    sentinel.ejecutar()
