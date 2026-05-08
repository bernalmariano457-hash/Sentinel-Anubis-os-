from __future__ import annotations
from core.command_handler import CommandHandler
from modules.rf.rf_module import RFModuleIntegrado
from core.validators import Validador
from core.log_sistema import LogSistema

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.markup import escape as _esc
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

# ── Asegurar ruta del proyecto ────────────────────────────────────────
if sys.platform == "win32":
    _proj = os.path.abspath(os.path.dirname(__file__))
    os.add_dll_directory(_proj)

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# ── Módulos propios ───────────────────────────────────────────────────

# ── Bootscreen ────────────────────────────────────────────────────────
try:
    from core.bootscreen import (
        ANUBIS_ART, COMANDOS_HELP, ESTILOS_LOG, MODULOS_BOOT,
        mostrar_ayuda, mostrar_banner, mostrar_bootloader,
    )
except ImportError:
    ESTILOS_LOG = {"INFO": ("cyan", "ℹ"), "WARNING": ("yellow", "⚠"),
                   "ERROR": ("red", "✖"),  "SUCCESS": ("green", "✔"),
                   "AUDIT": ("magenta", "🔍"), "DEBUG": ("dim", "·")}
    MODULOS_BOOT = []
    ANUBIS_ART = ""
    COMANDOS_HELP = {}

    def mostrar_bootloader(console, nombre, version, iface):
        console.print(
            Panel(f"[bold green]{nombre} v{version}[/bold green]", border_style="green"))

    def mostrar_banner(console, nombre, version, iface):
        console.print(Rule(f"[bold green]{nombre} v{version}[/bold green]"))

    def mostrar_ayuda(console, version, cmds):
        console.print(
            Panel("[dim]Sin ayuda disponible.[/dim]", title="AYUDA", border_style="cyan"))

# ── Auth ──────────────────────────────────────────────────────────────
try:
    from core.auth import GestorAuth
except ImportError:
    class GestorAuth:           # type: ignore
        def __init__(self, *a, **kw): pass
        def solicitar_acceso(self) -> bool: return True


def _importar(modulo: str, clase: str):
    """Importa una clase de forma segura; retorna None si falla."""
    try:
        m = __import__(modulo, fromlist=[clase])
        return getattr(m, clase)
    except Exception as exc:
        logging.getLogger("sentinel").debug(
            f"[IMPORT] {clase} ({modulo}): {exc}")
        return None


