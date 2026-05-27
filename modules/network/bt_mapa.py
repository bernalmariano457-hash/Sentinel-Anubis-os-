from __future__ import annotations

import asyncio
import hashlib
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from modules.network.bt_module import BluetoothModule, DispositivoBLE

try:
    from bleak import BleakScanner
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData
    BLEAK_OK = True
except ImportError:
    BLEAK_OK = False

from core.vendor_resolver import VendorResolver


# ══════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DEL CANVAS
# ══════════════════════════════════════════════════════════════════════

_W = 61    # ancho del canvas en caracteres
_H = 29    # alto del canvas en líneas
_CX = _W // 2
_CY = _H // 2
_RX = 28    # radio eje X (compensación aspecto terminal ~2.3×)
_RY = 13    # radio eje Y

# Anillos: (umbral_rssi, etiqueta_dist, color_anillo, fracción_radio)
_RINGS = [
    (-50,  "< 2m",   "bold red",    0.20),
    (-65,  "2–5m",   "yellow",      0.42),
    (-80,  "5–15m",  "green",       0.66),
    (-200, "> 15m",  "dim white",   0.88),
]

# Glifo por proximidad (dispositivo normal)
_GLYPHS: dict[str, tuple[str, str]] = {
    "MUY CERCA": ("✦", "bold red"),
    "CERCA":     ("●", "yellow"),
    "MEDIO":     ("◉", "green"),
    "LEJOS":     ("○", "dim white"),
}

# Glifo para dispositivos nuevos (parpadeo visual primeros 3 ciclos)
_GLYPH_NEW = ("◆", "bold cyan")

# Estela histórica: (char, style_template)  — se usa dim del color original
_TRAIL_CHARS = ["·", "·"]   # posiciones -1 y -2

# Indicadores de tendencia
_TREND_UP = "↑"   # acercándose
_TREND_DOWN = "↓"   # alejándose
_TREND_FLAT = "→"   # estable

# UUIDs de servicio BLE → tipo de dispositivo
_SERVICE_MAP: dict[str, str] = {
    "0000180f": "Batería",
    "0000180a": "Info.Disp.",
    "0000111e": "Manos Libres",
    "0000110b": "Audio A2DP",
    "00001108": "Auricular",
    "0000180d": "Frecuencia Card.",
    "00001812": "HID (teclado/ratón)",
    "00001803": "Alerta Inmediata",
    "00001802": "Alerta TX",
    "00001804": "Potencia TX",
    "00001816": "Velocidad/Cadencia",
    "00001818": "Ciclo/Potencia",
    "0000181c": "Info. Usuario",
    "0000fe9f": "Google Fast Pair",
    "0000fd6f": "Contact Tracing",
}

# EMA — factor de suavizado RSSI (0=sin suavizado, 1=sin memoria)
_EMA_ALPHA = 0.30

# Umbral de repulsión angular (radianes) entre dispositivos solapados
_REPULSION_THRESHOLD = 0.18   # ~10°
_REPULSION_ITERS = 8
_REPULSION_STEP = 0.12   # radianes por iter

# Ciclos que un dispositivo se considera "nuevo"
_NEW_CYCLES = 3

# Historial de RSSI por dispositivo
_RSSI_HISTORY_LEN = 6

# Umbral de tendencia (dBm de diferencia entre EMA actual y hace 3 ciclos)
_TREND_THRESHOLD = 3.0


# ══════════════════════════════════════════════════════════════════════
# INFERENCIA DE TIPO DE DISPOSITIVO
# ══════════════════════════════════════════════════════════════════════

def _infer_device_type(servicios: list[str]) -> str:
    for svc in servicios:
        short = svc.lower().replace("-", "")[:8]
        if short in _SERVICE_MAP:
            return _SERVICE_MAP[short]
    return "Desconocido"


# ══════════════════════════════════════════════════════════════════════
# TRACKING DE DISPOSITIVO — EMA, TENDENCIA, HISTORIAL
# ══════════════════════════════════════════════════════════════════════

