from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


import numpy as np
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import box

log = logging.getLogger("sentinel.rf.adsb")

_FREQ_ADSB = 1_090_000_000   # 1090 MHz — estándar mundial ADS-B
_SR_ADSB = 2_000_000       # 2 Msps
_PREAMBLE_US = 8               # µs de preámbulo Mode S

# ── pyModeS — decodificador completo (opcional) ──────────────────
_PYMODES_OK = False
try:
    import pyModeS as pms
    _PYMODES_OK = True
    log.info("pyModeS disponible — decodificación completa activada")
except ImportError:
    log.info("pyModeS no disponible — usando decodificador básico integrado")


# ══════════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════════

@dataclass
class Aeronave:
    icao:       str                   # Código ICAO de 24 bits (hex)
    callsign:   str = ""             # Indicativo de vuelo
    latitud:    float | None = None
    longitud:   float | None = None
    altitud_ft: int | None = None
    velocidad:  int | None = None  # nudos
    rumbo:      int | None = None  # grados
    squawk:     str | None = None
    msgs:       int = 0
    ultima_vez: float = field(default_factory=time.time)

    @property
    def activo(self) -> bool:
        """True si se vio en los últimos 60 segundos."""
        return (time.time() - self.ultima_vez) < 60

    @property
    def posicion(self) -> str | None:
        if self.latitud and self.longitud:
            return f"{self.latitud:.4f}°, {self.longitud:.4f}°"
        return None


@dataclass
class MensajeADSB:
    """Mensaje ADS-B crudo decodificado."""
    raw_hex:  str
    icao:     str
    tipo_df:  int    # Downlink Format
    timestamp: float = field(default_factory=time.time)


# ══════════════════════════════════════════════════════════════════
# DECODIFICADOR BÁSICO (sin pyModeS)
# ══════════════════════════════════════════════════════════════════

def _crc24(data: bytes) -> int:
    GENERATOR = 0xFFF409
    crc = 0
    for byte in data:
        crc ^= (byte << 16)
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= GENERATOR
    return crc & 0xFFFFFF


def _validar_mensaje(hex_str: str) -> bool:
    try:
        data = bytes.fromhex(hex_str)
        if len(data) < 7:
            return False
        payload = data[:-3]
        crc_msg = int.from_bytes(data[-3:], "big")
        return _crc24(payload) == crc_msg
    except Exception:
        return False


def _extraer_icao(hex_str: str) -> str:
    try:
        return hex_str[2:8].upper()
    except Exception:
        return "??????"


def _extraer_callsign_basico(hex_str: str) -> str:

    CHARSET = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ#####_###############0123456789######"
    try:
        if len(hex_str) < 22:
            return ""
        data = bytes.fromhex(hex_str)
        tc = (data[4] >> 3) & 0x1F
        if tc not in range(1, 5):
            return ""
        chars = []
        for i in range(8):
            byte_idx = 5 + (i * 6) // 8
            bit_off = (i * 6) % 8
            if byte_idx + 1 < len(data):
                val = ((data[byte_idx] << 8) | data[byte_idx + 1])
                val = (val >> (10 - bit_off)) & 0x3F
                chars.append(CHARSET[val])
        return "".join(chars).strip("#_ ")
    except Exception:
        return ""


def _extraer_altitud_basico(hex_str: str) -> int | None:
    try:
        data = bytes.fromhex(hex_str)
        tc = (data[4] >> 3) & 0x1F
        if 9 <= tc <= 18:
            alt_code = ((data[5] & 0xFF) << 4) | ((data[6] >> 4) & 0x0F)
            if alt_code:
                return (alt_code * 25) - 1000
    except Exception:
        pass
    return None


# ══════════════════════════════════════════════════════════════════
# DECODIFICADOR PRINCIPAL
# ══════════════════════════════════════════════════════════════════

