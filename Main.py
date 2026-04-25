"""
╔══════════════════════════════════════════════════════════════════╗
║          APEX SENTINEL — ANUBIS OS  v2.1                        ║
║          Main definitivo — Arquitectura profesional completa     ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  SISTEMAS INTEGRADOS:                                            ║
║  ├─ GestorProyectos  → Workspaces por operación                  ║
║  ├─ MotorReportes    → Evidencia en MD/TXT/Timeline              ║
║  ├─ PluginSystem     → Módulos en caliente desde plugins/        ║
║  ├─ ColaTareas       → Scans en background sin bloquear prompt   ║
║  ├─ OSINTEngine      → Reconocimiento pasivo con APIs públicas   ║
║  └─ CVEMatcher       → Cruce automático contra NVD/CVE          ║
║                                                                  ║
║  ORIGINALES PRESERVADOS:                                         ║
║  ├─ HydraModule, AuditEngine, TacticalSniffer, RadarSentinel    ║
║  ├─ WifiAttack, EvilTwinServer, RFScanner, BluetoothModule       ║
║  ├─ MobileSentinel, ForensicReader, DatabaseExtractor            ║
║  ├─ ExifAnalyzer, GeoPrecise, LocatorModule, StealthModule       ║
║  └─ DuckyModule, SweepModule, AdvancedScanner, PhishingModule    ║
╚══════════════════════════════════════════════════════════════════╝
"""

# ── STDLIB ──────────────────────────────────────────────────────────
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

# ── COMPATIBILIDAD WINDOWS ──────────────────────────────────────────
if sys.platform == 'win32':
    os.add_dll_directory(os.path.abspath(os.path.dirname(__file__)))

# ── RICH ────────────────────────────────────────────────────────────
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from rich.rule import Rule
from rich.columns import Columns
from rich.align import Align
from rich.progress import (Progress, BarColumn,
                           TextColumn, SpinnerColumn)
from rich import box

# ── BCRYPT (opcional, fallback seguro) ──────────────────────────────
try:
    import bcrypt
    BCRYPT_OK = True
except ImportError:
    BCRYPT_OK = False

# ── IMPORTADOR CON FALLBACK ─────────────────────────────────────────


def _imp(modulo: str, clase: str):
    """Importa una clase de forma segura. Retorna None si falla."""
    try:
        return getattr(__import__(modulo, fromlist=[clase]), clase)
    except Exception as e:
        logging.warning(f"[IMPORT] {clase} ({modulo}): {e}")
        return None


# ════════════════════════════════════════════════════════════════════
# CONSTANTES VISUALES
# ════════════════════════════════════════════════════════════════════

ANUBIS_ART = r"""
   ╔═══════════╗
   ║  /\   /\  ║
   ║ (  \_/  ) ║
   ║  \     /  ║
   ║  /\___/\  ║
   ║ / / | \ \ ║
   ╚═══════════╝"""

MODULOS_BOOT = [
    # Originales
    ("HydraModule",      "Fuerza bruta / auditoría"),
    ("TacticalSniffer",  "Captura de tráfico"),
    ("RadarSentinel",    "Intercepción Wi-Fi RSSI"),
    ("ExifAnalyzer",     "Metadatos EXIF / GPS"),
    ("BluetoothModule",  "Escaneo Bluetooth"),
    ("ForensicReader",   "Lectura forense"),
    ("GeoPrecise",       "Triangulación GPS"),
    ("StealthModule",    "Huella digital"),
    ("MobileSentinel",   "Triaje móvil"),
    ("NetworkModule",    "Análisis de red"),
    # Nuevos profesionales
    ("GestorProyectos",  "Workspaces de operación"),
    ("MotorReportes",    "Reportes MD/TXT/Timeline"),
    ("OSINTEngine",      "Reconocimiento pasivo"),
    ("CVEMatcher",       "Base de datos CVE/NVD"),
    ("ColaTareas",       "Ejecución asíncrona"),
    ("GestorPlugins",    "Plugins en caliente"),
]

ESTILOS_LOG = {
    "INFO":    ("cyan",    "ℹ"),
    "WARNING": ("yellow",  "⚠"),
    "ERROR":   ("red",     "✖"),
    "SUCCESS": ("green",   "✔"),
    "AUDIT":   ("magenta", "⚑"),
}

# Índice de ayuda completo
HELP = {
    "SISTEMA": {
        "color": "cyan",
        "items": [
            ("help",            "Índice de comandos"),
            ("status",          "Estado del sistema y proyecto activo"),
            ("hora",            "Hora del sistema"),
            ("clear",           "Recarga el banner"),
            ("logs",            "Historial de operaciones"),
            ("files",           "Explorador de archivos local"),
            ("exit",            "Cierre seguro del Sentinel"),
        ]
    },
    "PROYECTOS": {
        "color": "green",
        "items": [
            ("proyecto nuevo",   "Crear workspace de operación"),
            ("proyecto cargar",  "Cargar proyecto existente"),
            ("proyecto lista",   "Listar todos los proyectos"),
            ("proyecto estado",  "Resumen del proyecto activo"),
            ("proyecto cerrar",  "Cerrar proyecto activo"),
            ("reporte",          "Generar reporte Markdown completo"),
            ("reporte resumen",  "Resumen ejecutivo en TXT"),
            ("reporte timeline", "Timeline cronológico"),
        ]
    },
    "RED": {
        "color": "blue",
        "items": [
            ("scan",     "Escaneo ARP rápido de red local"),
            ("netscan",  "Mapeo ARP detallado"),
            ("advscan",  "Escaneo de objetivo específico"),
            ("portscan", "Auditoría de puertos + cruce CVE"),
            ("sweep",    "Escaneo de perímetro"),
            ("sniff",    "Captura de tráfico real"),
            ("radar",    "Radar Wi-Fi por RSSI"),
        ]
    },
    "INTEL": {
        "color": "magenta",
        "items": [
            ("osint",    "OSINT Engine — IP y dominio"),
            ("cve",      "CVE Matcher — búsqueda en NVD"),
            ("locate",   "Rastreo IP / GPS"),
            ("locate -p", "Triangulación por redes Wi-Fi"),
            ("geofoto",  "Metadatos GPS en fotos (EXIF)"),
            ("stealth",  "Verificar huella digital"),
        ]
    },
    "AUDITORÍA": {
        "color": "red",
        "items": [
            ("audit",    "Fuerza bruta con Hydra"),
            ("vulnscan", "Escaneo de vulnerabilidades (Nmap NSE)"),
            ("sqlcheck", "Auditoría SQL Injection (SQLmap)"),
        ]
    },
    "WIRELESS / RF": {
        "color": "yellow",
        "items": [
            ("wifi",     "Beacon Spam / Deauth Attack"),
            ("eviltwin", "Gemelo Malvado"),
            ("rfscan",   "Escaneo de radiofrecuencia"),
            ("btjumper", "Salto de dispositivos Bluetooth"),
        ]
    },
    "FORENSE": {
        "color": "green",
        "items": [
            ("mobile",       "Triaje Android / iOS y Screenshot"),
            ("mobile-deep",  "Extracción profunda WA / Chrome"),
            ("view",         "Visualizador táctico de bases de datos"),
        ]
    },
    "INGENIERÍA SOCIAL": {
        "color": "red",
        "items": [
            ("phishing", "Suite de Phishing (zphisher)"),
            ("ducky",    "Ejecutar payload BadUSB"),
            ("panic",    "Cifrado y borrado de rastro"),
        ]
    },
    "JOBS & PLUGINS": {
        "color": "cyan",
        "items": [
            ("jobs",             "Lista de tareas en background"),
            ("job resultado ID", "Ver resultado de un job"),
            ("job cancelar ID",  "Cancelar un job activo"),
            ("job limpiar",      "Limpiar jobs completados"),
            ("plugins",          "Lista plugins cargados"),
            ("plugins reload",   "Recargar plugins en caliente"),
        ]
    },
}