@dataclass
class DeviceTrack:
    address:          str
    rssi_history:     deque = field(
        default_factory=lambda: deque(maxlen=_RSSI_HISTORY_LEN))
    ema_rssi:         float = -99.0
    ema_history:      deque = field(default_factory=lambda: deque(maxlen=6))
    first_cycle:      int = 0
    last_cycle:       int = 0
    tipo:             str = "Desconocido"

    def update(self, rssi: int, cycle: int, servicios: list[str]) -> None:
        self.rssi_history.append(rssi)
        if self.ema_rssi == -99.0:
            self.ema_rssi = float(rssi)
        else:
            self.ema_rssi = _EMA_ALPHA * rssi + \
                (1 - _EMA_ALPHA) * self.ema_rssi
        self.ema_history.append(self.ema_rssi)
        self.last_cycle = cycle
        if self.tipo == "Desconocido" and servicios:
            self.tipo = _infer_device_type(servicios)

    @property
    def is_new_at(self) -> int:
        return self.first_cycle

    def tendencia(self) -> str:
        if len(self.ema_history) < 4:
            return _TREND_FLAT
        delta = self.ema_history[-1] - self.ema_history[-4]
        if delta > _TREND_THRESHOLD:
            return _TREND_UP
        if delta < -_TREND_THRESHOLD:
            return _TREND_DOWN
        return _TREND_FLAT

    def tendencia_style(self) -> str:
        t = self.tendencia()
        if t == _TREND_UP:
            return "bold red"
        if t == _TREND_DOWN:
            return "dim green"
        return "dim"

    def rssi_suavizado(self) -> int:
        return round(self.ema_rssi)

    def rssi_hist_fracs(self) -> list[float]:
        vals = list(self.rssi_history)
        # -2 y -1 (no el actual)
        return [_rssi_a_radio(r) for r in vals[-3:-1]]


# ══════════════════════════════════════════════════════════════════════
# HELPERS GEOMÉTRICOS
# ══════════════════════════════════════════════════════════════════════

def _mac_angulo(address: str) -> float:
    digest = int(hashlib.md5(address.encode()).hexdigest()[:8], 16)
    return (digest % 360) * math.pi / 180


def _rssi_a_radio(rssi: int) -> float:
    rssi = max(-100, min(-40, rssi))
    return 0.10 + (rssi - (-40)) / (-100.0 - (-40)) * 0.83


def _proximidad(rssi: int) -> str:
    if rssi >= -50:
        return "MUY CERCA"
    if rssi >= -65:
        return "CERCA"
    if rssi >= -80:
        return "MEDIO"
    return "LEJOS"


def _dist_canvas(ax, ay, bx, by) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


# ══════════════════════════════════════════════════════════════════════
# SEPARACIÓN DE ÁNGULOS — REPULSIÓN ITERATIVA
# ══════════════════════════════════════════════════════════════════════

def _separar_angulos(
    posiciones: dict[str, tuple[float, float, float]]
) -> dict[str, tuple[float, float, float]]:
    addrs = list(posiciones.keys())
    angulos = {a: posiciones[a][0] for a in addrs}

    for _ in range(_REPULSION_ITERS):
        for i in range(len(addrs)):
            for j in range(i + 1, len(addrs)):
                ai, aj = addrs[i], addrs[j]
                da = angulos[aj] - angulos[ai]
                # Normalizar diferencia angular a [-π, π]
                da = (da + math.pi) % (2 * math.pi) - math.pi
                if abs(da) < _REPULSION_THRESHOLD:
                    push = (_REPULSION_THRESHOLD - abs(da)) / \
                        2 + _REPULSION_STEP
                    sign = 1 if da >= 0 else -1
                    angulos[ai] -= push * sign
                    angulos[aj] += push * sign

    return {
        a: (angulos[a], posiciones[a][1], posiciones[a][2])
        for a in addrs
    }


# ══════════════════════════════════════════════════════════════════════
# CANVAS — RENDER
# ══════════════════════════════════════════════════════════════════════

_Canvas = list[list[tuple[str, str]]]


def _canvas_nuevo() -> _Canvas:
    return [[(" ", "") for _ in range(_W)] for _ in range(_H)]


def _put(g: _Canvas, x: int, y: int, c: str, s: str) -> None:
    if 0 <= x < _W and 0 <= y < _H:
        g[y][x] = (c, s)


def _draw_ring(g: _Canvas, frac: float, color: str) -> None:
    rx = frac * _RX
    ry = frac * _RY
    steps = max(int(2 * math.pi * math.sqrt((rx ** 2 + ry ** 2) / 2) * 1.6), 80)
    for i in range(steps):
        a = 2 * math.pi * i / steps
        x = round(_CX + rx * math.cos(a))
        y = round(_CY + ry * math.sin(a))
        _put(g, x, y, "·", color)