# ════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL
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
        self.nombre = self.config.get(
            "sistema", {}).get("nombre",  self.NOMBRE)
        self.version = self.config.get(
            "sistema", {}).get("version", self.VERSION)
        self.log = LogSistema(self.console)
        self.auth = GestorAuth(self.config, self.console, self.log)

        self._registrar_senales()
        self._cargar_modulos()

        # Despachador de comandos (separado del núcleo)
        self._cmd = CommandHandler(self)

    # ── Señales OS ────────────────────────────────────────────────────

    def _registrar_senales(self):
        def _handler(signum, frame):
            nombre_sig = "SIGINT" if signum == getattr(
                signal, "SIGINT", 2) else "SIGTERM"
            self.console.print(
                f"\n[yellow][!] Señal {nombre_sig} — cerrando...[/yellow]")
            self._cleanup()
            sys.exit(0)
        signal.signal(signal.SIGINT, _handler)
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm:
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
            if getattr(self, "rf", None):
                self.rf.cerrar()
        except Exception:
            pass

    # ── Configuración ─────────────────────────────────────────────────

    def _cargar_config(self) -> dict:
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"sistema": {"nombre": "Sentinel", "version": self.VERSION,
                                "primer_arranque": True}}
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    # ── Carga de módulos ──────────────────────────────────────────────

    def _cargar_modulos(self):
        imports = [
            ("checker",      "SystemChecker",    "core.SystemChecker"),
            ("audit_engine", "AuditEngine",       "modules.audit.AuditEngine"),
            ("dict_manager", "DictionaryManager",
             "modules.audit.DictionaryManager"),
            ("hydra",        "HydraModule",       "HydraModule"),
            ("reportes",     "ReportManager",     "modules.reporte.ReportManager"),
            ("stealth",      "Stealth",           "modules.forense.Stealth"),
            ("locator",      "LocatorModule",     "modules.geo.LocatorModule"),
            ("exif",         "ExifAnalyzer",      "modules.forense.ExifAnalyzer"),
            ("geopreciose",  "GeoPrecise",        "modules.geo.GeoPrecise"),
            ("wifi_attack",  "WifiAtack",         "modules.network.WifiAtack"),
            ("reader",       "ForensicReader",
             "modules.forense.ForensicReader"),
            ("sniffer",      "TacticalSniffer",
             "modules.network.TacticalSniffer"),
            ("bt",           "bt_module",         "modules.network.bt_module"),
            ("sweep",        "SweepModule",       "modules.network.SweepModule"),
            ("ducky",        "DuckyModule",       "modules.audit.DuckyModule"),
            ("adv_scanner",  "AdvancedScanner",
             "modules.network.AdvancedScanner"),
            ("mobile",       "MobileSentinel",
             "modules.forense.MobileSentinel"),
            ("security",     "SecurityModule",    "core.Security"),
            ("network",      "Network",           "modules.network.Network"),
            ("phishing",     "PhishingModule",    "modules.audit.PhishingModule"),
        ]

        for attr, clase, modulo in imports:
            Cls = _importar(modulo, clase)
            if Cls is None:
                setattr(self, attr, None)
                continue
            try:
                setattr(self, attr,
                        Cls() if clase in ("SystemChecker", "ReportManager", "DictionaryManager")
                        else Cls(self))
            except Exception as e:
                self.log.warning(f"{clase} falló al iniciar: {e}", "Init")
                setattr(self, attr, None)

        # Radar / Geomap
        try:
            from modules.network.RadarSentinel import RadarSentinel
            from modules.geo.GeomapSentinel import GeomapSentinel
            self.radar = RadarSentinel(interface="Wi-Fi")
            self.geomap = GeomapSentinel()
        except Exception as e:
            self.log.warning(f"Radar/Geomap: {e}", "Init")
            self.radar = self.geomap = None

        # EvilTwin
        try:
            from modules.network.EvilTwinServer import iniciar_servidor
            self._evil_twin_server = iniciar_servidor
        except Exception:
            self._evil_twin_server = None

        # Clases opcionales (instanciar bajo demanda)
        self._db_extractor_cls = _importar("db_extractor", "DatabaseExtractor")
        self._wa_decryptor_cls = _importar("WADecryptor",  "WhatsAppDecryptor")

        # ForensicReader directo si el genérico falló
        _FR = _importar("ForensicReader", "ForensicReader")
        if _FR is not None and self.reader is None:
            try:
                self.reader = _FR(self)
            except Exception as e:
                self.log.warning(f"ForensicReader directo: {e}", "Init")

        # Scapy
        try:
            from scapy.all import ARP, Ether, srp
            self._ARP, self._Ether, self._srp = ARP, Ether, srp
        except Exception:
            self._ARP = self._Ether = self._srp = None

        # Módulos profesionales
        for nombre_cls, modulo_str, attr_name in [
            ("GestorProyectos", "core.GestorProyectos",  "gp"),
            ("OSINTEngine",     "modules.osint.OSINTEngine", "osint"),
            ("CVEMatcher",      "modules.osint.CVEMatcher",  "cve"),
            ("ColaTareas",      "core.ColaTareas",        "cola"),
        ]:
            Cls = _importar(modulo_str, nombre_cls)
            try:
                setattr(self, attr_name, Cls(self) if Cls else None)
            except Exception as e:
                self.log.warning(f"{nombre_cls}: {e}", "Init")
                setattr(self, attr_name, None)

        # MotorReportes depende de GestorProyectos
        try:
            from modules.reporte.MotorReportes import MotorReportes
            self.motor_rep = MotorReportes(self) if self.gp else None
        except Exception as e:
            self.log.warning(f"MotorReportes: {e}", "Init")
            self.motor_rep = None

        # Plugins
        try:
            from core.PluginSystem import GestorPlugins, crear_plugin_ejemplo
            self.plugins = GestorPlugins(self)
            crear_plugin_ejemplo()
            self.plugins.cargar_todos()
        except Exception as e:
            self.log.warning(f"PluginSystem: {e}", "Init")
            self.plugins = None

        # RF Module Integrado
        try:
            self.rf = RFModuleIntegrado(self)
            self.log.info(f"RF Module cargado — {self.rf.hw_nombre}", "Init")
        except Exception as e:
            self.log.warning(f"RFModuleIntegrado: {e}", "Init")
            self.rf = None

    # ── Helpers ───────────────────────────────────────────────────────

    def _iface(self) -> str:
        return getattr(getattr(self, "bt", None), "iface", "wlan0mon")

    def _modulo_ok(self, nombre_attr: str) -> bool:
        m = getattr(self, nombre_attr, None)
        if m is None:
            self.console.print(
                f"[red][!] Módulo '{nombre_attr}' no disponible en este entorno.[/red]")
            return False
        return True

    def _limpiar(self):
        os.system("cls" if os.name == "nt" else "clear")

    def _run(self, cmd: list, timeout: int = 30, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, timeout=timeout, check=True, **kwargs)

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
        from rich import box as _box
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
        self.console.print(Panel(tabla, title="[bold green]MISSION ACCOMPLISHED[/bold green]",
                                 border_style="bright_green", expand=False))
        self.log.audit(f"Acceso obtenido en {ip} vía {servicio}", "Hydra")
        if self.gp:
            self.gp.registrar_hallazgo("CRITICO", f"Credenciales obtenidas en {ip}:{servicio}",
                                       f"Credenciales válidas: {credencial}",
                                       "Cambiar credenciales inmediatamente.")

    # ── Despachador ───────────────────────────────────────────────────

    def _despachar(self, entrada: str) -> bool:
        partes = entrada.strip().lower().split()
        if not partes:
            return True
        cmd = partes[0]
        args = partes[1:]
        c = self._cmd

        # Comandos con subargs
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

        tabla = {
            # Generales
            "help": lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "?": lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "status":    c.status,
            "hora": lambda: self.console.print(f"[cyan]Hora:[/cyan] {time.strftime('%H:%M:%S')}"),
            "clear": lambda: mostrar_banner(self.console, self.nombre, self.version, self._iface()),
            "cls": lambda: mostrar_banner(self.console, self.nombre, self.version, self._iface()),
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
            "btjumper": lambda: self.bt.iniciar_jumper() if self._modulo_ok("bt") else None,
            # RF
            "rfscan":    c.rfscan,
            "rfmenu":    c.rfmenu,
            "rfbarrido": c.rfbarrido,
            "rfbandas":  c.rfbandas,
            "rfdb":      c.rfdb,
            "rfstats":   c.rfstats,
            "rfstatus":  c.rfestado,
            # RF — nuevos módulos v2.2
            "radio":     c.radio,       # demodulación en tiempo real
            "rfgrabar":  c.rfgrabar,    # grabación IQ a archivo
            "rfplay":    c.rfplay,      # reproducir grabación IQ
            "adsb":      c.adsb,        # monitor ADS-B 1090 MHz
            # Mobile
            "mobile":       c.mobile,
            "mobile-deep":  c.mobile_deep,
            "view":         c.view,
            # OSINT / Geo
            "geofoto":   c.geofoto,
            "osint":     c.osint,
            "cve":       c.cve,
            # Ofensivo
            "phishing":  c.phishing,
            "ducky":     c.ducky,
            # Stealth
            "stealth":   c.stealth,
            "panic":     c.panic,
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

        if self.rf:
            rf_status = (f"[green]{self.rf.hw_nombre}[/green]"
                         if self.rf.hw_disponible else f"[yellow]{self.rf.hw_nombre}[/yellow]")
            self.console.print(f"\n[dim][RF] Hardware: {rf_status}[/dim]")

        if self.gp and not self.gp.proyecto_activo:
            self.console.print(
                "\n[dim][tip] Usa [bold white]proyecto nuevo[/bold white] "
                "para crear un workspace de operación.[/dim]\n"
            )

        while True:
            try:
                plab = f"[{_esc(str(self.gp.proyecto_activo.nombre))}]" \
                    if self.gp and self.gp.proyecto_activo else ""
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


# ── Punto de entrada ──────────────────────────────────────────────────

if __name__ == "__main__":
    for d in ["data/logs", "data/evidence", "data/evidence/rf",
              "data/evidence/rf/iq", "plugins"]:
        os.makedirs(d, exist_ok=True)

    ApexSentinel().ejecutar()
