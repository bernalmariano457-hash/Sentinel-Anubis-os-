"""
bootscreen.py — Apex Sentinel / AnubisOS
Módulo de pantalla de arranque, banner y ayuda.
Extraído de Main para mantener SRP; importar con:

    from bootscreen import mostrar_bootloader, mostrar_banner, mostrar_ayuda
"""

import os
import sys
import time
import random
import socket
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.columns import Columns
from rich.align import Align
from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn, TimeElapsedColumn
from rich import box
from rich.live import Live
from rich.padding import Padding


# ════════════════════════════════════════════════════════════════════
# ARTE ASCII  —  versión mejorada con más carácter
# ════════════════════════════════════════════════════════════════════

ANUBIS_ART = r"""
   ╔═══════════╗
   ║  /\   /\  ║
   ║ (  \_/  ) ║
   ║  \     /  ║
   ║  /\___/\  ║
   ║ / / | \ \ ║
   ╚═══════════╝"""
# Firma compacta para el banner rápido (clear)
ANUBIS_ART_COMPACT = r"""
  ╔═══════════════╗
  ║ ◈  ANUBIS  ◈ ║
  ║   SENTINEL   ║
  ╚═══════════════╝"""

# ════════════════════════════════════════════════════════════════════
# CONSTANTES
# ════════════════════════════════════════════════════════════════════

MODULOS_BOOT = [
    ("HydraModule",     "Fuerza bruta / auditoría",   "🔐"),
    ("TacticalSniffer", "Captura de tráfico",          "📡"),
    ("RadarSentinel",   "Intercepción Wi-Fi",          "📶"),
    ("ExifAnalyzer",    "Metadatos EXIF",              "🖼"),
    ("BluetoothModule", "Escaneo Bluetooth",           "🔵"),
    ("ForensicReader",  "Lectura forense",             "🔬"),
    ("GeoPrecise",      "Triangulación GPS",           "📍"),
    ("StealthModule",   "Huella digital",              "👁"),
    ("MobileSentinel",  "Triaje móvil",                "📱"),
    ("NetworkModule",   "Análisis de red",             "🌐"),
    ("GestorProyectos", "Workspaces de operación",     "📁"),
    ("MotorReportes",   "Reportes MD/TXT/Timeline",    "📄"),
    ("OSINTEngine",     "Reconocimiento pasivo",       "🔍"),
    ("CVEMatcher",      "Base de datos CVE/NVD",       "⚠"),
    ("ColaTareas",      "Ejecución asíncrona",         "⚙"),
    ("GestorPlugins",   "Plugins en caliente",         "🔌"),
]

# Colores por categoría de módulo para diferenciación visual
_COLOR_MOD = {
    "HydraModule":     "red",
    "TacticalSniffer": "cyan",
    "RadarSentinel":   "cyan",
    "ExifAnalyzer":    "yellow",
    "BluetoothModule": "blue",
    "ForensicReader":  "green",
    "GeoPrecise":      "magenta",
    "StealthModule":   "dim white",
    "MobileSentinel":  "yellow",
    "NetworkModule":   "cyan",
    "GestorProyectos": "green",
    "MotorReportes":   "green",
    "OSINTEngine":     "magenta",
    "CVEMatcher":      "red",
    "ColaTareas":      "dim cyan",
    "GestorPlugins":   "dim white",
}

ESTILOS_LOG = {
    "INFO":    ("cyan",    "ℹ"),
    "WARNING": ("yellow",  "⚠"),
    "ERROR":   ("red",     "✖"),
    "SUCCESS": ("green",   "✔"),
    "AUDIT":   ("magenta", "⚑"),
}


# ════════════════════════════════════════════════════════════════════
# HELPERS INTERNOS
# ════════════════════════════════════════════════════════════════════

def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d  %H:%M:%S")


def _plataforma() -> str:
    mapping = {"win32": "Windows", "linux": "Linux", "darwin": "macOS"}
    return mapping.get(sys.platform, sys.platform.upper())