def _draw_axes(g: _Canvas) -> None:
    for x in range(_W):
        if g[_CY][x][0] == " ":
            _put(g, x, _CY, "─", "dim")
    for y in range(_H):
        if g[y][_CX][0] == " ":
            _put(g, _CX, y, "│", "dim")
    _put(g, _CX, _CY, "⊕", "bold cyan")


def _ring_label(g: _Canvas) -> None:
    for _, label, color, frac in _RINGS:
        # Posición: lado derecho del anillo en el eje horizontal
        x = round(_CX + frac * _RX) + 1
        y = _CY
        if 0 <= x < _W - len(label) - 1 and 0 <= y < _H:
            for i, ch in enumerate(label):
                _put(g, x + i, y, ch, f"dim {color}")


def _canvas_a_text(g: _Canvas) -> Text:
    t = Text(no_wrap=True)
    for row in g:
        for char, style in row:
            t.append(char, style=style if style else "default")
        t.append("\n")
    return t


# ══════════════════════════════════════════════════════════════════════
# RENDER PRINCIPAL DEL MAPA
# ══════════════════════════════════════════════════════════════════════

def render_mapa(
    dispositivos: list["DispositivoBLE"],
    tracks: dict[str, DeviceTrack],
    ciclo: int,
) -> Text:
    g = _canvas_nuevo()

    # 1 — Anillos
    for _, _, color, frac in _RINGS:
        _draw_ring(g, frac, color)

    # 2 — Ejes y etiquetas
    _draw_axes(g)
    _ring_label(g)

    if not dispositivos:
        return _canvas_a_text(g)

    # 3 — Calcular posiciones base
    posiciones: dict[str, tuple[float, float, float]] = {}
    for d in dispositivos:
        tr = tracks.get(d.address)
        rssi_ema = tr.rssi_suavizado() if tr else d.rssi
        posiciones[d.address] = (
            _mac_angulo(d.address),
            _rssi_a_radio(rssi_ema),
            float(rssi_ema),
        )

    # 4 — Separación de ángulos solapados
    posiciones = _separar_angulos(posiciones)

    # 5 — Dibujar estelas (histórico) de lejos a cerca
    for d in sorted(dispositivos, key=lambda d: d.rssi):
        tr = tracks.get(d.address)
        if not tr or len(tr.rssi_history) < 2:
            continue
        angle = posiciones[d.address][0]
        prox_key = _proximidad(d.rssi)
        _, base_style = _GLYPHS[prox_key]
        for hist_frac in tr.rssi_hist_fracs():
            hx = round(_CX + hist_frac * _RX * math.cos(angle))
            hy = round(_CY + hist_frac * _RY * math.sin(angle))
            # Solo dibujar si la celda está libre o tiene otra estela
            if g[hy][hx][0] in (" ", "·", "─", "│") if 0 <= hy < _H and 0 <= hx < _W else False:
                _put(g, hx, hy, "·", f"dim {base_style}")

    # 6 — Dibujar dispositivos (de lejos a cerca, los cercanos encima)
    for d in sorted(dispositivos, key=lambda d: d.rssi):
        angle, frac, _ = posiciones[d.address]
        x = round(_CX + frac * _RX * math.cos(angle))
        y = round(_CY + frac * _RY * math.sin(angle))

        tr = tracks.get(d.address)
        es_nuevo = tr and (ciclo - tr.first_cycle) < _NEW_CYCLES

        if es_nuevo:
            glyph, style = _GLYPH_NEW
        else:
            prox_key = _proximidad(tr.rssi_suavizado() if tr else d.rssi)
            glyph, style = _GLYPHS[prox_key]

        _put(g, x, y, glyph, style)

    return _canvas_a_text(g)


# ══════════════════════════════════════════════════════════════════════
# PANEL LATERAL
# ══════════════════════════════════════════════════════════════════════

