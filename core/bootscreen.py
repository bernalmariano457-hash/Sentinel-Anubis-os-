from __future__ import annotations

import asyncio
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import unicodedata
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

_CAJA: box.Box = box.ROUNDED

# ── Paleta "Grafito / Acero" ─────────────────────────────────────────────
# Un único acento (azul acero) sobre grises fríos, en vez del verde neón
# genérico de "terminal de hacker de película": pensado para leerse como
# una consola de operaciones seria y discreta. Todo el color de la UI
# sale de estas siete constantes — para retocar la paleta más adelante,
# alcanza con cambiar los valores acá, no hay que tocar el resto del
# archivo.
C_TEXTO:   str = "white"        # texto de lectura principal (valores)
C_DIM:     str = "grey58"       # texto secundario (etiquetas, timestamps)
C_MUTED:   str = "grey42"       # texto terciario (debug, separadores)
C_ACENTO:  str = "steel_blue1"  # títulos, énfasis, prompt, arte ASCII
C_BORDE:   str = "steel_blue"   # bordes de panel (acento más apagado)
C_OK:      str = "sea_green3"   # éxito / estado activo
C_ALERTA:  str = "orange3"      # advertencia / estado degradado
C_PELIGRO: str = "red"          # error / estado caído — se deja el rojo
                                 # puro a propósito: es la única señal
                                 # "dura" de la paleta y necesita seguir
                                 # leyéndose como alarma, no como acento.

_SIMBOLOS_ESTADO: Dict[str, str] = {"activo": "●", "degradado": "◐", "caido": "✖"}
_ESTILOS_ESTADO: Dict[str, str] = {
    "activo": C_OK, "degradado": C_ALERTA, "caido": f"bold {C_PELIGRO}",
}

ESTILOS_LOG: Dict[str, Tuple[str, str]] = {
    "INFO":    (C_DIM,               "ℹ"),
    "SUCCESS": (C_OK,                "✔"),
    "WARNING": (C_ALERTA,            "⚠"),
    "ERROR":   (f"bold {C_PELIGRO}", "✖"),
    "AUDIT":   (f"bold {C_ACENTO}",  "⚑"),
    "DEBUG":   (C_MUTED,             "·"),
}

ANUBIS_ART = "\n".join([
    r"   ▄████████████████████▄",
    r"   █  ╔═══════════════╗  █",
    r"   █  ║   /\     /\   ║  █",
    r"   █  ║  (  \   /  )  ║  █",
    r"   █  ║   \  \_/  /   ║  █",
    r"   █  ║   /  ___  \   ║  █",
    r"   █  ║  / / | | \ \  ║  █",
    r"   █  ║ /_/__|_|__\_\ ║  █",
    r"   █  ╚═══════════════╝  █",
    r"   ▀████████████████████▀",
])

ANUBIS = ANUBIS_ART

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
    ("Recovery",         "Carving forense de medios eliminados"),
    ("FlipperZero",      "Bridge serial Flipper Zero"),
]

_GRUPOS_MODULOS: Dict[str, List[str]] = {
    "Red":       ["RadarSentinel", "TacticalSniffer", "BluetoothModule"],
    "RF":        ["RFModule", "SpectrumAnalyzer"],
    "Forense":   ["ExifAnalyzer", "ForensicReader", "MobileSentinel", "StealthModule"],
    "Acceso":    ["HydraModule"],
    "OSINT":     ["OSINTEngine", "CVEMatcher", "GeoPrecise"],
    "Proyectos": ["GestorProyectos", "MotorReportes", "ColaTareas", "GestorPlugins"],
    "Seguridad": ["SecurityModule", "Recovery"],
    "Hardware":  ["FlipperZero"],
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
        ("geofoto",              "Extraer GPS de fotografías EXIF"),
        ("locate / locate -p",   "Localización por IP / GPS activo"),
        ("view",                 "Leer archivo forense"),
        ("mobile",               "Triaje básico de móvil"),
        ("mobile-deep",          "Análisis profundo de móvil"),
        ("recover",              "File carving forense (.dd/.img o /dev/sdX)"),
        ("recover ver <id>",     "Tabla de resultados de un job de carving"),
        ("stealth",              "Verificar identidad digital"),
        ("panic",                "Borrado de emergencia"),
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
    "FLIPPER ZERO": [
        ("flipper",          "Menú interactivo Flipper Zero"),
        ("flipper-status",   "Telemetría: batería, temperatura, storage"),
        ("flipper-nfc",      "Escaneo NFC de alta frecuencia"),
        ("flipper-rfid",     "Lectura RFID de baja frecuencia (125 kHz)"),
        ("flipper-capture",  "Captura Sub-GHz → archivo .sub"),
        ("flipper-list",     "Listar capturas Sub-GHz en el dispositivo"),
    ],
}


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