class ADSBDecoder:

    TTL_AERONAVE = 60    # segundos sin mensaje para considerar fuera de rango
    MAX_AERONAVES = 50   # máximo en pantalla

    def __init__(self, sentinel) -> None:
        self.sentinel = sentinel
        self.console: Console = getattr(sentinel, "console", Console())
        self._aeronaves: dict[str, Aeronave] = {}
        self._lock = threading.Lock()
        self._corriendo = False
        self._msgs_total = 0
        self._msgs_validos = 0

    # ── API pública ────────────────────────────────────────────────

    def iniciar(self, duracion_seg: int | None = None) -> None:
        if not self._verificar_hardware():
            return

        self._corriendo = True
        self._aeronaves = {}
        self._msgs_total = 0
        inicio = time.time()

        self.console.print(Panel(
            f"[bold cyan]ADS-B MONITOR — 1090 MHz[/bold cyan]\n"
            f"[dim]Decodificando transponders Mode S / ADS-B[/dim]\n"
            f"[dim]pyModeS: {'✓ activo' if _PYMODES_OK else '○ básico integrado'}[/dim]",
            border_style="cyan",
            title="[bold]APEX SENTINEL · RF[/bold]",
        ))

        hilo_captura = threading.Thread(
            target=self._bucle_captura,
            args=(duracion_seg, inicio),
            daemon=True,
        )
        hilo_captura.start()

        try:
            with Live(self._render_tabla(), console=self.console,
                      refresh_per_second=2) as live:
                while self._corriendo:
                    if duracion_seg and (time.time() - inicio) > duracion_seg:
                        self._corriendo = False
                        break
                    live.update(self._render_tabla())
                    time.sleep(0.5)
        except KeyboardInterrupt:
            self._corriendo = False

        hilo_captura.join(timeout=3)
        self._mostrar_resumen()

    def aeronaves_activas(self) -> list[Aeronave]:
        with self._lock:
            return [a for a in self._aeronaves.values() if a.activo]

    # ── Captura y decodificación ───────────────────────────────────

    def _bucle_captura(self, duracion: int | None, inicio: float) -> None:
        sdr = getattr(self.sentinel, "rf_scanner", None)

        if sdr is None or not hasattr(sdr, "_capturar"):
            # Modo demo sin hardware
            self._modo_demo(duracion, inicio)
            return

        while self._corriendo:
            if duracion and (time.time() - inicio) > duracion:
                break

            muestras = sdr._capturar(_FREQ_ADSB)
            if muestras is None:
                time.sleep(0.5)
                continue

            mensajes = self._detectar_preamble(muestras)
            for msg in mensajes:
                self._procesar_mensaje(msg)

    def _detectar_preamble(self, iq: np.ndarray) -> list[str]:
        mensajes = []
        try:
            mag = np.abs(iq)
            umbral = np.mean(mag) * 2.5

            # Buscar picos de preámbulo (simplificado para portabilidad)
            picos = np.where(mag > umbral)[0]
            i = 0
            while i < len(picos) - 1:
                pos = picos[i]
                # Mensaje largo (112 bits = 224 µs a 2 Msps = 448 samples)
                fin = pos + 448
                if fin < len(mag):
                    bits = self._demodular_bits(mag[pos:fin])
                    if bits:
                        hex_msg = self._bits_a_hex(bits)
                        if hex_msg and _validar_mensaje(hex_msg):
                            mensajes.append(hex_msg)
                            self._msgs_validos += 1
                    self._msgs_total += 1
                    i += 50
                else:
                    i += 1
        except Exception as e:
            log.debug(f"Error en detección de preámbulo: {e}")
        return mensajes

    def _demodular_bits(self, mag: np.ndarray) -> list[int]:
        try:
            bits = []
            for i in range(0, min(len(mag) - 2, 112 * 2), 2):
                bit = 1 if mag[i] > mag[i + 1] else 0
                bits.append(bit)
            return bits if len(bits) >= 56 else []
        except Exception:
            return []

    def _bits_a_hex(self, bits: list[int]) -> str:
        try:
            result = ""
            for i in range(0, len(bits) - 7, 8):
                byte = 0
                for j in range(8):
                    byte = (byte << 1) | bits[i + j]
                result += f"{byte:02X}"
            return result
        except Exception:
            return ""

    def _procesar_mensaje(self, hex_str: str) -> None:
        try:
            icao = _extraer_icao(hex_str)
            if not icao or icao == "??????":
                return

            with self._lock:
                if icao not in self._aeronaves:
                    self._aeronaves[icao] = Aeronave(icao=icao)

                a = self._aeronaves[icao]
                a.msgs += 1
                a.ultima_vez = time.time()

                # Usar pyModeS si disponible
                if _PYMODES_OK:
                    self._decodificar_pymodes(hex_str, a)
                else:
                    self._decodificar_basico(hex_str, a)

        except Exception as e:
            log.debug(f"Error procesando mensaje {hex_str}: {e}")

    def _decodificar_pymodes(self, hex_str: str, aeronave: Aeronave) -> None:
        try:
            df = pms.df(hex_str)
            if df == 17:
                tc = pms.adsb.typecode(hex_str)
                if 1 <= tc <= 4:
                    cs = pms.adsb.callsign(hex_str)
                    if cs:
                        aeronave.callsign = cs.strip()
                elif 9 <= tc <= 18:
                    alt = pms.adsb.altitude(hex_str)
                    if alt:
                        aeronave.altitud_ft = int(alt)
                elif tc == 19:
                    vel = pms.adsb.velocity(hex_str)
                    if vel and vel[0]:
                        aeronave.velocidad = int(vel[0])
                        aeronave.rumbo = int(vel[1]) if vel[1] else None
        except Exception:
            pass

    def _decodificar_basico(self, hex_str: str, aeronave: Aeronave) -> None:
        if not aeronave.callsign:
            cs = _extraer_callsign_basico(hex_str)
            if cs:
                aeronave.callsign = cs
        if aeronave.altitud_ft is None:
            alt = _extraer_altitud_basico(hex_str)
            if alt:
                aeronave.altitud_ft = alt

    # ── Demo sin hardware ──────────────────────────────────────────

    def _modo_demo(self, duracion: int | None, inicio: float) -> None:
        demos = [
            ("ABC123", "AMX001", 35000, 450, 270),
            ("DEF456", "UAL320", 28000, 480, 90),
            ("789GHI", "DAL145", 41000, 510, 180),
            ("JKL012", "AAL789", 15000, 280, 45),
            ("MNO345", "WN1234", 22000, 390, 315),
        ]
        while self._corriendo:
            if duracion and (time.time() - inicio) > duracion:
                break
            for icao, cs, alt, vel, hdg in demos:
                with self._lock:
                    if icao not in self._aeronaves:
                        self._aeronaves[icao] = Aeronave(icao=icao)
                    a = self._aeronaves[icao]
                    a.callsign = cs
                    a.altitud_ft = alt + np.random.randint(-200, 200)
                    a.velocidad = vel + np.random.randint(-20, 20)
                    a.rumbo = hdg
                    a.msgs += 1
                    a.ultima_vez = time.time()
                self._msgs_total += 1
                self._msgs_validos += 1
            time.sleep(2)

    # ── Renderizado ────────────────────────────────────────────────

    def _render_tabla(self) -> Panel:
        tabla = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            show_edge=False,
            expand=True,
        )
        tabla.add_column("ICAO",     style="bold yellow",  width=8)
        tabla.add_column("Callsign", style="bold white",   width=10)
        tabla.add_column("Alt (ft)", justify="right",      width=10)
        tabla.add_column("Vel (kt)", justify="right",      width=9)
        tabla.add_column("Rumbo",    justify="right",      width=7)
        tabla.add_column("Msgs",     justify="right",
                         width=6, style="dim")
        tabla.add_column("Estado",   width=10)

        activas = sorted(
            self.aeronaves_activas(),
            key=lambda a: a.msgs,
            reverse=True,
        )[:self.MAX_AERONAVES]

        for a in activas:
            tiempo_inactivo = time.time() - a.ultima_vez
            if tiempo_inactivo < 5:
                estado = "[green]● activo[/green]"
            elif tiempo_inactivo < 30:
                estado = "[yellow]○ débil[/yellow]"
            else:
                estado = "[red]× perdido[/red]"

            tabla.add_row(
                a.icao,
                a.callsign or "[dim]?[/dim]",
                f"{a.altitud_ft:,}" if a.altitud_ft else "[dim]—[/dim]",
                str(a.velocidad) if a.velocidad else "[dim]—[/dim]",
                f"{a.rumbo}°" if a.rumbo else "[dim]—[/dim]",
                str(a.msgs),
                estado,
            )

        n_activas = len(activas)
        tasa = self._msgs_validos / max(1, self._msgs_total) * 100

        footer = (
            f"[dim]Aeronaves: [bold]{n_activas}[/bold] · "
            f"Msgs: {self._msgs_total} · "
            f"Válidos: {tasa:.0f}% · "
            f"{'pyModeS activo' if _PYMODES_OK else 'Decoder básico'}[/dim]"
        )

        return Panel(
            tabla,
            title="[bold cyan]ADS-B · 1090 MHz · Transponders detectados[/bold cyan]",
            subtitle=footer,
            border_style="cyan",
        )

    def _mostrar_resumen(self) -> None:
        activas = self.aeronaves_activas()
        self.console.print(Panel(
            f"[bold green]Monitoreo ADS-B completado[/bold green]\n\n"
            f"  Aeronaves detectadas:  [bold]{len(self._aeronaves)}[/bold]\n"
            f"  Aeronaves activas:     [bold]{len(activas)}[/bold]\n"
            f"  Mensajes procesados:   [bold]{self._msgs_total}[/bold]\n"
            f"  Mensajes válidos:      [bold]{self._msgs_validos}[/bold]",
            border_style="green",
            title="[bold]RESUMEN ADS-B[/bold]",
        ))
        # Registrar en sistema de logs
        try:
            self.sentinel.reportes.registrar_evento(
                "ADSB",
                f"Monitoreo completado: {len(self._aeronaves)} aeronaves, "
                f"{self._msgs_total} mensajes"
            )
        except Exception:
            pass

    def _verificar_hardware(self) -> bool:
        rf = getattr(self.sentinel, "rf_scanner", None)
        if rf is None:
            self.console.print(
                "[yellow][!] rf_scanner no disponible — "
                "iniciando en modo DEMO[/yellow]"
            )
        return True   # siempre permite demo
