import os
import csv
import sys
import time
import threading
from datetime import datetime
from collections import deque

import numpy as np

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.align import Align
from rich import box

# ════════════════════════════════════════════════════════════════════
# DETECCIÓN DE HARDWARE
# ════════════════════════════════════════════════════════════════════

SDR_TIPO = None   # "RTL-SDR" | "HackRF" | None
SDR_CLASE = None   # Clase del driver

try:
    from rtlsdr import RtlSdr as _RtlSdr
    SDR_TIPO = "RTL-SDR"
    SDR_CLASE = _RtlSdr
except ImportError:
    pass

if SDR_TIPO is None:
    try:
        import SoapySDR as _SoapySDR
        devs = _SoapySDR.Device.enumerate()
        if devs:
            SDR_TIPO = devs[0].get("driver", "SoapySDR").upper()
            SDR_CLASE = _SoapySDR.Device
    except Exception:
        pass

# ════════════════════════════════════════════════════════════════════
# BASE DE DATOS DE BANDAS DE FRECUENCIA
# ════════════════════════════════════════════════════════════════════

BANDAS = [
    # (freq_min_MHz, freq_max_MHz, nombre, tipo, descripcion, color_rich)
    (26.9,   27.4,   "CB Radio",         "PMR",
     "Banda ciudadana 27MHz",             "yellow"),
    (87.5,   108.0,  "FM Radio",         "BROADCAST",
     "Radiodifusión FM comercial",         "cyan"),
    (108.0,  118.0,  "VOR/ILS",          "AVIATION",
     "Radionavegación VOR e ILS",          "blue"),
    (118.0,  137.0,  "ATC Voice",        "AVIATION",
     "Control de tráfico aéreo — voz",     "blue"),
    (137.0,  138.0,  "NOAA/MetSat",      "SATELLITE",
     "Imágenes meteorológicas NOAA",       "magenta"),
    (138.0,  144.0,  "Militar VHF",      "MILITARY",
     "Comunicaciones militares VHF",       "red"),
    (144.0,  148.0,  "VHF Amateur",      "AMATEUR",
     "Radio amateur VHF (2m)",             "green"),
    (150.0,  174.0,  "VHF PMR",          "PMR",
     "Radio móvil profesional VHF",        "yellow"),
    (162.0,  162.55, "NOAA Weather",     "BROADCAST",
     "Radio meteorológica NOAA",           "cyan"),
    (315.0,  315.1,  "ISM 315MHz",       "ISM",
     "Mandos a distancia 315MHz",          "orange3"),
    (406.0,  406.1,  "EPIRB/ELT",        "SAFETY",
     "Balizas de emergencia COSPAS-SARSAT", "bright_red"),
    (430.0,  440.0,  "UHF Amateur",      "AMATEUR",
     "Radio amateur UHF (70cm)",           "green"),
    (433.05, 434.79, "ISM 433MHz",       "ISM",
     "IoT, sensores, LoRa EU, mandos",     "orange3"),
    (446.0,  446.2,  "PMR446",           "PMR",
     "Walkie-talkies civiles sin licencia", "yellow"),
    (450.0,  470.0,  "UHF PMR",          "PMR",
     "Radio móvil profesional UHF",        "yellow"),
    (462.5,  462.7,  "GMRS/FRS",         "PMR",
     "Servicio móvil general USA",         "yellow"),
    (470.0,  694.0,  "TDT",              "BROADCAST",
     "Televisión digital terrestre",       "cyan"),
    (806.0,  869.0,  "TETRA/LMR",        "PMR",
     "Radio digital TETRA, Motorola",      "yellow"),
    (862.0,  870.0,  "ISM 868MHz",       "ISM",
     "LoRa EU, Sigfox, Zigbee, Z-Wave",   "orange3"),
    (902.0,  928.0,  "ISM 915MHz",       "ISM",
     "LoRa US, RFID, DSSS",                "orange3"),
    (929.0,  932.0,  "Paging",           "PAGING",
     "Servicio de búsqueda de personas",   "dim"),
    (935.0,  960.0,  "GSM 900 DL",       "CELLULAR",
     "Downlink GSM 900 MHz",               "red"),
    (1090.0, 1090.1, "ADS-B",            "AVIATION",
     "Transponder aeronaves — posición",   "bright_blue"),
    (1215.0, 1300.0, "GPS L2 / GNSS",    "GNSS",
     "GPS L2, GLONASS, Galileo",           "bright_cyan"),
    (1525.0, 1559.0, "Inmarsat",         "SATELLITE",
     "Satélite Inmarsat — marítimo/aéreo", "magenta"),
    (1559.0, 1610.0, "GPS L1 / GNSS",    "GNSS",
     "GPS L1 (1575.42MHz), Galileo E1",   "bright_cyan"),
    (1710.0, 1785.0, "LTE Band 4 UL",    "CELLULAR",
     "Uplink LTE AWS-1",                   "red"),
    (1805.0, 1880.0, "GSM/LTE 1800 DL",  "CELLULAR",
     "Downlink DCS-1800 / LTE B3",         "red"),
    (1920.0, 1980.0, "UMTS/LTE UL",      "CELLULAR",
     "Uplink 3G/4G banda IMT",             "red"),
    (2110.0, 2170.0, "UMTS/LTE DL",      "CELLULAR",
     "Downlink 3G/4G banda IMT",           "red"),
    (2400.0, 2484.0, "Wi-Fi / BT 2.4G",  "WIRELESS",
     "Wi-Fi 802.11b/g/n, Bluetooth",      "bright_green"),
    (2483.5, 2500.0, "ISM 2.4GHz",       "ISM",
     "Cordless phones, ZigBee",            "orange3"),
    (3400.0, 3800.0, "5G NR n78",        "CELLULAR",
     "5G banda media C-band",              "bright_red"),
    (5150.0, 5850.0, "Wi-Fi 5GHz",       "WIRELESS",
     "Wi-Fi 802.11a/n/ac/ax",             "bright_green"),
]