_ip_cache: Optional[str] = None


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


def _plataforma_str() -> str:
    if _PLATFORM_OK:
        try:
            info = _detect_platform()
            return f"{info.kind.name}  {info.machine}"
        except Exception:
            pass
    return f"{platform.machine()}  {sys.platform}"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _pantalla_compacta(console: Console) -> bool:
    return console.size.width < _ANCHO_MINIMO_COMPLETO


def _titulo_hud(compacto: bool) -> str:
    if compacto:
        return "[bold steel_blue1]◈ ANUBIS OS ◈[/bold steel_blue1]"
    return "[bold steel_blue1]◈  A N U B I S   O S  ◈[/bold steel_blue1]"


def _tabla_base(compacto: bool) -> Table:
    tabla = Table.grid(padding=(0, 1) if compacto else (0, 2))
    tabla.add_column(style="grey58", justify="right", min_width=10 if compacto else 14)
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


def _linea_barra(idx: int, total: int, ancho: int) -> str:
    proporcion = idx / total if total else 1.0
    llenos = int(ancho * proporcion)
    barra = "█" * llenos + "░" * (ancho - llenos)
    pct = int(proporcion * 100)
    return (
        f"[grey58][[/grey58][bold steel_blue1]{barra}[/bold steel_blue1]"
        f"[grey58]][/grey58] [bold steel_blue1]{pct:>3}%[/bold steel_blue1]"
    )


def _panel_hero(
    nombre: str,
    version: str,
    iface: str,
    ip: str,
    plataforma: str,
    hora_arranque: str,
    compacto: bool,
) -> Panel:
    tabla = _tabla_base(compacto)
    tabla.add_row("SISTEMA", f"[bold steel_blue1]APEX SENTINEL[/bold steel_blue1] [grey58]v{version}[/grey58]")
    tabla.add_row("OPERADOR", f"[bold steel_blue1]{nombre}[/bold steel_blue1]")
    tabla.add_row("ESTADO", "[bold sea_green3]● EN LÍNEA[/bold sea_green3]")
    tabla.add_row("INTERFAZ", f"[white]{iface}[/white]")
    tabla.add_row("IP LOCAL", f"[white]{ip}[/white]")
    if not compacto:
        tabla.add_row("PLATAFORMA", f"[grey58]{plataforma}[/grey58]")
        tabla.add_row("ARRANQUE", f"[grey58]{hora_arranque}[/grey58]")
    tabla.add_row("", "")
    if compacto:
        tabla.add_row("AVISO", "[bold red]⚠ AUTHORIZED USE ONLY[/bold red]")
    else:
        tabla.add_row("AVISO", "[bold red]⚠  AUTHORIZED USE ONLY — ACCESO RESTRINGIDO[/bold red]")

    layout = Layout()
    if compacto:
        layout.update(Align.center(tabla, vertical="middle"))
        alto = 9
        relleno: Tuple[int, int] = (0, 1)
    else:
        layout.split_row(
            Layout(name="arte", size=_ANCHO_ARTE),
            Layout(name="info", ratio=1),
        )
        layout["arte"].update(Align.center(Text(ANUBIS_ART, style="bold steel_blue1"), vertical="middle"))
        layout["info"].update(Align.left(tabla, vertical="middle"))
        alto = 14
        relleno = (1, 3)

    return Panel(
        layout,
        title=_titulo_hud(compacto),
        subtitle=None if compacto else "[grey58]APEX SENTINEL — SISTEMA OPERATIVO TÁCTICO[/grey58]",
        border_style="steel_blue",
        box=_CAJA,
        padding=relleno,
        height=alto,
    )


