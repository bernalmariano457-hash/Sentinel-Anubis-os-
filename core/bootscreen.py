from __future__ import annotations

import asyncio
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

try:
    import fcntl
    _FCNTL_DISPONIBLE = True
except ImportError:
    _FCNTL_DISPONIBLE = False

try:
    from core.platform import detect as _detect_platform
    _PLATFORM_OK = True
except ImportError:
    _PLATFORM_OK = False


_ANCHO_MINIMO_COMPLETO: int = 80
_ANCHO_ARTE: int = 29
_ANCHO_BARRA_NORMAL: int = 26
_ANCHO_BARRA_COMPACTA: int = 14

_SIOCGIFADDR: int = 0x8915
_RUTA_SYS_NET: str = "/sys/class/net"
_RUTA_THERMAL: str = "/sys/class/thermal/thermal_zone0/temp"
_RUTA_PROC_STAT: str = "/proc/stat"
_RUTA_PROC_MEMINFO: str = "/proc/meminfo"

_UMBRAL_PCT_ALERTA: float = 70.0
_UMBRAL_PCT_CRITICO: float = 90.0
_UMBRAL_TEMP_ALERTA: float = 65.0
_UMBRAL_TEMP_CRITICO: float = 80.0

_SIMBOLOS_ESTADO: Dict[str, str] = {"activo": "●", "degradado": "◐", "caido": "✖"}
_ESTILOS_ESTADO: Dict[str, str] = {"activo": "green", "degradado": "yellow", "caido": "red"}

_GUTTER_COLUMNAS_AYUDA: int = 2
_SOBRECARGA_PANEL_AYUDA: int = 8
_ANCHO_MIN_COMANDO: int = 20
_ANCHO_MIN_DESCRIPCION: int = 24


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

ESTILOS_LOG: Dict[str, Tuple[str, str]] = {
    "INFO":    ("cyan",         "ℹ"),
    "SUCCESS": ("green",        "✔"),
    "WARNING": ("yellow",       "⚠"),
    "ERROR":   ("bold red",     "✖"),
    "AUDIT":   ("bold magenta", "⚑"),
    "DEBUG":   ("dim",          "·"),
}

