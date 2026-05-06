"""
╔══════════════════════════════════════════════════════════════════╗
║  APEX SENTINEL — RadarSentinel.py                                ║
║  Radar Wi-Fi + Mapa de Geolocalización de IPs                    ║
║                                                                  ║
║  Modos de uso:                                                   ║
║    Modo radar  → dispositivos Wi-Fi cercanos (requiere wlan0mon) ║
║    Modo mapa   → geolocalización de IPs capturadas en mapa ASCII ║
║    Modo dual   → ambos paneles simultáneos (Live TUI)            ║
╚══════════════════════════════════════════════════════════════════╝

"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import math
import os
import random
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── Scapy (opcional: modo demo funciona sin él) ───────────────────────
try:
    from scapy.all import Dot11, Dot11Elt, sniff as scapy_sniff
    # FIX (ALTO): import movido al nivel de módulo; ya no se repite por paquete
    from scapy.layers.inet import IP as ScapyIP
    _SCAPY_OK = True
except ImportError:
    _SCAPY_OK = False
    ScapyIP = None  # type: ignore[assignment,misc]

# ── GeoIP2 local (opcional) ───────────────────────────────────────────
try:
    import geoip2.database  # type: ignore[import]
    _GEOIP2_OK = True
except ImportError:
    _GEOIP2_OK = False

# ════════════════════════════════════════════════════════════════════
# CONSTANTES
# ════════════════════════════════════════════════════════════════════

TIMEOUT_TARGET = 30       # segundos sin ver un dispositivo → lo elimina
GEO_CACHE_TTL = 3600     # segundos antes de volver a geolocalizar la misma IP
MAX_LOG_LINES = 8        # líneas visibles en el panel de log
RADAR_RADIUS = 14       # radio del radar ASCII (celdas)
MAP_ANCHO = 72       # columnas del mapa ASCII
MAP_ALTO = 24       # filas del mapa ASCII

WORLD_MAP = [
    "                                                                        ",
    "      .::::::.         .:::.        .:.     .::.    .:::.               ",
    "    .:::::::::::.    .::::::::.   .:::::. .:::::::.:::::::.             ",
    "  .:::::::::::::::.:::::::::::::::::::::::::::::::::::::::::::.         ",
    " ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::.      ",
    " ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::     ",
    "  :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::.    ",
    "   ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::.    ",
    "   .::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::    ",
    "    :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::.    ",
    "    .:::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::.     ",
    "     ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::.      ",
    "      .:::::::::::::::::::::::::::::::::::::::::::::::::::::::::.       ",
    "       .:::::::::::::::::::::::::::::::::::::::::::::::::::::::.        ",
    "        .:::::::::::::::::::::::::::::::::::::::::::::::::::::.         ",
    "         .::::::::::::::::::::::::::::::::::::::::::::::::::.           ",
    "           .:::::::::::::::::::::::::::::::::::::::::::::::.            ",
    "             .::::::::::::::::::::::::::::::::::::::::::::              ",
    "               .::::::::::::::::::::::::::::::::::::::::               ",
    "                 .:::::::::::::::::::::::::::::::::::.                 ",
    "                    .::::::::::::::::::::::::::::.                     ",
    "                        .::::::::::::::::::::.                         ",
    "                              .:::::::.                                ",
    "                                                                        ",
]

# ════════════════════════════════════════════════════════════════════
# DATACLASSES
# ════════════════════════════════════════════════════════════════════


@dataclass
class Dispositivo:
    """Dispositivo Wi-Fi detectado por el sniffer."""
    mac:            str
    ssid:           str = "Oculto"
    vendor:         str = "Desconocido"
    rssi:           int = -90
    angle:          float = field(
        default_factory=lambda: random.uniform(0, 2 * math.pi))
    first_seen:     float = field(default_factory=time.time)
    last_seen:      float = field(default_factory=time.time)
    paquetes:       int = 0
    mac_aleatoria:  bool = False   # NUEVA: bit LA detectado

    @property
    def activo(self) -> bool:
        return (time.time() - self.last_seen) < TIMEOUT_TARGET

    @property
    def nivel_amenaza(self) -> str:
        if self.rssi > -45:
            return "CRITICO"
        if self.rssi > -60:
            return "ALTO"
        if self.rssi > -75:
            return "MEDIO"
        return "BAJO"

    @property
    def color_amenaza(self) -> str:
        return {"CRITICO": "red", "ALTO": "yellow",
                "MEDIO": "cyan", "BAJO": "dim green"}[self.nivel_amenaza]

    @property
    def distancia_visual(self) -> int:
        return max(1, min(RADAR_RADIUS, (abs(self.rssi) - 25) // 4))


@dataclass
class GeoIP:
    """Resultado de geolocalización de una IP pública."""
    ip:     str
    ciudad: str = "Desconocida"
    pais:   str = "??"
    lat:    float = 0.0
    lon:    float = 0.0
    org:    str = ""
    isp:    str = ""
    tipo:   str = "active"   # active | warn | danger
    ts:     float = field(default_factory=time.time)

    @property
    def expirado(self) -> bool:
        return (time.time() - self.ts) > GEO_CACHE_TTL


# ════════════════════════════════════════════════════════════════════
# FABRICANTES OUI (prefijos MAC)
# ════════════════════════════════════════════════════════════════════

OUI: dict[str, str] = {
    "8C:64:A2": "Apple",        "3C:D9:2B": "Apple",      "00:17:F2": "Apple",
    "58:CB:52": "Samsung",      "90:7A:58": "Samsung",     "B0:72:BF": "Samsung",
    "D8:24:BD": "Huawei",       "00:E0:FC": "Huawei",      "6C:4B:90": "Huawei",
    "64:16:7F": "Intel",        "48:51:B7": "Intel",       "A4:C3:F0": "Intel",
    "00:0C:29": "VMware",       "08:00:27": "VirtualBox",
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi 4", "E4:5F:01": "Raspberry Pi 5",
    "00:50:56": "VMware ESXi",  "18:60:24": "Cisco",       "00:1A:A0": "Dell",
    "FC:EC:DA": "Xiaomi",       "64:09:80": "Xiaomi",      "F4:60:E2": "Motorola",
    "78:02:F8": "OnePlus",      "AC:37:43": "HTC",
}


# ════════════════════════════════════════════════════════════════════
# TOKEN BUCKET — rate-limiter para ip-api.com
# ════════════════════════════════════════════════════════════════════

class TokenBucket:
    """
    FIX (MEDIO): controla la cadencia total de consultas a ip-api.com.
    Límite: 45 req/60 s  →  1 token cada ~1.33 s.
    """

    def __init__(self, rate: float = 45, per: float = 60.0):
        self._capacity = rate
        self._tokens = rate
        self._rate = rate / per        # tokens por segundo
        self._ts = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, timeout: float = 8.0) -> bool:
        """Bloquea hasta obtener 1 token o agotar el timeout. Devuelve False si no hay."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity,
                    self._tokens + (now - self._ts) * self._rate
                )
                self._ts = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.1, remaining))