def _glitch_text(console: Console, texto: str, repeticiones: int = 3):
    """Efecto glitch: imprime el texto con caracteres corruptos y luego el original."""
    glitch_chars = "░▒▓█▄▀■□▪▫"
    for _ in range(repeticiones):
        corrompido = "".join(
            random.choice(glitch_chars) if random.random() < 0.25 else c
            for c in texto
        )
        console.print(f"\r[dim green]{corrompido}[/dim green]", end="")
        time.sleep(0.04)
    console.print(f"\r[bold green]{texto}[/bold green]")


def _scanline(console: Console, ancho: int = 60):
    """Línea de escaneo animada al inicio."""
    chars = "▰▱"
    for i in range(ancho + 1):
        barra = chars[0] * i + chars[1] * (ancho - i)
        pct = int((i / ancho) * 100)
        console.print(
            f"\r  [dim green]{barra}[/dim green] [bold green]{pct:>3}%[/bold green]",
            end=""
        )
        time.sleep(0.018)
    console.print()


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 1 — HEADER del bootloader
# ════════════════════════════════════════════════════════════════════

def _construir_header(nombre: str, version: str, iface: str) -> Panel:
    """Panel principal con arte ASCII + info del sistema."""

    # Arte ASCII izquierdo
    arte = Text(ANUBIS_ART, style="bold green", justify="center")

    # Separador vertical
    sep = Text("\n" * 2 + "│\n│\n│\n│\n│\n│\n│\n│", style="dim green")

    # Tabla de info derecha
    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim cyan",   justify="right",  min_width=12)
    info.add_column(style="bold white", justify="left",   min_width=24)

    info.add_row("",          "")
    info.add_row(
        "SISTEMA",   f"[bold white]APEX SENTINEL[/bold white]  [dim]v{version}[/dim]")
    info.add_row("OPERADOR",  f"[bold green]{nombre}[/bold green]")
    info.add_row("HOST",      f"[cyan]{_hostname()}[/cyan]")
    info.add_row("PLATAFORMA", f"[dim]{_plataforma()}[/dim]")
    info.add_row("IFACE",     f"[cyan]{iface}[/cyan]")
    info.add_row("TIMESTAMP", f"[dim]{_ts()}[/dim]")
    info.add_row("",          "")
    info.add_row("ESTADO",    "[bold green]● OPERACIONAL[/bold green]")
    info.add_row("AVISO",     "[bold red]⚠  AUTHORIZED USE ONLY[/bold red]")
    info.add_row("",          "")

    layout = Columns(
        [Align(arte, vertical="middle"), Align(info, vertical="middle")],
        equal=False, expand=True
    )
    return Panel(
        layout,
        title="[bold green]  ◈  ANUBIS OS  ◈  [/bold green]",
        subtitle=f"[dim green]APEX SENTINEL  ·  TACTICAL OPERATING SYSTEM[/dim green]",
        border_style="green",
        box=box.DOUBLE_EDGE,
        padding=(1, 3),
    )


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 2 — Barra de progreso de carga de módulos
# ════════════════════════════════════════════════════════════════════

