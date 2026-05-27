from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

# ── Importar detección de plataforma (opcional — graceful fallback) ───
try:
    from core.platform import detect as _detect_platform
    _PLATFORM_OK = True
except ImportError:
    _PLATFORM_OK = False

# ══════════════════════════════════════════════════════════════════════
# ARTE ASCII — mascara de Anubis (sin modificar)
# ══════════════════════════════════════════════════════════════════════

ANUBIS_ART = "\n".join([
    r"   ▄████████████████████▄",
    r"   █  ╔═══════════════╗  █",
    r"   █  ║   /\     /\   ║  █",
    r"   █  ║  (  \   /  )  ║  █",
    r"   █  ║   \  \_/  /   ║  █",
    r"   █  ║   /  ___  \   ║  █",
    r"   █  ║  / / | | \ \  ║  █",
    r"   █  ║ /_/__|_|__\_\  ║  █",
    r"   █  ╚═══════════════╝  █",
    r"   ▀████████████████████▀",
])

ANUBIS = ANUBIS_ART

# ══════════════════════════════════════════════════════════════════════
# ESTILOS DE LOG
# ══════════════════════════════════════════════════════════════════════

ESTILOS_LOG: dict[str, tuple[str, str]] = {
    "INFO":    ("cyan",         "ℹ"),
    "SUCCESS": ("green",        "✔"),
    "WARNING": ("yellow",       "⚠"),
    "ERROR":   ("bold red",     "✖"),
    "AUDIT":   ("bold magenta", "⚑"),
    "DEBUG":   ("dim",          "·"),
}

# ══════════════════════════════════════════════════════════════════════
# MÓDULOS CONOCIDOS — con agrupación por categoría para el resumen
# ══════════════════════════════════════════════════════════════════════

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

# Agrupación visual para la línea de resumen compacta
_GRUPOS_MODULOS: dict[str, list[str]] = {
    "Red":      ["RadarSentinel", "TacticalSniffer", "BluetoothModule"],
    "RF":       ["RFModule", "SpectrumAnalyzer"],
    "Forense":  ["ExifAnalyzer", "ForensicReader", "MobileSentinel", "StealthModule"],
    "Acceso":   ["HydraModule"],
    "OSINT":    ["OSINTEngine", "CVEMatcher", "GeoPrecise"],
    "Proyectos":["GestorProyectos", "MotorReportes", "ColaTareas", "GestorPlugins"],
    "Seguridad":["SecurityModule", "Recovery"],
}

# ══════════════════════════════════════════════════════════════════════
# TABLA DE AYUDA
# ══════════════════════════════════════════════════════════════════════

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
        ("advscan",          "Escaneo avanzado (Nmap)"),
        ("portscan",         "Escaneo de puertos TCP"),
        ("sweep",            "Barrido ICMP de subred"),
        ("sniff",            "Captura de paquetes"),
        ("radar",            "Modo radar Wi-Fi RSSI"),
        ("wifitri",          "Triangulación Wi-Fi por RSSI"),
        ("btjumper",         "Escaneo Bluetooth LE básico"),
        ("btmapa",           "Mapa radar BLE en tiempo real"),
    ],
    "RF / SDR": [
        ("spectrum / sa",    "Analizador de espectro en tiempo real"),
        ("rfscan",           "Escaneo de frecuencias RF"),
        ("rfmenu",           "Menú interactivo de opciones RF"),
        ("rfbarrido",        "Barrido de espectro por rango"),
        ("rfbandas",         "Escanear todas las bandas conocidas"),
        ("rfstats",          "Estadísticas de sesión RF"),
        ("rfstatus",         "Estado del hardware SDR"),
        ("radio",            "Escuchar y demodular señal"),
        ("rfgrabar",         "Grabar señal IQ a archivo"),
        ("rfplay",           "Reproducir grabación IQ"),
        ("adsb",             "Monitor ADS-B — aeronaves"),
        ("noaa",             "NOAA APT — imágenes satélite 137 MHz"),
    ],
    "ATAQUES": [
        ("audit",            "Auditoría de credenciales"),
        ("vulnscan",         "Análisis de vulnerabilidades"),
        ("sqlcheck",         "Auditoría de inyección SQL"),
        ("wifi",             "Auditoría Wi-Fi"),
        ("eviltwin",         "Portal cautivo wireless"),
        ("phishing",         "Clonar página de phishing"),
        ("ducky",            "Payload USB Ducky"),
    ],
    "FORENSE": [
        ("geofoto",          "Extraer GPS de fotografías EXIF"),
        ("locate / locate -p","Localización por IP / GPS activo"),
        ("view",             "Leer archivo forense"),
        ("mobile",           "Triaje básico de móvil"),
        ("mobile-deep",      "Análisis profundo de móvil"),
        ("stealth",          "Verificar identidad digital"),
        ("panic",            "Borrado de emergencia"),
    ],
    "PROYECTOS": [
        ("proyecto nuevo",   "Crear workspace de operación"),
        ("proyecto cargar",  "Cargar proyecto existente"),
        ("proyecto lista",   "Listar todos los proyectos"),
        ("proyecto estado",  "Resumen del proyecto activo"),
        ("reporte",          "Generar reporte completo"),
    ],
    "INTELIGENCIA": [
        ("osint",            "Motor de reconocimiento pasivo"),
        ("cve",              "Búsqueda en base CVE / NVD"),
        ("jobs",             "Ver cola de tareas asíncronas"),
        ("plugins",          "Listar plugins cargados"),
        ("plugins reload",   "Recargar plugins en caliente"),
    ],
}


