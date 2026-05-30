from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape as _esc
from rich.prompt import Prompt
from rich.panel import Panel
from rich.rule import Rule

from core.sentinel_ui import animar_barra, mostrar_dashboard_exito
from core.vendor_resolver import VendorResolver
from core.command_handler import CommandHandler
from core.ModuleRegistry import ModuleRegistry
from core.log_sistema import LogSistema

# Modo desarrollo: asegura que el proyecto esté en el path antes de importar core/
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

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

# auth es crítico — si no existe el módulo el sistema no debería arrancar,
# pero mantenemos el fallback para entornos de desarrollo sin el paquete completo
try:
    from core.auth import GestorAuth
except ImportError:
    class GestorAuth:  # type: ignore[misc]
        def __init__(self, *a: Any, **kw: Any) -> None: pass
        def solicitar_acceso(self) -> bool: return True


_WORK_DIRS = (
    "data/logs", "data/evidence", "data/evidence/rf",
    "data/evidence/rf/iq", "data/evidence/mobile",
    "core/data/logs", "core/data/security", "plugins",
)


def _ensure_dirs() -> None:
    for d in _WORK_DIRS:
        os.makedirs(d, exist_ok=True)


class ApexSentinel:

    VERSION = "2.3"
    NOMBRE = "ApexSentinel"

    def __init__(self) -> None:
        _ensure_dirs()

        self.console = Console()
        self.log = LogSistema(self.console)
        self.config = self._cargar_config()
        self.nombre = self.config.get(
            "sistema", {}).get("nombre",  self.NOMBRE)
        self.version = self.config.get(
            "sistema", {}).get("version", self.VERSION)
        self.auth = GestorAuth(self.config, self.console, self.log)

        self._registrar_senales()

        VendorResolver._USER_AGENT = f"ApexSentinel/{self.version}"

        self._registry = ModuleRegistry(self)
        self._registry.cargar_todos()

        self._cmd = CommandHandler(self)

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

    # Señales del sistema

    def _registrar_senales(self) -> None:
        def _handler(signum: int, frame: Any) -> None:
            sig = "SIGINT" if signum == getattr(
                signal, "SIGINT", 2) else "SIGTERM"
            self.console.print(
                f"\n[yellow][!] Señal {sig} — cerrando...[/yellow]")
            self._cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, _handler)
        term = getattr(signal, "SIGTERM", None)
        if term:
            signal.signal(term, _handler)

    def _cleanup(self) -> None:
        try:
            if self.log:
                self.log.info("Sesión terminada.", "ApexSentinel")
            if getattr(self, "radar", None):
                try:
                    self.radar.stop_sniffing()
                except Exception:
                    pass
            if getattr(self, "cola", None):
                self.cola.limpiar_completadas()
            if getattr(self, "gp", None) and self.gp.proyecto_activo:
                self.gp.cerrar_proyecto()
            if getattr(self, "rf", None):
                try:
                    self.rf.cerrar()
                except Exception:
                    pass
            for _attr in ("wifitri", "adsb"):
                _mod = getattr(self, _attr, None)
                if _mod and hasattr(_mod, "cerrar"):
                    try:
                        _mod.cerrar()
                    except Exception:
                        pass
        except Exception:
            pass

    # Config

    def _cargar_config(self) -> dict[str, Any]:
        try:
            with open("config.json", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"sistema": {
                "nombre": "Sentinel",
                "version": self.VERSION,
                "primer_arranque": True,
            }}
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    def _guardar_config(self) -> None:
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except OSError as e:
            self.log.warning(f"No se pudo guardar config.json: {e}", "Config")

    # Helpers

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

    # Delegados de UI — compatibilidad con módulos existentes

    def obtener_fabricante(self, mac: str) -> str:
        return VendorResolver.resolve(mac)

    def animar_barra(self, tarea: str, pasos: int = 20) -> None:
        animar_barra(self.console, tarea, pasos)

    def mostrar_dashboard_exito(self, ip: str, servicio: str, credencial: str) -> None:
        mostrar_dashboard_exito(
            self.console, self.log, ip, servicio, credencial,
            gp=getattr(self, "gp", None),
        )

    # Despachador de comandos

    def _despachar(self, entrada: str) -> bool:
        partes = entrada.strip().lower().split()
        if not partes:
            return True
        cmd, args = partes[0], partes[1:]
        c = self._cmd

        def _ble_mapa(s: "ApexSentinel") -> None:
            try:
                from modules.network.bt_mapa import BLEMapaRadar
            except ImportError:
                self.console.print(
                    "[red][!] bt_mapa.py no encontrado en modules/network/[/red]")
                return
            duracion = 120
            try:
                raw = self.console.input(
                    "\n[bold cyan]  [?] Duración en segundos (Enter = 120)[/bold cyan]: "
                ).strip()
                if raw.isdigit():
                    duracion = int(raw)
            except (KeyboardInterrupt, EOFError):
                pass
            BLEMapaRadar(s.bt).iniciar(duracion_seg=duracion)

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

        def _banner() -> None:
            proy = (self.gp.proyecto_actual.nombre
                    if getattr(self, "gp", None) and
                    getattr(self.gp, "proyecto_actual", None) else None)
            mostrar_banner(self.console, self.nombre,
                           self.version, self._iface(), proyecto=proy)

        tabla: dict[str, Any] = {
            "help": lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "?": lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "status":    c.status,
            "hora": lambda: self.console.print(
                f"[cyan]Hora:[/cyan] {time.strftime('%H:%M:%S')}"),
            "clear":     _banner,
            "cls":       _banner,
            "logs":      self.log.mostrar_historial,
            "files":     c.files,
            # Red
            "scan":      c.scan,      "netscan":   c.scan,
            "advscan":   c.advscan,   "portscan":  c.portscan,
            "sweep":     c.sweep,     "sniff":     c.sniff,
            "radar":     c.radar,     "audit":     c.audit,
            "vulnscan":  c.vulnscan,  "sqlcheck":  c.sqlcheck,
            # Wireless
            "wifi":      c.wifi,      "eviltwin":  c.eviltwin,
            "btjumper": lambda: (self.bt.iniciar_jumper()
                                 if self._modulo_ok("bt") else None),
            "btmapa": lambda: (_ble_mapa(self)
                               if self._modulo_ok("bt") else None),
            # RF / SDR
            "rfscan":    c.rfscan,    "rfmenu":    c.rfmenu,
            "rfbarrido": c.rfbarrido, "rfbandas":  c.rfbandas,
            "rfdb":      c.rfdb,      "rfstats":   c.rfstats,
            "rfstatus":  c.rfestado,  "radio":     c.radio,
            "rfgrabar":  c.rfgrabar,  "rfplay":    c.rfplay,
            "adsb":      c.adsb,
            "noaa":      c.noaa,
            # WiFi triangulación
            "wifitri": lambda: (self.wifitri.menu()
                                if self._modulo_ok("wifitri") else None),
            # Spectrum
            "spectrum":  c.spectrum,
            "sa":        c.spectrum,
            # Mobile / Forense
            "mobile":      c.mobile,
            "mobile-deep": c.mobile_deep,
            "view":        c.view,
            # OSINT / Geo
            "geofoto":   c.geofoto,
            "osint":     c.osint,
            "cve":       c.cve,
            # Ofensivo
            "phishing":  c.phishing,
            "ducky":     c.ducky,
            "stealth":   c.stealth,
            "panic":     c.panic,
        }

        if cmd in tabla:
            try:
                tabla[cmd]()
            except Exception as exc:
                self.console.print(f"[red][!] Error en '{cmd}': {exc}[/red]")
                self.log.error(str(exc), f"cmd:{cmd}")
            return True

        if getattr(self, "plugins", None) and self.plugins.tiene_comando(cmd):
            self.plugins.ejecutar_comando(cmd, args)
            return True

        return False

    # Bucle principal

    def ejecutar(self) -> None:
        if not self.auth.solicitar_acceso():
            self.console.print(
                "[red][!] Acceso denegado. Sistema bloqueado.[/red]")
            self.log.warning(
                "Sistema bloqueado por intentos fallidos.", "GestorAuth")
            return

        if getattr(self, "checker", None):
            self.checker.verificar_dependencias()

        self.log.verificar_y_limpiar()

        if getattr(self, "stealth", None):
            self.stealth.verificar_identidad()

        self.log.info("Sistema iniciado correctamente.", "ApexSentinel")

        if getattr(self, "rf", None):
            rf_tag = (f"[green]{self.rf.hw_nombre}[/green]"
                      if self.rf.hw_disponible
                      else f"[yellow]{self.rf.hw_nombre}[/yellow]")
            self.console.print(f"\n[dim][RF] Hardware: {rf_tag}[/dim]")

        if getattr(self, "gp", None) and not self.gp.proyecto_activo:
            self.console.print(
                "\n[dim][tip] Usa [bold white]proyecto nuevo[/bold white] "
                "para crear un workspace de operación.[/dim]\n")

        while True:
            try:
                plab = (
                    f"[{_esc(str(self.gp.proyecto_activo.nombre))}]"
                    if getattr(self, "gp", None) and self.gp.proyecto_activo
                    else ""
                )
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
                        f"[yellow][?] Comando '[bold]{entrada}[/bold]' no "
                        f"reconocido. Escribe [bold white]help[/bold white] "
                        f"para ver opciones.[/yellow]")
            except EOFError:
                self._cleanup()
                break
            except Exception as exc:
                self.console.print(f"[red][!] Error inesperado: {exc}[/red]")
                self.log.error(str(exc), "Bucle principal")


def main() -> None:
    # Entry point registrado en pyproject.toml → [project.scripts] sentinel
    _ensure_dirs()
    ApexSentinel().ejecutar()


if __name__ == "__main__":
    main()
