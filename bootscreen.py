import time
import os
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns
from rich.text import Text
from rich.align import Align
from rich.rule import Rule
from rich import box
from rich.live import Live
from rich.progress import Progress, BarColumn, TextColumn, SpinnerColumn

console = Console()

ANUBIS_ART = r"""
   ╔═══════════╗
   ║  /\   /\  ║
   ║ (  \_/  ) ║
   ║  \     /  ║
   ║  /\___/\  ║
   ║ / / | \ \ ║
   ╚═══════════╝"""

MODULOS = [
    ("HydraModule",     "Fuerza bruta / auditoría"),
    ("TacticalSniffer", "Captura de tráfico"),
    ("RadarSentinel",   "Intercepción Wi-Fi"),
    ("ExifAnalyzer",    "Metadatos EXIF"),
    ("BluetoothModule", "Escaneo Bluetooth"),
    ("ForensicReader",  "Lectura forense"),
    ("GeoPrecise",      "Triangulación GPS"),
    ("StealthModule",   "Huella digital"),
]


def limpiar_pantalla():
    os.system("cls" if os.name == "nt" else "clear")


def mostrar_bootloader(nombre: str = "Sentinel", version: str = "2.1", iface: str = "wlan0mon"):
    """
    Pantalla de arranque animada con:
    - Arte ASCII de Anubis
    - Tabla de info del sistema
    - Carga progresiva de módulos
    """
    limpiar_pantalla()

    # --- Cabecera: Arte + Info del sistema ---
    arte = Text(ANUBIS_ART, style="bold green")

    info = Table.grid(padding=(0, 2))
    info.add_column(style="dim cyan", justify="right")
    info.add_column(style="white")

    info.add_row(
        "SISTEMA",    f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    info.add_row("OPERADOR",   f"[bold green]{nombre}[/bold green]")
    info.add_row("ESTADO",     "[bold green]● ACTIVO[/bold green]")
    info.add_row("IFACE",      f"[cyan]{iface}[/cyan]")
    info.add_row(
        "PLATAFORMA", f"[dim]{os.name.upper()} / {os.uname().sysname if hasattr(os, 'uname') else 'WIN32'}[/dim]")
    info.add_row("", "")
    info.add_row("AVISO",      "[bold red]⚠  AUTHORIZED USE ONLY[/bold red]")

    header = Columns([
        Align(arte, vertical="middle"),
        Align(info, vertical="middle"),
    ], equal=False, expand=True)

    console.print(Panel(
        header,
        title="[bold green]ANUBIS OS[/bold green]",
        subtitle="[dim]SISTEMA OPERATIVO TÁCTICO[/dim]",
        border_style="green",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))

    # --- Carga de módulos con barra de progreso ---
    console.print()

    with Progress(
        SpinnerColumn(spinner_name="dots", style="green"),
        TextColumn("[cyan]{task.description:<30}[/cyan]"),
        BarColumn(bar_width=30, style="green", complete_style="bold green"),
        TextColumn("[bold green]{task.percentage:>3.0f}%[/bold green]"),
        console=console,
        transient=False,
    ) as progress:

        tarea = progress.add_task("Iniciando núcleo...", total=len(MODULOS))

        for nombre_mod, desc in MODULOS:
            progress.update(
                tarea, description=f"Cargando [bold]{nombre_mod}[/bold]...")
            time.sleep(0.18)
            progress.advance(tarea)

        progress.update(
            tarea, description="[bold green]Todos los módulos en línea[/bold green]")
        time.sleep(0.3)

    # --- Tabla de módulos cargados ---
    console.print()
    tabla_mods = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold cyan",
        show_edge=False,
        expand=True,
    )
    tabla_mods.add_column("Módulo",      style="green",  min_width=20)
    tabla_mods.add_column("Función",     style="white",  min_width=25)
    tabla_mods.add_column("Estado",      justify="center")

    for nombre_mod, desc in MODULOS:
        tabla_mods.add_row(
            nombre_mod, desc, "[bold green]● LISTO[/bold green]")

    console.print(Panel(
        tabla_mods,
        title="[bold]MÓDULOS DEL SISTEMA[/bold]",
        border_style="dim green",
        padding=(0, 1),
    ))

    console.print()
    console.print(Rule(style="dim green"))
    console.print(
        Align.center(
            "[dim]Escribe [bold white]help[/bold white] para ver los comandos disponibles[/dim]"
        )
    )
    console.print(Rule(style="dim green"))
    console.print()


def mostrar_banner(nombre: str = "Sentinel", version: str = "2.1", iface: str = "wlan0mon"):
    """
    Banner compacto que se muestra al hacer 'clear' durante la sesión.
    Más ligero que el bootloader completo.
    """
    limpiar_pantalla()

    grid = Table.grid(padding=(0, 4), expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=2)

    izquierda = Text(ANUBIS_ART, style="bold green")

    derecha = Table.grid(padding=(0, 1))
    derecha.add_column(style="dim cyan", justify="right", min_width=12)
    derecha.add_column(style="white")
    derecha.add_row(
        "SISTEMA",   f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    derecha.add_row("OPERADOR",  f"[bold green]{nombre}[/bold green]")
    derecha.add_row("ESTADO",    "[bold green]● ACTIVO[/bold green]")
    derecha.add_row("IFACE",     f"[cyan]{iface}[/cyan]")
    derecha.add_row("AVISO",     "[red]AUTHORIZED USE ONLY[/red]")

    grid.add_row(izquierda, derecha)

    console.print(Panel(
        grid,
        border_style="green",
        box=box.HEAVY_EDGE,
        padding=(0, 1),
    ))
    console.print(Rule(style="dim green"))
    console.print()


# --- Prueba directa ---
if __name__ == "__main__":
    mostrar_bootloader(nombre="Sentinel", version="2.1", iface="wlan0mon")
    input("AnubisOS@Sentinel:~# ")
    mostrar_banner(nombre="Sentinel", version="2.1", iface="wlan0mon")