MODULOS_BOOT: List[Tuple[str, str]] = [
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

_GRUPOS_MODULOS: Dict[str, List[str]] = {
    "Red":       ["RadarSentinel", "TacticalSniffer", "BluetoothModule"],
    "RF":        ["RFModule", "SpectrumAnalyzer"],
    "Forense":   ["ExifAnalyzer", "ForensicReader", "MobileSentinel", "StealthModule"],
    "Acceso":    ["HydraModule"],
    "OSINT":     ["OSINTEngine", "CVEMatcher", "GeoPrecise"],
    "Proyectos": ["GestorProyectos", "MotorReportes", "ColaTareas", "GestorPlugins"],
    "Seguridad": ["SecurityModule", "Recovery"],
}


COMANDOS_HELP: Dict[str, List[Tuple[str, str]]] = {
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
        ("locate / locate -p", "Localización por IP / GPS activo"),
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

_ip_cache: Optional[str] = None


@dataclass
class SnapshotSistema:
    cpu_pct: float
    ram_pct: float
    ram_usada_gb: float
    ram_total_gb: float
    disco_pct: float
    disco_usado_gb: float
    disco_total_gb: float
    temperatura_c: Optional[float]


class MonitorTelemetria:

    def __init__(self) -> None:
        self._cpu_previo: Optional[Tuple[int, int]] = None

    def _jiffies_cpu(self) -> Optional[Tuple[int, int]]:
        try:
            with open(_RUTA_PROC_STAT, "r", encoding="utf-8") as manejador:
                primera_linea = manejador.readline()
        except OSError:
            return None
        partes = primera_linea.split()
        if len(partes) < 5 or partes[0] != "cpu":
            return None
        try:
            valores = [int(v) for v in partes[1:]]
        except ValueError:
            return None
        ocioso = valores[3] + (valores[4] if len(valores) > 4 else 0)
        total = sum(valores)
        return ocioso, total

    def cpu_pct(self) -> float:
        actual = self._jiffies_cpu()
        previo = self._cpu_previo
        self._cpu_previo = actual
        if actual is None or previo is None:
            return 0.0
        delta_total = actual[1] - previo[1]
        if delta_total <= 0:
            return 0.0
        delta_ocioso = actual[0] - previo[0]
        uso = 1.0 - (delta_ocioso / delta_total)
        return max(0.0, min(100.0, uso * 100.0))

    def memoria(self) -> Tuple[float, float, float]:
        try:
            with open(_RUTA_PROC_MEMINFO, "r", encoding="utf-8") as manejador:
                lineas = manejador.readlines()
        except OSError:
            return 0.0, 0.0, 0.0
        valores: Dict[str, int] = {}
        for linea in lineas:
            clave, separador, resto = linea.partition(":")
            if not separador:
                continue
            partes_resto = resto.strip().split(" ")
            if partes_resto and partes_resto[0].isdigit():
                valores[clave] = int(partes_resto[0])
        total_kb = valores.get("MemTotal", 0)
        if total_kb <= 0:
            return 0.0, 0.0, 0.0
        disponible_kb = valores.get("MemAvailable", valores.get("MemFree", 0))
        usada_kb = max(0, total_kb - disponible_kb)
        pct = usada_kb / total_kb * 100.0
        return pct, usada_kb / (1024 ** 2), total_kb / (1024 ** 2)

    def temperatura_c(self) -> Optional[float]:
        try:
            with open(_RUTA_THERMAL, "r", encoding="utf-8") as manejador:
                crudo = manejador.read().strip()
            return int(crudo) / 1000.0
        except (OSError, ValueError):
            return None

    def disco(self, ruta: Union[str, "os.PathLike[str]"] = "/") -> Tuple[float, float, float]:
        try:
            uso = shutil.disk_usage(ruta)
        except OSError:
            return 0.0, 0.0, 0.0
        if uso.total <= 0:
            return 0.0, 0.0, 0.0
        pct = uso.used / uso.total * 100.0
        return pct, uso.used / (1024 ** 3), uso.total / (1024 ** 3)

    def snapshot(self) -> SnapshotSistema:
        cpu = self.cpu_pct()
        ram_pct, ram_usada, ram_total = self.memoria()
        disco_pct, disco_usado, disco_total = self.disco()
        temp = self.temperatura_c()
        return SnapshotSistema(
            cpu_pct=cpu,
            ram_pct=ram_pct,
            ram_usada_gb=ram_usada,
            ram_total_gb=ram_total,
            disco_pct=disco_pct,
            disco_usado_gb=disco_usado,
            disco_total_gb=disco_total,
            temperatura_c=temp,
        )


def _formatear_gb(valor: Union[int, float]) -> str:
    return f"{float(valor):.1f}G"


def _color_pct(valor: float) -> str:
    if valor >= _UMBRAL_PCT_CRITICO:
        return "bold red"
    if valor >= _UMBRAL_PCT_ALERTA:
        return "yellow"
    return "green"


def _color_temp(valor: float) -> str:
    if valor >= _UMBRAL_TEMP_CRITICO:
        return "bold red"
    if valor >= _UMBRAL_TEMP_ALERTA:
        return "yellow"
    return "green"


def _limpiar() -> None:
    if os.name == "nt":
        subprocess.run(["cls"], shell=True, check=False)
    else:
        subprocess.run(["clear"], check=False)


def _interfaces_activas() -> List[str]:
    try:
        nombres = sorted(os.listdir(_RUTA_SYS_NET))
    except OSError:
        return []
    candidatas: List[Tuple[str, str]] = []
    for nombre in nombres:
        if nombre == "lo":
            continue
        ruta_operstate = os.path.join(_RUTA_SYS_NET, nombre, "operstate")
        try:
            with open(ruta_operstate, "r", encoding="utf-8") as manejador:
                estado = manejador.read().strip()
        except OSError:
            continue
        candidatas.append((nombre, estado))
    activas = [nombre for nombre, estado in candidatas if estado == "up"]
    if activas:
        return activas
    return [nombre for nombre, estado in candidatas if estado == "unknown"]


def _ip_de_interfaz(nombre: str) -> Optional[str]:
    if not _FCNTL_DISPONIBLE:
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            paquete = struct.pack("256s", nombre[:15].encode("utf-8"))
            crudo = fcntl.ioctl(sock.fileno(), _SIOCGIFADDR, paquete)
        return socket.inet_ntoa(crudo[20:24])
    except OSError:
        return None


def _get_ip() -> str:
    global _ip_cache
    if _ip_cache:
        return _ip_cache
    for nombre in _interfaces_activas():
        ip = _ip_de_interfaz(nombre)
        if ip:
            _ip_cache = ip
            return ip
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
    return f"{platform.machine()}  {sys.platform}"


def _pantalla_compacta(console: Console) -> bool:
    return console.size.width < _ANCHO_MINIMO_COMPLETO


def _titulo_hud(compacto: bool) -> str:
    if compacto:
        return "[bold green]◈ ANUBIS OS ◈[/bold green]"
    return "[bold green]◈  A N U B I S   O S  ◈[/bold green]"


def _tabla_base(compacto: bool) -> Table:
    tabla = Table.grid(padding=(0, 1) if compacto else (0, 2))
    tabla.add_column(style="dim green", justify="right", min_width=10 if compacto else 14)
    tabla.add_column(style="white")
    return tabla


def _estado_grupos(estados: Optional[Dict[str, bool]]) -> List[Tuple[str, str]]:
    resultado: List[Tuple[str, str]] = []
    for grupo, nombres in _GRUPOS_MODULOS.items():
        if estados is None:
            resultado.append((grupo, "activo"))
            continue
        activos = [n for n in nombres if estados.get(n, False)]
        degradados = [n for n in nombres if n in estados and not estados[n]]
        if not activos and not degradados:
            continue
        if degradados and not activos:
            resultado.append((grupo, "caido"))
        elif degradados:
            resultado.append((grupo, "degradado"))
        else:
            resultado.append((grupo, "activo"))
    return resultado


def _resumen_modulos(estados: Optional[Dict[str, bool]]) -> Text:
    texto = Text("  ")
    if not estados:
        texto.append("Módulos cargados", style="dim green")
        return texto
    ok = sum(1 for v in estados.values() if v)
    total = len(estados)
    for grupo, estado in _estado_grupos(estados):
        simbolo = _SIMBOLOS_ESTADO[estado]
        estilo = _ESTILOS_ESTADO[estado]
        texto.append(f"{simbolo} {grupo} ", style=estilo)
    texto.append(f" [{ok}/{total}]", style="dim green")
    return texto


def _linea_barra(idx: int, total: int, ancho: int) -> str:
    proporcion = idx / total if total else 1.0
    llenos = int(ancho * proporcion)
    barra = "█" * llenos + "░" * (ancho - llenos)
    pct = int(proporcion * 100)
    return (
        f"[dim green][[/dim green][bold green]{barra}[/bold green]"
        f"[dim green]][/dim green] [bold green]{pct:>3}%[/bold green]"
    )


def _linea_telemetria(snap: SnapshotSistema, compacto: bool) -> str:
    color_cpu = _color_pct(snap.cpu_pct)
    color_ram = _color_pct(snap.ram_pct)
    partes = [f"[dim green]CPU[/dim green] [{color_cpu}]{snap.cpu_pct:>4.0f}%[/{color_cpu}]"]

    if compacto:
        partes.append(f"[dim green]RAM[/dim green] [{color_ram}]{snap.ram_pct:>4.0f}%[/{color_ram}]")
    else:
        ram_detalle = f"{_formatear_gb(snap.ram_usada_gb)}/{_formatear_gb(snap.ram_total_gb)}"
        partes.append(
            f"[dim green]RAM[/dim green] [{color_ram}]{snap.ram_pct:>4.0f}%[/{color_ram}] "
            f"[dim]({ram_detalle})[/dim]"
        )

    if snap.temperatura_c is not None:
        etiqueta_temp = "TMP" if compacto else "TEMP"
        color_temp = _color_temp(snap.temperatura_c)
        partes.append(
            f"[dim green]{etiqueta_temp}[/dim green] "
            f"[{color_temp}]{snap.temperatura_c:>4.0f}C[/{color_temp}]"
        )

    if not compacto:
        color_disco = _color_pct(snap.disco_pct)
        disco_detalle = f"{_formatear_gb(snap.disco_usado_gb)}/{_formatear_gb(snap.disco_total_gb)}"
        partes.append(
            f"[dim green]DISK[/dim green] [{color_disco}]{snap.disco_pct:>4.0f}%[/{color_disco}] "
            f"[dim]({disco_detalle})[/dim]"
        )

    return "   ".join(partes)


def _columnas_ayuda(ancho_consola: int) -> int:
    ancho_dos = max(1, (ancho_consola - _GUTTER_COLUMNAS_AYUDA) // 2 - 1)
    max_desc_dos = ancho_dos - _SOBRECARGA_PANEL_AYUDA - _ANCHO_MIN_COMANDO
    return 2 if max_desc_dos >= _ANCHO_MIN_DESCRIPCION else 1


def _dimensiones_panel_ayuda(ancho_consola: int, columnas: int) -> Tuple[int, int]:
    ancho_panel = max(34, (ancho_consola - _GUTTER_COLUMNAS_AYUDA * (columnas - 1)) // columnas - 1)
    max_desc = max(_ANCHO_MIN_DESCRIPCION, ancho_panel - _SOBRECARGA_PANEL_AYUDA - _ANCHO_MIN_COMANDO)
    return ancho_panel, max_desc


def _panel_hero(nombre: str, version: str, iface: str, console: Console) -> Panel:
    compacto = _pantalla_compacta(console)
    tabla = _tabla_base(compacto)
    tabla.add_row("SISTEMA", f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    tabla.add_row("OPERADOR", f"[bold green]{nombre}[/bold green]")
    tabla.add_row("ESTADO", "[bold green]● EN LÍNEA[/bold green]")
    tabla.add_row("INTERFAZ", f"[cyan]{iface}[/cyan]")
    tabla.add_row("IP LOCAL", f"[cyan]{_get_ip()}[/cyan]")
    if not compacto:
        tabla.add_row("PLATAFORMA", f"[dim]{_plataforma_str()}[/dim]")
        tabla.add_row("ARRANQUE", f"[dim]{datetime.now().strftime('%d/%m/%Y  %H:%M:%S')}[/dim]")
    tabla.add_row("", "")
    if compacto:
        tabla.add_row("AVISO", "[bold red]⚠ AUTHORIZED USE ONLY[/bold red]")
    else:
        tabla.add_row("AVISO", "[bold red]⚠  AUTHORIZED USE ONLY — ACCESO RESTRINGIDO[/bold red]")

    layout = Layout()
    if compacto:
        layout.update(Align.center(tabla, vertical="middle"))
        alto = 9
        caja = box.SQUARE
        relleno: Tuple[int, int] = (0, 1)
    else:
        layout.split_row(
            Layout(name="arte", size=_ANCHO_ARTE),
            Layout(name="info", ratio=1),
        )
        layout["arte"].update(Align.center(Text(ANUBIS_ART, style="bold green"), vertical="middle"))
        layout["info"].update(Align.left(tabla, vertical="middle"))
        alto = 14
        caja = box.DOUBLE_EDGE
        relleno = (1, 3)

    return Panel(
        layout,
        title=_titulo_hud(compacto),
        subtitle=None if compacto else "[dim green]APEX SENTINEL — SISTEMA OPERATIVO TÁCTICO[/dim green]",
        border_style="green",
        box=caja,
        padding=relleno,
        height=alto,
    )


def _cuadro_boot(
    idx: int,
    total: int,
    nombre_mod: str,
    activo: bool,
    snap: SnapshotSistema,
    compacto: bool,
) -> Panel:
    ancho_barra = _ANCHO_BARRA_COMPACTA if compacto else _ANCHO_BARRA_NORMAL
    barra = _linea_barra(idx, total, ancho_barra)
    telemetria = _linea_telemetria(snap, compacto)
    estado_txt = "[bold green]OK[/bold green]" if activo else "[yellow]—[/yellow]"
    nombre_fmt = nombre_mod if compacto else f"{nombre_mod:<24}"

    contenido = (
        f"\n  {barra}\n\n"
        f"  [dim green]{nombre_fmt}[/dim green]  {estado_txt}\n\n"
        f"  {telemetria}\n"
    )
    return Panel(
        contenido,
        title=_titulo_hud(compacto),
        subtitle=f"[dim green]Verificando módulos — {idx}/{total}[/dim green]",
        border_style="green",
        box=box.ROUNDED,
        padding=(0, 2) if not compacto else (0, 1),
    )


def _panel_resumen_modulos(
    estados_modulos: Optional[Dict[str, bool]],
    ok_count: int,
    total: int,
    compacto: bool,
) -> Panel:
    partes: List[str] = []
    for grupo, estado in _estado_grupos(estados_modulos):
        simbolo = _SIMBOLOS_ESTADO[estado]
        color = _ESTILOS_ESTADO[estado]
        partes.append(f"[{color}]{simbolo} {grupo}[/{color}]")
    contenido = "  ".join(partes)

    degradados = [nombre for nombre, activo in (estados_modulos or {}).items() if not activo]
    if degradados:
        limite = 4 if compacto else 6
        listado = "  ".join(f"[dim]{d}[/dim]" for d in degradados[:limite])
        restante = len(degradados) - limite
        extra = f"  [dim]+{restante} más[/dim]" if restante > 0 else ""
        contenido += f"\n\n  [yellow]○ Sin cargar:[/yellow]  {listado}{extra}"

    return Panel(
        contenido,
        title=f"[dim green]{ok_count}/{total} módulos activos[/dim green]",
        border_style="dim green",
        box=box.ROUNDED,
        padding=(0, 1),
    )


async def _ejecutar_boot(
    console: Console,
    modulos: List[str],
    estados_modulos: Optional[Dict[str, bool]],
    compacto: bool,
) -> None:
    total = len(modulos)
    monitor = MonitorTelemetria()
    with Live(console=console, refresh_per_second=24, screen=False) as live:
        for idx, nombre_mod in enumerate(modulos, 1):
            snap = await asyncio.to_thread(monitor.snapshot)
            activo = estados_modulos is None or estados_modulos.get(nombre_mod, True)
            live.update(_cuadro_boot(idx, total, nombre_mod, activo, snap, compacto))
            await asyncio.sleep(0.035)


def mostrar_bootloader(
    console: Console,
    nombre: str,
    version: str,
    iface: str,
    estados_modulos: Optional[Dict[str, bool]] = None,
) -> None:
    _limpiar()
    compacto = _pantalla_compacta(console)
    modulos = list(estados_modulos.keys()) if estados_modulos else [m for m, _ in MODULOS_BOOT]
    total = len(modulos)

    asyncio.run(_ejecutar_boot(console, modulos, estados_modulos, compacto))

    console.print()
    console.print(_panel_hero(nombre, version, iface, console))

    ok_count = sum(1 for v in estados_modulos.values() if v) if estados_modulos else total
    console.print(_panel_resumen_modulos(estados_modulos, ok_count, total, compacto))

    console.print(Rule(style="dim green"))
    console.print(
        Align.center(
            "[dim]Escribe [bold white]help[/bold white] para ver comandos  "
            "·  [bold white]exit[/bold white] para salir[/dim]"
        )
    )
    console.print(Rule(style="dim green"))
    console.print()


def mostrar_banner(
    console: Console,
    nombre: str,
    version: str,
    iface: str,
    proyecto: Optional[str] = None,
) -> None:
    _limpiar()
    compacto = _pantalla_compacta(console)

    tabla = _tabla_base(compacto)
    tabla.add_row("SISTEMA", f"[bold white]APEX SENTINEL[/bold white] [dim]v{version}[/dim]")
    tabla.add_row("ESTADO", "[bold green]● EN LÍNEA[/bold green]")
    if compacto:
        tabla.add_row("INTERFAZ", f"[cyan]{iface}[/cyan]")
    else:
        tabla.add_row("INTERFAZ", f"[cyan]{iface}[/cyan]  [dim]{_get_ip()}[/dim]")
    tabla.add_row("HORA", f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]")
    if proyecto:
        tabla.add_row("PROYECTO", f"[bold green]{proyecto}[/bold green]")
    tabla.add_row("", "")
    tabla.add_row("AVISO", "[bold red]AUTHORIZED USE ONLY[/bold red]")

    layout = Layout()
    if compacto:
        layout.update(Align.center(tabla, vertical="middle"))
        alto = 9 if proyecto else 8
        caja = box.SQUARE
        relleno: Tuple[int, int] = (0, 1)
    else:
        layout.split_row(
            Layout(name="arte", size=_ANCHO_ARTE),
            Layout(name="info", ratio=1),
        )
        layout["arte"].update(Align.center(Text(ANUBIS_ART, style="bold green"), vertical="middle"))
        layout["info"].update(Align.left(tabla, vertical="middle"))
        alto = 12
        caja = box.HEAVY_EDGE
        relleno = (0, 2)

    console.print(
        Panel(
            layout,
            title=_titulo_hud(compacto),
            border_style="green",
            box=caja,
            padding=relleno,
            height=alto,
        )
    )
    console.print(Rule(style="dim green"))
    console.print()


def mostrar_ayuda(
    console: Console,
    version: str,
    comandos: Optional[Dict[str, List[Tuple[str, str]]]] = None,
) -> None:
    if comandos is None:
        comandos = COMANDOS_HELP
    compacto = _pantalla_compacta(console)

    console.print()
    console.print(
        Panel(
            Align.center(
                f"[bold green]APEX SENTINEL  v{version}[/bold green]\n"
                "[dim]ANUBIS OS — Sistema Operativo Táctico[/dim]"
            ),
            border_style="green",
            box=box.DOUBLE_EDGE,
            padding=(0, 2) if not compacto else (0, 1),
        )
    )
    console.print()

    ancho_consola = console.size.width
    columnas_por_fila = _columnas_ayuda(ancho_consola)
    ancho_panel, ancho_max_desc = _dimensiones_panel_ayuda(ancho_consola, columnas_por_fila)

    cols: List[Panel] = []
    for categoria, cmds in comandos.items():
        tb = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold green",
            show_edge=False,
            expand=True,
            padding=(0, 1),
        )
        tb.add_column(f"▸  {categoria}", style="cyan", min_width=_ANCHO_MIN_COMANDO, no_wrap=True)
        tb.add_column("Descripción", style="dim white", max_width=ancho_max_desc, overflow="fold")
        for cmd, desc in cmds:
            tb.add_row(f"[bold white]{cmd}[/bold white]", desc)
        cols.append(
            Panel(tb, border_style="dim green", box=box.ROUNDED, padding=(0, 1), width=ancho_panel)
        )

    for i in range(0, len(cols), columnas_por_fila):
        fila = cols[i: i + columnas_por_fila]
        console.print(Columns(fila, equal=False, expand=False))

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


if __name__ == "__main__":
    _con = Console()
    estados_demo: Dict[str, bool] = {
        "RadarSentinel": True,  "TacticalSniffer": True,
        "RFModule": True,       "SpectrumAnalyzer": True,
        "ExifAnalyzer": True,   "ForensicReader": True,
        "StealthModule": True,  "MobileSentinel": True,
        "OSINTEngine": True,    "CVEMatcher": True,
        "GestorProyectos": True, "MotorReportes": True,
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