# ══════════════════════════════════════════════════════════════════════
# UTILIDADES INTERNAS
# ══════════════════════════════════════════════════════════════════════

_ip_cache: str | None = None


def _limpiar() -> None:
    if os.name == "nt":
        subprocess.run(["cls"], shell=True, check=False)
    else:
        subprocess.run(["clear"], check=False)


def _get_ip() -> str:
    global _ip_cache
    if _ip_cache:
        return _ip_cache
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        _ip_cache = s.getsockname()[0]
        s.close()
        return _ip_cache
    except Exception:
        return "—"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _plataforma_str() -> str:
    if _PLATFORM_OK:
        try:
            info = _detect_platform()
            return f"{info.kind.name}  {info.machine}"
        except Exception:
            pass
    import platform
    return f"{platform.machine()}  {sys.platform}"


# ══════════════════════════════════════════════════════════════════════
# COMPONENTES VISUALES
# ══════════════════════════════════════════════════════════════════════

def _panel_hero(nombre: str, version: str, iface: str) -> Panel:
    arte = Text(ANUBIS_ART, style="bold green")

    inf = Table.grid(padding=(0, 2))
    inf.add_column(style="dim green", justify="right", min_width=14)
    inf.add_column(style="white")

    def row(k: str, v: str) -> None:
        inf.add_row(k, v)

    row("SISTEMA",
        f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    row("OPERADOR",   f"[bold green]{nombre}[/bold green]")
    row("ESTADO",     "[bold green]● EN LÍNEA[/bold green]")
    row("INTERFAZ",   f"[cyan]{iface}[/cyan]")
    row("IP LOCAL",   f"[cyan]{_get_ip()}[/cyan]")
    row("PLATAFORMA", f"[dim]{_plataforma_str()}[/dim]")
    row("ARRANQUE",   f"[dim]{datetime.now().strftime('%d/%m/%Y  %H:%M:%S')}[/dim]")
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


def _resumen_modulos(estados: dict[str, bool] | None) -> Text:
    t = Text("  ")
    if not estados:
        t.append("Módulos cargados", style="dim green")
        return t

    ok = sum(1 for v in estados.values() if v)
    total = len(estados)

    for grupo, nombres in _GRUPOS_MODULOS.items():
        activos = [n for n in nombres if estados.get(n, False)]
        degradados = [n for n in nombres if n in estados and not estados[n]]
        if not activos and not degradados:
            continue
        if degradados:
            t.append(f"○ {grupo} ", style="yellow")
        else:
            t.append(f"● {grupo} ", style="green")

    t.append(f" [{ok}/{total}]", style="dim green")
    return t


def _linea_modulo_live(idx: int, total: int, nombre: str) -> Text:
    pct = int((idx / total) * 100)
    bar_w = 20
    filled = int(bar_w * idx / total)
    bar = "█" * filled + "░" * (bar_w - filled)
    t = Text()
    t.append("  ")
    t.append(f"[{bar}]", style="green")
    t.append(f" {pct:>3}%  ", style="bold green")
    t.append(f"{nombre}", style="dim green")
    return t


# ══════════════════════════════════════════════════════════════════════
# BOOTLOADER — pantalla única que se actualiza con Rich Live
# ══════════════════════════════════════════════════════════════════════

def mostrar_bootloader(
    console: Console,
    nombre: str,
    version: str,
    iface: str,
    estados_modulos: dict[str, bool] | None = None,
) -> None:
    _limpiar()
    hero = _panel_hero(nombre, version, iface)

    modulos = list(estados_modulos.keys()) if estados_modulos else [m for m, _ in MODULOS_BOOT]
    total   = len(modulos)

    # ── Fase 1: Barra de carga animada ───────────────────────────────
    with Live(console=console, refresh_per_second=30, screen=False) as live:
        for i, nombre_mod in enumerate(modulos, 1):
            pct    = int((i / total) * 100)
            bar_w  = 26
            filled = int(bar_w * i / total)
            bar    = "█" * filled + "░" * (bar_w - filled)
            estado = "[bold green]OK[/bold green]" if (
                estados_modulos is None or estados_modulos.get(nombre_mod, True)
            ) else "[yellow]—[/yellow]"

            contenido = (
                f"\n  [green][{bar}][/green]  "
                f"[bold green]{pct:>3}%[/bold green]  "
                f"[dim green]{nombre_mod:<30}[/dim green]  {estado}\n"
            )
            live.update(Panel(
                contenido,
                title="[bold green]◈  A N U B I S   O S  ◈[/bold green]",
                subtitle=f"[dim green]Verificando módulos — {i}/{total}[/dim green]",
                border_style="green",
                box=box.ROUNDED,
                padding=(0, 2),
            ))
            time.sleep(0.03)

    # ── Fase 2: Hero panel ────────────────────────────────────────────
    console.print(hero)

    # ── Fase 3: Resumen de módulos (sin Layout — evita espacios vacíos)
    ok_count   = (
        sum(1 for v in estados_modulos.values() if v)
        if estados_modulos else total
    )
    degradados = (
        [k for k, v in estados_modulos.items() if not v]
        if estados_modulos else []
    )

    # Línea de grupos con colores
    grupos_str = "  "
    for grupo, nombres in _GRUPOS_MODULOS.items():
        tiene_activos   = any(estados_modulos.get(n, False) for n in nombres) if estados_modulos else True
        tiene_degradado = any(n in estados_modulos and not estados_modulos[n] for n in nombres) if estados_modulos else False
        if not any(n in (estados_modulos or {}) for n in nombres):
            continue
        if tiene_degradado and not tiene_activos:
            grupos_str += f"[red]✖ {grupo}[/red]  "
        elif tiene_degradado:
            grupos_str += f"[yellow]◐ {grupo}[/yellow]  "
        else:
            grupos_str += f"[green]● {grupo}[/green]  "

    resumen_content = grupos_str
    if degradados:
        degrad_str = "  ".join(f"[dim]{d}[/dim]" for d in degradados[:6])
        extra      = f"  [dim]+{len(degradados) - 6} más[/dim]" if len(degradados) > 6 else ""
        resumen_content += f"\n\n  [yellow]○ Sin cargar:[/yellow]  {degrad_str}{extra}"

    console.print(Panel(
        resumen_content,
        title=f"[dim green]{ok_count}/{total} módulos activos[/dim green]",
        border_style="dim green",
        box=box.ROUNDED,
        padding=(0, 1),
    ))

    # ── Cierre: ready line ────────────────────────────────────────────
    console.print(Rule(style="dim green"))
    console.print(
        Align.center(
            "[dim]Escribe [bold white]help[/bold white] para ver comandos  "
            "·  [bold white]exit[/bold white] para salir[/dim]"
        )
    )
    console.print(Rule(style="dim green"))
    console.print()


# ══════════════════════════════════════════════════════════════════════
# BANNER COMPACTO — comando clear / cls
# ══════════════════════════════════════════════════════════════════════

def mostrar_banner(
    console: Console,
    nombre: str,
    version: str,
    iface: str,
    proyecto: str | None = None,
) -> None:
    _limpiar()

    arte = Text(ANUBIS_ART, style="bold green")

    inf = Table.grid(padding=(0, 1))
    inf.add_column(style="dim green", justify="right", min_width=12)
    inf.add_column(style="white")

    def row(k: str, v: str) -> None:
        inf.add_row(k, v)

    row("SISTEMA",   f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    row("ESTADO",    "[bold green]● EN LÍNEA[/bold green]")
    row("INTERFAZ",  f"[cyan]{iface}[/cyan]  [dim]{_get_ip()}[/dim]")
    row("HORA",      f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]")
    if proyecto:
        row("PROYECTO", f"[bold green]{proyecto}[/bold green]")
    row("",          "")
    row("AVISO",     "[bold red]AUTHORIZED USE ONLY[/bold red]")

    console.print(
        Panel(
            Columns(
                [Align(arte, vertical="middle"), Align(inf, vertical="middle")],
                equal=False,
                expand=True,
            ),
            title="[bold green]◈  ANUBIS OS  ◈[/bold green]",
            border_style="green",
            box=box.HEAVY_EDGE,
            padding=(0, 2),
        )
    )
    console.print(Rule(style="dim green"))
    console.print()


# ══════════════════════════════════════════════════════════════════════
# MENÚ DE AYUDA
# ══════════════════════════════════════════════════════════════════════

def mostrar_ayuda(
    console: Console,
    version: str,
    comandos: dict[str, list[tuple[str, str]]] | None = None,
) -> None:
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
        tb.add_column(f"▸  {categoria}", style="cyan", min_width=22, no_wrap=True)
        tb.add_column("Descripción", style="dim white")
        for cmd, desc in cmds:
            tb.add_row(f"[bold white]{cmd}[/bold white]", desc)
        cols.append(Panel(tb, border_style="dim green", box=box.ROUNDED, padding=(0, 1)))

    pares = [cols[i: i + 2] for i in range(0, len(cols), 2)]
    for par in pares:
        console.print(Columns(par, equal=True, expand=True))

    console.print()
    console.print(Rule(style="dim green"))
    console.print(
        Align.center(
            "[dim]Todos los módulos respetan [bold white]Ctrl+C[/bold white] "
            "para cancelar  ·  [bold white]exit[/bold white] para cerrar[/dim]"
        )
    )
    console.print(Rule(style="dim green"))
    console.print()


# ══════════════════════════════════════════════════════════════════════
# PRUEBA STANDALONE
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    _con = Console()
    estados_demo = {
        "RadarSentinel": True,  "TacticalSniffer": True,
        "RFModule": True,       "SpectrumAnalyzer": True,
        "ExifAnalyzer": True,   "ForensicReader": True,
        "StealthModule": True,  "MobileSentinel": True,
        "OSINTEngine": True,    "CVEMatcher": True,
        "GestorProyectos": True,"MotorReportes": True,
        "HydraModule": True,    "GestorPlugins": True,
        "Recovery": False,
    }
    try:
        mostrar_bootloader(_con, "Sentinel", "2.3", "wlan0mon", estados_demo)
        input("AnubisOS@Sentinel~# ")
        mostrar_banner(_con, "Sentinel", "2.3", "wlan0mon", proyecto="Operacion-Alpha")
        input("AnubisOS@Sentinel~# ")
        mostrar_ayuda(_con, "2.3")
    except KeyboardInterrupt:
        _con.print("\n[yellow][!] Cancelado.[/yellow]")
