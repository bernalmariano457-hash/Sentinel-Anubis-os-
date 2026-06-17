from __future__ import annotations

import json
import os
import signal
import stat
import sys
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

from rich.console import Console
from rich.markup import escape as _esc
from rich.prompt import Prompt
from rich.panel import Panel
from rich.rule import Rule

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from core.sentinel_ui import animar_barra, mostrar_dashboard_exito
from core.vendor_resolver import VendorResolver
from core.command_handler import CommandHandler
from core.ModuleRegistry import ModuleRegistry
from core.log_sistema import LogSistema

try:
    from core.bootscreen import (
        COMANDOS_HELP,
        mostrar_ayuda,
        mostrar_banner,
        mostrar_bootloader,
    )
except ImportError:
    COMANDOS_HELP: dict[str, Any] = {}

    def mostrar_bootloader(c: Console, nombre: str, version: str,
                           iface: str, estados_modulos: Any = None) -> None:
        c.print(Panel(f"[bold green]{nombre} v{version}[/bold green]"))

    def mostrar_banner(c: Console, nombre: str, version: str,
                       iface: str, proyecto: str | None = None) -> None:
        c.print(Rule(f"[bold green]{nombre} v{version}[/bold green]"))

    def mostrar_ayuda(c: Console, version: str,
                      cmds: dict[str, Any] | None = None) -> None:
        c.print(Panel("[dim]Sin ayuda.[/dim]", title="AYUDA"))

try:
    from core.auth import GestorAuth
except ImportError:
    class GestorAuth:  # type: ignore[misc]
        def __init__(self, *a: Any, **kw: Any) -> None: pass
        def solicitar_acceso(self) -> bool: return True


_WORK_DIRS: tuple[str, ...] = (
    "data/logs", "data/evidence", "data/evidence/rf",
    "data/evidence/rf/iq", "data/evidence/mobile",
    "core/data/logs", "core/data/security", "plugins",
)

_ENV_REQUIREMENTS: tuple[str, ...] = ()

_MIN_FREE_BYTES: int = 50 * 1024 * 1024


class BootstrapError(RuntimeError):
    pass


def _validate_bootstrap() -> None:
    missing_vars = [v for v in _ENV_REQUIREMENTS if not os.environ.get(v)]
    if missing_vars:
        raise BootstrapError(
            f"[FATAL] Variables de entorno requeridas ausentes: {missing_vars}"
        )

    for raw_path in _WORK_DIRS:
        target = Path(raw_path)
        target.mkdir(parents=True, exist_ok=True)

        resolved = target.resolve()
        try:
            mode = resolved.stat().st_mode
        except FileNotFoundError:
            raise BootstrapError(
                f"[FATAL] No se pudo crear o acceder al directorio: {resolved}"
            )

        owner_writable = bool(mode & stat.S_IWUSR)
        group_writable = bool(mode & stat.S_IWGRP)
        other_writable = bool(mode & stat.S_IWOTH)
        effective_uid = os.geteuid() if hasattr(os, "geteuid") else -1
        effective_gid = os.getegid() if hasattr(os, "getegid") else -1

        try:
            dir_stat = resolved.stat()
        except OSError:
            raise BootstrapError(
                f"[FATAL] Permisos ilegibles en: {resolved}"
            )

        is_owner = (effective_uid == dir_stat.st_uid)
        is_group = (effective_gid == dir_stat.st_gid)

        write_ok = (
            (is_owner and owner_writable)
            or (is_group and group_writable)
            or other_writable
            or effective_uid == 0
        )

        if not write_ok:
            raise BootstrapError(
                f"[FATAL] Sin permisos de escritura en: {resolved}"
            )

    try:
        statvfs = os.statvfs(".")
        free_bytes = statvfs.f_bavail * statvfs.f_frsize
        if free_bytes < _MIN_FREE_BYTES:
            raise BootstrapError(
                f"[FATAL] Espacio insuficiente en disco: "
                f"{free_bytes // 1024 // 1024} MB disponibles, "
                f"mínimo requerido: {_MIN_FREE_BYTES // 1024 // 1024} MB"
            )
    except AttributeError:
        pass


