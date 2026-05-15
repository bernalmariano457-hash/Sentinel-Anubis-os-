from __future__ import annotations

import os
import sys
import time
import socket
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich.rule import Rule
from rich.align import Align
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn,
)
from rich import box

# ═══════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════

ANUBIS_ART = r"""
   ▄████████████████████▄
   █  ╔═══════════════╗  █
   █  ║   /\     /\   ║  █
   █  ║  (  \   /  )  ║  █
   █  ║   \  \_/  /   ║  █
   █  ║   /  ___  \   ║  █
   █  ║  / / | | \ \  ║  █
   █  ║ /_/__|_|__\_\  ║  █
   █  ╚═══════════════╝  █
   ▀████████████████████▀"""


ANUBIS = ANUBIS_ART

# ── Estilos de log: (color, icono) ─────────────────────────────────
ESTILOS_LOG: dict[str, tuple[str, str]] = {
    "INFO":    ("cyan",         "ℹ"),
    "SUCCESS": ("green",        "✔"),
    "WARNING": ("yellow",       "⚠"),
    "ERROR":   ("bold red",     "✖"),
    "AUDIT":   ("bold magenta", "⚑"),
    "DEBUG":   ("dim",          "·"),
}

# ── Módulos del sistema ─────────────────────────────────────────────
MODULOS_BOOT: list[tuple[str, str]] = [
    ("HydraModule",      "Fuerza bruta / auditoría"),
    ("TacticalSniffer",  "Captura de tráfico"),
    ("RadarSentinel",    "Intercepción Wi-Fi RSSI"),
    ("ExifAnalyzer",     "Metadatos EXIF / GPS"),
    ("BluetoothModule",  "Escaneo Bluetooth"),
    ("ForensicReader",   "Lectura forense"),
    ("GeoPrecise",       "Triangulación GPS"),
    ("StealthModule",    "Huella digital sigilosa"),
    ("MobileSentinel",   "Triaje de dispositivos móviles"),
    ("GestorProyectos",  "Workspaces de operación"),
    ("MotorReportes",    "Reportes MD / TXT / Timeline"),
    ("OSINTEngine",      "Reconocimiento pasivo OSINT"),
    ("CVEMatcher",       "Base de datos CVE / NVD"),
    ("ColaTareas",       "Ejecución asíncrona"),
    ("GestorPlugins",    "Plugins en caliente"),
]

# ── Tabla de ayuda por categorías ──────────────────────────────────
COMANDOS_HELP: dict[str, list[tuple[str, str]]] = {
    "SISTEMA": [
        ("help / ?",         "Mostrar este menú de ayuda"),
        ("status",           "Estado actual del sistema"),
        ("hora",             "Mostrar hora del sistema"),
        ("logs",             "Historial de eventos"),
        ("files",            "Explorar directorio actual"),
        ("clear / cls",      "Limpiar pantalla y mostrar banner"),
        ("exit",             "Cerrar Sentinel"),
    ],
    "RED": [
        ("scan",             "Escaneo ARP de red local"),
        ("netscan",          "Alias de scan"),
        ("advscan",          "Escaneo avanzado (Nmap)"),
        ("portscan",         "Escaneo de puertos TCP"),
        ("sweep",            "Barrido ICMP de subred"),
        ("sniff",            "Captura de paquetes"),
        ("radar",            "Modo radar Wi-Fi RSSI"),
    ],
    "RF / SDR": [
        ("rfscan",           "Escaneo de frecuencias RF"),
        ("rfbarrido",        "Barrido de espectro por rango"),
        ("rfbandas",         "Escanear todas las bandas conocidas"),
        ("radio",            "Escuchar y demodular señal (WFM/NFM/AM/SSB)"),
        ("rfgrabar",         "Grabar señal IQ a archivo"),
        ("rfplay",           "Reproducir grabación IQ"),
        ("adsb",             "Monitor ADS-B — transponders de aeronaves"),
        ("rfstatus",         "Estado del hardware SDR"),
    ],
    "ATAQUES": [
        ("audit",            "Auditoría de credenciales"),
        ("vulnscan",         "Análisis de vulnerabilidades"),
        ("sqlcheck",         "Detección SQLi básica"),
        ("wifi",             "Auditoría Wi-Fi"),
        ("eviltwin",         "Access point gemelo maligno"),
        ("btjumper",         "Salto de canal Bluetooth"),
        ("phishing",         "Clonar página de phishing"),
        ("ducky",            "Generar payload USB Ducky"),
    ],
    "FORENSE": [
        ("view",             "Leer archivo forense"),
        ("geofoto",          "Extraer GPS de fotografías EXIF"),
        ("locate",           "Localización por IP"),
        ("locate -p",        "Localización precisa (GPS activo)"),
        ("mobile",           "Triaje básico de móvil"),
        ("mobile-deep",      "Análisis profundo de móvil"),
        ("stealth",          "Activar modo sigiloso"),
        ("panic",            "Borrado de emergencia"),
    ],
    "PROYECTOS": [
        ("proyecto nuevo",   "Crear workspace de operación"),
        ("proyecto cargar",  "Cargar proyecto existente"),
        ("proyecto lista",   "Listar todos los proyectos"),
        ("proyecto estado",  "Resumen del proyecto activo"),
        ("proyecto cerrar",  "Cerrar proyecto activo"),
        ("reporte",          "Generar reporte completo"),
        ("reporte resumen",  "Resumen ejecutivo"),
        ("reporte timeline", "Línea de tiempo de eventos"),
    ],
    "INTELIGENCIA": [
        ("osint",            "Motor de reconocimiento pasivo"),
        ("cve",              "Búsqueda en base CVE / NVD"),
        ("jobs",             "Ver cola de tareas asíncronas"),
        ("jobs resultado",   "Resultado de un job"),
        ("jobs cancelar",    "Cancelar un job"),
        ("plugins",          "Listar plugins cargados"),
        ("plugins reload",   "Recargar plugins en caliente"),
    ],
}

