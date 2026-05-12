from __future__ import annotations
from core.validators import Validador
from core.log_sistema import LogSistema
from core.ModuleRegistry import ModuleRegistry
from core.command_handler import CommandHandler

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.markup import escape as _esc
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt
from rich.rule import Rule

# ── Asegurar ruta del proyecto ────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── Core ──────────────────────────────────────────────────────────────

# ── Bootscreen ────────────────────────────────────────────────────────
try:
    from core.bootscreen import (
        COMANDOS_HELP,
        mostrar_ayuda,
        mostrar_banner,
        mostrar_bootloader,
    )
except ImportError:
    COMANDOS_HELP = {}

    def mostrar_bootloader(c, nombre, version, iface, estados_modulos=None):
        c.print(Panel(f"[bold green]{nombre} v{version}[/bold green]"))

    def mostrar_banner(c, nombre, version, iface, proyecto=None):
        c.print(Rule(f"[bold green]{nombre} v{version}[/bold green]"))

    def mostrar_ayuda(c, version, cmds=None):
        c.print(Panel("[dim]Sin ayuda.[/dim]", title="AYUDA"))

# ── Auth ──────────────────────────────────────────────────────────────
try:
    from core.auth import GestorAuth
except ImportError:
    class GestorAuth:           # type: ignore[misc]
        def __init__(self, *a, **kw): pass
        def solicitar_acceso(self) -> bool: return True