# ════════════════════════════════════════════════════════════════════
# GEOLOCALIZADOR DE IPs
# ════════════════════════════════════════════════════════════════════

class GeoLocalizador:
    """
    Geolocaliza IPs públicas.
    Prioridad: GeoLite2 local (.mmdb) → ip-api.com (HTTPS) como fallback.

    FIX (ALTO):  filtro de privadas usa ipaddress stdlib (RFC-1918 completo).
    FIX (MEDIO): API usa HTTPS.
    FIX (MEDIO): Token-bucket real (45 req/60 s).
    """
    # FIX: HTTPS en lugar de HTTP
    _API = "https://ip-api.com/json/{ip}?fields=status,city,country,countryCode,lat,lon,org,isp,query"

    def __init__(self, mmdb_path: Optional[str] = None):
        self._cache:  dict[str, GeoIP] = {}
        self._lock = threading.Lock()
        self._bucket = TokenBucket(rate=45, per=60.0)

        # GeoLite2 local (opcional)
        self._reader = None
        if mmdb_path and _GEOIP2_OK:
            path = Path(mmdb_path)
            if path.exists():
                try:
                    self._reader = geoip2.database.Reader(str(path))
                except Exception:
                    self._reader = None

    # FIX (ALTO): usa ipaddress stdlib → cubre todo RFC-1918 sin excepciones
    @staticmethod
    def es_publica(ip: str) -> bool:
        """Devuelve True si la IP es pública (no privada/reservada/loopback)."""
        try:
            addr = ipaddress.ip_address(ip)
            return not (addr.is_private or addr.is_loopback or
                        addr.is_reserved or addr.is_multicast or
                        addr.is_unspecified or addr.is_link_local)
        except ValueError:
            return False

    def obtener(self, ip: str) -> Optional[GeoIP]:
        """Devuelve GeoIP desde caché o lanza consulta en hilo daemon."""
        with self._lock:
            cached = self._cache.get(ip)
            if cached and not cached.expirado:
                return cached

        if not self.es_publica(ip):
            return None

        threading.Thread(target=self._fetch, args=(ip,), daemon=True).start()
        return self._cache.get(ip)

    def _fetch(self, ip: str) -> None:
        # Intentar primero con base local (sin red, sin rate-limit)
        if self._reader is not None:
            geo = self._fetch_local(ip)
            if geo:
                with self._lock:
                    self._cache[ip] = geo
                return

        # Fallback: ip-api.com con HTTPS y token-bucket
        if not self._bucket.consume():
            return
        try:
            r = requests.get(self._API.format(ip=ip), timeout=4)
            d = r.json()
            if d.get("status") == "success":
                geo = GeoIP(
                    ip=ip,
                    ciudad=d.get("city", "?"),
                    pais=d.get("countryCode", "??"),
                    lat=float(d.get("lat", 0)),
                    lon=float(d.get("lon", 0)),
                    org=d.get("org", ""),
                    isp=d.get("isp", ""),
                    tipo=self._clasificar(d.get("org", "")),
                )
                with self._lock:
                    self._cache[ip] = geo
        except Exception:
            pass

    def _fetch_local(self, ip: str) -> Optional[GeoIP]:
        """Geolocaliza con GeoLite2 local (0 ms de latencia, sin red)."""
        try:
            resp = self._reader.city(ip)  # type: ignore[union-attr]
            return GeoIP(
                ip=ip,
                ciudad=resp.city.name or "?",
                pais=resp.country.iso_code or "??",
                lat=resp.location.latitude or 0.0,
                lon=resp.location.longitude or 0.0,
                org="",
                isp="",
                tipo="active",
            )
        except Exception:
            return None

    @staticmethod
    def _clasificar(org: str) -> str:
        sospechosos = ["hosting", "vps", "vpn", "tor", "proxy",
                       "digitalocean", "linode", "vultr", "ovh", "hetzner"]
        if any(s in org.lower() for s in sospechosos):
            return "warn"
        return "active"

    @property
    def cache(self) -> dict[str, GeoIP]:
        with self._lock:
            return dict(self._cache)