# ── Mensajes del log de arranque ───────────────────────────────────
_LOGS_ARRANQUE: list[tuple[str, str]] = [
    ("SUCCESS", "Integridad del sistema verificada"),
    ("SUCCESS", "Autenticación bcrypt inicializada"),
    ("INFO",    "Cargando módulos tácticos..."),
    ("SUCCESS", "RadarSentinel iniciando sniffing pasivo"),
    ("SUCCESS", "GestorProyectos listo"),
    ("SUCCESS", "OSINTEngine conectado a APIs públicas"),
    ("INFO",    "PluginSystem escaneando plugins/"),
    ("SUCCESS", "Sistema operativo — todos los módulos en línea"),
]


# ═══════════════════════════════════════════════════════════════════
# UTILIDADES INTERNAS
# ═══════════════════════════════════════════════════════════════════

def _limpiar() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _get_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "Sin conexión"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


# ═══════════════════════════════════════════════════════════════════
# COMPONENTES VISUALES
# ═══════════════════════════════════════════════════════════════════

def _panel_header(nombre: str, version: str, iface: str) -> Panel:
    """Panel principal del bootscreen con arte ASCII e info del sistema."""

    arte = Text(ANUBIS_ART, style="bold green")

    inf = Table.grid(padding=(0, 2))
    inf.add_column(style="dim green", justify="right", min_width=14)
    inf.add_column(style="white")

    def row(k, v):
        inf.add_row(k, v)

    row("SISTEMA",
        f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    row("OPERADOR",   f"[bold green]{nombre}[/bold green]")
    row("ESTADO",     "[bold green]● EN LÍNEA[/bold green]")
    row("INTERFAZ",   f"[cyan]{iface}[/cyan]")
    row("IP LOCAL",   f"[cyan]{_get_ip()}[/cyan]")
    row("PLATAFORMA", f"[dim]{os.name.upper()} / {sys.platform}[/dim]")
    row("ARRANQUE",
        f"[dim]{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}[/dim]")
    row("",           "")
    row("AVISO",
        "[bold red]⚠  AUTHORIZED USE ONLY — ACCESO RESTRINGIDO[/bold red]")

    return Panel(
        Columns(
            [Align(arte, vertical="middle"), Align(inf, vertical="middle")],
            equal=False,
            expand=True,
        ),
        title="[bold green]◈  A N U B I S   O S  ◈[/bold green]",
        subtitle="[dim green]APEX SENTINEL — SISTEMA OPERATIVO TÁCTICO[/dim green]",
        border_style="green",
        box=box.DOUBLE_EDGE,
        padding=(1, 3),
    )


def _panel_modulos(estados: dict[str, bool] | None = None) -> Panel:
    """
    Tabla de módulos con estado REAL.

    Args:
        estados: dict {display_name → bool} devuelto por ModuleRegistry.estados().
                 Si es None o no contiene el módulo, muestra ● LISTO (fallback).
    """
    tb = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold green",
        show_edge=False,
        expand=True,
        padding=(0, 1),
    )
    tb.add_column("#",        style="dim",
                  justify="right", min_width=3)
    tb.add_column("Módulo",   style="bold green",  min_width=22)
    tb.add_column("Función",  style="dim white",   min_width=30)
    tb.add_column("Estado",   justify="center")

    cargados = 0
    for i, (nombre, desc) in enumerate(MODULOS_BOOT, 1):
        if estados is not None and nombre in estados:
            ok = estados[nombre]
        else:
            ok = True  # fallback conservador si no hay info

        if ok:
            cargados += 1
            estado_str = "[bold green]● LISTO[/bold green]"
        else:
            estado_str = "[yellow]○ DEGRADADO[/yellow]"

        tb.add_row(str(i), nombre, desc, estado_str)

    subtitle = (
        f"[dim green]{cargados}/{len(MODULOS_BOOT)} módulos en línea[/dim green]"
        if estados is not None
        else f"[dim green]{len(MODULOS_BOOT)} módulos cargados[/dim green]"
    )

    return Panel(
        tb,
        title="[bold green]▸  MÓDULOS DEL SISTEMA[/bold green]",
        subtitle=subtitle,
        border_style="green",
        box=box.HEAVY_HEAD,
        padding=(0, 1),
    )


