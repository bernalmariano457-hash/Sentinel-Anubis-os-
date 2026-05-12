from __future__ import annotations

import asyncio
import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

if TYPE_CHECKING:
    from sentinel import ApexSentinel

logger = logging.getLogger(__name__)

# ── Importación defensiva de bleak ────────────────────────────────────
try:
    from bleak import BleakScanner, BleakClient
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
    BLEAK_OK = True
except ImportError:
    BLEAK_OK = False
    BLEDevice = None
    AdvertisementData = None

# ── Base de datos mínima de OUIs para fingerprinting ──────────────────
# Primeros 3 bytes de la MAC → fabricante aproximado
_OUI_MAP: dict[str, str] = {
    "00:1A:7D": "Apple",        "AC:DE:48": "Apple",
    "00:17:F2": "Apple",        "F0:18:98": "Apple",
    "00:50:F2": "Microsoft",    "28:18:78": "Microsoft",
    "00:15:5D": "Microsoft",    "B8:27:EB": "Raspberry Pi",
    "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi",
    "00:1B:DC": "Samsung",      "8C:71:F8": "Samsung",
    "00:1D:FE": "Fitbit",       "88:B4:A6": "Fitbit",
    "A4:C1:38": "Espressif",    "30:AE:A4": "Espressif",
    "24:6F:28": "Espressif",    "00:1B:63": "Apple",
}


def _oui_lookup(address: str) -> str:

    prefijo = address.upper()[:8]
    return _OUI_MAP.get(prefijo, "Desconocido")


# ════════════════════════════════════════════════════════════════════
# DATACLASS DE DISPOSITIVO BLE
# ════════════════════════════════════════════════════════════════════

@dataclass
class DispositivoBLE:

    nombre: str
    address: str
    rssi: int
    fabricante: str
    servicios: list[str]
    primera_vez: str = field(
        default_factory=lambda: datetime.now().isoformat())
    ultima_vez: str = field(default_factory=lambda: datetime.now().isoformat())
    veces_visto: int = 1

    def actualizar(self, rssi: int):
        self.rssi = rssi
        self.ultima_vez = datetime.now().isoformat()
        self.veces_visto += 1

    def to_dict(self) -> dict:
        return {
            "nombre":      self.nombre,
            "address":     self.address,
            "rssi":        self.rssi,
            "fabricante":  self.fabricante,
            "servicios":   self.servicios,
            "primera_vez": self.primera_vez,
            "ultima_vez":  self.ultima_vez,
            "veces_visto": self.veces_visto,
        }

    @property
    def proximidad(self) -> str:
        """Estimación de proximidad basada en RSSI."""
        if self.rssi >= -50:
            return "[bold red]MUY CERCA[/bold red]"
        if self.rssi >= -70:
            return "[yellow]CERCA[/yellow]"
        if self.rssi >= -85:
            return "[green]MEDIO[/green]"
        return "[dim]LEJOS[/dim]"