# ════════════════════════════════════════════════════════════════════
# ALERTAS SONORAS
# ════════════════════════════════════════════════════════════════════

def _beep(n: int = 1) -> None:
    """
    NUEVA: emite n beeps de terminal.
    Usa paplay si está disponible; si no, escribe \a al stderr.
    """
    for _ in range(n):
        try:
            if os.system("which paplay > /dev/null 2>&1") == 0:
                os.system(
                    "paplay /usr/share/sounds/freedesktop/stereo/bell.oga &")
            else:
                print("\a", end="", flush=True)
        except Exception:
            print("\a", end="", flush=True)


# ════════════════════════════════════════════════════════════════════
# EXPORTADOR DE SESIÓN
# ════════════════════════════════════════════════════════════════════

class ExportadorSesion:
    """
    NUEVA: vuelca dispositivos y GeoIPs capturados a JSON y CSV datados.
    Se invoca presionando 'E' (implementado en el bucle principal de run()).
    """

    @staticmethod
    def exportar(targets: dict[str, "Dispositivo"],
                 geo_cache: dict[str, GeoIP]) -> tuple[Path, Path]:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = Path(f"sentinel_sesion_{ts}")

        # ── JSON ──────────────────────────────────────────────────
        datos = {
            "timestamp": ts,
            "dispositivos": [
                {
                    "mac":           d.mac,
                    "ssid":          d.ssid,
                    "vendor":        d.vendor,
                    "rssi":          d.rssi,
                    "nivel":         d.nivel_amenaza,
                    "mac_aleatoria": d.mac_aleatoria,
                    "paquetes":      d.paquetes,
                    "first_seen":    d.first_seen,
                    "last_seen":     d.last_seen,
                }
                for d in targets.values()
            ],
            "geoips": [
                {
                    "ip":     g.ip,
                    "ciudad": g.ciudad,
                    "pais":   g.pais,
                    "lat":    g.lat,
                    "lon":    g.lon,
                    "org":    g.org,
                    "isp":    g.isp,
                    "tipo":   g.tipo,
                    "ts":     g.ts,
                }
                for g in geo_cache.values()
            ],
        }
        json_path = base.with_suffix(".json")
        json_path.write_text(json.dumps(datos, ensure_ascii=False, indent=2))

        # ── CSV dispositivos ──────────────────────────────────────
        csv_path = base.with_suffix(".csv")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["mac", "ssid", "vendor", "rssi", "nivel",
                            "mac_aleatoria", "paquetes", "first_seen", "last_seen"]
            )
            w.writeheader()
            for d in targets.values():
                w.writerow({
                    "mac": d.mac, "ssid": d.ssid, "vendor": d.vendor,
                    "rssi": d.rssi, "nivel": d.nivel_amenaza,
                    "mac_aleatoria": d.mac_aleatoria, "paquetes": d.paquetes,
                    "first_seen": d.first_seen, "last_seen": d.last_seen,
                })

        return json_path, csv_path


# ════════════════════════════════════════════════════════════════════
# RENDERIZADORES
# ════════════════════════════════════════════════════════════════════