# ════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class ApexSentinel:

    VERSION = "2.3"
    NOMBRE = "ApexSentinel"

    # ── OUI local — caché de fabricantes ─────────────────────────────
    _OUI_LOCAL: dict[str, str] = {
        "8C:64:A2": "Apple",         "3C:D9:2B": "Apple",      "00:17:F2": "Apple",
        "58:CB:52": "Samsung",       "90:7A:58": "Samsung",     "B0:72:BF": "Samsung",
        "D8:24:BD": "Huawei",        "00:E0:FC": "Huawei",      "6C:4B:90": "Huawei",
        "64:16:7F": "Intel",         "48:51:B7": "Intel",       "A4:C3:F0": "Intel",
        "00:0C:29": "VMware",        "08:00:27": "VirtualBox",
        "B8:27:EB": "Raspberry Pi",  "DC:A6:32": "Raspberry Pi 4",
        "E4:5F:01": "Raspberry Pi 5",
        "00:50:56": "VMware ESXi",   "18:60:24": "Cisco",       "00:1A:A0": "Dell",
        "FC:EC:DA": "Xiaomi",        "64:09:80": "Xiaomi",      "F4:60:E2": "Motorola",
        "78:02:F8": "OnePlus",       "AC:37:43": "HTC",
    }
    _OUI_CACHE: dict[str, str] = {}

    def __init__(self):
        # ── Directorios de trabajo ─────────────────────────────────────
        for d in ["data/logs", "data/evidence", "data/evidence/rf",
                  "data/evidence/rf/iq", "data/evidence/mobile",
                  "core/data/logs", "core/data/security", "plugins"]:
            os.makedirs(d, exist_ok=True)

        self.console = Console()
        self.log = LogSistema(self.console)
        self.config = self._cargar_config()
        self.nombre = self.config.get(
            "sistema", {}).get("nombre",  self.NOMBRE)
        self.version = self.config.get(
            "sistema", {}).get("version", self.VERSION)
        self.auth = GestorAuth(self.config, self.console, self.log)

        self._registrar_senales()

        # ── Carga declarativa de módulos ───────────────────────────────
        self._registry = ModuleRegistry(self)
        self._registry.cargar_todos()

        # ── Despachador de comandos ────────────────────────────────────
        self._cmd = CommandHandler(self)

        # ── primer_arranque: persistir False tras el primer boot ───────
        if self.config.get("sistema", {}).get("primer_arranque", False):
            self.config["sistema"]["primer_arranque"] = False
            self._guardar_config()

        # ── Bootscreen con estados REALES ──────────────────────────────
        mostrar_bootloader(
            self.console,
            nombre=self.nombre,
            version=self.version,
            iface=self._iface(),
            estados_modulos=self._registry.estados(),
        )

    # ── Señales ───────────────────────────────────────────────────────

    def _registrar_senales(self) -> None:
        def _handler(signum, frame):
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
        except Exception:
            pass

    # ── Configuración ─────────────────────────────────────────────────

    def _cargar_config(self) -> dict:
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"sistema": {"nombre": "Sentinel",
                                "version": self.VERSION,
                                "primer_arranque": True}}
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    def _guardar_config(self) -> None:
        """Persiste config.json (necesario para primer_arranque → False)."""
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except OSError as e:
            self.log.warning(f"No se pudo guardar config.json: {e}", "Config")

    # ── Helpers ───────────────────────────────────────────────────────

    def _iface(self) -> str:
        return getattr(getattr(self, "bt", None), "iface", "wlan0mon")

    def _modulo_ok(self, nombre_attr: str) -> bool:
        """Verifica si un módulo está disponible; imprime aviso si no."""
        if getattr(self, nombre_attr, None) is None:
            self.console.print(
                f"[red][!] Módulo '[bold]{nombre_attr}[/bold]' "
                f"no disponible en este entorno.[/red]"
            )
            return False
        return True

    def _limpiar(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")

    def _run(self, cmd: list, timeout: int = 30,
             **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, timeout=timeout, check=True, **kwargs)

    # ── Fabricante de MAC ─────────────────────────────────────────────

    def obtener_fabricante(self, mac: str) -> str:
        mac_upper = mac.upper()
        if mac_upper in self._OUI_CACHE:
            return self._OUI_CACHE[mac_upper]

        prefijo = mac_upper[:8]
        if prefijo in self._OUI_LOCAL:
            vendor = self._OUI_LOCAL[prefijo]
            self._OUI_CACHE[mac_upper] = vendor
            return vendor

        try:
            if int(mac.split(":")[0], 16) & 0x02:
                self._OUI_CACHE[mac_upper] = "MAC aleatorizada"
                return "MAC aleatorizada"
        except (ValueError, IndexError):
            pass

        try:
            import requests
            r = requests.get(
                f"https://api.macvendors.com/{mac}",
                timeout=3,
                headers={"User-Agent": f"ApexSentinel/{self.version}"},
            )
            vendor = r.text.strip() if r.status_code == 200 else "Desconocido"
        except Exception:
            vendor = "Desconocido"

        self._OUI_CACHE[mac_upper] = vendor
        return vendor

    # ── Barra de progreso ─────────────────────────────────────────────

    def animar_barra(self, tarea: str, pasos: int = 20) -> None:
        """Rich Progress — compatible con Live activo (sin print() desnudo)."""
        with Progress(
            SpinnerColumn(style="bold green"),
            TextColumn("[green]{task.description}[/green]"),
            BarColumn(bar_width=24, complete_style="bold green"),
            TextColumn("[bold green]{task.percentage:>3.0f}%[/bold green]"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as pg:
            tk = pg.add_task(tarea, total=pasos)
            for _ in range(pasos):
                time.sleep(0.05)
                pg.advance(tk)
        self.console.print(f"[bold green][OK][/bold green] {tarea}")

    # ── Dashboard de éxito ────────────────────────────────────────────

    def mostrar_dashboard_exito(self, ip: str, servicio: str,
                                credencial: str) -> None:
        from rich import box
        from rich.table import Table
        tabla = Table(title="ACCESO OBTENIDO", header_style="bold green")
        tabla.add_column("Objetivo",           style="cyan",
                         justify="center")
        tabla.add_column("Protocolo",          style="yellow",
                         justify="center")
        tabla.add_column("Credenciales (U:P)",
                         style="bold white", justify="center")
        tabla.add_row(ip, servicio.upper(), credencial)
        self.console.print(
            Panel(tabla, title="[bold green]MISSION ACCOMPLISHED[/bold green]",
                  border_style="bright_green", expand=False))
        self.log.audit(f"Acceso obtenido en {ip} vía {servicio}", "Hydra")
        if getattr(self, "gp", None):
            self.gp.registrar_hallazgo(
                "CRITICO",
                f"Credenciales obtenidas en {ip}:{servicio}",
                f"Credenciales válidas: {credencial}",
                "Cambiar credenciales inmediatamente.",
            )

    # ── Despachador ───────────────────────────────────────────────────

    def _despachar(self, entrada: str) -> bool:
        partes = entrada.strip().lower().split()
        if not partes:
            return True
        cmd, args = partes[0], partes[1:]
        c = self._cmd

        # Comandos con subargumentos
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

        # Banner con proyecto activo
        def _banner():
            proy = (self.gp.proyecto_actual.nombre
                    if getattr(self, "gp", None) and
                    getattr(self.gp, "proyecto_actual", None) else None)
            mostrar_banner(self.console, self.nombre,
                           self.version, self._iface(), proyecto=proy)

        tabla: dict[str, Any] = {
            # Sistema
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
            "scan":      c.scan,
            "netscan":   c.scan,
            "advscan":   c.advscan,
            "portscan":  c.portscan,
            "sweep":     c.sweep,
            "sniff":     c.sniff,
            "radar":     c.radar,
            "audit":     c.audit,
            "vulnscan":  c.vulnscan,
            "sqlcheck":  c.sqlcheck,
            # Wireless
            "wifi":      c.wifi,
            "eviltwin":  c.eviltwin,
            "btjumper": lambda: (self.bt.iniciar_jumper()
                                 if self._modulo_ok("bt") else None),
            # RF
            "rfscan":    c.rfscan,
            "rfmenu":    c.rfmenu,
            "rfbarrido": c.rfbarrido,
            "rfbandas":  c.rfbandas,
            "rfdb":      c.rfdb,
            "rfstats":   c.rfstats,
            "rfstatus":  c.rfestado,
            "radio":     c.radio,
            "rfgrabar":  c.rfgrabar,
            "rfplay":    c.rfplay,
            "adsb":      c.adsb,
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

    # ── Bucle principal ───────────────────────────────────────────────

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


# ── Punto de entrada ──────────────────────────────────────────────────

from typing import Any  # noqa: E402 — necesario para la anotación en _despachar

if __name__ == "__main__":
    for d in ["data/logs", "data/evidence", "data/evidence/rf",
              "data/evidence/rf/iq", "core/data/logs",
              "core/data/security", "plugins"]:
        os.makedirs(d, exist_ok=True)
    ApexSentinel().ejecutar()