# ════════════════════════════════════════════════════════════════════
# MÓDULO PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class BluetoothModule:

    SCAN_TIMEOUT = 10.0   # segundos por escaneo BLE
    BRIDGE_TIMEOUT = 30.0   # segundos sin datos antes de cerrar puente
    BRIDGE_BUF = 4096   # bytes por lectura en puente

    def __init__(self, sentinel: "ApexSentinel"):
        self.sentinel = sentinel
        self.console: Console = getattr(sentinel, "console", Console())
        self.log = getattr(sentinel, "log",     None)
        self.gp = getattr(sentinel, "gp",      None)

        # Estado de sesión
        self._dispositivos: dict[str, DispositivoBLE] = {}
        self._lock = threading.Lock()
        self._monitoreo_activo = False

        if not BLEAK_OK:
            self._warn(
                "bleak no instalado — BLE deshabilitado. "
                "Instala con: pip install bleak --break-system-packages"
            )

    # ── Helpers ───────────────────────────────────────────────────────

    def _info(self, msg: str):
        if self.log:
            self.log.info(msg, "BluetoothModule")
        else:
            self.console.print(f"[cyan][*][/cyan] {msg}")

    def _warn(self, msg: str):
        if self.log:
            self.log.warning(msg, "BluetoothModule")
        else:
            self.console.print(f"[yellow][!][/yellow] {msg}")

    def _error(self, msg: str):
        if self.log:
            self.log.error(msg, "BluetoothModule")
        else:
            self.console.print(f"[red][!][/red] {msg}")

    def _run_async(self, coro) -> None:

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Ya hay loop: ejecutar en thread dedicado
            resultado = {"exc": None}

            def _target():
                try:
                    asyncio.run(coro)
                except Exception as e:
                    resultado["exc"] = e

            t = threading.Thread(target=_target, daemon=True)
            t.start()
            t.join()
            if resultado["exc"]:
                raise resultado["exc"]
        else:
            asyncio.run(coro)

    # ── Renderizado ───────────────────────────────────────────────────

    def _tabla_dispositivos(self, dispositivos: list[DispositivoBLE]) -> Panel:
        if not dispositivos:
            return Panel(
                "[dim]No se encontraron dispositivos BLE en el entorno.[/dim]",
                title="[bold cyan]BLUETOOTH LE — SCAN[/bold cyan]",
                border_style="cyan",
            )

        tb = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            show_edge=False,
            expand=True,
        )
        tb.add_column("Dispositivo",  style="white",  min_width=22)
        tb.add_column("MAC",          style="cyan",
                      min_width=18, no_wrap=True)
        tb.add_column("RSSI",         justify="right", min_width=8)
        tb.add_column("Proximidad",   min_width=12)
        tb.add_column("Fabricante",   style="yellow", min_width=14)
        tb.add_column("Servicios",    style="dim",
                      min_width=6, justify="right")
        tb.add_column("Visto",        style="dim",
                      min_width=4, justify="right")

        ordenados = sorted(dispositivos, key=lambda d: d.rssi, reverse=True)
        for d in ordenados:
            rssi_style = (
                "bold red" if d.rssi >= -50 else
                "yellow" if d.rssi >= -70 else
                "green" if d.rssi >= -85 else
                "dim"
            )
            tb.add_row(
                d.nombre or "[dim]<sin nombre>[/dim]",
                d.address,
                f"[{rssi_style}]{d.rssi} dBm[/{rssi_style}]",
                d.proximidad,
                d.fabricante,
                str(len(d.servicios)),
                str(d.veces_visto),
            )

        ts = datetime.now().strftime("%H:%M:%S")
        return Panel(
            tb,
            title=(f"[bold cyan]BLUETOOTH LE — {len(dispositivos)} dispositivos[/bold cyan]"
                   f"  [dim]{ts}[/dim]"),
            border_style="cyan",
            box=box.HEAVY_HEAD,
        )

    # ── Escaneo BLE ───────────────────────────────────────────────────

    def iniciar_jumper(self):
        if not BLEAK_OK:
            self.console.print(
                "[red][!] bleak no disponible. "
                "pip install bleak --break-system-packages[/red]")
            return

        self.console.print(
            "\n[bold cyan][*] Iniciando escaneo Bluetooth LE...[/bold cyan]"
            f"\n[dim]    Timeout: {self.SCAN_TIMEOUT}s | "
            "Ctrl+C para interrumpir[/dim]\n"
        )
        try:
            self._run_async(self._escanear_una_vez())
        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Escaneo interrumpido.[/yellow]")
        except Exception as e:
            self._error(f"Error en escaneo BLE: {e}")
            logger.exception("BLE scan error")

    async def _escanear_una_vez(self):
        encontrados: list[DispositivoBLE] = []

        def _callback(device: "BLEDevice", adv: "AdvertisementData"):
            servicios = [str(u) for u in (adv.service_uuids or [])]
            disp = DispositivoBLE(
                nombre=device.name or "",
                address=device.address,
                rssi=adv.rssi if adv.rssi else -99,
                fabricante=_oui_lookup(device.address),
                servicios=servicios,
            )
            encontrados.append(disp)
            with self._lock:
                if device.address in self._dispositivos:
                    self._dispositivos[device.address].actualizar(disp.rssi)
                else:
                    self._dispositivos[device.address] = disp

        scanner = BleakScanner(detection_callback=_callback)
        await scanner.start()
        await asyncio.sleep(self.SCAN_TIMEOUT)
        await scanner.stop()

        # Renderizar resultado
        self.console.print(self._tabla_dispositivos(encontrados))

        # Registrar evidencia si hay proyecto activo
        self._registrar_evidencia(encontrados, "escaneo_unico")

        self._info(f"Escaneo BLE completado: {len(encontrados)} dispositivos")

    def monitoreo_continuo(self, duracion_seg: int = 60,
                           callback_nuevo: Callable | None = None):
        if not BLEAK_OK:
            self.console.print("[red][!] bleak no disponible.[/red]")
            return

        self.console.print(
            f"\n[bold cyan][*] Monitoreo BLE continuo — {duracion_seg}s[/bold cyan]\n"
            "[dim]    Ctrl+C para detener[/dim]\n"
        )
        self._monitoreo_activo = True
        try:
            self._run_async(
                self._monitoreo_loop(duracion_seg, callback_nuevo)
            )
        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Monitoreo detenido.[/yellow]")
        except Exception as e:
            self._error(f"Error en monitoreo BLE: {e}")
            logger.exception("BLE monitor error")
        finally:
            self._monitoreo_activo = False

    async def _monitoreo_loop(self, duracion_seg: int,
                              callback_nuevo: Callable | None):
        conocidos: set[str] = set()
        inicio = time.time()

        while time.time() - inicio < duracion_seg:
            ciclo_nuevos: list[DispositivoBLE] = []

            def _cb(device: "BLEDevice", adv: "AdvertisementData"):
                servicios = [str(u) for u in (adv.service_uuids or [])]
                rssi = adv.rssi if adv.rssi else -99
                with self._lock:
                    if device.address in self._dispositivos:
                        self._dispositivos[device.address].actualizar(rssi)
                    else:
                        disp = DispositivoBLE(
                            nombre=device.name or "",
                            address=device.address,
                            rssi=rssi,
                            fabricante=_oui_lookup(device.address),
                            servicios=servicios,
                        )
                        self._dispositivos[device.address] = disp
                        if device.address not in conocidos:
                            ciclo_nuevos.append(disp)
                            conocidos.add(device.address)
                            if callback_nuevo:
                                try:
                                    callback_nuevo(disp)
                                except Exception:
                                    pass

            scanner = BleakScanner(detection_callback=_cb)
            await scanner.start()
            await asyncio.sleep(min(5.0, duracion_seg))
            await scanner.stop()

            # Actualizar vista
            import os
            os.system("cls" if __import__("os").name == "nt" else "clear")
            with self._lock:
                todos = list(self._dispositivos.values())

            self.console.print(self._tabla_dispositivos(todos))
            elapsed = time.time() - inicio
            self.console.print(
                f"[dim]  {elapsed:.0f}s / {duracion_seg}s  |  "
                f"Total sesión: {len(todos)}  |  "
                f"Nuevos este ciclo: {len(ciclo_nuevos)}[/dim]"
            )

            if ciclo_nuevos:
                for d in ciclo_nuevos:
                    self.console.print(
                        f"[bold cyan][+] NUEVO:[/bold cyan] "
                        f"{d.nombre or '<sin nombre>'} | {d.address} | "
                        f"{d.rssi} dBm | {d.fabricante}"
                    )

        # Resumen final y evidencia
        with self._lock:
            todos = list(self._dispositivos.values())
        self._registrar_evidencia(todos, "monitoreo_continuo")
        self._info(
            f"Monitoreo BLE {duracion_seg}s: "
            f"{len(todos)} dispositivos únicos"
        )

    # ── Evidencia ─────────────────────────────────────────────────────

    def _registrar_evidencia(self, dispositivos: list[DispositivoBLE],
                             tipo: str):
        """Registra los resultados BLE en el GestorProyectos si hay uno activo."""
        if not self.gp or not dispositivos:
            return
        try:
            self.gp.registrar_evidencia(
                f"bt_{tipo}",
                f"BLE {tipo}: {len(dispositivos)} dispositivos",
                {
                    "tipo":         tipo,
                    "timestamp":    datetime.now().isoformat(),
                    "total":        len(dispositivos),
                    "dispositivos": [d.to_dict() for d in dispositivos],
                },
            )
            # Hallazgo si hay dispositivos muy cercanos
            cercanos = [d for d in dispositivos if d.rssi >= -50]
            for d in cercanos:
                self.gp.registrar_hallazgo(
                    "MEDIO",
                    f"Dispositivo BLE muy cercano: {d.nombre or d.address}",
                    f"MAC: {d.address}  RSSI: {d.rssi} dBm  "
                    f"Fabricante: {d.fabricante}",
                    "Verificar si es un dispositivo autorizado en el entorno.",
                )
        except Exception as e:
            logger.warning("Error registrando evidencia BLE: %s", e)

    # ── Puente TCP ────────────────────────────────────────────────────

    def puente(self, origen: socket.socket, destino: socket.socket,
               etiqueta: str = "BRIDGE") -> dict:
        metricas = {
            "bytes_tx":   0,
            "paquetes":   0,
            "duracion_s": 0.0,
            "errores":    0,
            "etiqueta":   etiqueta,
        }
        inicio = time.monotonic()

        try:
            origen.settimeout(self.BRIDGE_TIMEOUT)
            destino.settimeout(self.BRIDGE_TIMEOUT)

            self._info(f"[{etiqueta}] Puente TCP activo — "
                       f"buf={self.BRIDGE_BUF}B  timeout={self.BRIDGE_TIMEOUT}s")

            while True:
                try:
                    data = origen.recv(self.BRIDGE_BUF)
                except socket.timeout:
                    self._warn(f"[{etiqueta}] Timeout — cerrando puente.")
                    break

                if not data:
                    self._info(f"[{etiqueta}] Conexión cerrada por el origen.")
                    break

                try:
                    destino.sendall(data)
                    metricas["bytes_tx"] += len(data)
                    metricas["paquetes"] += 1
                    logger.debug("[%s] → %d bytes", etiqueta, len(data))
                except (OSError, BrokenPipeError) as e:
                    self._warn(f"[{etiqueta}] Error de escritura: {e}")
                    metricas["errores"] += 1
                    break

        except OSError as e:
            self._error(f"[{etiqueta}] Error de socket: {e}")
            metricas["errores"] += 1
            logger.exception("[%s] Socket error", etiqueta)

        finally:
            metricas["duracion_s"] = round(time.monotonic() - inicio, 2)
            for sock in (origen, destino):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                    sock.close()
                except OSError:
                    pass

            self._info(
                f"[{etiqueta}] Puente cerrado — "
                f"{metricas['bytes_tx']:,} bytes  "
                f"{metricas['paquetes']} paquetes  "
                f"{metricas['duracion_s']}s  "
                f"errores: {metricas['errores']}"
            )

        return metricas

    def puente_bidireccional(self, sock_a: socket.socket,
                             sock_b: socket.socket,
                             etiqueta: str = "MITM") -> tuple[dict, dict]:
        metricas_ab: dict = {}
        metricas_ba: dict = {}

        # Duplicar sockets para cada dirección
        # (se cierran al terminar ambos threads)
        evento_stop = threading.Event()

        def _hilo_ab():
            metricas_ab.update(
                self.puente(sock_a, sock_b, f"{etiqueta} A→B"))
            evento_stop.set()

        def _hilo_ba():
            # Esperar a que el otro hilo cierre para terminar limpio
            metricas_ba.update(
                self.puente(sock_b, sock_a, f"{etiqueta} B→A"))
            evento_stop.set()

        t_ab = threading.Thread(target=_hilo_ab, daemon=True)
        t_ba = threading.Thread(target=_hilo_ba, daemon=True)
        t_ab.start()
        t_ba.start()

        evento_stop.wait()
        t_ab.join(timeout=2)
        t_ba.join(timeout=2)

        return metricas_ab, metricas_ba

    # ── Estado y sesión ───────────────────────────────────────────────

    def estado(self):
        with self._lock:
            total = len(self._dispositivos)
            cercanos = sum(
                1 for d in self._dispositivos.values() if d.rssi >= -50)
            fabricantes = {d.fabricante
                           for d in self._dispositivos.values()
                           if d.fabricante != "Desconocido"}

        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim cyan", justify="right", min_width=22)
        g.add_column(style="white")

        g.add_row("Driver BLE",         "[green]bleak OK[/green]"
                  if BLEAK_OK else "[red]No disponible[/red]")
        g.add_row("Dispositivos sesión", str(total))
        g.add_row("Muy cercanos",        str(cercanos))
        g.add_row("Fabricantes únicos",  str(len(fabricantes)))
        g.add_row("Monitoreo activo",    "[green]SÍ[/green]"
                                         if self._monitoreo_activo else "[dim]NO[/dim]")
        g.add_row("Timeout puente",      f"{self.BRIDGE_TIMEOUT}s")
        g.add_row("Buffer puente",       f"{self.BRIDGE_BUF} bytes")

        self.console.print(Panel(
            g,
            title="[bold cyan]BLUETOOTH MODULE — ESTADO[/bold cyan]",
            border_style="cyan",
        ))

    def limpiar_sesion(self):
        with self._lock:
            n = len(self._dispositivos)
            self._dispositivos.clear()
        self._info(f"Sesión BLE reseteada ({n} dispositivos eliminados).")