# ════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE HARDWARE
# ════════════════════════════════════════════════════════════════════

class ConfigSDR:
    """Parámetros de configuración del receptor SDR."""

    # RTL-SDR
    RTLSDR_SAMPLE_RATE = 2.048e6    # Hz  — máximo estable para RTL-SDR
    RTLSDR_GAIN_DEFAULT = 40.2       # dB  — ganancia moderada en campo
    # ppm — corrección de cristal (calibrar con kalibrate-rtl)
    RTLSDR_PPM = 0

    # FFT
    FFT_SIZE = 2048              # Resolución del espectro (potencia de 2)
    SAMPLES_N = 512 * 1024        # Muestras por captura
    VENTANA = "blackman"        # blackman > hann > hamming para rechazo de lóbulos
    PROMEDIO_N = 3                 # Capturas a promediar (reduce ruido)

    # Detección de señales
    UMBRAL_MARGEN_DB = 12.0          # dB sobre el piso de ruido para detección
    UMBRAL_ABS_DBM = -85.0         # dBm mínimo absoluto
    PICOS_MAX = 20            # Máximo de picos a reportar por captura

    # Waterfall
    WATERFALL_ROWS = 15            # Historial de capturas mostradas
    WATERFALL_ANCHO = 64            # Columnas del waterfall

    # Exportación
    EXPORT_PATH = "data/evidence/rf"


# ════════════════════════════════════════════════════════════════════
# MOTOR DSP — PROCESAMIENTO DE SEÑAL DIGITAL
# ════════════════════════════════════════════════════════════════════