def _cargar_modulos_con_progreso(console: Console):
    """
    Progreso mejorado:
    - Spinner + descripción + barra + porcentaje + tiempo transcurrido
    - Velocidad variable (módulos críticos más lentos)
    - Mensaje de estado al completar
    """
    CRITICOS = {"HydraModule", "TacticalSniffer", "OSINTEngine", "CVEMatcher"}

    with Progress(
        SpinnerColumn(spinner_name="dots2", style="bold green"),
        TextColumn("  [cyan]{task.description:<38}[/cyan]"),
        BarColumn(bar_width=30, style="dim green", complete_style="bold green",
                  finished_style="bold green"),
        TextColumn("[bold green]{task.percentage:>3.0f}%[/bold green]"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        total = len(MODULOS_BOOT)
        tarea = progress.add_task(
            "[dim]Preparando núcleo...[/dim]", total=total)

        for nombre_mod, desc, icono in MODULOS_BOOT:
            color = _COLOR_MOD.get(nombre_mod, "white")
            label = f"{icono}  [{color}]{nombre_mod:<18}[/{color}] [dim]{desc}[/dim]"
            progress.update(tarea, description=label)
            # Módulos críticos toman un poco más — sensación de peso real
            delay = 0.18 if nombre_mod in CRITICOS else 0.09
            time.sleep(delay)
            progress.advance(tarea)

        progress.update(
            tarea, description="[bold green]✔  Todos los módulos en línea[/bold green]")
        time.sleep(0.3)


# ════════════════════════════════════════════════════════════════════
# SECCIÓN 3 — Tabla de módulos cargados (post-boot)
# ════════════════════════════════════════════════════════════════════

def _tabla_modulos(console: Console):
    """Tabla compacta en 2 columnas para no ocupar toda la pantalla."""
    mitad = len(MODULOS_BOOT) // 2
    col_a = MODULOS_BOOT[:mitad]
    col_b = MODULOS_BOOT[mitad:]

    tabla = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold cyan",
        show_edge=False,
        expand=True,
        padding=(0, 1),
    )
    tabla.add_column("Módulo",   style="green",     min_width=18, no_wrap=True)
    tabla.add_column("Función",  style="dim white",  min_width=22)
    tabla.add_column("",         style="dim green",
                     min_width=2,  justify="center")
    tabla.add_column("Módulo",   style="green",     min_width=18, no_wrap=True)
    tabla.add_column("Función",  style="dim white",  min_width=22)
    tabla.add_column("Estado",   style="bold green",
                     min_width=8,  justify="center")

    for (nm_a, desc_a, ico_a), (nm_b, desc_b, ico_b) in zip(col_a, col_b):
        col_a_color = _COLOR_MOD.get(nm_a, "green")
        col_b_color = _COLOR_MOD.get(nm_b, "green")
        tabla.add_row(
            f"[{col_a_color}]{ico_a} {nm_a}[/{col_a_color}]", desc_a, "│",
            f"[{col_b_color}]{ico_b} {nm_b}[/{col_b_color}]", desc_b,
            "[bold green]● OK[/bold green]",
        )

    console.print(Panel(
        tabla,
        title="[bold white]MÓDULOS DEL SISTEMA[/bold white]",
        subtitle=f"[dim]{len(MODULOS_BOOT)} módulos registrados[/dim]",
        border_style="dim green",
        box=box.HEAVY_EDGE,
        padding=(0, 1),
    ))


# ════════════════════════════════════════════════════════════════════
# API PÚBLICA — BOOTLOADER COMPLETO
# ════════════════════════════════════════════════════════════════════

def mostrar_bootloader(console: Console, nombre: str, version: str, iface: str):
    """
    Secuencia de arranque completa:
      1. Limpieza de pantalla
      2. Efecto scanline inicial
      3. Header con arte ASCII + info del sistema
      4. Barra de progreso de módulos (con velocidad variable)
      5. Tabla compacta 2 columnas con módulos cargados
      6. Pie con instrucción de ayuda
    """
    os.system("cls" if os.name == "nt" else "clear")

    # ── 1. Intro: scanline + título con glitch ────────────────────────
    console.print()
    console.print(Align.center(
        "[dim green]INICIALIZANDO APEX SENTINEL...[/dim green]"))
    console.print()
    _scanline(console, ancho=58)
    console.print()

    # ── 2. Header principal ───────────────────────────────────────────
    console.print(_construir_header(nombre, version, iface))
    console.print()

    # ── 3. Progreso de módulos ────────────────────────────────────────
    console.print(Rule(
        title="[dim green]CARGA DE MÓDULOS[/dim green]",
        style="dim green",
        align="left"
    ))
    console.print()
    _cargar_modulos_con_progreso(console)
    console.print()

    # ── 4. Tabla de módulos ───────────────────────────────────────────
    _tabla_modulos(console)
    console.print()

    # ── 5. Pie ────────────────────────────────────────────────────────
    console.print(Rule(style="dim green"))
    console.print(Align.center(
        "[dim]Escribe [bold white]help[/bold white] para ver comandos  "
        "·  [bold white]exit[/bold white] para salir[/dim]"
    ))
    console.print(Rule(style="dim green"))
    console.print()


# ════════════════════════════════════════════════════════════════════
# API PÚBLICA — BANNER RÁPIDO (clear / cls)
# ════════════════════════════════════════════════════════════════════

def mostrar_banner(console: Console, nombre: str, version: str, iface: str):
    """
    Banner compacto para el comando 'clear'.
    No hace animaciones — respuesta inmediata.
    """
    os.system("cls" if os.name == "nt" else "clear")

    arte = Text(ANUBIS_ART_COMPACT, style="bold green", justify="center")

    der = Table.grid(padding=(0, 1))
    der.add_column(style="dim cyan",   justify="right", min_width=12)
    der.add_column(style="bold white", justify="left")
    der.add_row(
        "SISTEMA",   f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    der.add_row("OPERADOR",  f"[bold green]{nombre}[/bold green]")
    der.add_row("HOST",      f"[cyan]{_hostname()}[/cyan]")
    der.add_row("IFACE",     f"[cyan]{iface}[/cyan]")
    der.add_row(
        "HORA",      f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]")
    der.add_row("ESTADO",    "[bold green]● ACTIVO[/bold green]")
    der.add_row("AVISO",     "[bold red]⚠ AUTHORIZED USE ONLY[/bold red]")

    grid = Table.grid(padding=(0, 4), expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=2)
    grid.add_row(Align(arte, vertical="middle"), Align(der, vertical="middle"))

    console.print(Panel(
        grid,
        border_style="green",
        box=box.HEAVY_EDGE,
        padding=(0, 2),
        title="[bold green]◈ ANUBIS OS[/bold green]",
        subtitle="[dim green]TACTICAL OS[/dim green]",
    ))
    console.print(Rule(style="dim green"))
    console.print()


# ════════════════════════════════════════════════════════════════════
# API PÚBLICA — MENÚ DE AYUDA
# ════════════════════════════════════════════════════════════════════

def mostrar_ayuda(console: Console, version: str, comandos: dict):
    """
    Menú de ayuda con categorías en 2 columnas.
    Recibe el dict COMANDOS_HELP desde Main para no duplicar datos.
    """
    console.print()
    console.print(Rule(
        title=f"[bold white]ANUBIS OS — COMMAND INDEX[/bold white]  [dim]v{version}[/dim]",
        style="green"
    ))
    console.print()

    bloques = []
    for categoria, datos in comandos.items():
        color = datos["color"]
        tabla = Table(
            box=box.SIMPLE, show_header=False, show_edge=False,
            padding=(0, 1), expand=True
        )
        tabla.add_column(
            "cmd",  style=f"bold {color}", min_width=16, no_wrap=True)
        tabla.add_column("desc", style="dim white")
        for cmd, desc in datos["items"]:
            tabla.add_row(cmd, desc)
        bloques.append(Panel(
            tabla,
            title=f"[bold {color}]{categoria}[/bold {color}]",
            border_style=color,
            box=box.ROUNDED,
            padding=(0, 1),
        ))

    for i in range(0, len(bloques), 2):
        par = bloques[i:i+2]
        console.print(
            Columns(par, equal=True, expand=True) if len(par) == 2 else par[0]
        )
        console.print()

    console.print(Rule(style="dim green"))
    console.print(
        "  [dim]Tip:[/dim] Escribe el comando y presiona [bold white]Enter[/bold white]  ·  "
        "Salir: [bold white]exit[/bold white]  ·  "
        "Limpiar: [bold white]clear[/bold white]"
    )
    console.print(Rule(style="dim green"))
    console.print()