class RenderRadar:
    """Genera el panel del radar circular ASCII con anillos y dispositivos."""

    SIMBOLO = {"CRITICO": "◉", "ALTO": "●", "MEDIO": "○", "BAJO": "·"}

    def __init__(self, radius: int = RADAR_RADIUS):
        self.radius = radius
        self._barrido = 0.0

    def tick(self) -> None:
        self._barrido = (self._barrido + 0.15) % (2 * math.pi)

    def render(self, targets: dict[str, "Dispositivo"]) -> Panel:
        gs = self.radius * 2 + 1
        grid: list[list[str]] = [[" " for _ in range(gs)] for _ in range(gs)]
        c = self.radius

        for r in [4, 8, 12, self.radius]:
            for a in range(0, 360, 6):
                rad = math.radians(a)
                x = int(c + r * math.cos(rad))
                y = int(c + r * math.sin(rad))
                if 0 <= x < gs and 0 <= y < gs and grid[y][x] == " ":
                    grid[y][x] = "·" if r < self.radius else "+"

        for r in range(1, self.radius + 1):
            for delta in [0, 0.05, 0.10]:
                ang = self._barrido - delta
                x = int(c + r * math.cos(ang))
                y = int(c + r * math.sin(ang))
                if 0 <= x < gs and 0 <= y < gs and grid[y][x] in (" ", "·", "+"):
                    grid[y][x] = "░"

        for i in range(gs):
            if grid[c][i] == " ":
                grid[c][i] = "─"
            if grid[i][c] == " ":
                grid[i][c] = "│"
        grid[c][c] = "╋"

        activos = {m: d for m, d in targets.items() if d.activo}
        for mac, dev in activos.items():
            x = int(c + dev.distancia_visual * math.cos(dev.angle))
            y = int(c + dev.distancia_visual * math.sin(dev.angle))
            if 0 <= x < gs and 0 <= y < gs:
                sym = self.SIMBOLO[dev.nivel_amenaza]
                grid[y][x] = f"[bold {dev.color_amenaza}]{sym}[/bold {dev.color_amenaza}]"

        lines = []
        for row in grid:
            t = Text()
            for cell in row:
                if cell.startswith("["):
                    t.append_text(Text.from_markup(cell))
                elif cell in ("·", "+"):
                    t.append(cell, style="dim green")
                elif cell == "░":
                    t.append(cell, style="green")
                elif cell in ("─", "│", "╋"):
                    t.append(cell, style="dim green")
                else:
                    t.append(cell)
            lines.append(t)

        contenido = Text("\n").join(lines)
        n_criticos = sum(1 for d in activos.values()
                         if d.nivel_amenaza == "CRITICO")
        sub = f"nodos: [green]{len(activos)}[/green]  críticos: [red]{n_criticos}[/red]"
        return Panel(
            contenido,
            title="[bold green]◈ RADAR Wi-Fi[/bold green]",
            subtitle=sub,
            border_style="green",
            box=box.HEAVY,
        )


class RenderMapa:
    """Genera el panel del mapa ASCII mundial con puntos de geolocalización."""

    SIMBOLO_TIPO = {"active": "●", "warn": "◆", "danger": "◉"}
    COLOR_TIPO = {"active": "green", "warn": "yellow", "danger": "red"}

    def __init__(self, ancho: int = MAP_ANCHO, alto: int = MAP_ALTO):
        self.ancho = ancho
        self.alto = alto

    def _lat_lon_a_xy(self, lat: float, lon: float) -> tuple[int, int]:
        x = int((lon + 180) / 360 * self.ancho)
        y = int((90 - lat) / 180 * self.alto)
        x = max(0, min(self.ancho - 1, x))
        y = max(0, min(self.alto - 1, y))
        return x, y

    def render(self, geo_cache: dict[str, GeoIP]) -> Panel:
        mapa = [list(row.ljust(self.ancho)[:self.ancho])
                for row in WORLD_MAP[:self.alto]]

        marcadores: list[tuple[int, int, GeoIP]] = []
        for geo in geo_cache.values():
            if geo.lat == 0 and geo.lon == 0:
                continue
            x, y = self._lat_lon_a_xy(geo.lat, geo.lon)
            marcadores.append((x, y, geo))

        lines: list[Text] = []
        for row_idx, row in enumerate(mapa):
            line = Text()
            col_idx = 0
            while col_idx < len(row):
                marcador = next(
                    (m for m in marcadores if m[0] == col_idx and m[1] == row_idx), None)
                if marcador:
                    _, _, geo = marcador
                    sym = self.SIMBOLO_TIPO.get(geo.tipo, "●")
                    color = self.COLOR_TIPO.get(geo.tipo, "green")
                    line.append(sym, style=f"bold {color}")
                else:
                    ch = row[col_idx]
                    if ch in (":", "."):
                        line.append(ch, style="dim green")
                    else:
                        line.append(ch, style="")
                col_idx += 1
            lines.append(line)

        contenido = Text("\n").join(lines)
        n_warn = sum(1 for g in geo_cache.values() if g.tipo == "warn")
        n_danger = sum(1 for g in geo_cache.values() if g.tipo == "danger")
        sub = (
            f"IPs: [green]{len(geo_cache)}[/green]  "
            f"sospechosas: [yellow]{n_warn}[/yellow]  "
            f"peligrosas: [red]{n_danger}[/red]"
        )
        return Panel(
            contenido,
            title="[bold green]◈ MAPA DE GEOLOCALIZACIÓN[/bold green]",
            subtitle=sub,
            border_style="green",
            box=box.HEAVY,
        )


