"""
╔══════════════════════════════════════════════════════╗
║         APEX SENTINEL — ANUBIS OS  v2.1              ║
║         Main integrado con arquitectura mejorada     ║
╚══════════════════════════════════════════════════════╝

Integra:
  - bootscreen.py     → Pantalla de arranque animada
  - help_menu.py      → Menú de ayuda por categorías
  - log_visual.py     → Sistema de logs estructurado
  - validators.py     → Validaciones de entrada
  - Command Pattern   → Cada comando es una clase limpia
  - bcrypt            → Autenticación segura
  - Todos los comandos originales preservados
"""

import os
import sys
import json
import time
import socket
import hashlib
import logging
import threading
import subprocess
import ipaddress
import re
from datetime import datetime

# --- COMPATIBILIDAD WINDOWS ---
if sys.platform == 'win32':
    path_proyecto = os.path.abspath(os.path.dirname(__file__))
    os.add_dll_directory(path_proyecto)

# --- INTERFAZ ---
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from rich.rule import Rule
from rich.columns import Columns
from rich.align import Align
from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn
from rich import box

# --- AUTENTICACIÓN SEGURA ---
try:
    import bcrypt
    BCRYPT_OK = True
except ImportError:
    BCRYPT_OK = False

# --- BOOTSCREEN & AUTH ---
from bootscreen import (
    mostrar_bootloader, mostrar_banner, mostrar_ayuda,
    MODULOS_BOOT, ESTILOS_LOG, ANUBIS_ART, COMANDOS_HELP,
)
from auth import GestorAuth

# --- MÓDULOS TÁCTICOS ---


def _importar(modulo, clase):
    try:
        m = __import__(modulo, fromlist=[clase])
        return getattr(m, clase)
    except Exception as e:
        logging.warning(f"[IMPORT] {clase} no disponible: {e}")
        return None

# ANUBIS_ART, MODULOS_BOOT, ESTILOS_LOG → importados desde bootscreen.py


# ============================================================
# VALIDADORES
# ============================================================