def _panel_lateral(
    dispositivos: list["DispositivoBLE"],
    tracks: dict[str, DeviceTrack],
    t_inicio: float,
    ciclo: int,
    nuevos: int,
    alertas: list[str],
) -> Panel:
    elapsed = int(time.time() - t_inicio)
    hh, mm = divmod(elapsed, 3600)
    mm, ss = divmod(mm, 60)

    # ── Stats compactos ───────────────────────────────────────────────
    total = len(dispositivos)
    cercanos = sum(1 for d in dispositivos if d.rssi >= -65)
    fab_set = {d.fabricante for d in dispositivos
               if d.fabricante and d.fabricante != "Desconocido"}
    acercandose = sum(
        1 for d in dispositivos
        if tracks.get(d.address) and tracks[d.address].tendencia() == _TREND_UP
    )

    stats = Table.grid(padding=(0, 1))
    stats.add_column(style="dim cyan",   justify="right", min_width=12)
    stats.add_column(style="bold white", min_width=7)

    stats.add_row("Dispositivos",  str(total))
    stats.add_row("Cercanos",      f"[yellow]{cercanos}[/yellow]")
    stats.add_row("Acercándose",   f"[bold red]{acercandose}[/bold red]"
                  if acercandose else "[dim]0[/dim]")
    stats.add_row("Fabricantes",   str(len(fab_set)))
    stats.add_row("Nuevos ciclo",  f"[cyan]{nuevos}[/cyan]"
                  if nuevos else "[dim]0[/dim]")
    stats.add_row("Ciclo",         f"[dim]{ciclo}[/dim]")
    stats.add_row("Sesión",        f"[dim]{hh:02d}:{mm:02d}:{ss:02d}[/dim]")
    stats.add_row(
        "Hora",          f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim]")

    # ── Tabla de dispositivos ─────────────────────────────────────────
    tb = Table(
        box=box.SIMPLE,
        header_style="bold cyan",
        show_edge=False,
        expand=True,
        padding=(0, 1),
    )
    tb.add_column("",            min_width=1,  no_wrap=True)   # glifo
    tb.add_column("Dispositivo", min_width=13, no_wrap=True, style="white")
    tb.add_column("RSSI",        min_width=8,  no_wrap=True, justify="right")
    tb.add_column("Tend.",       min_width=3,  no_wrap=True, justify="center")
    tb.add_column("Tipo",        min_width=10,
                  no_wrap=True, style="dim yellow")

    ordenados = sorted(dispositivos, key=lambda d: d.rssi, reverse=True)
    for d in ordenados[:16]:
        tr = tracks.get(d.address)
        rssi_s = tr.rssi_suavizado() if tr else d.rssi
        prox_key = _proximidad(rssi_s)
        es_nuevo = tr and (ciclo - tr.first_cycle) < _NEW_CYCLES

        if es_nuevo:
            glyph, g_style = _GLYPH_NEW
        else:
            glyph, g_style = _GLYPHS[prox_key]

        _, p_style = _GLYPHS[prox_key]
        rssi_str = f"[{p_style}]{rssi_s} dBm[/{p_style}]"
        tend_sym = tr.tendencia() if tr else _TREND_FLAT
        tend_sty = tr.tendencia_style() if tr else "dim"
        tipo = (tr.tipo if tr else "—")[:11]
        nombre = (d.nombre or "<sin nombre>")[:13]

        tb.add_row(
            f"[{g_style}]{glyph}[/{g_style}]",
            nombre,
            rssi_str,
            f"[{tend_sty}]{tend_sym}[/{tend_sty}]",
            tipo,
        )

    # ── Alertas ───────────────────────────────────────────────────────
    alert_text = Text()
    if alertas:
        alert_text.append("\n  ALERTAS\n", style="bold red")
        for a in alertas[-3:]:
            alert_text.append(f"  ⚠ {a}\n", style="yellow")

    # ── Leyenda ───────────────────────────────────────────────────────
    leyenda = Text("\n  LEYENDA\n", style="dim cyan")
    for prox_key, (glyph, style) in _GLYPHS.items():
        dist = {
            "MUY CERCA": "< 2m",
            "CERCA":     "2–5m",
            "MEDIO":     "5–15m",
            "LEJOS":     "> 15m",
        }[prox_key]
        leyenda.append(f"  {glyph} ", style=style)
        leyenda.append(f"{prox_key:<10} ", style=style)
        leyenda.append(f"{dist}\n", style="dim")

    leyenda.append(f"\n  {_GLYPH_NEW[0]} ", style=_GLYPH_NEW[1])
    leyenda.append("NUEVO         < 3 ciclos\n", style="dim")
    leyenda.append(f"\n  {_TREND_UP} acercándose  ", style="bold red")
    leyenda.append(f"{_TREND_DOWN} alejándose  ", style="dim green")
    leyenda.append(f"{_TREND_FLAT} estable\n", style="dim")
    leyenda.append("  · · estela de posición anterior\n", style="dim")

    contenido = Group(stats, Rule(style="dim cyan"), tb, alert_text, leyenda)
    return Panel(
        contenido,
        title="[bold cyan]DISPOSITIVOS[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(0, 1),
    )