class MotorDSP:
    """
    Motor de procesamiento de señal digital.
    Implementa FFT, estimación de piso de ruido y detección de picos.
    """

    VENTANAS = {
        "blackman": np.blackman,   # Mejor rechazo de lóbulos laterales
        "hann":     np.hanning,    # Balance entre resolución y rechazo
        "hamming":  np.hamming,    # Buena resolución de frecuencia
        "flat_top":  None,         # Mejor para medición de amplitud
    }

    def __init__(self, fft_size: int = ConfigSDR.FFT_SIZE,
                 ventana: str = ConfigSDR.VENTANA):
        self.fft_size = fft_size
        self.ventana_n = ventana
        self._ventana = self._crear_ventana(ventana, fft_size)
        self._factor_ventana = np.sum(self._ventana ** 2)

    def _crear_ventana(self, nombre: str, n: int) -> np.ndarray:
        if nombre == "flat_top":
            # Ventana Flat-top para medición precisa de amplitud
            a = [0.21557895, 0.41663158, 0.27726316, 0.08357895, 0.00694737]
            w = np.zeros(n)
            for k, ak in enumerate(a):
                w += ak * np.cos(2 * np.pi * k * np.arange(n) / n)
            return w
        fn = self.VENTANAS.get(nombre, np.blackman)
        return fn(n)

    def calcular_psd(self, muestras: np.ndarray,
                     sample_rate: float) -> tuple[np.ndarray, np.ndarray]:
        """
        Calcula la Densidad Espectral de Potencia.

        Proceso:
          1. Toma bloque central de muestras
          2. Aplica ventana para reducir spectral leakage
          3. FFT con zero-padding para mayor resolución
          4. Convierte a dBm con referencia correcta
          5. Aplica corrección por factor de ventana

        Retorna:
          freqs_hz  : array de frecuencias relativas al centro (Hz)
          psd_dbm   : array de potencia en dBm
        """
        n = self.fft_size

        # Extraer bloque central (evitar transitorios de inicio/fin)
        centro = len(muestras) // 2
        bloque = muestras[centro - n//2: centro + n//2]

        if len(bloque) < n:
            bloque = np.pad(bloque, (0, n - len(bloque)))

        # Aplicar ventana
        bloque_ventana = bloque[:n] * self._ventana

        # FFT y centrar en DC
        espectro = np.fft.fftshift(np.fft.fft(bloque_ventana, n=n))

        # Potencia normalizada por factor de ventana y número de puntos
        potencia = (np.abs(espectro) ** 2) / self._factor_ventana

        # Convertir a dBm (referencia: 1 mW en impedancia normalizada)
        potencia = np.maximum(potencia, 1e-15)  # Evitar log(0)
        psd_dbm = 10.0 * np.log10(potencia) + 30.0

        # Eje de frecuencias relativas
        freqs_hz = np.fft.fftshift(
            np.fft.fftfreq(n, d=1.0 / sample_rate)
        )

        return freqs_hz, psd_dbm

    def promediar_capturas(self, capturas: list[np.ndarray]) -> np.ndarray:
        """
        Promedia múltiples capturas de PSD para reducir ruido.
        Usa promedio en escala lineal (no dBm) para resultado correcto.
        """
        lineales = [10 ** (c / 10.0) for c in capturas]
        promedio = np.mean(lineales, axis=0)
        return 10.0 * np.log10(np.maximum(promedio, 1e-15))

    def estimar_piso_ruido(self, psd_dbm: np.ndarray) -> float:
        """
        Estima el piso de ruido usando la mediana del espectro.
        La mediana es robusta frente a picos de señal.
        Se excluye el 10% central (posible señal DC offset del SDR).
        """
        n = len(psd_dbm)
        excl = int(n * 0.05)
        datos = np.concatenate([psd_dbm[:n//2 - excl],
                                psd_dbm[n//2 + excl:]])
        return float(np.median(datos))

    def detectar_picos(self, freqs_hz: np.ndarray,
                       psd_dbm: np.ndarray,
                       freq_centro_hz: float,
                       sample_rate: float) -> list[dict]:
        """
        Detecta picos de señal sobre el umbral dinámico.

        Algoritmo:
          1. Calcular piso de ruido (mediana)
          2. Umbral = piso + margen configurable
          3. Buscar máximos locales sobre el umbral
          4. Para cada pico: calcular freq absoluta, BW a -3dB, SNR
          5. Filtrar picos demasiado cercanos (resolución de frecuencia)
        """
        piso = self.estimar_piso_ruido(psd_dbm)
        umbral = max(piso + ConfigSDR.UMBRAL_MARGEN_DB,
                     ConfigSDR.UMBRAL_ABS_DBM)

        resolucion_hz = sample_rate / self.fft_size
        min_separacion = int(10e3 / resolucion_hz)  # 10 kHz mínimo entre picos

        picos = []
        n = len(psd_dbm)
        i = 1

        while i < n - 1 and len(picos) < ConfigSDR.PICOS_MAX:
            # Máximo local sobre umbral
            if psd_dbm[i] >= umbral and \
               psd_dbm[i] > psd_dbm[i-1] and \
               psd_dbm[i] > psd_dbm[i+1]:

                # Refinar posición del pico (interpolación cuadrática)
                idx_fino = self._refinar_pico(psd_dbm, i)

                # Frecuencia absoluta
                freq_rel_hz = float(np.interp(idx_fino,
                                              np.arange(n), freqs_hz))
                freq_abs_hz = freq_centro_hz + freq_rel_hz
                freq_abs_mhz = freq_abs_hz / 1e6

                # Ancho de banda a -3dB
                bw_hz = self._bw_3db(psd_dbm, i, freqs_hz)

                # SNR
                snr_db = float(psd_dbm[i]) - piso

                picos.append({
                    "freq_mhz":  round(freq_abs_mhz, 4),
                    "freq_hz":   freq_abs_hz,
                    "potencia":  round(float(psd_dbm[i]), 1),
                    "snr_db":    round(snr_db, 1),
                    "bw_hz":     round(bw_hz, 0),
                    "bw_khz":    round(bw_hz / 1e3, 2),
                    "piso_dbm":  round(piso, 1),
                    "timestamp": datetime.now().isoformat(),
                })

                # Avanzar más allá del ancho de la señal
                i += max(min_separacion,
                         int(bw_hz / resolucion_hz) // 2 + 1)
            else:
                i += 1

        # Ordenar por SNR descendente
        return sorted(picos, key=lambda p: p["snr_db"], reverse=True)

    def _refinar_pico(self, psd: np.ndarray, idx: int) -> float:
        """Interpolación cuadrática para precisión sub-bin."""
        if idx <= 0 or idx >= len(psd) - 1:
            return float(idx)
        a = psd[idx - 1]
        b = psd[idx]
        c = psd[idx + 1]
        denom = 2 * (2 * b - a - c)
        if abs(denom) < 1e-10:
            return float(idx)
        return idx + (a - c) / denom

    def _bw_3db(self, psd: np.ndarray, idx_pico: int,
                freqs_hz: np.ndarray) -> float:
        """Calcula ancho de banda a -3dB del pico."""
        nivel_3db = psd[idx_pico] - 3.0
        n = len(psd)

        izq = idx_pico
        while izq > 0 and psd[izq] > nivel_3db:
            izq -= 1

        der = idx_pico
        while der < n - 1 and psd[der] > nivel_3db:
            der += 1

        return abs(float(freqs_hz[der]) - float(freqs_hz[izq]))


# ════════════════════════════════════════════════════════════════════
# RENDERIZADOR — VISUALIZACIÓN EN TERMINAL
# ════════════════════════════════════════════════════════════════════

WATERFALL_CHARS = " ·░▒▓█"
BARRA_INTENSIDAD = " ▁▂▃▄▅▆▇█"


class Renderizador:
    """Renderiza espectro, waterfall y tablas en terminal Rich."""

    def __init__(self, console: Console):
        self.console = console

    def espectro(self, freqs_hz: np.ndarray, psd_dbm: np.ndarray,
                 freq_centro_mhz: float, picos: list,
                 sample_rate: float, hw: str) -> Panel:
        """
        Renderiza el espectro de potencia como gráfico ASCII.
        Incluye:
          - Eje Y en dBm con escala real
          - Barras coloreadas por intensidad (verde → amarillo → rojo)
          - Línea de umbral visual
          - Marcadores de picos detectados
          - Etiquetas de frecuencia en eje X
        """
        ancho = ConfigSDR.WATERFALL_ANCHO
        alto = 14
        db_min = -110.0
        db_max = -20.0

        # Remuestrear PSD al ancho de pantalla
        idx = np.linspace(0, len(psd_dbm) - 1, ancho).astype(int)
        psd_d = psd_dbm[idx]

        def y(val):
            return int(np.clip(
                (val - db_min) / (db_max - db_min) * alto, 0, alto
            ))

        alturas = [y(v) for v in psd_d]
        piso = np.median(psd_dbm)
        umbral_y = y(piso + ConfigSDR.UMBRAL_MARGEN_DB)

        texto = Text()

        for fila in range(alto, -1, -1):
            db_label = db_min + (fila / alto) * (db_max - db_min)
            texto.append(f"{db_label:>6.0f} │", style="dim green")

            for col, h in enumerate(alturas):
                if h >= fila:
                    ratio = h / alto
                    if ratio >= 0.85:
                        texto.append("█", style="bold red")
                    elif ratio >= 0.65:
                        texto.append("█", style="red")
                    elif ratio >= 0.45:
                        texto.append("█", style="yellow")
                    elif ratio >= 0.25:
                        texto.append("█", style="green")
                    else:
                        texto.append("▄", style="dim green")
                elif fila == umbral_y:
                    texto.append("─", style="dim red")
                else:
                    texto.append(" ")
            texto.append("\n")

        # Eje X
        bw_mhz = sample_rate / 1e6
        freq_ini = freq_centro_mhz - bw_mhz / 2
        freq_fin = freq_centro_mhz + bw_mhz / 2

        texto.append("       └" + "─" * ancho + "\n", style="dim green")
        etiqueta = (f"  {freq_ini:.3f}"
                    + " " * (ancho // 2 - 8)
                    + f"{freq_centro_mhz:.3f} [centro]"
                    + " " * (ancho // 2 - 10)
                    + f"{freq_fin:.3f} MHz\n")
        texto.append(etiqueta, style="dim green")

        # Info de picos en el gráfico
        if picos:
            texto.append(
                f"\n  [dim red]▲ umbral: piso({piso:.0f}) + "
                f"{ConfigSDR.UMBRAL_MARGEN_DB}dB = "
                f"{piso + ConfigSDR.UMBRAL_MARGEN_DB:.0f} dBm[/dim red]\n"
            )

        hw_tag = f"[dim]{hw}[/dim]"
        ts = datetime.now().strftime("%H:%M:%S")
        return Panel(
            texto,
            title=(f"[bold green]ESPECTRO RF — "
                   f"{freq_centro_mhz:.4f} MHz[/bold green]  "
                   f"{hw_tag}  [dim]{ts}[/dim]"),
            border_style="green",
            box=box.HEAVY_HEAD,
        )

    def waterfall(self, historial: deque,
                  freq_centro_mhz: float) -> Panel:
        """
        Renderiza el waterfall (cascada temporal).
        Más reciente arriba, más antiguo abajo.
        Intensidad de color indica potencia.
        """
        if not historial:
            return Panel("[dim]Sin datos de waterfall.[/dim]",
                         title="WATERFALL", border_style="dim green")

        ancho = ConfigSDR.WATERFALL_ANCHO
        texto = Text()
        db_min, db_max = -110.0, -20.0

        for i, psd in enumerate(historial):
            idx = np.linspace(0, len(psd) - 1, ancho).astype(int)
            fila = psd[idx]
            antigüedad = i / max(len(historial) - 1, 1)  # 0=nuevo, 1=viejo

            texto.append("  ")
            for val in fila:
                v = np.clip((val - db_min) / (db_max - db_min), 0, 1)
                cidx = int(v * (len(WATERFALL_CHARS) - 1))
                char = WATERFALL_CHARS[cidx]

                if v > 0.75:
                    style = "bold red" if antigüedad < 0.3 else "red"
                elif v > 0.50:
                    style = "yellow" if antigüedad < 0.3 else "dark_orange"
                elif v > 0.25:
                    style = "green" if antigüedad < 0.3 else "dark_green"
                else:
                    style = "dim"

                texto.append(char, style=style)
            texto.append("\n")

        return Panel(
            texto,
            title=(f"[bold green]WATERFALL — "
                   f"{freq_centro_mhz:.3f} MHz[/bold green]  "
                   f"[dim]{len(historial)} capturas[/dim]"),
            border_style="dim green",
            box=box.SIMPLE,
        )

    def tabla_picos(self, picos: list) -> Panel:
        """Tabla de señales detectadas con clasificación y métricas."""
        if not picos:
            return Panel(
                "[dim]No se detectaron señales sobre el umbral de detección.[/dim]",
                title="[green]SEÑALES DETECTADAS[/green]",
                border_style="dim green",
            )

        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia",  style="cyan",  min_width=15, no_wrap=True)
        tb.add_column("Potencia",    justify="right", min_width=11)
        tb.add_column("SNR",         justify="right", min_width=8)
        tb.add_column("BW",          justify="right", min_width=10)
        tb.add_column("Banda",       min_width=16)
        tb.add_column("Tipo",        min_width=10)
        tb.add_column("Descripción", style="dim", min_width=20)

        for p in picos:
            # Estilo según potencia
            if p["potencia"] > -50:
                pot_t = Text(f"{p['potencia']:.1f} dBm", style="bold red")
            elif p["potencia"] > -70:
                pot_t = Text(f"{p['potencia']:.1f} dBm", style="yellow")
            else:
                pot_t = Text(f"{p['potencia']:.1f} dBm", style="green")

            banda = p.get("banda")
            b_str = "—"
            t_str = "—"
            d_str = "—"
            if banda:
                col = banda["color"]
                b_str = f"[{col}]{banda['nombre']}[/{col}]"
                t_str = f"[{col}]{banda['tipo']}[/{col}]"
                d_str = banda["desc"][:28]

            tb.add_row(
                f"{p['freq_mhz']:.4f} MHz",
                pot_t,
                f"{p['snr_db']:.1f} dB",
                f"{p['bw_khz']:.2f} kHz",
                b_str, t_str, d_str,
            )

        return Panel(
            tb,
            title=f"[bold green]SEÑALES DETECTADAS  [{len(picos)}][/bold green]",
            border_style="green",
            box=box.HEAVY_HEAD,
        )

    def resumen_escaneo(self, freq_mhz: float, picos: list,
                        duracion: float, hw: str,
                        iteraciones: int) -> Panel:
        """Panel de resumen al finalizar el escaneo."""
        snr_max = max((p["snr_db"] for p in picos), default=0)
        pot_max = max((p["potencia"] for p in picos), default=-999)
        bw_med = (sum(p["bw_khz"] for p in picos) / len(picos)
                  if picos else 0)

        bandas = set()
        for p in picos:
            if p.get("banda"):
                bandas.add(p["banda"]["nombre"])

        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim green", justify="right", min_width=22)
        g.add_column(style="white")

        g.add_row("Frecuencia",        f"{freq_mhz:.4f} MHz")
        g.add_row("Hardware",          hw)
        g.add_row("Duración",          f"{duracion:.1f} s")
        g.add_row("Iteraciones FFT",   str(iteraciones))
        g.add_row("Señales detectadas", str(len(picos)))
        g.add_row("Potencia máxima",   f"{pot_max:.1f} dBm")
        g.add_row("SNR máximo",        f"{snr_max:.1f} dB")
        g.add_row("BW promedio",       f"{bw_med:.2f} kHz")
        g.add_row("Bandas",            ", ".join(bandas) if bandas else "—")

        return Panel(g,
                     title="[bold green]RESUMEN DEL ESCANEO[/bold green]",
                     border_style="green")

    def mapa_barrido(self, resultados: list) -> Panel:
        """Mapa visual de actividad para barrido de espectro."""
        tb = Table(box=box.SIMPLE_HEAD, header_style="bold green",
                   show_edge=False, expand=True)
        tb.add_column("Frecuencia",  style="cyan",  min_width=14, no_wrap=True)
        tb.add_column("Actividad",   min_width=18)
        tb.add_column("Pot. máx",    justify="right", min_width=11)
        tb.add_column("SNR",         justify="right", min_width=8)
        tb.add_column("Piso RF",     justify="right", min_width=10)
        tb.add_column("Banda",       min_width=18)

        ordenados = sorted(resultados,
                           key=lambda x: x["snr"], reverse=True)

        for r in ordenados[:30]:
            nivel = int(np.clip(r["snr"] / 35 * 16, 0, 16))
            barra = "█" * nivel + "·" * (16 - nivel)

            if r["snr"] > 25:
                b_sty = "bold red"
                p_sty = "bold red"
            elif r["snr"] > 15:
                b_sty = "yellow"
                p_sty = "yellow"
            elif r["snr"] > 8:
                b_sty = "green"
                p_sty = "green"
            else:
                b_sty = "dim"
                p_sty = "dim"

            banda_n = "—"
            if r.get("banda"):
                col = r["banda"]["color"]
                banda_n = f"[{col}]{r['banda']['nombre']}[/{col}]"

            tb.add_row(
                f"{r['freq_mhz']:.3f} MHz",
                Text(barra, style=b_sty),
                Text(f"{r['pot_max']:.1f} dBm", style=p_sty),
                f"{r['snr']:.1f} dB",
                f"{r['piso']:.1f} dBm",
                banda_n,
            )

        return Panel(tb,
                     title="[bold green]MAPA DE ACTIVIDAD RF[/bold green]",
                     border_style="green",
                     box=box.HEAVY_HEAD)


# ════════════════════════════════════════════════════════════════════
# RF SCANNER — CLASE PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class RFScanner:
    """
    Escáner de radiofrecuencia profesional para AnubisOS.

    Uso desde el Main:
        self.rf.escanear_frecuencia(433.92)
        self.rf.barrido_espectro(400, 500, paso_mhz=0.5)
        self.rf.menu()
    """

    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.console = getattr(sentinel, "console", Console())
        self.log = getattr(sentinel, "log",     None)
        self.gp = getattr(sentinel, "gp",      None)

        # Hardware
        self.sdr = None
        self.sample_rate = ConfigSDR.RTLSDR_SAMPLE_RATE
        self.gain = ConfigSDR.RTLSDR_GAIN_DEFAULT
        self.hw_nombre = "No inicializado"
        self._lock = threading.Lock()

        # Motores
        self.dsp = MotorDSP()
        self.render = Renderizador(self.console)

        # Estado de sesión
        self._waterfall = deque(maxlen=ConfigSDR.WATERFALL_ROWS)
        self._senales_sesion = []
        self._capturas_sesion = 0

        # Inicializar hardware
        self._conectar_hardware()

    # ── HARDWARE ─────────────────────────────────────────────────────

    def _conectar_hardware(self):
        """Conecta al hardware SDR disponible."""
        if SDR_TIPO == "RTL-SDR" and SDR_CLASE:
            try:
                self.sdr = SDR_CLASE()
                self.sdr.sample_rate = self.sample_rate
                self.sdr.gain = self.gain
                self.sdr.set_bias_tee(False)   # Bias-T apagado por defecto
                if ConfigSDR.RTLSDR_PPM != 0:
                    self.sdr.freq_correction = ConfigSDR.RTLSDR_PPM
                self.hw_nombre = f"RTL-SDR  gain={self.gain}dB"
                self._print(f"[green][+] RTL-SDR conectado — "
                            f"SR: {self.sample_rate/1e6:.3f} MHz  "
                            f"Gain: {self.gain} dB[/green]")
                return
            except Exception as e:
                self._print(f"[red][!] RTL-SDR error: {e}[/red]")

        if SDR_TIPO and SDR_CLASE and "SOAPY" in SDR_TIPO.upper():
            try:
                import SoapySDR
                self.sdr = SoapySDR.Device({"driver": SDR_TIPO.lower()})
                self.sdr.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0,
                                       self.sample_rate)
                self.sdr.setGain(SoapySDR.SOAPY_SDR_RX, 0, self.gain)
                self.hw_nombre = SDR_TIPO
                self._print(f"[green][+] {SDR_TIPO} conectado.[/green]")
                return
            except Exception as e:
                self._print(f"[red][!] {SDR_TIPO} error: {e}[/red]")

        # Sin hardware
        self.hw_nombre = "SIN HARDWARE SDR"
        self._print(
            "[red][!] No se detectó hardware SDR. "
            "Conecta un RTL-SDR o HackRF.[/red]\n"
            "[dim]    Instala los drivers: pip install pyrtlsdr[/dim]\n"
            "[dim]    RTL-SDR: https://www.rtl-sdr.com/[/dim]"
        )

    def configurar_ganancia(self, ganancia):
        """Ajusta la ganancia del receptor en campo."""
        if self.sdr is None:
            self._print("[red][!] Sin hardware conectado.[/red]")
            return
        try:
            if SDR_TIPO == "RTL-SDR":
                self.sdr.gain = ganancia
            self.gain = ganancia
            self.hw_nombre = (self.hw_nombre.split("gain=")[0]
                              + f"gain={ganancia}dB")
            self._print(
                f"[green][+] Ganancia ajustada a {ganancia} dB[/green]")
        except Exception as e:
            self._print(f"[red][!] Error ajustando ganancia: {e}[/red]")

    # ── CAPTURA ───────────────────────────────────────────────────────

    def _capturar(self, freq_hz: float) -> np.ndarray | None:
        """
        Captura muestras IQ del hardware real.
        Retorna None si no hay hardware disponible.
        """
        if self.sdr is None:
            self._print(
                "[red][!] Sin hardware SDR. "
                "Conecta un RTL-SDR o HackRF para operar.[/red]"
            )
            return None

        with self._lock:
            try:
                if SDR_TIPO == "RTL-SDR":
                    self.sdr.center_freq = freq_hz
                    muestras = self.sdr.read_samples(ConfigSDR.SAMPLES_N)
                    self._capturas_sesion += 1
                    return np.array(muestras, dtype=np.complex64)

                # SoapySDR genérico
                import SoapySDR
                self.sdr.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, freq_hz)
                buff = np.zeros(ConfigSDR.SAMPLES_N, dtype=np.complex64)
                sr = self.sdr.setupStream(SoapySDR.SOAPY_SDR_RX,
                                          SoapySDR.SOAPY_SDR_CF32)
                self.sdr.activateStream(sr)
                sr2 = self.sdr.readStream(sr, [buff],
                                          ConfigSDR.SAMPLES_N, timeoutUs=5_000_000)
                self.sdr.deactivateStream(sr)
                self.sdr.closeStream(sr)
                self._capturas_sesion += 1
                return buff[:sr2.ret] if sr2.ret > 0 else buff

            except Exception as e:
                self._print(f"[red][!] Error capturando muestras: {e}[/red]")
                if self.log:
                    self.log.error(f"Captura SDR: {e}", "RFScanner")
                return None

    def _identificar_banda(self, freq_mhz: float) -> dict | None:
        """Identifica la banda de una frecuencia."""
        for fmin, fmax, nombre, tipo, desc, color in BANDAS:
            if fmin <= freq_mhz <= fmax:
                return {"nombre": nombre, "tipo": tipo,
                        "desc": desc, "color": color}
        return None

    def _enriquecer_picos(self, picos: list) -> list:
        """Añade info de banda a cada pico detectado."""
        for p in picos:
            p["banda"] = self._identificar_banda(p["freq_mhz"])
        return picos

    # ── API PÚBLICA ───────────────────────────────────────────────────

    def escanear_frecuencia(self, freq_mhz: float, duracion: int = 10):
        """
        Escanea una frecuencia con visualización en tiempo real.
        Muestra espectro, waterfall y tabla de señales actualizados
        cada captura durante el tiempo especificado.
        """
        if self.sdr is None:
            self._print(
                "[red][!] Operación cancelada: sin hardware SDR.[/red]")
            return

        freq_hz = freq_mhz * 1e6
        banda = self._identificar_banda(freq_mhz)

        self._print()
        if banda:
            col = banda["color"]
            self._print(
                f"[bold green][RF] Sintonizando {freq_mhz:.4f} MHz — "
                f"[{col}]{banda['nombre']}[/{col}]  "
                f"[dim]{banda['desc']}[/dim][/bold green]"
            )
        else:
            self._print(f"[bold green][RF] Sintonizando {freq_mhz:.4f} MHz "
                        f"— Banda no clasificada[/bold green]")

        self._print(
            f"[dim]  Hardware: {self.hw_nombre}  |  "
            f"BW: {self.sample_rate/1e6:.3f} MHz  |  "
            f"FFT: {self.dsp.fft_size} pts  |  "
            f"Duración: {duracion}s  |  "
            f"Ctrl+C para detener[/dim]\n"
        )
        time.sleep(0.5)

        inicio = time.time()
        iteracion = 0
        todos_picos = []

        try:
            while time.time() - inicio < duracion:
                # Captura con promediado para reducir ruido
                capturas_psd = []
                for _ in range(ConfigSDR.PROMEDIO_N):
                    muestras = self._capturar(freq_hz)
                    if muestras is None:
                        return
                    _, psd = self.dsp.calcular_psd(muestras, self.sample_rate)
                    capturas_psd.append(psd)

                freqs_hz, _ = self.dsp.calcular_psd(muestras, self.sample_rate)
                psd_prom = self.dsp.promediar_capturas(capturas_psd)

                # Detectar y enriquecer picos
                picos = self.dsp.detectar_picos(
                    freqs_hz, psd_prom, freq_hz, self.sample_rate
                )
                picos = self._enriquecer_picos(picos)
                todos_picos.extend(picos)
                self._senales_sesion.extend(picos)

                # Waterfall
                self._waterfall.appendleft(psd_prom.copy())

                # Renderizar
                os.system("cls" if os.name == "nt" else "clear")
                self.console.print(self.render.espectro(
                    freqs_hz, psd_prom, freq_mhz, picos,
                    self.sample_rate, self.hw_nombre
                ))
                self.console.print(self.render.waterfall(
                    self._waterfall, freq_mhz
                ))
                self.console.print(self.render.tabla_picos(picos))

                elapsed = time.time() - inicio
                self.console.print(
                    f"[dim]  Iteración {iteracion+1}  |  "
                    f"{elapsed:.1f}s / {duracion}s  |  "
                    f"Picos: {len(picos)}  |  "
                    f"Capturas totales: {self._capturas_sesion}[/dim]"
                )
                iteracion += 1

        except KeyboardInterrupt:
            self._print(
                "\n[yellow][!] Escaneo interrumpido por el operador.[/yellow]")

        duracion_real = time.time() - inicio

        # Resumen
        self.console.print()
        self.console.print(self.render.resumen_escaneo(
            freq_mhz, todos_picos, duracion_real,
            self.hw_nombre, iteracion
        ))

        # Exportar evidencia
        if todos_picos:
            self._exportar_csv_picos(todos_picos, freq_mhz)

        # Registrar en proyecto
        self._registrar_evidencia(freq_mhz, todos_picos, duracion_real)

        if self.log:
            self.log.info(
                f"Escaneo RF {freq_mhz:.3f} MHz: "
                f"{len(todos_picos)} señales en {duracion_real:.0f}s",
                "RFScanner"
            )

    def barrido_espectro(self, freq_ini_mhz: float,
                         freq_fin_mhz: float,
                         paso_mhz: float = 1.0):
        """
        Barre un rango de frecuencias y genera mapa de actividad.
        Captura una muestra por frecuencia y reporta potencia máxima y SNR.
        """
        if self.sdr is None:
            self._print(
                "[red][!] Operación cancelada: sin hardware SDR.[/red]")
            return

        freqs = np.arange(freq_ini_mhz, freq_fin_mhz + paso_mhz, paso_mhz)
        self._print(
            f"\n[bold green][RF] Barrido de espectro: "
            f"{freq_ini_mhz:.1f} → {freq_fin_mhz:.1f} MHz  "
            f"(paso: {paso_mhz:.2f} MHz  |  {len(freqs)} puntos)[/bold green]\n"
        )

        resultados = []
        try:
            for i, freq in enumerate(freqs):
                muestras = self._capturar(freq * 1e6)
                if muestras is None:
                    break

                _, psd = self.dsp.calcular_psd(muestras, self.sample_rate)
                piso = self.dsp.estimar_piso_ruido(psd)
                pot_max = float(np.max(psd))
                snr = pot_max - piso
                banda = self._identificar_banda(freq)

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
                    end=""
                )

        except KeyboardInterrupt:
            self._print("\n[yellow][!] Barrido interrumpido.[/yellow]")

        print()
        self.console.print()

        if resultados:
            self.console.print(self.render.mapa_barrido(resultados))
            self._exportar_csv_barrido(resultados, freq_ini_mhz, freq_fin_mhz)

            if self.gp:
                self.gp.registrar_evidencia(
                    "rf_sweep",
                    f"Barrido RF {freq_ini_mhz:.0f}–{freq_fin_mhz:.0f} MHz: "
                    f"{len(resultados)} puntos",
                    {"ini_mhz": freq_ini_mhz, "fin_mhz": freq_fin_mhz,
                     "paso_mhz": paso_mhz, "puntos": len(resultados),
                     "hardware": self.hw_nombre}
                )

    def escaneo_bandas_conocidas(self):
        """
        Escanea rápidamente el centro de cada banda conocida
        y muestra un mapa de actividad global.
        """
        if self.sdr is None:
            self._print(
                "[red][!] Operación cancelada: sin hardware SDR.[/red]")
            return

        self._print(
            f"\n[bold green][RF] Escaneo de {len(BANDAS)} "
            f"bandas conocidas...[/bold green]\n"
        )
        resultados = []

        for fmin, fmax, nombre, tipo, desc, color in BANDAS:
            freq = (fmin + fmax) / 2.0
            # Verificar rango del hardware
            if SDR_TIPO == "RTL-SDR" and (freq < 24 or freq > 1766):
                continue

            muestras = self._capturar(freq * 1e6)
            if muestras is None:
                break

            _, psd = self.dsp.calcular_psd(muestras, self.sample_rate)
            piso = self.dsp.estimar_piso_ruido(psd)
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
                end=""
            )

        print()
        self.console.print()
        if resultados:
            self.console.print(self.render.mapa_barrido(resultados))

    def menu(self):
        """Menú interactivo del módulo RF para uso en campo."""
        self.console.print()
        self.console.print(Panel(
            f"[bold green]RF SCANNER — {self.hw_nombre}[/bold green]\n\n"
            "[green][1][/green] Escanear frecuencia específica\n"
            "[green][2][/green] Barrido de espectro (rango)\n"
            "[green][3][/green] Escaneo de bandas conocidas\n"
            "[green][4][/green] Ajustar ganancia\n"
            "[green][5][/green] Ver señales de esta sesión\n"
            "[green][6][/green] Estado del hardware",
            border_style="green",
            title="[bold green]RF SCANNER[/bold green]",
        ))

        opt = self.console.input(
            "[bold green][?] Opción: [/bold green]"
        ).strip()

        if opt == "1":
            freq_s = self.console.input(
                "[bold cyan][?] Frecuencia (MHz): [/bold cyan]"
            ).strip()
            dur_s = self.console.input(
                "[bold cyan][?] Duración segundos [10]: [/bold cyan]"
            ).strip()
            try:
                self.escanear_frecuencia(
                    float(freq_s),
                    int(dur_s) if dur_s else 10
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
                    float(ini_s),
                    float(fin_s),
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
                    self.render.tabla_picos(self._senales_sesion[-50:])
                )
            else:
                self._print(
                    "[dim]Sin señales registradas en esta sesión.[/dim]")

        elif opt == "6":
            self.estado()

    def estado(self):
        """Muestra el estado del hardware y la sesión."""
        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim green", justify="right", min_width=20)
        g.add_column(style="white")

        g.add_row("Hardware",          self.hw_nombre)
        g.add_row("Driver detectado",  SDR_TIPO or "Ninguno")
        g.add_row("Sample rate",       f"{self.sample_rate/1e6:.3f} MHz")
        g.add_row("Ganancia",          str(self.gain))
        g.add_row("Tamaño FFT",        str(self.dsp.fft_size))
        g.add_row("Ventana",           self.dsp.ventana_n)
        g.add_row("Umbral margen",     f"{ConfigSDR.UMBRAL_MARGEN_DB} dB")
        g.add_row("Umbral absoluto",   f"{ConfigSDR.UMBRAL_ABS_DBM} dBm")
        g.add_row("Capturas sesión",   str(self._capturas_sesion))
        g.add_row("Señales sesión",    str(len(self._senales_sesion)))
        g.add_row("Bandas en DB",      str(len(BANDAS)))

        self.console.print(Panel(g, title="[bold green]ESTADO RF SCANNER[/bold green]",
                                 border_style="green"))

    def cerrar(self):
        """Cierra la conexión con el hardware SDR de forma segura."""
        if self.sdr is not None:
            try:
                if SDR_TIPO == "RTL-SDR":
                    self.sdr.close()
                self._print(
                    "[green][+] SDR desconectado correctamente.[/green]")
            except Exception as e:
                self._print(f"[yellow][!] Error al cerrar SDR: {e}[/yellow]")
            finally:
                self.sdr = None

    # ── EXPORTACIÓN ──────────────────────────────────────────────────

    def _exportar_csv_picos(self, picos: list, freq_mhz: float):
        """Exporta señales detectadas a CSV."""
        os.makedirs(ConfigSDR.EXPORT_PATH, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = (f"{ConfigSDR.EXPORT_PATH}/"
              f"scan_{freq_mhz:.0f}MHz_{ts}.csv")
        try:
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "freq_mhz", "potencia", "snr_db",
                    "bw_khz", "piso_dbm", "banda", "timestamp"
                ])
                w.writeheader()
                for p in picos:
                    w.writerow({
                        "freq_mhz":  p["freq_mhz"],
                        "potencia":  p["potencia"],
                        "snr_db":    p["snr_db"],
                        "bw_khz":    p["bw_khz"],
                        "piso_dbm":  p["piso_dbm"],
                        "banda":     p["banda"]["nombre"] if p.get("banda") else "—",
                        "timestamp": p["timestamp"],
                    })
            self._print(f"[green][+] Evidencia exportada → {fn}[/green]")
        except OSError as e:
            self._print(f"[red][!] Error exportando CSV: {e}[/red]")

    def _exportar_csv_barrido(self, resultados: list,
                              freq_ini: float, freq_fin: float):
        """Exporta resultados de barrido a CSV."""
        os.makedirs(ConfigSDR.EXPORT_PATH, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = (f"{ConfigSDR.EXPORT_PATH}/"
              f"sweep_{freq_ini:.0f}-{freq_fin:.0f}MHz_{ts}.csv")
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
                        "banda":    r["banda"]["nombre"] if r.get("banda") else "—",
                    })
            self._print(f"[green][+] Barrido exportado → {fn}[/green]")
        except OSError as e:
            self._print(f"[red][!] Error exportando CSV: {e}[/red]")

    def _registrar_evidencia(self, freq_mhz: float,
                             picos: list, duracion: float):
        """Registra el escaneo en el proyecto activo si existe."""
        if not self.gp or not picos:
            return

        self.gp.registrar_evidencia(
            "rf_scan",
            f"Escaneo RF en {freq_mhz:.3f} MHz: {len(picos)} señales",
            {
                "freq_mhz":  freq_mhz,
                "duracion_s": round(duracion, 1),
                "hardware":  self.hw_nombre,
                "señales":   [
                    {
                        "freq": p["freq_mhz"],
                        "pot":  p["potencia"],
                        "snr":  p["snr_db"],
                        "bw":   p["bw_khz"],
                        "banda": p["banda"]["nombre"] if p.get("banda") else "—",
                    }
                    for p in picos
                ],
            }
        )

        # Hallazgo si hay señal fuerte no clasificada
        no_clasificadas = [p for p in picos
                           if not p.get("banda") and p["snr_db"] > 20]
        for p in no_clasificadas:
            self.gp.registrar_hallazgo(
                "MEDIO",
                f"Señal no clasificada en {p['freq_mhz']:.3f} MHz",
                f"Potencia: {p['potencia']:.1f} dBm  "
                f"SNR: {p['snr_db']:.1f} dB  "
                f"BW: {p['bw_khz']:.2f} kHz",
                "Investigar origen. Puede ser dispositivo ilícito o "
                "interferencia no autorizada."
            )

    # ── HELPER ───────────────────────────────────────────────────────

    def _print(self, msg: str = ""):
        if self.console:
            self.console.print(msg)
        else:
            import re
            print(re.sub(r"\[.*?\]", "", msg))