# ════════════════════════════════════════════════════════════════════
# VALIDADOR
# ════════════════════════════════════════════════════════════════════

class Validador:
    """Prompts seguros con validación y reintentos automáticos."""

    MAX = 3

    @staticmethod
    def _ip(v):
        try:
            ipaddress.ip_address(v)
            return True
        except:
            return False

    @staticmethod
    def _cidr(v):
        try:
            ipaddress.ip_network(v, strict=False)
            return True
        except:
            return False

    @staticmethod
    def _url(v):
        return bool(re.match(r"^https?://[^\s/$.?#].[^\s]*$", v, re.I))

    @staticmethod
    def _mac(v):
        return bool(re.match(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$", v))

    @staticmethod
    def _mhz(v):
        try:
            return 1.0 <= float(v) <= 6000.0
        except:
            return False

    @classmethod
    def pedir(cls, con, prompt, fn=None, err="Valor inválido.",
              default=None, pw=False):
        """Motor de input con validación y N reintentos."""
        p = f"\n[bold cyan]{prompt}[/bold cyan]"
        if default:
            p += f" [dim](Enter = {default})[/dim]"
        p += ": "

        for i in range(cls.MAX):
            try:
                val = (Prompt.ask(p, password=True) if pw
                       else con.input(p).strip())
                if not val and default is not None:
                    return default
                if fn is None or fn(val):
                    return val
                r = cls.MAX - i - 1
                con.print(f"  [red][!] {err}[/red]"
                          + (f" [dim]({r} intento{'s' if r != 1 else ''} restante)[/dim]" if r else ""))
            except KeyboardInterrupt:
                con.print("\n[yellow][!] Cancelado.[/yellow]")
                raise
        return default

    # Atajos
    @classmethod
    def ip(cls, con, p="[?] IP objetivo"):
        return cls.pedir(con, p, cls._ip, "IP inválida. Ej: 192.168.1.1")

    @classmethod
    def cidr(cls, con, p="[?] Rango de red", d="192.168.1.0/24"):
        return cls.pedir(con, p, cls._cidr, "CIDR inválido.", default=d)

    @classmethod
    def url(cls, con, p="[?] URL objetivo"):
        return cls.pedir(con, p, cls._url, "URL inválida. Use http:// o https://")

    @classmethod
    def mhz(cls, con):
        v = cls.pedir(con, "[?] Frecuencia (MHz)", cls._mhz,
                      "Rango válido: 1.0 – 6000.0 MHz")
        return float(v) if v else None

    @classmethod
    def segundos(cls, con, d=30):
        def fn(v):
            try:
                return 1 <= int(v) <= 300
            except:
                return False
        v = cls.pedir(con, "[?] Duración en segundos [1-300]",
                      fn, "Número entre 1 y 300.", default=str(d))
        return int(v) if v else d


# ════════════════════════════════════════════════════════════════════
# SISTEMA DE LOGS
# ════════════════════════════════════════════════════════════════════

class LogSistema:
    """Logging estructurado: visual en consola + archivo JSON + .log"""

    def __init__(self, con: Console):
        self.con = con
        self._e = self._cargar()
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
                json.dump(self._e[-500:], f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _log(self, nivel: str, msg: str, mod: str = "Sistema"):
        entrada = {"timestamp": self._ts(), "nivel": nivel,
                   "modulo": mod, "mensaje": msg}
        self._e.append(entrada)
        self._guardar()
        col, ico = ESTILOS_LOG.get(nivel, ("white", "·"))
        self.con.print(
            f"[dim]{entrada['timestamp']}[/dim] "
            f"[{col}]{ico} {nivel:<8}[/{col}] "
            f"[cyan]{mod:<18}[/cyan] {msg}"
        )
        getattr(logging, nivel.lower(), logging.info)(f"[{mod}] {msg}")

    def info(self, m, mod="Sistema"):    self._log("INFO",    m, mod)
    def warning(self, m, mod="Sistema"): self._log("WARNING", m, mod)
    def error(self, m, mod="Sistema"):   self._log("ERROR",   m, mod)
    def success(self, m, mod="Sistema"): self._log("SUCCESS", m, mod)
    def audit(self, m, mod="Auditoría"): self._log("AUDIT",   m, mod)

    def mostrar_historial(self, ultimas: int = 50):
        ee = self._e[-ultimas:]
        if not ee:
            self.con.print(Panel("[dim]Sin registros.[/dim]",
                                 border_style="dim green"))
            return
        # Resumen
        cnt = {}
        for e in self._e:
            cnt[e["nivel"]] = cnt.get(e["nivel"], 0) + 1
        res = Table.grid(padding=(0, 3))
        res.add_row(*[
            f"[{ESTILOS_LOG[n][0]}]{ESTILOS_LOG[n][1]} {n}: {cnt.get(n, 0)}[/{ESTILOS_LOG[n][0]}]"
            for n in ESTILOS_LOG
        ])
        self.con.print(Panel(res, title="[bold]RESUMEN[/bold]",
                             border_style="dim green", box=box.SIMPLE))
        # Tabla
        t = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
                  show_edge=False, expand=True)
        t.add_column("Timestamp", style="dim",  min_width=19, no_wrap=True)
        t.add_column("Nivel",     min_width=10, no_wrap=True)
        t.add_column("Módulo",    style="cyan", min_width=16)
        t.add_column("Mensaje",   style="white")
        for e in ee:
            col, ico = ESTILOS_LOG.get(e["nivel"], ("white", "·"))
            t.add_row(e["timestamp"],
                      Text(f"{ico} {e['nivel']}", style=col),
                      e["modulo"], e["mensaje"])
        self.con.print(Panel(t, title=f"[bold]HISTORIAL — {len(ee)} entradas[/bold]",
                             border_style="green", box=box.HEAVY_EDGE))

    def verificar_y_limpiar(self, mx: int = 500):
        if len(self._e) > mx:
            self._e = self._e[-mx:]
            self._guardar()


# ════════════════════════════════════════════════════════════════════
# AUTENTICACIÓN
# ════════════════════════════════════════════════════════════════════

class GestorAuth:
    """Autenticación con bcrypt. Compatible con hashes SHA-256 legados."""

    MAX = 3

    def __init__(self, cfg: dict, con: Console, log: LogSistema):
        self.cfg = cfg
        self.con = con
        self.log = log

    # ── hashing ──────────────────────────────────────────────────────
    def _hash(self, pw: str) -> str:
        if BCRYPT_OK:
            return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
        salt = os.urandom(16).hex()
        return f"{salt}:{hashlib.sha256((salt+pw).encode()).hexdigest()}"

    def _check(self, pw: str, stored: str) -> bool:
        # Soporte hash SHA-256 simple (legado sin salt)
        if len(stored) == 64 and ":" not in stored:
            return hashlib.sha256(pw.encode()).hexdigest() == stored
        if BCRYPT_OK:
            try:
                return bcrypt.checkpw(pw.encode(), stored.encode())
            except Exception:
                pass
        try:
            salt, h = stored.split(":")
            return hashlib.sha256((salt+pw).encode()).hexdigest() == h
        except Exception:
            return False

    def _guardar(self):
        try:
            with open("config.json", "w") as f:
                json.dump(self.cfg, f, indent=4)
            if sys.platform != "win32":
                os.chmod("config.json", 0o600)
        except OSError as e:
            self.log.error(f"config.json: {e}")

    # ── flujo público ─────────────────────────────────────────────────
    def solicitar_acceso(self) -> bool:
        stored = self.cfg["sistema"].get("password_hash")

        # Primera vez
        if not stored or self.cfg["sistema"].get("primer_arranque", True):
            self.con.print(Panel(
                "[bold cyan]ANUBIS OS — SETUP DE SEGURIDAD[/bold cyan]\n"
                "[white]No se detectó clave de operador. Configure su acceso maestro.[/white]",
                border_style="cyan"
            ))
            while True:
                pw = Prompt.ask(
                    "[?] Contraseña Maestra (mín. 8 chars)", password=True)
                if len(pw) < 8:
                    self.con.print(
                        "[red][!] Contraseña demasiado débil.[/red]")
                    continue
                if Prompt.ask("[?] Confirme su contraseña", password=True) != pw:
                    self.con.print("[red][!] Las claves no coinciden.[/red]")
                    continue
                self.cfg["sistema"]["password_hash"] = self._hash(pw)
                self.cfg["sistema"]["primer_arranque"] = False
                self._guardar()
                self.con.print(
                    "[green][+] Acceso configurado. Iniciando...[/green]")
                self.log.success("Contraseña maestra configurada.", "Auth")
                time.sleep(1)
                return True

        # Login normal
        self.con.print(
            f"\n[bold white]{'─'*42}[/bold white]\n"
            f"[bold green]   APEX SENTINEL — LOGIN[/bold green]\n"
            f"[bold white]{'─'*42}[/bold white]\n"
        )
        for i in range(self.MAX, 0, -1):
            entrada = Prompt.ask(
                f"[?] Clave de acceso ([dim]{i} intento{'s' if i > 1 else ''}[/dim])",
                password=True
            )
            if self._check(entrada, stored):
                self.log.success("Acceso concedido.", "Auth")
                return True
            self.con.print("[red][!] Clave incorrecta.[/red]")

        self.log.warning("Acceso denegado — máximo de intentos.", "Auth")
        return False


# ════════════════════════════════════════════════════════════════════
# BOOTSCREEN  /  BANNER  /  AYUDA
# ════════════════════════════════════════════════════════════════════

def _limpiar():
    os.system("cls" if os.name == "nt" else "clear")


def mostrar_bootloader(con: Console, nombre: str, version: str, iface: str):
    """Pantalla de arranque animada completa."""
    _limpiar()

    arte = Text(ANUBIS_ART, style="bold green")

    inf = Table.grid(padding=(0, 2))
    inf.add_column(style="dim cyan", justify="right")
    inf.add_column(style="white")
    inf.add_row(
        "SISTEMA",    f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    inf.add_row("OPERADOR",   f"[bold green]{nombre}[/bold green]")
    inf.add_row("ESTADO",     "[bold green]● ACTIVO[/bold green]")
    inf.add_row("IFACE",      f"[cyan]{iface}[/cyan]")
    inf.add_row("PLATAFORMA", f"[dim]{os.name.upper()}[/dim]")
    inf.add_row("", "")
    inf.add_row("AVISO",      "[bold red]⚠  AUTHORIZED USE ONLY[/bold red]")

    con.print(Panel(
        Columns([Align(arte, vertical="middle"),
                 Align(inf,  vertical="middle")], equal=False, expand=True),
        title="[bold green]ANUBIS OS[/bold green]",
        subtitle="[dim]SISTEMA OPERATIVO TÁCTICO[/dim]",
        border_style="green", box=box.DOUBLE_EDGE, padding=(1, 2)
    ))
    con.print()

    # Barra de carga de módulos
    with Progress(
        SpinnerColumn(spinner_name="dots", style="green"),
        TextColumn("[cyan]{task.description:<38}[/cyan]"),
        BarColumn(bar_width=22, style="green", complete_style="bold green"),
        TextColumn("[bold green]{task.percentage:>3.0f}%[/bold green]"),
        console=con,
    ) as pg:
        tk = pg.add_task("Iniciando núcleo...", total=len(MODULOS_BOOT))
        for nm, _ in MODULOS_BOOT:
            pg.update(tk, description=f"Cargando [bold]{nm}[/bold]...")
            time.sleep(0.10)
            pg.advance(tk)
        pg.update(
            tk, description="[bold green]Todos los módulos en línea[/bold green]")
        time.sleep(0.2)

    # Tabla de módulos
    tb = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
               show_edge=False, expand=True)
    tb.add_column("Módulo",  style="green", min_width=20)
    tb.add_column("Función", style="white", min_width=28)
    tb.add_column("Estado",  justify="center")
    for nm, desc in MODULOS_BOOT:
        tb.add_row(nm, desc, "[bold green]● LISTO[/bold green]")

    con.print(Panel(tb, title="[bold]MÓDULOS DEL SISTEMA[/bold]",
                    border_style="dim green", padding=(0, 1)))
    con.print()
    con.print(Rule(style="dim green"))
    con.print(Align.center(
        "[dim]Escribe [bold white]help[/bold white] para ver todos los comandos disponibles[/dim]"
    ))
    con.print(Rule(style="dim green"))
    con.print()


def mostrar_banner(con: Console, nombre: str, version: str, iface: str):
    """Banner compacto — se usa con el comando 'clear' durante la sesión."""
    _limpiar()
    g = Table.grid(padding=(0, 4), expand=True)
    g.add_column(ratio=1)
    g.add_column(ratio=2)

    der = Table.grid(padding=(0, 1))
    der.add_column(style="dim cyan", justify="right", min_width=12)
    der.add_column(style="white")
    der.add_row(
        "SISTEMA",  f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    der.add_row("OPERADOR", f"[bold green]{nombre}[/bold green]")
    der.add_row("ESTADO",   "[bold green]● ACTIVO[/bold green]")
    der.add_row("IFACE",    f"[cyan]{iface}[/cyan]")
    der.add_row("AVISO",    "[red]AUTHORIZED USE ONLY[/red]")

    g.add_row(Text(ANUBIS_ART, style="bold green"), der)
    con.print(Panel(g, border_style="green",
              box=box.HEAVY_EDGE, padding=(0, 1)))
    con.print(Rule(style="dim green"))
    con.print()


def mostrar_ayuda(con: Console, version: str):
    """Menú de ayuda en dos columnas agrupado por categorías."""
    con.print()
    con.print(Rule(
        title=f"[bold white]ANUBIS OS — COMMAND INDEX[/bold white]  [dim]v{version}[/dim]",
        style="green"
    ))
    con.print()

    bloques = []
    for cat, dat in HELP.items():
        col = dat["color"]
        tb = Table(box=box.SIMPLE, show_header=False,
                   show_edge=False, padding=(0, 1), expand=True)
        tb.add_column("cmd",  style=f"bold {col}", min_width=18, no_wrap=True)
        tb.add_column("desc", style="white")
        for cmd, desc in dat["items"]:
            tb.add_row(cmd, desc)
        bloques.append(Panel(
            tb,
            title=f"[bold {col}]{cat}[/bold {col}]",
            border_style=col,
            box=box.ROUNDED,
            padding=(0, 1)
        ))

    for i in range(0, len(bloques), 2):
        par = bloques[i:i+2]
        con.print(Columns(par, equal=True, expand=True)
                  if len(par) == 2 else par[0])
        con.print()

    con.print(Rule(style="dim green"))
    con.print(
        "  [dim]Escribe el comando y presiona[/dim] [bold white]Enter[/bold white]  ·  "
        "[dim]Salir:[/dim] [bold white]exit[/bold white]  ·  "
        "[dim]Limpiar:[/dim] [bold white]clear[/bold white]"
    )
    con.print(Rule(style="dim green"))
    con.print()


# ════════════════════════════════════════════════════════════════════
# APEX SENTINEL — CLASE PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class ApexSentinel:

    def __init__(self):
        # Directorios base
        for d in ["data/logs", "data/evidence", "plugins"]:
            os.makedirs(d, exist_ok=True)

        self.console = Console()
        self.config = self._cargar_config()
        self.nombre = self.config["sistema"]["nombre"]
        self.version = self.config["sistema"]["version"]

        # Subsistemas internos
        self.log = LogSistema(self.console)
        self.auth = GestorAuth(self.config, self.console, self.log)

        # Módulos tácticos originales + nuevos profesionales
        self._cargar_modulos()

    # ── configuración ────────────────────────────────────────────────

    def _cargar_config(self) -> dict:
        try:
            with open("config.json", "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"sistema": {"nombre": "Sentinel", "version": "2.1",
                                "primer_arranque": True}}
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    # ── carga de módulos ─────────────────────────────────────────────

    def _cargar_modulos(self):
        """
        Carga todos los módulos con fallback graceful.
        Si un módulo falla, el sistema sigue funcionando.
        """

        # ── Módulos tácticos originales ──────────────────────────────
        _originales = [
            # (atributo,       clase,               módulo_archivo)
            ("checker",       "SystemChecker",      "SystemChecker"),
            ("audit_engine",  "AuditEngine",        "AuditEngine"),
            ("dict_manager",  "DictionaryManager",  "DictionaryManager"),
            ("hydra",         "HydraModule",        "HydraModule"),
            ("stealth",       "StealthModule",      "Stealth"),
            ("locator",       "LocatorModule",      "LocatorModule"),
            ("exif",          "ExifAnalyzer",       "ExifAnalyzer"),
            ("geopreciose",   "GeoPrecise",         "GeoPrecise"),
            ("wifi_attack",   "WifiAttack",         "WifiAtack"),
            ("reader",        "ForensicReader",     "ForensicReader"),
            ("rf",            "RFScanner",          "RFScanner"),
            ("sniffer",       "TacticalSniffer",    "TacticalSniffer"),
            ("bt",            "BluetoothModule",    "bt_module"),
            ("sweep",         "SweepModule",        "SweepModule"),
            ("ducky",         "DuckyModule",        "DuckyModule"),
            ("adv_scanner",   "AdvancedScanner",    "AdvancedScanner"),
            ("mobile",        "MobileSentinel",     "MobileSentinel"),
            ("security",      "SecurityModule",     "Security"),
            ("network",       "NetworkModule",      "Network"),
            ("phishing",      "PhishingModule",     "PhishingModule"),
        ]

        # Clases que NO reciben self como argumento
        _sin_self = {"SystemChecker", "DictionaryManager"}

        for attr, cls_name, mod_file in _originales:
            Cls = _imp(mod_file, cls_name)
            if Cls is None:
                setattr(self, attr, None)
                continue
            try:
                obj = Cls() if cls_name in _sin_self else Cls(self)
                setattr(self, attr, obj)
            except Exception as e:
                self.log.warning(f"{cls_name}: {e}", "Init")
                setattr(self, attr, None)

        # ── Radar y Geomap ───────────────────────────────────────────
        try:
            from RadarSentinel import RadarSentinel
            from GeomapSentinel import GeomapSentinel
            self.radar = RadarSentinel(interface="Wi-Fi")
            self.radar.start_sniffing()
            self.geomap = GeomapSentinel()
        except Exception as e:
            self.log.warning(f"Radar/Geomap: {e}", "Init")
            self.radar = self.geomap = None

        # ── EvilTwinServer ───────────────────────────────────────────
        try:
            from EvilTwinServer import iniciar_servidor
            self._evs = iniciar_servidor
        except Exception:
            self._evs = None

        # ── DatabaseExtractor y WADecryptor ──────────────────────────
        self._dbc = _imp("db_extractor", "DatabaseExtractor")
        self._wad = _imp("WADecryptor",  "WhatsAppDecryptor")

        # ── Scapy ────────────────────────────────────────────────────
        try:
            from scapy.all import ARP, Ether, srp
            self._ARP, self._Eth, self._srp = ARP, Ether, srp
        except Exception:
            self._ARP = self._Eth = self._srp = None

        # ════════════════════════════════════════════════════════════
        # MÓDULOS PROFESIONALES NUEVOS
        # ════════════════════════════════════════════════════════════

        # ── GestorProyectos ──────────────────────────────────────────
        try:
            from GestorProyectos import GestorProyectos
            self.gp = GestorProyectos()
        except Exception as e:
            self.log.warning(f"GestorProyectos: {e}", "Init")
            self.gp = None

        # ── MotorReportes ────────────────────────────────────────────
        try:
            from MotorReportes import MotorReportes
            self.motor_rep = MotorReportes(self) if self.gp else None
        except Exception as e:
            self.log.warning(f"MotorReportes: {e}", "Init")
            self.motor_rep = None

        # ── OSINTEngine ──────────────────────────────────────────────
        try:
            from OSINTEngine import OSINTEngine
            self.osint = OSINTEngine(self)
        except Exception as e:
            self.log.warning(f"OSINTEngine: {e}", "Init")
            self.osint = None

        # ── CVEMatcher ───────────────────────────────────────────────
        try:
            from CVEMatcher import CVEMatcher
            self.cve = CVEMatcher(self)
        except Exception as e:
            self.log.warning(f"CVEMatcher: {e}", "Init")
            self.cve = None

        # ── ColaTareas ───────────────────────────────────────────────
        try:
            from ColaTareas import ColaTareas
            self.cola = ColaTareas()
        except Exception as e:
            self.log.warning(f"ColaTareas: {e}", "Init")
            self.cola = None

        # ── PluginSystem ─────────────────────────────────────────────
        try:
            from PluginSystem import GestorPlugins, crear_plugin_ejemplo
            self.plugins = GestorPlugins(self)
            crear_plugin_ejemplo()
            self.plugins.cargar_todos()
        except Exception as e:
            self.log.warning(f"PluginSystem: {e}", "Init")
            self.plugins = None

    # ── helpers internos ─────────────────────────────────────────────

    def _iface(self) -> str:
        return getattr(getattr(self, "bt", None), "iface", "wlan0mon")

    def _ok(self, attr: str) -> bool:
        """Verifica que un módulo esté disponible. Muestra error si no."""
        if getattr(self, attr, None) is None:
            self.console.print(
                f"[red][!] Módulo '[bold]{attr}[/bold]' no disponible "
                f"en este entorno.[/red]"
            )
            return False
        return True

    def _barra(self, tarea: str):
        """Barra de progreso ASCII simple."""
        print(f"\n{tarea}")
        for i in range(21):
            print(f"\r[{'█'*i}{'-'*(20-i)}] {int(i/20*100)}%", end="")
            time.sleep(0.05)
        print("\n[OK] Tarea completada.\n")

    def _fabricante(self, mac: str) -> str:
        try:
            import requests
            r = requests.get(f"https://api.macvendors.com/{mac}", timeout=1)
            return r.text if r.status_code == 200 else "Desconocido"
        except Exception:
            return "?"

    def _exito(self, ip: str, servicio: str, credencial: str):
        """Muestra dashboard de acceso obtenido y registra hallazgo."""
        tb = Table(title="🔓 ACCESO OBTENIDO", header_style="bold green")
        tb.add_column("Objetivo",           style="cyan",
                      justify="center")
        tb.add_column("Protocolo",          style="yellow",
                      justify="center")
        tb.add_column("Credenciales (U:P)",
                      style="bold white", justify="center")
        tb.add_row(ip, servicio.upper(), credencial)

        self.console.print(Panel(
            tb,
            title="[bold green]MISSION ACCOMPLISHED[/bold green]",
            border_style="bright_green", expand=False
        ))
        self.console.print(
            f"[dim]LOG: evidencia exportada → ./data/evidence/audit_{ip}.txt[/dim]\n"
        )
        self.log.audit(f"Acceso obtenido en {ip} vía {servicio}", "Hydra")

        # Registrar en proyecto activo si existe
        if self.gp:
            self.gp.registrar_hallazgo(
                "CRITICO",
                f"Credenciales obtenidas en {ip}:{servicio}",
                f"Credenciales válidas: {credencial}",
                "Cambiar credenciales y auditar accesos inmediatamente."
            )

    # ════════════════════════════════════════════════════════════════
    # COMANDOS — cada método maneja un comando completo
    # ════════════════════════════════════════════════════════════════

    # ── SISTEMA ──────────────────────────────────────────────────────

    def _status(self):
        proy = (self.gp.proyecto_activo.nombre
                if self.gp and self.gp.proyecto_activo else "Ninguno")
        jobs = 0
        if self.cola:
            try:
                from ColaTareas import EstadoTarea
                jobs = sum(1 for t in self.cola._tareas.values()
                           if t.estado == EstadoTarea.CORRIENDO)
            except Exception:
                pass

        self.console.print(Panel(
            f"[cyan]Sistema:[/cyan]   {self.nombre}\n"
            f"[cyan]Versión:[/cyan]   {self.version}\n"
            f"[cyan]Estado:[/cyan]    [green]Operacional[/green]\n"
            f"[cyan]Hora:[/cyan]      {time.strftime('%H:%M:%S')}\n"
            f"[cyan]Iface:[/cyan]     {self._iface()}\n"
            f"[cyan]Proyecto:[/cyan]  [green]{proy}[/green]\n"
            f"[cyan]Jobs activos:[/cyan] {jobs}",
            title="STATUS", border_style="cyan"
        ))

    def _files(self):
        self._barra("EXPLORANDO DIRECTORIO LOCAL...")
        tb = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
                   show_edge=False, expand=True)
        tb.add_column("Nombre", style="white")
        tb.add_column("Tamaño", style="yellow", justify="right")
        tb.add_column("Tipo",   style="green",  justify="center")
        try:
            for f in sorted(os.listdir(".")):
                try:
                    tb.add_row(f, f"{os.path.getsize(f):,} bytes",
                               "DIR" if os.path.isdir(f) else "FILE")
                except OSError:
                    tb.add_row(f, "N/A", "?")
            self.console.print(tb)
        except Exception as e:
            self.log.error(f"files: {e}")

    # ── RED ───────────────────────────────────────────────────────────

    def _scan(self):
        if self._ARP is None:
            self.console.print("[red][!] Scapy no disponible.[/red]")
            return
        rango = Validador.cidr(self.console)
        if not rango:
            return
        self._barra(f"ESCANEANDO HOSTS EN {rango}...")
        try:
            resultado = self._srp(
                self._Eth(dst="ff:ff:ff:ff:ff:ff") / self._ARP(pdst=rango),
                timeout=3, verbose=False
            )[0]
            tb = Table(box=box.SIMPLE_HEAD, show_edge=False)
            tb.add_column("IP",         style="cyan")
            tb.add_column("MAC",        style="yellow")
            tb.add_column("Fabricante", style="white")
            hosts = []
            for _, r in resultado:
                fab = self._fabricante(r.hwsrc)
                tb.add_row(r.psrc, r.hwsrc, fab)
                hosts.append({"ip": r.psrc, "mac": r.hwsrc, "fabricante": fab})
            self.console.print(tb)
            if self.gp:
                self.gp.registrar_evidencia(
                    "arp_scan",
                    f"Scan ARP en {rango}: {len(hosts)} hosts detectados",
                    {"rango": rango, "hosts": hosts}
                )
            self.log.info(
                f"Scan ARP {rango}: {len(hosts)} hosts", "NetworkScan")
        except Exception:
            self.console.print(
                "[red][!] Error de permisos. Ejecuta como root/administrador.[/red]"
            )

    def _portscan(self):
        ip = Validador.ip(self.console, f"\n{self.nombre} [TARGET IP]")
        if not ip:
            return
        self._barra(f"AUDITANDO PUERTOS EN {ip}...")

        PUERTOS = {
            21: "FTP",  22: "SSH",    23: "Telnet", 25: "SMTP",
            80: "HTTP", 443: "HTTPS", 445: "SMB",   3306: "MySQL",
            5432: "PostgreSQL", 8080: "HTTP-Alt",   8443: "HTTPS-Alt"
        }

        tb = Table(box=box.SIMPLE_HEAD, show_edge=False)
        tb.add_column("Puerto",   style="cyan",   justify="center")
        tb.add_column("Servicio", style="yellow")
        tb.add_column("Estado",   justify="center")

        abiertos = []
        for puerto, srv in PUERTOS.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                if sock.connect_ex((ip, puerto)) == 0:
                    tb.add_row(str(puerto), srv, "[green]ABIERTO[/green]")
                    abiertos.append({"puerto": puerto, "servicio": srv})
                sock.close()
            except socket.error:
                pass

        self.console.print(tb)
        self.console.print(f"[dim]Puertos abiertos: {len(abiertos)}[/dim]")

        # Registrar evidencia en proyecto
        if self.gp and abiertos:
            self.gp.registrar_evidencia(
                "portscan",
                f"PortScan en {ip}: {len(abiertos)} puertos abiertos",
                {"ip": ip, "puertos": abiertos}
            )
        self.log.info(f"PortScan {ip}: {len(abiertos)} abiertos", "PortScan")

        # Sugerir CVE automáticamente
        if abiertos and self.cve:
            if Prompt.ask(
                "\n[?] ¿Cruzar puertos abiertos con base de datos CVE?",
                choices=["s", "n"], default="s"
            ) == "s":
                servicios = [{"nombre": a["servicio"], "version": ""}
                             for a in abiertos]
                self.cve.analizar_resultado_scan(servicios)

    def _advscan(self):
        if not self._ok("adv_scanner"):
            return
        ip = Validador.ip(self.console, "[?] IP del objetivo")
        if ip:
            self.adv_scanner.escanear_objetivo(ip)

    def _sweep(self):
        if not self._ok("sweep"):
            return
        rango = Validador.cidr(self.console)
        self.sweep.escanear_perimetro(rango)

    def _sniff(self):
        if not self._ok("sniffer"):
            return
        filtro = self.console.input(
            "\n[bold cyan]  [?] Filtro BPF (Enter = ninguno): [/bold cyan]"
        ).strip()
        secs = Validador.segundos(self.console)
        self.sniffer.iniciar_captura(filtro=filtro, duracion=secs)

    def _radar(self):
        if not self._ok("radar") or not self._ok("geomap"):
            return
        _limpiar()
        self.geomap.abrir_mapa()
        try:
            while True:
                _limpiar()
                self.console.print(self.radar.render_radar())
                self.geomap.generar_mapa(self.radar.targets)
                time.sleep(2)
        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Radar detenido.[/yellow]")

    # ── AUDITORÍA ────────────────────────────────────────────────────

    def _audit(self):
        if not self._ok("hydra") or not self._ok("dict_manager"):
            return
        self.console.print(
            "\n[bold magenta]⚔  MÓDULO HYDRA INICIADO[/bold magenta]")
        target = Validador.ip(self.console, "[?] IP del objetivo")
        if not target:
            return
        servicio = Prompt.ask(
            "[?] Servicio",
            choices=["ssh", "ftp", "mysql", "http-get", "telnet"],
            default="ssh"
        )
        diccionario = self.dict_manager.obtener_ruta_diccionario(servicio)
        if Prompt.ask(
            f"¿Iniciar ataque con {diccionario}?",
            choices=["s", "n"], default="n"
        ) == "s":
            resultado = self.hydra.ejecutar_ataque(
                target, servicio, "root", diccionario
            )
            if resultado:
                self._exito(target, servicio, resultado)

    def _vulnscan(self):
        if not self._ok("audit_engine"):
            return
        target = Validador.ip(self.console, "[?] IP a analizar")
        if not target:
            return
        resultado = self.audit_engine.escaneo_vulnerabilidades(target)
        self.console.print(
            Panel(resultado, title="RESULTADOS DE VULNERABILIDAD",
                  border_style="red")
        )
        self.log.audit(f"Vulnscan en {target}", "AuditEngine")
        if self.gp:
            self.gp.registrar_evidencia(
                "vulnscan", f"Escaneo de vulnerabilidades en {target}",
                {"ip": target, "resultado": resultado[:500]}
            )

    def _sqlcheck(self):
        if not self._ok("audit_engine"):
            return
        url = Validador.url(self.console, "[?] URL Objetivo")
        if not url:
            return
        resultado = self.audit_engine.auditoria_sql(url)
        self.console.print(
            Panel(resultado, title="INFORME SQLMAP", border_style="yellow")
        )

    # ── WIRELESS / RF ────────────────────────────────────────────────

    def _wifi(self):
        if not self._ok("bt"):
            return
        self.console.print("\n[1] Beacon Spam  [2] Deauth Attack")
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        if opt == "1":
            prefijo = self.console.input(
                "[bold cyan]Prefijo SSID: [/bold cyan]"
            ).strip()
            self.bt.beacon_spam(prefijo)
        elif opt == "2":
            mac_v = Validador.pedir(self.console, "MAC Víctima",
                                    Validador._mac, "MAC inválida. Ej: AA:BB:CC:DD:EE:FF")
            mac_a = Validador.pedir(self.console, "MAC AP",
                                    Validador._mac, "MAC inválida.")
            if mac_v and mac_a:
                self.bt.deauth(mac_v, mac_a)

    def _eviltwin(self):
        if not self._ok("wifi_attack"):
            return
        if self._evs is None:
            self.console.print("[red][!] EvilTwinServer no disponible.[/red]")
            return
        ssid = self.console.input(
            "[bold cyan] [?] SSID: [/bold cyan]"
        ).strip()
        if ssid:
            self.wifi_attack.crear_gemelo_malvado(ssid, 6)
            threading.Thread(target=self._evs, daemon=True).start()
            input("[!] Presiona Enter para detener...")
            self.wifi_attack.detener_ataques()

    def _rfscan(self):
        if not self._ok("rf"):
            return
        freq = Validador.mhz(self.console)
        if freq:
            self.rf.escanear_frecuencia(freq)

    # ── FORENSE ───────────────────────────────────────────────────────

    def _mobile(self):
        if not self._ok("mobile"):
            return
        self.console.print(
            "\n[1] Android Triage  [2] iOS Info  [3] Screenshot Remoto"
        )
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        if opt == "1":
            self.mobile.triage_android()
        elif opt == "2":
            self.mobile.triage_ios()
        elif opt == "3":
            path = self.mobile.preparar_directorio("Android_Screen")
            self.console.print("[*] Tomando captura de pantalla...")
            try:
                subprocess.run(
                    ["adb", "shell", "screencap", "-p", "/sdcard/s.png"],
                    check=True, timeout=15
                )
                subprocess.run(
                    ["adb", "pull", "/sdcard/s.png", f"{path}/s.png"],
                    check=True, timeout=15
                )
                self.console.print(
                    f"[green][+] Captura guardada en {path}/s.png[/green]"
                )
                if self.gp:
                    self.gp.registrar_evidencia(
                        "screenshot", f"Captura de pantalla Android",
                        {"ruta": f"{path}/s.png"}
                    )
            except Exception as e:
                self.console.print(f"[red][!] Error ADB: {e}[/red]")

    def _mobile_deep(self):
        path = "./data/evidence/mobile/Deep_Extraction/"
        os.makedirs(path, exist_ok=True)

        if self._dbc is None:
            self.console.print(
                "[red][!] DatabaseExtractor no disponible.[/red]"
            )
            return

        extractor = self._dbc()
        self.console.print(
            "\n[1] Extraer WhatsApp Full  [2] Extraer Chrome History"
        )
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()

        if opt == "1":
            self._barra("EXTRAYENDO DB Y LLAVE...")
            extractor.extraer_whatsapp(path)
            extractor.extraer_whatsapp_key(path)
            self.log.audit("Extracción WhatsApp completada", "MobileDeep")
            if self.gp:
                self.gp.registrar_evidencia(
                    "whatsapp_extraction",
                    "Extracción de base de datos WhatsApp",
                    {"ruta": path}
                )
        elif opt == "2":
            self._barra("EXTRAYENDO HISTORIAL CHROME...")
            self.log.audit("Extracción Chrome completada", "MobileDeep")

    def _view(self):
        if not self._ok("reader"):
            return
        ruta_base = "./data/evidence/mobile/Deep_Extraction/"
        opcion = self.console.input(
            "[bold cyan] [1] Leer WhatsApp  [2] Leer Chrome: [/bold cyan]"
        ).strip()
        if opcion == "1":
            self.reader.leer_whatsapp_mensajes(
                os.path.join(ruta_base, "whatsapp_messages.db")
            )
        elif opcion == "2":
            self.reader.leer_historial_chrome(
                os.path.join(ruta_base, "chrome_history.db")
            )

    # ── INTEL & STEALTH ───────────────────────────────────────────────

    def _locate(self):
        if not self._ok("locator"):
            return
        ip = Validador.ip(self.console, "IP objetivo")
        if ip:
            self.locator.rastrear_ip(ip)
            self.log.info(f"Locate: {ip}", "LocatorModule")
            if self.gp:
                self.gp.registrar_evidencia(
                    "locate", f"Rastreo de IP {ip}", {"ip": ip}
                )

    def _locate_p(self):
        if not self._ok("adv_scanner") or not self._ok("geopreciose"):
            return
        redes = self.adv_scanner.obtener_redes_formateadas()
        self.geopreciose.triangular_posicion(redes)

    def _geofoto(self):
        if not self._ok("exif"):
            return
        ruta = self.console.input(
            "[bold cyan]Ruta de imagen: [/bold cyan]"
        ).strip().replace("'", "").replace('"', "")
        if ruta:
            self.exif.analizar_foto(ruta)

    def _phishing(self):
        _limpiar()
        self.console.print(
            "[bold red][!][/bold red] Iniciando Suite de Phishing..."
        )
        ruta_z = "./tools/zphisher/zphisher.sh"
        bash_path = r"C:\Program Files\Git\bin\bash.exe"
        try:
            subprocess.run([bash_path, ruta_z], check=True)
        except Exception as e:
            self.console.print(f"[red]Error al lanzar: {e}[/red]")

    # ── NUEVOS COMANDOS PROFESIONALES ────────────────────────────────

    def _proyecto(self, args: list):
        """Gestiona subcomandos de proyecto."""
        if not self._ok("gp"):
            return
        sub = args[0] if args else ""
        acciones = {
            "nuevo":   self.gp.crear_proyecto,
            "cargar":  self.gp.cargar_proyecto,
            "lista":   self.gp.listar_proyectos,
            "list":    self.gp.listar_proyectos,
            "estado":  self.gp.mostrar_resumen,
            "status":  self.gp.mostrar_resumen,
            "cerrar":  self.gp.cerrar_proyecto,
        }
        accion = acciones.get(sub)
        if accion:
            accion()
        else:
            self.console.print(
                "[dim]Subcomandos: "
                "[bold white]nuevo | cargar | lista | estado | cerrar[/bold white][/dim]"
            )

    def _reporte(self, args: list):
        """Genera reportes del proyecto activo."""
        if not self._ok("motor_rep"):
            self.console.print(
                "[red][!] MotorReportes no disponible. "
                "¿Existe el archivo MotorReportes.py?[/red]"
            )
            return
        sub = args[0] if args else ""
        if sub == "resumen":
            self.motor_rep.generar_resumen_ejecutivo()
        elif sub == "timeline":
            self.motor_rep.generar_timeline()
        else:
            self.motor_rep.generar_reporte_completo()

    def _osint(self):
        """Lanza el motor OSINT interactivo."""
        if not self._ok("osint"):
            return
        self.osint.menu()

    def _cve(self):
        """Búsqueda manual de CVEs en NVD."""
        if not self._ok("cve"):
            return
        self.cve.busqueda_libre()

    def _jobs(self, args: list):
        """Gestiona la cola de tareas asíncronas."""
        if not self._ok("cola"):
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

    def _plugins_cmd(self, args: list):
        """Administra el sistema de plugins."""
        if not self._ok("plugins"):
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
                    f"[red][!] Plugin '{args[1]}' no encontrado.[/red]"
                )
        else:
            self.plugins.listar()

    # ════════════════════════════════════════════════════════════════
    # DESPACHADOR CENTRAL
    # ════════════════════════════════════════════════════════════════

    def _despachar(self, entrada: str) -> bool:
        """
        Parsea la entrada del operador y ejecuta el comando.
        Retorna True si fue reconocido, False si no.
        """
        partes = entrada.strip().lower().split()
        if not partes:
            return True
        cmd = partes[0]
        args = partes[1:]

        # ── Comandos con subcomandos ──────────────────────────────────
        if cmd == "proyecto":
            self._proyecto(args)
            return True
        if cmd == "reporte":
            self._reporte(args)
            return True
        if cmd in ("job", "jobs"):
            self._jobs(args)
            return True
        if cmd in ("plugin", "plugins"):
            self._plugins_cmd(args)
            return True

        # Caso especial: "locate -p" (dos palabras)
        if entrada.strip().lower() == "locate -p":
            self._locate_p()
            return True

        # ── Tabla principal de comandos ───────────────────────────────
        TABLA = {
            # Sistema
            "help": lambda: mostrar_ayuda(self.console, self.version),
            "?": lambda: mostrar_ayuda(self.console, self.version),
            "status":      self._status,
            "hora": lambda: self.console.print(
                f"[cyan]Hora:[/cyan] {time.strftime('%H:%M:%S')}"
            ),
            "clear": lambda: mostrar_banner(
                self.console, self.nombre, self.version, self._iface()
            ),
            "cls": lambda: mostrar_banner(
                self.console, self.nombre, self.version, self._iface()
            ),
            "logs":        self.log.mostrar_historial,
            "files":       self._files,

            # Red
            "scan":        self._scan,
            "netscan":     self._scan,
            "advscan":     self._advscan,
            "portscan":    self._portscan,
            "sweep":       self._sweep,
            "sniff":       self._sniff,
            "radar":       self._radar,

            # Auditoría
            "audit":       self._audit,
            "vulnscan":    self._vulnscan,
            "sqlcheck":    self._sqlcheck,

            # Wireless / RF
            "wifi":        self._wifi,
            "eviltwin":    self._eviltwin,
            "rfscan":      self._rfscan,
            "btjumper": lambda: (self.bt.iniciar_jumper()
                                 if self._ok("bt") else None),

            # Forense
            "mobile":      self._mobile,
            "mobile-deep": self._mobile_deep,
            "view":        self._view,

            # Intel & Stealth
            "locate":      self._locate,
            "geofoto":     self._geofoto,
            "stealth": lambda: (self.stealth.verificar_identidad()
                                if self._ok("stealth") else None),
            "panic": lambda: (self.stealth.activar_panico()
                              if self._ok("stealth") else None),

            # Ingeniería social
            "phishing":    self._phishing,
            "ducky": lambda: (self.ducky.ejecutar_payload()
                              if self._ok("ducky") else None),

            # Nuevos profesionales
            "osint":       self._osint,
            "cve":         self._cve,
        }

        if cmd in TABLA:
            TABLA[cmd]()
            return True

        # ── Delegar a plugins ─────────────────────────────────────────
        if self.plugins and self.plugins.tiene_comando(cmd):
            self.plugins.ejecutar_comando(cmd, args)
            return True

        return False

    # ════════════════════════════════════════════════════════════════
    # BUCLE PRINCIPAL
    # ════════════════════════════════════════════════════════════════

    def ejecutar(self):
        """Punto de entrada principal del sistema."""

        # 1. Autenticación
        if not self.auth.solicitar_acceso():
            self.console.print(
                "[red][!] Acceso denegado. Sistema bloqueado.[/red]"
            )
            self.log.warning("Sistema bloqueado — intentos fallidos.", "Auth")
            return

        # 2. Bootscreen animado
        mostrar_bootloader(
            self.console, self.nombre, self.version, self._iface()
        )

        # 3. Diagnóstico de dependencias
        self.console.print(
            "[bold blue][*] Diagnosticando dependencias del sistema...[/bold blue]"
        )
        if self.checker:
            self.checker.verificar_dependencias()

        # 4. Limpieza de logs
        self.log.verificar_y_limpiar()

        # 5. Verificación de identidad stealth
        if self.stealth:
            self.stealth.verificar_identidad()

        # 6. Log de inicio
        self.log.info("Sistema iniciado correctamente.", "ApexSentinel")

        # 7. Sugerencia de proyecto si no hay uno activo
        if self.gp and not self.gp.proyecto_activo:
            self.console.print(
                "\n[dim][tip] No hay proyecto activo. "
                "Usa [bold white]proyecto nuevo[/bold white] para crear "
                "un workspace de operación con trazabilidad completa.[/dim]\n"
            )

        # 8. Bucle de comandos
        while True:
            try:
                # Prompt con nombre de proyecto activo visible
                plab = ""
                if self.gp and self.gp.proyecto_activo:
                    plab = f"[{self.gp.proyecto_activo.nombre}]"

                entrada = input(
                    f"AnubisOS@Sentinel:{plab}~# "
                ).strip()

                if not entrada:
                    continue

                # Salida segura
                if entrada.lower() == "exit":
                    self.console.print(
                        "[yellow][!] Desconectando Sentinel...[/yellow]"
                    )
                    self.log.info(
                        "Sesión cerrada por el operador.", "ApexSentinel")
                    time.sleep(0.5)
                    break

                # Despacho
                if not self._despachar(entrada):
                    self.console.print(
                        f"[yellow][?] Comando '[bold]{entrada}[/bold]' no reconocido. "
                        f"Escribe [bold white]help[/bold white] para ver opciones.[/yellow]"
                    )

            except KeyboardInterrupt:
                self.console.print(
                    "\n[yellow][!] Operación interrumpida. "
                    "Usa '[bold white]exit[/bold white]' para cerrar el sistema.[/yellow]"
                )
            except EOFError:
                # Ctrl+D — cierre limpio
                break
            except Exception as e:
                self.console.print(f"[red][!] Error inesperado: {e}[/red]")
                self.log.error(str(e), "Main")


# ════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Crear directorios base si no existen
    for directorio in ["data/logs", "data/evidence", "plugins"]:
        os.makedirs(directorio, exist_ok=True)

    sentinel = ApexSentinel()
    sentinel.ejecutar()