# ══════════════════════════════════════════════════════════════════════
# VISTA COMPLETA
# ══════════════════════════════════════════════════════════════════════

def render_vista(
    dispositivos: list["DispositivoBLE"],
    tracks:        dict[str, DeviceTrack],
    t_inicio:      float,
    ciclo:         int,
    nuevos:        int,
    alertas:       list[str],
) -> Columns:
    ts = datetime.now().strftime("%H:%M:%S")

    panel_mapa = Panel(
        render_mapa(dispositivos, tracks, ciclo),
        title=f"[bold cyan]BLUETOOTH LE — RADAR[/bold cyan]  [dim]{ts}[/dim]",
        subtitle=(
            "[dim]ángulo=hash(MAC)  ·  radio=RSSI(EMA)  ·  "
            "estela=historial  ·  [bold cyan]◆[/bold cyan]=nuevo[/dim]"
        ),
        border_style="cyan",
        box=box.HEAVY_EDGE,
        padding=(0, 1),
    )
    panel_lat = _panel_lateral(
        dispositivos, tracks, t_inicio, ciclo, nuevos, alertas
    )
    return Columns([panel_mapa, panel_lat], expand=True, equal=False)


# ══════════════════════════════════════════════════════════════════════
# DETECCIÓN DE ALERTAS
# ══════════════════════════════════════════════════════════════════════

def _evaluar_alertas(
    dispositivos: list["DispositivoBLE"],
    tracks: dict[str, DeviceTrack],
    alertas: list[str],
) -> None:
    for d in dispositivos:
        tr = tracks.get(d.address)
        if not tr:
            continue
        # Dispositivo muy cercano que se acerca más
        if d.rssi >= -55 and tr.tendencia() == _TREND_UP:
            msg = f"Muy cercano acercándose: {d.nombre or d.address[:17]}"
            if msg not in alertas:
                alertas.append(msg)
        # Salto brusco de RSSI (> 20 dBm en 2 ciclos)
        hist = list(tr.rssi_history)
        if len(hist) >= 3 and (hist[-1] - hist[-3]) > 20:
            msg = f"Salto RSSI: {d.nombre or d.address[:17]} ({hist[-3]}→{hist[-1]} dBm)"
            if msg not in alertas:
                alertas.append(msg)
    # Mantener solo las últimas 6
    del alertas[:-6]