def _cuadro_boot(idx: int, total: int, nombre_mod: str, activo: bool, compacto: bool) -> Panel:
    ancho_barra = _ANCHO_BARRA_COMPACTA if compacto else _ANCHO_BARRA_NORMAL
    barra = _linea_barra(idx, total, ancho_barra)

    estado = "activo" if activo else "caido"
    simbolo, color = _SIMBOLOS_ESTADO[estado], _ESTILOS_ESTADO[estado]
    etiqueta = "OK" if activo else "FALLO"
    estado_txt = f"[{color}]{simbolo} {etiqueta}[/{color}]"
    nombre_fmt = nombre_mod if compacto else f"{nombre_mod:<24}"

    contenido = (
        f"\n  {barra}\n\n"
        f"  [grey58]{nombre_fmt}[/grey58]  {estado_txt}\n"
    )
    return Panel(
        contenido,
        title=_titulo_hud(compacto),
        subtitle=f"[grey58]Verificando módulos — {idx}/{total}[/grey58]",
        border_style="steel_blue",
        box=_CAJA,
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
        listado = "  ".join(f"[grey58]{d}[/grey58]" for d in degradados[:limite])
        restante = len(degradados) - limite
        extra = f"  [grey58]+{restante} más[/grey58]" if restante > 0 else ""
        contenido += f"\n\n  [orange3]○ Sin cargar:[/orange3]  {listado}{extra}"

    return Panel(
        contenido,
        title=f"[grey58]{ok_count}/{total} módulos activos[/grey58]",
        border_style="steel_blue",
        box=_CAJA,
        padding=(0, 1),
    )


def _panel_hud(compacto: bool, ip: str, hora: str) -> Panel:
    tabla = Table.grid(padding=(0, 2))
    tabla.add_column(style="grey58", justify="right")
    tabla.add_column()
    tabla.add_row("ESTADO", "[bold sea_green3]● EN LÍNEA[/bold sea_green3]")
    tabla.add_row("IP", f"[white]{ip}[/white]")
    tabla.add_row("HORA", f"[grey58]{hora}[/grey58]")

    return Panel(
        Align.center(tabla),
        title=_titulo_hud(compacto),
        border_style="steel_blue",
        box=_CAJA,
        padding=(1, 2),
    )


def _limpiar() -> None:
    if os.name == "nt":
        subprocess.run(["cls"], shell=True, check=False)
    else:
        subprocess.run(["clear"], check=False)


async def _ejecutar_boot(
    console: Console,
    modulos: List[str],
    estados_modulos: Optional[Dict[str, bool]],
    compacto: bool,
) -> None:
    total = len(modulos)
    with Live(console=console, refresh_per_second=24, screen=False) as live:
        for idx, nombre_mod in enumerate(modulos, 1):
            activo = estados_modulos is None or estados_modulos.get(nombre_mod, True)
            live.update(_cuadro_boot(idx, total, nombre_mod, activo, compacto))
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
    console.print(_panel_hero(
        nombre=nombre,
        version=version,
        iface=iface,
        ip=_get_ip(),
        plataforma=_plataforma_str(),
        hora_arranque=datetime.now().strftime("%d/%m/%Y  %H:%M:%S"),
        compacto=compacto,
    ))

    ok_count = sum(1 for v in estados_modulos.values() if v) if estados_modulos else total
    console.print(_panel_resumen_modulos(estados_modulos, ok_count, total, compacto))

    console.print(Rule(style="grey58"))
    console.print(
        Align.center(
            "[grey58]Escribe [bold steel_blue1]help[/bold steel_blue1] para ver comandos  "
            "·  [bold steel_blue1]exit[/bold steel_blue1] para salir[/grey58]"
        )
    )
    console.print(Rule(style="grey58"))
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
    console.print()
    console.print(_panel_hud(compacto, ip=_get_ip(), hora=_ts()))
    console.print(Rule(style="grey58"))
    console.print()


def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_acentos if not unicodedata.combining(c)).lower()