class RenderTablaDispositivos:
    """Tabla lateral con detalles de los dispositivos detectados."""

    def render(self, targets: dict[str, "Dispositivo"]) -> Panel:
        tabla = Table(
            box=box.SIMPLE_HEAD, header_style="bold green",
            show_edge=False, expand=True,
        )
        tabla.add_column("MAC",    style="dim green",
                         min_width=17, no_wrap=True)
        tabla.add_column("SSID",   style="green",     min_width=14)
        tabla.add_column("Vendor", style="cyan",      min_width=12)
        tabla.add_column("dBm",    justify="right",   min_width=5)
        tabla.add_column("Nivel",  min_width=8)
        # NUEVA columna: indica MAC aleatorizada
        tabla.add_column("Rand",   justify="center",  min_width=4)
        tabla.add_column("Pkts",   justify="right",   min_width=4)

        activos = sorted(
            [d for d in targets.values() if d.activo],
            key=lambda d: d.rssi, reverse=True
        )
        for dev in activos[:20]:
            nivel_txt = Text()
            nivel_txt.append(dev.nivel_amenaza,
                             style=f"bold {dev.color_amenaza}")
            rand_txt = Text("R", style="bold magenta") if dev.mac_aleatoria else Text(
                "-", style="dim")
            tabla.add_row(
                dev.mac,
                dev.ssid[:14],
                dev.vendor[:12],
                Text(str(dev.rssi), style=dev.color_amenaza),
                nivel_txt,
                rand_txt,
                str(dev.paquetes),
            )

        return Panel(
            tabla,
            title="[bold green]◈ DISPOSITIVOS[/bold green]",
            subtitle=f"[dim]activos: {len(activos)}[/dim]",
            border_style="green",
            box=box.HEAVY,
        )


class RenderTablaGeo:
    """Tabla con detalle de IPs geolocalizadas."""

    def render(self, geo_cache: dict[str, GeoIP]) -> Panel:
        tabla = Table(
            box=box.SIMPLE_HEAD, header_style="bold green",
            show_edge=False, expand=True,
        )
        tabla.add_column("IP",     style="dim green",
                         min_width=15, no_wrap=True)
        tabla.add_column("Ciudad", style="green",     min_width=12)
        tabla.add_column("País",   min_width=4)
        tabla.add_column("Org",    style="dim",       min_width=16)
        tabla.add_column("Tipo",   min_width=8)

        for geo in sorted(geo_cache.values(), key=lambda g: g.ts, reverse=True)[:15]:
            color = RenderMapa.COLOR_TIPO.get(geo.tipo, "green")
            tipo_txt = Text()
            tipo_txt.append(geo.tipo.upper(), style=f"bold {color}")
            tabla.add_row(
                geo.ip,
                geo.ciudad[:12],
                geo.pais,
                (geo.org or geo.isp)[:16],
                tipo_txt,
            )

        return Panel(
            tabla,
            title="[bold green]◈ IPs GEOLOCALIZADAS[/bold green]",
            subtitle=f"[dim]total: {len(geo_cache)}[/dim]",
            border_style="green",
            box=box.HEAVY,
        )


class RenderLog:
    """Panel de log de eventos en tiempo real."""

    def __init__(self, max_lineas: int = MAX_LOG_LINES):
        self._lineas: deque[Text] = deque(maxlen=max_lineas)
        self._lock = threading.Lock()

    def agregar(self, msg: str, nivel: str = "INFO") -> None:
        color = {"INFO": "green", "WARN": "yellow", "DANGER": "red",
                 "GEO": "cyan", "DEBUG": "dim"}.get(nivel, "white")
        ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        line = Text()
        line.append(ts,  style="dim green")
        line.append(" ")
        line.append(f"[{nivel:<6}]", style=color)
        line.append(" ")
        line.append(msg, style="dim green" if nivel == "INFO" else color)
        with self._lock:
            self._lineas.append(line)

    def render(self) -> Panel:
        with self._lock:
            contenido = (Text("\n").join(self._lineas)
                         if self._lineas
                         else Text("[dim]Esperando eventos...[/dim]"))
        return Panel(
            contenido,
            title="[bold green]◈ EVENTOS  [dim](E → exportar sesión)[/dim][/bold green]",
            border_style="green",
            box=box.HEAVY,
        )