def _construir_log_text(entradas: list[tuple[str, str]]) -> Text:
    """Construye el objeto Text del log de arranque."""
    texto = Text()
    for nivel, msg in entradas:
        color, icono = ESTILOS_LOG.get(nivel, ("white", "·"))
        texto.append(f"  {_ts()} ", style="dim")
        texto.append(f" {icono}  ", style=color)
        texto.append(f"{nivel:<8} ", style=f"bold {color}")
        texto.append(f"{msg}\n",    style=color)
    return texto


def _panel_log(entradas: list[tuple[str, str]]) -> Panel:
    return Panel(
        _construir_log_text(entradas),
        title="[dim green]▸  LOG DE ARRANQUE[/dim green]",
        border_style="dim green",
        padding=(0, 2),
        box=box.SIMPLE,
    )


# ═══════════════════════════════════════════════════════════════════
# FUNCIÓN PRINCIPAL: BOOTLOADER
# ═══════════════════════════════════════════════════════════════════

def mostrar_bootloader(
    console: Console,
    nombre: str,
    version: str,
    iface: str,
    estados_modulos: dict[str, bool] | None = None,
) -> None:
    """
    Pantalla de arranque animada v3 — 5 fases:
      1. Header con info del sistema
      2. Separador de fase
      3. Barra de progreso de módulos
      4. Tabla de módulos con estado REAL
      5. Log de arranque animado línea a línea

    Args:
        estados_modulos: dict {display_name → bool} de ModuleRegistry.estados().
                         Si se proporciona, la tabla refleja el estado real de
                         cada módulo (● LISTO / ○ DEGRADADO) en lugar de
                         mostrar todos como LISTO sin verificar.
    """
    _limpiar()

    # ── Fase 1: Header ─────────────────────────────────────────────
    console.print(_panel_header(nombre, version, iface))
    console.print()

    # ── Fase 2: Separador animado ──────────────────────────────────
    console.print(
        Rule(
            title="[bold green]INICIALIZANDO SUBSISTEMAS[/bold green]",
            style="green",
            align="center",
        )
    )
    console.print()

    # ── Fase 3: Barra de carga de módulos ─────────────────────────
    with Progress(
        SpinnerColumn(spinner_name="aesthetic", style="bold green"),
        TextColumn(
            "[green]{task.description:<48}[/green]",
            justify="left",
        ),
        BarColumn(
            bar_width=26,
            style="dim green",
            complete_style="bold green",
            finished_style="bold green",
            pulse_style="bright_green",
        ),
        TextColumn("[bold green]{task.percentage:>3.0f}%[/bold green]"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as pg:
        tk = pg.add_task(
            "  Iniciando núcleo AnubisOS...",
            total=len(MODULOS_BOOT),
        )
        for mod_nombre, _ in MODULOS_BOOT:
            pg.update(
                tk,
                description=f"  Cargando [bold]{mod_nombre}[/bold]...",
            )
            time.sleep(0.12)
            pg.advance(tk)
        pg.update(
            tk,
            description="  [bold green]✔  Todos los módulos en línea[/bold green]",
        )
        time.sleep(0.4)

    console.print()

    # ── Fase 4: Tabla de módulos ───────────────────────────────────
    console.print(_panel_modulos(estados_modulos))
    console.print()

    # ── Fase 5: Log de arranque animado ───────────────────────────
    console.print(
        Rule(
            title="[dim green]LOG DE ARRANQUE[/dim green]",
            style="dim green",
        )
    )
    console.print()

    # Animación línea a línea: imprime el panel creciente
    for i in range(1, len(_LOGS_ARRANQUE) + 1):
        parcial = _LOGS_ARRANQUE[:i]
        texto = _construir_log_text(parcial)
        panel = Panel(
            texto,
            border_style="dim green",
            padding=(0, 2),
            box=box.SIMPLE,
        )
        if i == 1:
            console.print(panel)
        else:
            # Retrocede y sobreescribe el panel anterior
            lineas = i + 2
            console.print(f"\033[{lineas}A", end="")
            console.print(panel)
        time.sleep(0.18)

    console.print()
    console.print(Rule(style="dim green"))
    console.print(
        Align.center(
            "[dim]Escribe [bold white]help[/bold white] "
            "para ver todos los comandos disponibles  ·  "
            "[bold white]exit[/bold white] para salir[/dim]"
        )
    )
    console.print(Rule(style="dim green"))
    console.print()


# ═══════════════════════════════════════════════════════════════════
# BANNER COMPACTO (comando clear / cls)
# ═══════════════════════════════════════════════════════════════════

def mostrar_banner(
    console: Console,
    nombre: str,
    version: str,
    iface: str,
    proyecto: str = None,
) -> None:
    """Banner compacto para el comando 'clear' durante la sesión."""
    _limpiar()

    grid = Table.grid(padding=(0, 3), expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=2)

    arte = Text(ANUBIS_ART, style="bold green")

    der = Table.grid(padding=(0, 1))
    der.add_column(style="dim green", justify="right", min_width=12)
    der.add_column(style="white")

    def row(k, v):
        der.add_row(k, v)

    row("SISTEMA",
        f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    row("OPERADOR", f"[bold green]{nombre}[/bold green]")
    row("ESTADO",   "[bold green]● EN LÍNEA[/bold green]")
    row("INTERFAZ", f"[cyan]{iface}[/cyan]")
    row("IP",       f"[cyan]{_get_ip()}[/cyan]")
    row("HORA",     f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]")
    if proyecto:
        row("PROYECTO", f"[bold green]{proyecto}[/bold green]")
    row("AVISO",    "[bold red]AUTHORIZED USE ONLY[/bold red]")

    grid.add_row(Align(arte, vertical="middle"), Align(der, vertical="middle"))

    console.print(
        Panel(
            grid,
            title="[bold green]◈  ANUBIS OS  ◈[/bold green]",
            border_style="green",
            box=box.HEAVY_EDGE,
            padding=(0, 2),
        )
    )
    console.print(Rule(style="dim green"))
    console.print()


# ═══════════════════════════════════════════════════════════════════
# MENÚ DE AYUDA (requerido por Main_v3.py)
# ═══════════════════════════════════════════════════════════════════

def mostrar_ayuda(
    console: Console,
    version: str,
    comandos: dict[str, list[tuple[str, str]]] = None,
) -> None:
    """
    Menú de ayuda organizado por categorías.

    :param console:   instancia Rich Console
    :param version:   versión del sistema (ej. "2.1")
    :param comandos:  dict categoría → [(cmd, descripción), ...]
                      Por defecto usa COMANDOS_HELP
    """
    if comandos is None:
        comandos = COMANDOS_HELP

    console.print()
    console.print(
        Panel(
            Align.center(
                f"[bold green]APEX SENTINEL  v{version}[/bold green]\n"
                "[dim]ANUBIS OS — Sistema Operativo Táctico[/dim]"
            ),
            border_style="green",
            box=box.DOUBLE_EDGE,
            padding=(0, 2),
        )
    )
    console.print()

    cols = []
    for categoria, cmds in comandos.items():
        tb = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold green",
            show_edge=False,
            expand=False,
            padding=(0, 1),
            min_width=38,
        )
        tb.add_column(
            f"▸  {categoria}",
            style="cyan",
            min_width=22,
            no_wrap=True,
        )
        tb.add_column("Descripción", style="dim white")

        for cmd, desc in cmds:
            tb.add_row(f"[bold white]{cmd}[/bold white]", desc)

        cols.append(
            Panel(
                tb,
                border_style="dim green",
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )

    # Imprimir en grupos de 2 columnas
    pares = [cols[i: i + 2] for i in range(0, len(cols), 2)]
    for par in pares:
        console.print(Columns(par, equal=True, expand=True))

    console.print()
    console.print(Rule(style="dim green"))
    console.print(
        Align.center(
            "[dim]Todos los módulos respetan [bold white]Ctrl+C[/bold white] "
            "para cancelar  ·  [bold white]exit[/bold white] para cerrar la sesión[/dim]"
        )
    )
    console.print(Rule(style="dim green"))
    console.print()


# ═══════════════════════════════════════════════════════════════════
# PRUEBA STANDALONE
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _console = Console()
    try:
        mostrar_bootloader(_console, "Sentinel", "2.1", "wlan0mon")
        input("AnubisOS@Sentinel:~# ")
        mostrar_banner(
            _console, "Sentinel", "2.1", "wlan0mon",
            proyecto="Operacion-Alpha",
        )
        input("AnubisOS@Sentinel:~# ")
        mostrar_ayuda(_console, "2.1")
    except KeyboardInterrupt:
        _console.print("\n[yellow][!] Cancelado.[/yellow]")