# ══════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class BLEMapaRadar:
    SCAN_INTERVAL = 5.0

    def __init__(self, bt_module: "BluetoothModule"):
        self.bt = bt_module
        self.console: Console = getattr(bt_module, "console", Console())
        self.log = getattr(bt_module, "log",  None)
        self._lock = getattr(bt_module, "_lock", threading.Lock())
        self._disp = getattr(bt_module, "_dispositivos", {})
        # Tracks extendidos propios del radar (no compartidos con bt_module)
        self._tracks: dict[str, DeviceTrack] = {}
        self._alertas: list[str] = []

    # ── Helpers ───────────────────────────────────────────────────────

    def _info(self, msg: str) -> None:
        if self.log:
            self.log.info(msg, "BLEMapaRadar")
        else:
            self.console.print(f"[cyan][*][/cyan] {msg}")

    def _run_async(self, coro) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            exc_box: list = []

            def _t():
                try:
                    asyncio.run(coro)
                except Exception as e:
                    exc_box.append(e)
            t = threading.Thread(target=_t, daemon=True)
            t.start()
            t.join()
            if exc_box:
                raise exc_box[0]
        else:
            asyncio.run(coro)

    # ── Punto de entrada ──────────────────────────────────────────────

    def iniciar(self, duracion_seg: int = 120) -> None:
        if not BLEAK_OK:
            self.console.print(
                "[red][!] bleak no disponible.[/red]\n"
                "[dim]    pip install bleak --break-system-packages[/dim]"
            )
            return
        self.console.print(
            f"\n[bold cyan][*] BLE Radar Map[/bold cyan]  "
            f"[dim]{duracion_seg}s · Ctrl+C para detener[/dim]\n"
        )
        try:
            self._run_async(self._loop(duracion_seg))
        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Radar detenido.[/yellow]")
        except Exception as e:
            self.console.print(f"[red][!] Error: {e}[/red]")
        finally:
            self._guardar_evidencia()
            self._resumen_final()

    # ── Loop principal ────────────────────────────────────────────────

    async def _loop(self, duracion_seg: int) -> None:
        t_inicio = time.time()
        conocidos: set[str] = set()
        ciclo = 0

        with Live(
            console=self.console,
            refresh_per_second=4,
            screen=False,
        ) as live:

            while time.time() - t_inicio < duracion_seg:
                ciclo += 1
                nuevos_ciclo: list = []

                # ── Escaneo BLE ───────────────────────────────────────
                def _cb(device: "BLEDevice", adv: "AdvertisementData"):
                    rssi = adv.rssi if adv.rssi else -99
                    servicios = [str(u) for u in (adv.service_uuids or [])]
                    with self._lock:
                        if device.address in self._disp:
                            self._disp[device.address].actualizar(rssi)
                        else:
                            from modules.network.bt_module import DispositivoBLE
                            d = DispositivoBLE(
                                nombre=device.name or "",
                                address=device.address,
                                rssi=rssi,
                                fabricante=VendorResolver.resolve(
                                    device.address),
                                servicios=servicios,
                            )
                            self._disp[device.address] = d

                        # Actualizar track extendido
                        addr = device.address
                        if addr not in self._tracks:
                            self._tracks[addr] = DeviceTrack(
                                address=addr,
                                first_cycle=ciclo,
                                last_cycle=ciclo,
                            )
                            nuevos_ciclo.append(addr)
                            conocidos.add(addr)
                        self._tracks[addr].update(rssi, ciclo, servicios)

                scanner = BleakScanner(detection_callback=_cb)
                await scanner.start()
                await asyncio.sleep(self.SCAN_INTERVAL)
                await scanner.stop()

                # ── Snapshot + alertas + render ───────────────────────
                with self._lock:
                    snapshot = list(self._disp.values())

                _evaluar_alertas(snapshot, self._tracks, self._alertas)

                live.update(render_vista(
                    snapshot,
                    self._tracks,
                    t_inicio,
                    ciclo,
                    len(nuevos_ciclo),
                    self._alertas,
                ))

        # Render final estático
        with self._lock:
            snapshot = list(self._disp.values())
        self.console.print(render_vista(
            snapshot, self._tracks, t_inicio, ciclo, 0, self._alertas
        ))

    # ── Resumen final ─────────────────────────────────────────────────

    def _resumen_final(self) -> None:
        with self._lock:
            total = len(self._disp)
        if total == 0:
            return
        self.console.print(Rule(style="dim cyan"))
        self.console.print(Align.center(
            f"[dim]Sesión completada — "
            f"[bold white]{total}[/bold white] dispositivos únicos  ·  "
            f"[bold white]{len(self._alertas)}[/bold white] alertas generadas[/dim]"
        ))
        self.console.print(Rule(style="dim cyan"))
        self.console.print()

    # ── Evidencia ─────────────────────────────────────────────────────

    def _guardar_evidencia(self) -> None:
        gp = getattr(self.bt, "gp", None)
        if not gp:
            return
        with self._lock:
            dispositivos = list(self._disp.values())
        if not dispositivos:
            return
        try:
            tracks_data = {
                addr: {
                    "ema_rssi":    round(tr.ema_rssi, 1),
                    "tendencia":   tr.tendencia(),
                    "tipo":        tr.tipo,
                    "ciclos_visto": tr.last_cycle - tr.first_cycle + 1,
                }
                for addr, tr in self._tracks.items()
            }
            gp.registrar_evidencia(
                "bt_mapa_radar",
                f"BLE Radar: {len(dispositivos)} dispositivos — "
                f"{len(self._alertas)} alertas",
                {
                    "timestamp":    datetime.now().isoformat(),
                    "total":        len(dispositivos),
                    "alertas":      self._alertas,
                    "dispositivos": [d.to_dict() for d in dispositivos],
                    "tracks":       tracks_data,
                },
            )
            cercanos = [d for d in dispositivos if d.rssi >= -65]
            for d in cercanos:
                tr = self._tracks.get(d.address)
                gp.registrar_hallazgo(
                    "MEDIO",
                    f"BLE cercano: {d.nombre or d.address}",
                    f"MAC: {d.address}  RSSI: {d.rssi} dBm  "
                    f"EMA: {round(tr.ema_rssi)}  "
                    f"Tendencia: {tr.tendencia()}  Fab: {d.fabricante}",
                    "Verificar si es un dispositivo autorizado.",
                )
        except Exception as e:
            self._info(f"Evidencia no guardada: {e}")