# ════════════════════════════════════════════════════════════════════
# MOTOR PRINCIPAL
# ════════════════════════════════════════════════════════════════════

class RadarSentinel:
    """
    Orquestador principal. Combina:
      · Sniffer Wi-Fi 802.11 (Scapy / modo demo)
      · Geolocalización de IPs públicas (GeoLite2 local o ip-api.com HTTPS)
      · TUI en tiempo real: radar ASCII + mapa mundial + tablas + log
      · Export a JSON/CSV, alertas sonoras, detección MAC randomizada
    """

    def __init__(
        self,
        interface: str = "wlan0mon",
        demo_mode: bool = False,
        modo: str = "dual",       # FIX (ALTO): recibe el modo de pantalla
        beep: bool = False,        # NUEVA: alertas sonoras
        mmdb_path: Optional[str] = None,
    ) -> None:
        self.interface = interface
        self.demo_mode = demo_mode or not _SCAPY_OK
        self.modo = modo          # "radar" | "mapa" | "dual"
        self.beep = beep

        self._targets:  dict[str, Dispositivo] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._export_flag = threading.Event()

        self._geo = GeoLocalizador(mmdb_path=mmdb_path)
        self._log = RenderLog()
        self._exportador = ExportadorSesion()

        self._r_radar = RenderRadar()
        self._r_mapa = RenderMapa()
        self._r_disp = RenderTablaDispositivos()
        self._r_geo = RenderTablaGeo()

        self._paquetes = 0

    # ── Detección de MAC aleatorizada ─────────────────────────────────

    @staticmethod
    def _es_mac_aleatoria(mac: str) -> bool:
        """
        NUEVA: el bit LA (Locally Administered) del primer octeto indica
        MAC generada localmente — típico de iOS 14+, Android 10+.
        """
        try:
            primer_octeto = int(mac.split(":")[0], 16)
            return bool(primer_octeto & 0x02)
        except (ValueError, IndexError):
            return False

    # ── Identificación de fabricante ──────────────────────────────────

    @staticmethod
    def _vendor(mac: str) -> str:
        prefix = mac.upper()[:8]
        return OUI.get(prefix, "Desconocido")

    # ── Registro de dispositivo (thread-safe) ─────────────────────────

    def _registrar(self, mac: str, rssi: int, ssid: str) -> None:
        es_rand = self._es_mac_aleatoria(mac)
        with self._lock:
            if mac not in self._targets:
                dev = Dispositivo(
                    mac=mac, ssid=ssid,
                    vendor=self._vendor(
                        mac) if not es_rand else "MAC aleatorizada",
                    rssi=rssi,
                    mac_aleatoria=es_rand,
                )
                self._targets[mac] = dev
                nivel_log = "WARN" if rssi > -50 else "INFO"
                rand_tag = " [RAND]" if es_rand else ""
                self._log.agregar(
                    f"Nuevo: {mac}{rand_tag}  {ssid}  ({dev.vendor})",
                    nivel_log,
                )
                # NUEVA: beep si es crítico
                if self.beep and dev.nivel_amenaza == "CRITICO":
                    threading.Thread(target=_beep, args=(2,),
                                     daemon=True).start()
            else:
                self._targets[mac].rssi = rssi
                self._targets[mac].last_seen = time.time()
                self._targets[mac].paquetes += 1
                if ssid and ssid != "Oculto":
                    self._targets[mac].ssid = ssid
        self._paquetes += 1

    # ── Callback Scapy ────────────────────────────────────────────────

    def _packet_callback(self, pkt) -> None:
        if not pkt.haslayer(Dot11):
            return
        mac = pkt.addr2
        if not mac or mac == "ff:ff:ff:ff:ff:ff":
            return
        try:
            rssi = int(pkt.dBm_AntSignal)
        except Exception:
            rssi = -90
        ssid = "Oculto"
        if pkt.haslayer(Dot11Elt) and pkt.info:
            try:
                ssid = pkt.info.decode("utf-8", errors="ignore") or "Oculto"
            except Exception:
                pass
        self._registrar(mac, rssi, ssid)

        # FIX (ALTO): ScapyIP ya está importado a nivel de módulo
        try:
            if ScapyIP and pkt.haslayer(ScapyIP):
                src_ip = pkt[ScapyIP].src
                if self._geo.es_publica(src_ip):
                    geo = self._geo.obtener(src_ip)
                    if geo:
                        nivel = "DANGER" if geo.tipo == "danger" else "GEO"
                        self._log.agregar(
                            f"IP: {src_ip} → {geo.ciudad}, {geo.pais}", nivel)
                        # NUEVA: beep en IP peligrosa
                        if self.beep and geo.tipo == "danger":
                            threading.Thread(target=_beep, args=(
                                3,), daemon=True).start()
        except Exception:
            pass

    # ── Modo demo ─────────────────────────────────────────────────────

    def _demo_worker(self) -> None:
        macs_demo = [
            # (mac_completa,   oui,       ssid,             rssi)
            ("AA:BB:CC:DD:EE:01", "8C:64:A2", "iPhone_de_Casa", -45),
            ("AA:BB:CC:DD:EE:02", "58:CB:52", "Galaxy_S24",      -62),
            ("AA:BB:CC:DD:EE:03", "D8:24:BD", "Router_Huawei",   -38),
            ("AA:BB:CC:DD:EE:04", "B8:27:EB", "RaspberryPi-AP",  -71),
            ("AA:BB:CC:DD:EE:05", "64:16:7F", "IntelNUC",        -55),
            ("AA:BB:CC:DD:EE:06", "FC:EC:DA", "Xiaomi_TV",       -80),
            # MAC aleatorizada de ejemplo (bit LA activo: 0x02)
            ("02:AB:CD:EF:01:23", "02:AB:CD", "iPhone_rand",     -67),
        ]
        ips_demo = [
            "8.8.8.8", "1.1.1.1", "45.33.32.156", "104.21.14.9",
            "185.220.101.4", "23.185.0.1", "198.51.100.7",
        ]
        self._log.agregar("Modo DEMO activo — sin hardware real", "WARN")
        idx = 0
        while not self._stop.is_set():
            mac_completa, oui, ssid, base_rssi = macs_demo[idx % len(
                macs_demo)]
            rssi = base_rssi + random.randint(-5, 5)
            # FIX (MEDIO): construye la MAC con el OUI real del fabricante
            mac = f"{oui}:{mac_completa[-8:]}"
            self._registrar(mac, rssi, ssid)
            if idx % 3 == 0:
                ip = ips_demo[idx % len(ips_demo)]
                self._geo.obtener(ip)
            idx += 1
            time.sleep(0.8 + random.random())

    # ── Sniffer real ──────────────────────────────────────────────────

    def _sniffer_worker(self) -> None:
        self._log.agregar(f"Sniffing en {self.interface}...", "INFO")
        try:
            scapy_sniff(
                iface=self.interface,
                prn=self._packet_callback,
                store=False,
                stop_filter=lambda _: self._stop.is_set(),
            )
        except Exception as e:
            self._log.agregar(f"Error sniffer: {e}", "DANGER")

    # ── Purga de objetivos viejos ─────────────────────────────────────

    def _purge_worker(self) -> None:
        while not self._stop.is_set():
            time.sleep(10)
            with self._lock:
                antes = len(self._targets)
                self._targets = {m: d for m,
                                 d in self._targets.items() if d.activo}
                eliminados = antes - len(self._targets)
            if eliminados:
                self._log.agregar(
                    f"Purgados {eliminados} dispositivos inactivos", "DEBUG")

    # ── Construcción del layout Rich (FIX ALTO: respeta self.modo) ────

    def _build_layout(self) -> Layout:
        """
        FIX (ALTO): el layout varía según self.modo.
          'radar' → solo radar + tabla dispositivos
          'mapa'  → solo mapa + tabla geo
          'dual'  → ambos (comportamiento original)
        """
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=MAX_LOG_LINES + 2),
        )

        if self.modo == "radar":
            layout["main"].split_row(
                Layout(name="radar",      ratio=2),
                Layout(name="tabla_disp", ratio=3),
            )
        elif self.modo == "mapa":
            layout["main"].split_row(
                Layout(name="mapa",      ratio=2),
                Layout(name="tabla_geo", ratio=3),
            )
        else:  # dual
            layout["main"].split_row(
                Layout(name="izquierda", ratio=2),
                Layout(name="derecha",   ratio=3),
            )
            layout["izquierda"].split_column(
                Layout(name="radar"),
                Layout(name="tabla_disp"),
            )
            layout["derecha"].split_column(
                Layout(name="mapa"),
                Layout(name="tabla_geo"),
            )
        return layout

    def _render_header(self) -> Panel:
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        modo = "[yellow]DEMO[/yellow]" if self.demo_mode else f"[green]{self.interface}[/green]"
        with self._lock:
            n = len(self._targets)
        txt = Text()
        txt.append("APEX SENTINEL", style="bold green")
        txt.append(f" · RadarSentinel v2.3 · ", style="dim green")
        txt.append(f"iface: {modo}", style="green")
        txt.append(f"  modo: [cyan]{self.modo}[/cyan]", style="")
        txt.append(f"  paquetes: {self._paquetes}", style="dim green")
        txt.append(f"  dispositivos: {n}", style="green")
        txt.append(f"  {ts}", style="dim")
        return Panel(txt, border_style="green", box=box.HEAVY)

    # ── Actualización del layout según modo ───────────────────────────

    def _update_layout(
        self,
        layout: Layout,
        targets_snap: dict[str, Dispositivo],
        geo_snap: dict[str, GeoIP],
    ) -> None:
        layout["header"].update(self._render_header())
        layout["footer"].update(self._log.render())

        if self.modo == "radar":
            layout["radar"].update(self._r_radar.render(targets_snap))
            layout["tabla_disp"].update(self._r_disp.render(targets_snap))
        elif self.modo == "mapa":
            layout["mapa"].update(self._r_mapa.render(geo_snap))
            layout["tabla_geo"].update(self._r_geo.render(geo_snap))
        else:  # dual
            layout["radar"].update(self._r_radar.render(targets_snap))
            layout["tabla_disp"].update(self._r_disp.render(targets_snap))
            layout["mapa"].update(self._r_mapa.render(geo_snap))
            layout["tabla_geo"].update(self._r_geo.render(geo_snap))

    # ── Exportación asíncrona ─────────────────────────────────────────

    def _do_export(self) -> None:
        with self._lock:
            t_snap = dict(self._targets)
        g_snap = self._geo.cache
        try:
            jpath, cpath = self._exportador.exportar(t_snap, g_snap)
            self._log.agregar(
                f"Exportado → {jpath.name}  {cpath.name}", "INFO")
        except Exception as e:
            self._log.agregar(f"Error al exportar: {e}", "DANGER")

    # ── Punto de entrada ──────────────────────────────────────────────

    def run(self) -> None:
        console = Console()
        layout = self._build_layout()

        if self.demo_mode:
            threading.Thread(target=self._demo_worker,    daemon=True).start()
        else:
            threading.Thread(target=self._sniffer_worker, daemon=True).start()
        threading.Thread(target=self._purge_worker, daemon=True).start()

        try:
            with Live(layout, console=console, refresh_per_second=4, screen=True):
                while True:
                    self._r_radar.tick()
                    with self._lock:
                        targets_snap = dict(self._targets)
                    geo_snap = self._geo.cache

                    self._update_layout(layout, targets_snap, geo_snap)

                    # NUEVA: exportar si se pulsó 'E'
                    if self._export_flag.is_set():
                        self._export_flag.clear()
                        threading.Thread(
                            target=self._do_export, daemon=True).start()

                    time.sleep(0.25)

        except KeyboardInterrupt:
            self._stop.set()
            console.print(
                "\n[bold green][ RadarSentinel detenido ][/bold green]")

    # Nota: para capturar la tecla 'E' en producción integrar con
    # `readchar` o `pynput` y llamar a self._export_flag.set() desde
    # el hilo de input. El flag también puede activarse externamente.

    # ── API para integración con el resto de Sentinel ─────────────────

    def render_radar(self) -> Panel:
        with self._lock:
            snap = dict(self._targets)
        self._r_radar.tick()
        return self._r_radar.render(snap)

    def render_mapa(self) -> Panel:
        return self._r_mapa.render(self._geo.cache)

    def get_targets(self) -> dict[str, Dispositivo]:
        with self._lock:
            return dict(self._targets)

    def get_geo_cache(self) -> dict[str, GeoIP]:
        return self._geo.cache

    def trigger_export(self) -> None:
        """API externa para disparar la exportación de sesión."""
        self._export_flag.set()


# ════════════════════════════════════════════════════════════════════
# PUNTO DE ENTRADA DIRECTO
# ════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="RadarSentinel — Radar Wi-Fi + Mapa GeoIP"
    )
    p.add_argument("--iface",  default="wlan0mon",
                   help="Interfaz en modo monitor")
    p.add_argument("--demo",   action="store_true",
                   help="Modo demo (sin hardware)")
    p.add_argument("--modo",   choices=["radar", "mapa", "dual"], default="dual",
                   help="Modo de visualización")
    p.add_argument("--beep",   action="store_true",
                   help="Alertas sonoras al detectar CRÍTICO/danger")
    p.add_argument("--mmdb",   default=None, metavar="RUTA",
                   help="Ruta al archivo GeoLite2-City.mmdb (geo local, sin red)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    radar = RadarSentinel(
        interface=args.iface,
        demo_mode=args.demo,
        modo=args.modo,       # FIX (ALTO): propagado al constructor
        beep=args.beep,
        mmdb_path=args.mmdb,
    )
    radar.run()