class _ShutdownCoordinator:

    def __init__(self) -> None:
        self._shutdown_event: threading.Event = threading.Event()
        self._registered_workers: list[Callable[[], None]] = []
        self._lock: threading.Lock = threading.Lock()

    def register_worker_shutdown(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._registered_workers.append(callback)

    def trigger(self) -> None:
        self._shutdown_event.set()
        with self._lock:
            workers = list(self._registered_workers)
        threads = [
            threading.Thread(target=cb, daemon=True, name=f"shutdown-{i}")
            for i, cb in enumerate(workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown_event.is_set()


class ApexSentinel:

    VERSION = "2.3"
    NOMBRE = "ApexSentinel"

    def __init__(self) -> None:
        self._initialized: bool = False
        self._coordinator: _ShutdownCoordinator = _ShutdownCoordinator()

        self.console = Console()
        self.log = LogSistema(self.console)
        self.config = self._cargar_config()
        self.nombre: str = self.config.get("sistema", {}).get("nombre", self.NOMBRE)
        self.version: str = self.config.get("sistema", {}).get("version", self.VERSION)
        self.auth = GestorAuth(self.config, self.console, self.log)

        self._registrar_senales()

        VendorResolver._USER_AGENT = f"ApexSentinel/{self.version}"

        self._registry = ModuleRegistry(self)
        self._registry.cargar_todos()

        self._cmd = CommandHandler(self)
        self._command_map: dict[str, Callable[[], None]] = self._build_command_map()

        if self.config.get("sistema", {}).get("primer_arranque", False):
            self.config["sistema"]["primer_arranque"] = False
            self._guardar_config()

        mostrar_bootloader(
            self.console,
            nombre=self.nombre,
            version=self.version,
            iface=self._iface(),
            estados_modulos=self._registry.estados(),
        )

        self._initialized = True

    def __enter__(self) -> "ApexSentinel":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        self._coordinator.trigger()
        self._cleanup()
        return False

    def _registrar_senales(self) -> None:
        def _signal_handler(signum: int, frame: Any) -> None:
            sig_name = "SIGINT" if signum == getattr(signal, "SIGINT", 2) else "SIGTERM"
            self.console.print(f"\n[yellow][!] Señal {sig_name} — cerrando...[/yellow]")
            self._coordinator.trigger()
            self._cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm:
            signal.signal(sigterm, _signal_handler)

    def _cleanup(self) -> None:
        try:
            self.log.info("Sesión terminada.", "ApexSentinel")
        except Exception:
            pass

        _closeable_attrs: tuple[tuple[str, str], ...] = (
            ("radar",   "stop_sniffing"),
            ("rf",      "cerrar"),
            ("wifitri", "cerrar"),
            ("adsb",    "cerrar"),
        )

        for attr_name, method_name in _closeable_attrs:
            module_instance = getattr(self, attr_name, None)
            if module_instance is None:
                continue
            closer = getattr(module_instance, method_name, None)
            if callable(closer):
                try:
                    closer()
                except Exception:
                    pass

        cola = getattr(self, "cola", None)
        if cola is not None:
            try:
                cola.limpiar_completadas()
            except Exception:
                pass

        gp = getattr(self, "gp", None)
        if gp is not None and getattr(gp, "proyecto_activo", False):
            try:
                gp.cerrar_proyecto()
            except Exception:
                pass

    def _cargar_config(self) -> dict[str, Any]:
        try:
            with open("config.json", encoding="utf-8") as config_file:
                return json.load(config_file)
        except FileNotFoundError:
            return {
                "sistema": {
                    "nombre": "Sentinel",
                    "version": self.VERSION,
                    "primer_arranque": True,
                }
            }
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    def _guardar_config(self) -> None:
        try:
            with open("config.json", "w", encoding="utf-8") as config_file:
                json.dump(self.config, config_file, ensure_ascii=False, indent=2)
        except OSError as write_error:
            self.log.warning(f"No se pudo guardar config.json: {write_error}", "Config")

    def _iface(self) -> str:
        return getattr(getattr(self, "bt", None), "iface", "wlan0mon")

    def _modulo_ok(self, nombre_attr: str) -> bool:
        if getattr(self, nombre_attr, None) is None:
            self.console.print(
                f"[red][!] Módulo '[bold]{nombre_attr}[/bold]' "
                f"no disponible en este entorno.[/red]"
            )
            return False
        return True

    def _limpiar(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")

    def obtener_fabricante(self, mac: str) -> str:
        return VendorResolver.resolve(mac)

    def animar_barra(self, tarea: str, pasos: int = 20) -> None:
        animar_barra(self.console, tarea, pasos)

    def mostrar_dashboard_exito(self, ip: str, servicio: str, credencial: str) -> None:
        mostrar_dashboard_exito(
            self.console, self.log, ip, servicio, credencial,
            gp=getattr(self, "gp", None),
        )

    def _build_command_map(self) -> dict[str, Callable[[], None]]:
        c = self._cmd

        def _banner() -> None:
            proyecto_nombre = (
                self.gp.proyecto_actual.nombre
                if getattr(self, "gp", None) and getattr(self.gp, "proyecto_actual", None)
                else None
            )
            mostrar_banner(
                self.console, self.nombre, self.version, self._iface(),
                proyecto=proyecto_nombre,
            )

        def _btmapa() -> None:
            if not self._modulo_ok("bt"):
                return
            try:
                from modules.network.bt_mapa import BLEMapaRadar
            except ImportError:
                self.console.print(
                    "[red][!] bt_mapa.py no encontrado en modules/network/[/red]"
                )
                return
            duracion = 120
            try:
                raw_input = self.console.input(
                    "\n[bold cyan]  [?] Duración en segundos (Enter = 120)[/bold cyan]: "
                ).strip()
                if raw_input.isdigit():
                    duracion = int(raw_input)
            except (KeyboardInterrupt, EOFError):
                pass
            BLEMapaRadar(self.bt).iniciar(duracion_seg=duracion)

        return {
            "help":        lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "?":           lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "status":      c.status,
            "hora":        lambda: self.console.print(
                               f"[cyan]Hora:[/cyan] {time.strftime('%H:%M:%S')}"),
            "clear":       _banner,
            "cls":         _banner,
            "logs":        self.log.mostrar_historial,
            "files":       c.files,
            "scan":        c.scan,
            "netscan":     c.scan,
            "advscan":     c.advscan,
            "portscan":    c.portscan,
            "sweep":       c.sweep,
            "sniff":       c.sniff,
            "radar":       c.radar,
            "audit":       c.audit,
            "vulnscan":    c.vulnscan,
            "sqlcheck":    c.sqlcheck,
            "wifi":        c.wifi,
            "eviltwin":    c.eviltwin,
            "btjumper":    lambda: (self.bt.iniciar_jumper() if self._modulo_ok("bt") else None),
            "btmapa":      _btmapa,
            "rfscan":      c.rfscan,
            "rfmenu":      c.rfmenu,
            "rfbarrido":   c.rfbarrido,
            "rfbandas":    c.rfbandas,
            "rfdb":        c.rfdb,
            "rfstats":     c.rfstats,
            "rfstatus":    c.rfestado,
            "radio":       c.radio,
            "rfgrabar":    c.rfgrabar,
            "rfplay":      c.rfplay,
            "adsb":        c.adsb,
            "noaa":        c.noaa,
            "wifitri":     lambda: (self.wifitri.menu() if self._modulo_ok("wifitri") else None),
            "spectrum":    c.spectrum,
            "sa":          c.spectrum,
            "mobile":      c.mobile,
            "mobile-deep": c.mobile_deep,
            "view":        c.view,
            "geofoto":     c.geofoto,
            "osint":       c.osint,
            "cve":         c.cve,
            "phishing":    c.phishing,
            "ducky":       c.ducky,
            "stealth":     c.stealth,
            "panic":       c.panic,
        }

    def _despachar(self, entrada: str) -> bool:
        partes = entrada.strip().lower().split()
        if not partes:
            return True

        cmd, args = partes[0], partes[1:]
        c = self._cmd

        if cmd == "proyecto":
            c.proyecto(args)
            return True

        if cmd == "reporte":
            c.reporte(args)
            return True

        if cmd in ("job", "jobs"):
            c.jobs(args)
            return True

        if cmd in ("plugin", "plugins"):
            c.plugins(args)
            return True

        if cmd == "locate":
            (c.locate_p if "-p" in args else c.locate)()
            return True

        handler = self._command_map.get(cmd)
        if handler is not None:
            try:
                handler()
            except Exception as dispatch_error:
                self.console.print(f"[red][!] Error en '{cmd}': {dispatch_error}[/red]")
                self.log.error(str(dispatch_error), f"cmd:{cmd}")
            return True

        plugin_registry = getattr(self, "plugins", None)
        if plugin_registry is not None and plugin_registry.tiene_comando(cmd):
            plugin_registry.ejecutar_comando(cmd, args)
            return True

        return False

    def ejecutar(self) -> None:
        if not self.auth.solicitar_acceso():
            self.console.print("[red][!] Acceso denegado. Sistema bloqueado.[/red]")
            self.log.warning("Sistema bloqueado por intentos fallidos.", "GestorAuth")
            return

        dependency_checker = getattr(self, "checker", None)
        if dependency_checker is not None:
            dependency_checker.verificar_dependencias()

        self.log.verificar_y_limpiar()

        stealth_module = getattr(self, "stealth", None)
        if stealth_module is not None:
            stealth_module.verificar_identidad()

        self.log.info("Sistema iniciado correctamente.", "ApexSentinel")

        rf_module = getattr(self, "rf", None)
        if rf_module is not None:
            rf_hardware_tag = (
                f"[green]{rf_module.hw_nombre}[/green]"
                if rf_module.hw_disponible
                else f"[yellow]{rf_module.hw_nombre}[/yellow]"
            )
            self.console.print(f"\n[dim][RF] Hardware: {rf_hardware_tag}[/dim]")

        gp_module = getattr(self, "gp", None)
        if gp_module is not None and not gp_module.proyecto_activo:
            self.console.print(
                "\n[dim][tip] Usa [bold white]proyecto nuevo[/bold white] "
                "para crear un workspace de operación.[/dim]\n"
            )

        while not self._coordinator.is_shutdown:
            try:
                proyecto_label = (
                    f"[{_esc(str(self.gp.proyecto_activo.nombre))}]"
                    if getattr(self, "gp", None) and self.gp.proyecto_activo
                    else ""
                )
                prompt_str = (
                    f"[bold green]AnubisOS[/bold green]"
                    f"[dim white]@[/dim white]"
                    f"[bold cyan]Sentinel[/bold cyan]"
                    f"[dim]{proyecto_label}[/dim]"
                    f"[bold white]~#[/bold white]"
                )
                entrada = Prompt.ask(prompt_str, default="").strip()

                if not entrada:
                    continue

                if entrada.lower() == "exit":
                    self.console.print("[yellow][!] Desconectando Sentinel...[/yellow]")
                    self.log.info("Sesión cerrada por el operador.", "ApexSentinel")
                    time.sleep(0.5)
                    break

                if not self._despachar(entrada):
                    self.console.print(
                        f"[yellow][?] Comando '[bold]{entrada}[/bold]' no "
                        f"reconocido. Escribe [bold white]help[/bold white] "
                        f"para ver opciones.[/yellow]"
                    )

            except EOFError:
                break
            except Exception as loop_error:
                self.console.print(f"[red][!] Error inesperado: {loop_error}[/red]")
                self.log.error(str(loop_error), "Bucle principal")


def main() -> None:
    try:
        _validate_bootstrap()
    except BootstrapError as bootstrap_failure:
        sys.stderr.write(str(bootstrap_failure) + "\n")
        sys.exit(1)

    with ApexSentinel() as sentinel:
        sentinel.ejecutar()


if __name__ == "__main__":
    main()