def _filtrar_comandos(
    comandos: Dict[str, List[Tuple[str, str]]],
    filtro: Optional[str],
) -> Dict[str, List[Tuple[str, str]]]:
    termino = _normalizar((filtro or "").strip())
    if not termino:
        return comandos

    # 1) ¿coincide con el nombre de alguna categoría? ("red", "rf", "ataques"...)
    por_categoria = {
        cat: cmds for cat, cmds in comandos.items()
        if termino in _normalizar(cat)
    }
    if por_categoria:
        return por_categoria

    # 2) si no, busca la palabra en nombres de comando y descripciones
    resultado: Dict[str, List[Tuple[str, str]]] = {}
    for cat, cmds in comandos.items():
        coincidencias = [
            (cmd, desc) for cmd, desc in cmds
            if termino in _normalizar(cmd) or termino in _normalizar(desc)
        ]
        if coincidencias:
            resultado[cat] = coincidencias
    return resultado


def _tabla_comandos(cmds: List[Tuple[str, str]]) -> Table:
    tabla = Table.grid(padding=(0, 2), expand=True)
    tabla.add_column(style="bold steel_blue1", no_wrap=True)
    tabla.add_column(style="grey58", overflow="fold", ratio=1)
    for cmd, desc in cmds:
        tabla.add_row(cmd, desc)
    return tabla


def mostrar_ayuda(
    console: Console,
    version: str,
    comandos: Optional[Dict[str, List[Tuple[str, str]]]] = None,
    filtro: Optional[str] = None,
) -> None:
    if comandos is None:
        comandos = COMANDOS_HELP

    console.print()
    console.print(
        Align.center(
            f"[bold steel_blue1]APEX SENTINEL[/bold steel_blue1] [grey58]v{version}[/grey58]   "
            "[grey58]ANUBIS OS — Sistema Operativo Táctico[/grey58]"
        )
    )
    console.print(Rule(style="grey58"))

    categorias = _filtrar_comandos(comandos, filtro)

    if not categorias:
        console.print()
        console.print(
            f"[grey58]Sin coincidencias para[/grey58] [bold steel_blue1]'{filtro}'[/bold steel_blue1]"
        )
        console.print(
            "[grey58]Prueba[/grey58] [bold steel_blue1]help[/bold steel_blue1] "
            "[grey58]a secas, o[/grey58] [bold steel_blue1]help <categoría>[/bold steel_blue1]"
        )
        console.print()
        console.print(Rule(style="grey58"))
        console.print()
        return

    for categoria, cmds in categorias.items():
        console.print()
        console.print(Rule(f"[bold steel_blue1]▸ {categoria}[/bold steel_blue1]", style="grey58", align="left"))
        console.print(_tabla_comandos(cmds))

    console.print()
    console.print(Rule(style="grey58"))
    if filtro:
        console.print(
            Align.center(
                f"[grey58]Resultados para[/grey58] [bold steel_blue1]'{filtro}'[/bold steel_blue1]  ·  "
                "[grey58]escribe[/grey58] [bold steel_blue1]help[/bold steel_blue1] "
                "[grey58]para ver todo[/grey58]"
            )
        )
    else:
        console.print(
            Align.center(
                "[bold steel_blue1]help <categoría|palabra>[/bold steel_blue1] [grey58]filtra[/grey58]  ·  "
                "[bold steel_blue1]exit[/bold steel_blue1] [grey58]para salir[/grey58]"
            )
        )
    console.print(Rule(style="grey58"))
    console.print()


if __name__ == "__main__":
    _con = Console(highlight=False)
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
        _con.print("\n[grey58][!] Cancelado.[/grey58]")