class Validador:
    MAX_INTENTOS = 3

    @staticmethod
    def es_ip(v):
        try:
            ipaddress.ip_address(v)
            return True
        except ValueError:
            return False

    @staticmethod
    def es_rango_cidr(v):
        try:
            ipaddress.ip_network(v, strict=False)
            return True
        except ValueError:
            return False

    @staticmethod
    def es_mac(v):
        return bool(re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", v))

    @staticmethod
    def es_url(v):
        return bool(re.match(r"^https?://[^\s/$.?#].[^\s]*$", v, re.IGNORECASE))

    @staticmethod
    def es_frecuencia(v):
        try:
            return 1.0 <= float(v) <= 6000.0
        except ValueError:
            return False

    @classmethod
    def pedir(cls, console, prompt, validador=None, error="Valor inválido.",
              default=None, password=False, intentos=None):
        max_i = intentos or cls.MAX_INTENTOS
        prompt_fmt = f"\n[bold cyan]{prompt}[/bold cyan]"
        if default:
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
    def pedir_ip(cls, console, prompt="[?] IP objetivo"):
        return cls.pedir(console, prompt, cls.es_ip, "IP inválida. Ej: 192.168.1.1")

    @classmethod
    def pedir_rango(cls, console, prompt="[?] Rango de red", default="192.168.1.0/24"):
        return cls.pedir(console, prompt, cls.es_rango_cidr,
                         "CIDR inválido. Ej: 192.168.1.0/24", default=default)

    @classmethod
    def pedir_url(cls, console, prompt="[?] URL objetivo"):
        return cls.pedir(console, prompt, cls.es_url,
                         "URL inválida. Debe empezar con http:// o https://")

    @classmethod
    def pedir_frecuencia(cls, console, prompt="[?] Frecuencia (MHz)"):
        v = cls.pedir(console, prompt, cls.es_frecuencia,
                      "Frecuencia inválida. Rango: 1.0 - 6000.0 MHz")
        return float(v) if v else None

    @classmethod
    def pedir_segundos(cls, console, prompt="[?] Duración (segundos)",
                       minimo=1, maximo=300, default=30):
        def validar(v):
            try:
                return minimo <= int(v) <= maximo
            except ValueError:
                return False
        v = cls.pedir(console, f"{prompt} [{minimo}-{maximo}]", validar,
                      f"Número entre {minimo} y {maximo}.", default=str(default))
        return int(v) if v else default


# ============================================================
# SISTEMA DE LOGS
# ============================================================

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

    def _ts(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _cargar(self):
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

    def _log(self, nivel, mensaje, modulo="Sistema"):
        entrada = {"timestamp": self._ts(), "nivel": nivel,
                   "modulo": modulo, "mensaje": mensaje}
        self._entradas.append(entrada)
        self._guardar()
        color, icono = ESTILOS_LOG.get(nivel, ("white", "·"))
        # Usar Text + append para evitar MarkupError con contenido dinámico
        from rich.text import Text as _Text
        line = _Text()
        line.append(entrada["timestamp"],           style="dim")
        line.append(" ")
        line.append(f"{icono} {nivel:<8}",          style=color)
        line.append(" ")
        line.append(f"{str(modulo):<18}",           style="cyan")
        line.append(" ")
        line.append(str(mensaje))
        self.console.print(line)
        getattr(logging, nivel.lower(), logging.info)(f"[{modulo}] {mensaje}")

    def info(self, msg, modulo="Sistema"):    self._log("INFO", msg, modulo)
    def warning(self, msg, modulo="Sistema"): self._log("WARNING", msg, modulo)
    def error(self, msg, modulo="Sistema"):   self._log("ERROR", msg, modulo)
    def success(self, msg, modulo="Sistema"): self._log("SUCCESS", msg, modulo)
    def audit(self, msg, modulo="Auditoría"): self._log("AUDIT", msg, modulo)

    def mostrar_historial(self, ultimas=50):
        entradas = self._entradas[-ultimas:]
        if not entradas:
            self.console.print(Panel("[dim]Sin registros.[/dim]",
                                     title="HISTORIAL", border_style="dim green"))
            return
        conteos = {}
        for e in self._entradas:
            conteos[e["nivel"]] = conteos.get(e["nivel"], 0) + 1
        # Resumen con Text.append — evita MarkupError con iconos especiales
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
            tabla.add_row(
                e["timestamp"],
                nivel_txt,
                str(e["modulo"]),
                str(e["mensaje"]),
            )
        self.console.print(Panel(tabla,
                                 title=f"[bold]HISTORIAL — {len(entradas)} entradas[/bold]",
                                 border_style="green", box=box.HEAVY_EDGE))

    def verificar_y_limpiar(self, max_entradas=500):
        if len(self._entradas) > max_entradas:
            self._entradas = self._entradas[-max_entradas:]
            self._guardar()


# mostrar_bootloader, mostrar_banner, mostrar_ayuda → importados desde bootscreen.py


# ============================================================
# CLASE PRINCIPAL
# ============================================================

class ApexSentinel:

    def __init__(self):
        for d in ["data/logs", "data/evidence", "plugins"]:
            os.makedirs(d, exist_ok=True)
        self.console = Console()
        self.config = self._cargar_config()
        self.nombre = self.config["sistema"]["nombre"]
        self.version = self.config["sistema"]["version"]
        self.log = LogSistema(self.console)
        self.auth = GestorAuth(self.config, self.console, self.log)
        self._registrar_senales()
        self._cargar_modulos()

    def _registrar_senales(self):
        """Registra manejadores de SIGINT y SIGTERM para cierre limpio."""
        import signal

        def _handler(signum, frame):
            nombre_sig = "SIGINT" if signum == getattr(
                signal, "SIGINT", 2) else "SIGTERM"
            self.console.print(
                f"\n[yellow][!] Señal {nombre_sig} recibida — cerrando Sentinel...[/yellow]"
            )
            self._cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT,  _handler)
        # SIGTERM no existe en Windows; proteger con getattr
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm is not None:
            signal.signal(sigterm, _handler)

    def _cleanup(self):
        """Libera recursos antes de salir (llamado por señal o exit normal)."""
        try:
            if self.log:
                self.log.info(
                    "Sesión terminada por señal del sistema.", "ApexSentinel")
            if getattr(self, "radar", None):
                self.radar.stop_sniffing()
            if getattr(self, "cola", None):
                self.cola.limpiar_completadas()
            if getattr(self, "gp", None) and self.gp.proyecto_activo:
                self.gp.cerrar_proyecto()
        except Exception:
            pass  # cleanup nunca debe propagar excepciones

    def _cargar_config(self) -> dict:
        try:
            with open("config.json", "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"sistema": {"nombre": "Sentinel", "version": "2.1",
                                "primer_arranque": True}}
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    def _cargar_modulos(self):
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
            ("rf",           "RFScanner",         "RFScanner"),
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

        try:
            from RadarSentinel import RadarSentinel
            from GeomapSentinel import GeomapSentinel
            self.radar = RadarSentinel(interface="Wi-Fi")
            self.radar.start_sniffing()
            self.geomap = GeomapSentinel()
        except Exception as e:
            self.log.warning(f"Radar/Geomap no disponibles: {e}", "Init")
            self.radar = self.geomap = None

        try:
            from EvilTwinServer import iniciar_servidor
            self._evil_twin_server = iniciar_servidor
        except Exception:
            self._evil_twin_server = None

        self._db_extractor_cls = _importar("db_extractor", "DatabaseExtractor")
        self._wa_decryptor_cls = _importar("WADecryptor",  "WhatsAppDecryptor")

        try:
            from scapy.all import ARP, Ether, srp
            self._ARP, self._Ether, self._srp = ARP, Ether, srp
        except Exception:
            self._ARP = self._Ether = self._srp = None

        # ── Módulos profesionales nuevos ─────────────────────────────
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

    # ── helpers ──────────────────────────────────────────────────────

    def _iface(self):
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
            r = requests.get(f"https://api.macvendors.com/{mac}", timeout=1)
            return r.text if r.status_code == 200 else "Desconocido"
        except Exception:
            return "Error"

    def mostrar_dashboard_exito(self, ip: str, servicio: str, credencial: str):
        tabla = Table(title="ACCESO OBTENIDO", show_header=True,
                      header_style="bold green")
        tabla.add_column("Objetivo",           style="cyan",
                         justify="center")
        tabla.add_column("Protocolo",          style="yellow",
                         justify="center")
        tabla.add_column("Credenciales (U:P)",
                         style="bold white", justify="center")
        tabla.add_row(ip, servicio.upper(), credencial)
        self.console.print("\n")
        self.console.print(Panel(tabla,
                                 title="[bold green]MISSION ACCOMPLISHED[/bold green]",
                                 border_style="bright_green", expand=False))
        self.console.print(
            f"[dim]LOG: Resultado exportado a ./data/evidence/audit_{ip}.txt[/dim]\n"
        )
        self.log.audit(f"Acceso obtenido en {ip} vía {servicio}", "Hydra")
        if self.gp:
            self.gp.registrar_hallazgo(
                "CRITICO",
                f"Credenciales obtenidas en {ip}:{servicio}",
                f"Credenciales válidas: {credencial}",
                "Cambiar credenciales inmediatamente."
            )

    def _limpiar(self):
        os.system("cls" if os.name == "nt" else "clear")

    # ── COMANDOS ─────────────────────────────────────────────────────

    def _cmd_status(self):
        proy = (self.gp.proyecto_activo.nombre
                if self.gp and self.gp.proyecto_activo else "Ninguno")
        self.console.print(Panel(
            f"[cyan]Sistema:[/cyan]  {self.nombre}\n"
            f"[cyan]Versión:[/cyan]  {self.version}\n"
            f"[cyan]Estado:[/cyan]   [green]Operacional[/green]\n"
            f"[cyan]Hora:[/cyan]     {time.strftime('%H:%M:%S')}\n"
            f"[cyan]Iface:[/cyan]    {self._iface()}\n"
            f"[cyan]Proyecto:[/cyan] [green]{proy}[/green]",
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
                timeout=3, verbose=False)[0]
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
                self.gp.registrar_evidencia("arp_scan",
                                            f"Scan ARP en {rango}: {len(hosts)} hosts",
                                            {"rango": rango, "hosts": hosts})
            self.log.info(
                f"Scan ARP en {rango}: {len(resultado)} hosts", "NetworkScan")
        except Exception:
            self.console.print(
                "[red][!] Error de permisos. Ejecuta como root/administrador.[/red]")

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
            self.gp.registrar_evidencia("portscan",
                                        f"PortScan en {objetivo}: {len(abiertos)} puertos",
                                        {"ip": objetivo, "puertos": abiertos})
        self.log.info(
            f"PortScan {objetivo}: {len(abiertos)} puertos abiertos", "PortScan")
        if abiertos and self.cve:
            if Prompt.ask("\n[?] ¿Cruzar con base de datos CVE?",
                          choices=["s", "n"], default="s") == "s":
                self.cve.analizar_resultado_scan(
                    [{"nombre": a["servicio"], "version": ""} for a in abiertos])

    def _cmd_sweep(self):
        if not self._modulo_ok("sweep"):
            return
        rango = Validador.pedir_rango(self.console)
        self.sweep.escanear_perimetro(rango)

    def _cmd_sniff(self):
        if not self._modulo_ok("sniffer"):
            return
        filtro = self.console.input(
            "\n[bold cyan]  [?] Filtro (Enter para ninguno)[/bold cyan]: ").strip()
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
            mac_ap = Validador.pedir(self.console, "MAC AP",
                                     Validador.es_mac, "MAC inválida.")
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

    def _cmd_rfscan(self):
        if not self._modulo_ok("rf"):
            return
        freq = Validador.pedir_frecuencia(self.console)
        if freq:
            self.rf.escanear_frecuencia(freq)

    # ── helper centralizado para subprocess con timeout ──────────────
    def _run(self, cmd: list, timeout: int = 30, **kwargs) -> subprocess.CompletedProcess:
        """
        Wrapper sobre subprocess.run con timeout garantizado.
        Lanza TimeoutExpired / CalledProcessError al llamador.
        """
        return subprocess.run(cmd, timeout=timeout, check=True, **kwargs)

    def _cmd_mobile(self):
        if not self._modulo_ok("mobile"):
            return
        self.console.print(
            "\n[1] Android Triage  [2] iOS Info  [3] Screenshot Remoto")
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
                          f"{path}/s.png"],    timeout=15)
                self.console.print(
                    f"[green][+] Captura guardada en {path}/s.png[/green]")
                self.log.success(
                    f"Screenshot guardado en {path}/s.png", "MobileSentinel")
            except subprocess.TimeoutExpired:
                self.console.print(
                    "[red][!] ADB tardó demasiado. Verifica la conexión.[/red]")
                self.log.error("ADB timeout en screenshot", "MobileSentinel")
            except subprocess.CalledProcessError as e:
                self.console.print(
                    f"[red][!] Error ADB (código {e.returncode}): {e}[/red]")
                self.log.error(f"Screenshot ADB: {e}", "MobileSentinel")
            except Exception as e:
                self.console.print(f"[red][!] Error inesperado ADB: {e}[/red]")
                self.log.error(f"Screenshot ADB: {e}", "MobileSentinel")

    def _cmd_mobile_deep(self):
        path = "./data/evidence/mobile/Deep_Extraction/"
        os.makedirs(path, exist_ok=True)
        if self._db_extractor_cls is None:
            self.console.print(
                "[red][!] DatabaseExtractor no disponible.[/red]")
            return
        extractor = self._db_extractor_cls()
        self.console.print(
            "\n[1] Extraer WhatsApp Full  [2] Extraer Chrome History")
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        if opt == "1":
            self.animar_barra("EXTRAYENDO DB Y LLAVE...")
            extractor.extraer_whatsapp(path)
            extractor.extraer_whatsapp_key(path)
            self.log.audit("Extracción WhatsApp completada", "MobileDeep")
        elif opt == "2":
            self.animar_barra("EXTRAYENDO HISTORIAL CHROME...")
            self.log.audit("Extracción Chrome completada", "MobileDeep")

    def _cmd_view(self):
        if not self._modulo_ok("reader"):
            return
        ruta_base = "./data/evidence/mobile/Deep_Extraction/"
        opcion = self.console.input(
            "[bold cyan] [1] Leer WhatsApp  [2] Leer Chrome: [/bold cyan]"
        ).strip()
        if opcion == "1":
            self.reader.leer_whatsapp_mensajes(
                os.path.join(ruta_base, "whatsapp_messages.db"))
        elif opcion == "2":
            self.reader.leer_historial_chrome(
                os.path.join(ruta_base, "chrome_history.db"))

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

    # ── PHISHING CORREGIDO ── detecta OS automáticamente ─────────────
    def _cmd_phishing(self):
        self._limpiar()
        self.console.print(
            "[bold red][!][/bold red] Iniciando Suite de Phishing...")
        ruta_z = "./tools/zphisher/zphisher.sh"

        # Verificar que zphisher existe antes de intentar ejecutarlo
        if not os.path.exists(ruta_z):
            self.console.print(
                "[red][!] zphisher no encontrado en ./tools/zphisher/[/red]\n"
                "[dim]Instálalo con:[/dim]\n"
                "[cyan]  git clone https://github.com/htr-tech/zphisher.git "
                "tools/zphisher[/cyan]"
            )
            return

        try:
            if sys.platform == "win32":
                # Windows — usa Git Bash
                bash_path = r"C:\Program Files\Git\bin\bash.exe"
                if not os.path.exists(bash_path):
                    self.console.print(
                        "[red][!] Git Bash no encontrado.[/red]\n"
                        "[dim]Instala Git desde https://git-scm.com[/dim]"
                    )
                    return
                subprocess.run([bash_path, ruta_z], check=True)
            else:
                # Linux / Termux / uConsole — bash nativo
                subprocess.run(["bash", ruta_z], check=True)

        except Exception as e:
            self.console.print(f"[red]Error al lanzar: {e}[/red]")
            self.log.error(f"Phishing launch: {e}", "PhishingModule")

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

    # ── NUEVOS COMANDOS PROFESIONALES ────────────────────────────────

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

    # ── DESPACHADOR ───────────────────────────────────────────────────

    def _despachar(self, entrada: str) -> bool:
        partes = entrada.strip().lower().split()
        if not partes:
            return True
        cmd = partes[0]
        args = partes[1:]

        # Subcomandos con argumentos
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
        # locate acepta "-p" como argumento → despacho limpio sin comparar entrada raw
        if cmd == "locate":
            self._cmd_locate_p() if "-p" in args else self._cmd_locate()
            return True
        # Tabla principal
        tabla = {
            "help": lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "?": lambda: mostrar_ayuda(self.console, self.version, COMANDOS_HELP),
            "status":      self._cmd_status,
            "hora": lambda: self.console.print(f"[cyan]Hora:[/cyan] {time.strftime('%H:%M:%S')}"),
            "clear": lambda: mostrar_banner(self.console, self.nombre, self.version, self._iface()),
            "cls": lambda: mostrar_banner(self.console, self.nombre, self.version, self._iface()),
            "logs":        self.log.mostrar_historial,
            "files":       self._cmd_files,
            "scan":        self._cmd_scan,
            "netscan":     self._cmd_netscan,
            "advscan":     self._cmd_advscan,
            "portscan":    self._cmd_portscan,
            "sweep":       self._cmd_sweep,
            "sniff":       self._cmd_sniff,
            "radar":       self._cmd_radar,
            "audit":       self._cmd_audit,
            "vulnscan":    self._cmd_vulnscan,
            "sqlcheck":    self._cmd_sqlcheck,
            "wifi":        self._cmd_wifi,
            "eviltwin":    self._cmd_eviltwin,
            "rfscan":      self._cmd_rfscan,
            "btjumper": lambda: self.bt.iniciar_jumper() if self._modulo_ok("bt") else None,
            "mobile":      self._cmd_mobile,
            "mobile-deep": self._cmd_mobile_deep,
            "view":        self._cmd_view,
            "geofoto":     self._cmd_geofoto,
            "phishing":    self._cmd_phishing,
            "ducky":       self._cmd_ducky,
            "stealth":     self._cmd_stealth,
            "panic":       self._cmd_panic,
            "osint":       self._cmd_osint,
            "cve":         self._cmd_cve,
        }

        if cmd in tabla:
            tabla[cmd]()
            return True

        if self.plugins and self.plugins.tiene_comando(cmd):
            self.plugins.ejecutar_comando(cmd, args)
            return True

        return False

    # ── BUCLE PRINCIPAL ───────────────────────────────────────────────

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


# ============================================================
# PUNTO DE ENTRADA
# ============================================================

if __name__ == "__main__":
    for d in ["data/logs", "data/evidence", "plugins"]:
        os.makedirs(d, exist_ok=True)
    sentinel = ApexSentinel()
    sentinel.ejecutar()
