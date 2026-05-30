#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import math
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from rich.align import Align
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich import box

if TYPE_CHECKING:
    pass  # sentinel type imported lazily to avoid circular imports

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

log = logging.getLogger("sentinel.network.wifi_tri")

CONFIG_PATH = Path.home() / ".config" / "wifi-tri" / "config.json"
TX_POWER_DBM = -40.0
PATH_LOSS_EXP = 2.7
MAX_DIST_M = 80.0
SMOOTH_ALPHA = 0.35
MAP_W = 58
MAP_H = 22

AP_STYLES: list[tuple[str, str]] = [
    ("bright_cyan",    "◆"),
    ("bright_yellow",  "★"),
    ("bright_magenta", "▲"),
    ("bright_green",   "●"),
    ("bright_red",     "■"),
    ("orange1",        "◉"),
    ("deep_pink1",     "◈"),
    ("spring_green1",  "⬟"),
]


@dataclass
class APConfig:
    ssid: str
    x:    float
    y:    float


@dataclass
class Config:
    room_w:       float = 20.0
    room_h:       float = 15.0
    tx_power:     float = TX_POWER_DBM
    path_loss_exp: float = PATH_LOSS_EXP
    scan_interval: float = 2.0
    access_points: dict[str, APConfig] = field(default_factory=dict)

    @staticmethod
    def load(path: Path = CONFIG_PATH) -> Config:
        if not path.exists():
            return Config()
        try:
            raw = json.loads(path.read_text())
            cfg = Config(
                room_w=raw.get("room_w", 20.0),
                room_h=raw.get("room_h", 15.0),
                tx_power=raw.get("tx_power", TX_POWER_DBM),
                path_loss_exp=raw.get("path_loss_exp", PATH_LOSS_EXP),
                scan_interval=raw.get("scan_interval", 2.0),
            )
            for bssid, ap in raw.get("access_points", {}).items():
                cfg.access_points[bssid.upper()] = APConfig(
                    ssid=ap["ssid"], x=float(ap["x"]), y=float(ap["y"])
                )
            return cfg
        except Exception:
            return Config()

    def save(self, path: Path = CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "room_w":        self.room_w,
            "room_h":        self.room_h,
            "tx_power":      self.tx_power,
            "path_loss_exp": self.path_loss_exp,
            "scan_interval": self.scan_interval,
            "access_points": {
                bssid: {"ssid": ap.ssid, "x": ap.x, "y": ap.y}
                for bssid, ap in self.access_points.items()
            },
        }, indent=2, ensure_ascii=False))


@dataclass
class AccessPoint:
    ssid:      str
    bssid:     str
    rssi_dbm:  float
    channel:   int = 0
    band:      str = "2.4G"
    distance_m: float = 0.0
    pos_x:     float = -1.0
    pos_y:     float = -1.0
    color:     str = "white"
    icon:      str = "◆"
    history:   list[float] = field(default_factory=list)

    def quality(self) -> int:
        return int(max(0, min(100, 2 * (self.rssi_dbm + 100))))

    def signal_bar(self) -> str:
        q = self.quality()
        filled = round(q / 20)
        color = "bright_green" if q >= 70 else "yellow" if q >= 40 else "bright_red"
        return f"[{color}]{'█' * filled}{'░' * (5 - filled)}[/]"

    def rssi_style(self) -> str:
        if self.rssi_dbm >= -50:
            return "bright_green"
        if self.rssi_dbm >= -65:
            return "green"
        if self.rssi_dbm >= -75:
            return "yellow"
        if self.rssi_dbm >= -85:
            return "orange1"
        return "bright_red"


@dataclass
class TriangulationResult:
    x:            float = 0.0
    y:            float = 0.0
    confidence:   float = 0.0
    error_radius: float = 0.0
    aps_used:     int = 0
    method:       str = "none"


def rssi_to_distance(rssi: float, tx: float, n: float) -> float:
    if rssi >= tx:
        return 0.3
    return min(10.0 ** ((tx - rssi) / (10.0 * n)), MAX_DIST_M)


def _lstsq(rows_A: list[list[float]], rows_b: list[float]) -> tuple[float, float]:
    if _HAS_NUMPY:
        A = np.array(rows_A, dtype=float)
        b = np.array(rows_b, dtype=float)
        r, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        return float(r[0]), float(r[1])

    # Normal equations: (AᵀA)x = Aᵀb
    n = len(rows_A)
    ata = [[0.0, 0.0], [0.0, 0.0]]
    atb = [0.0, 0.0]
    for i in range(n):
        for r in range(2):
            atb[r] += rows_A[i][r] * rows_b[i]
            for c in range(2):
                ata[r][c] += rows_A[i][r] * rows_A[i][c]
    det = ata[0][0] * ata[1][1] - ata[0][1] * ata[1][0]
    if abs(det) < 1e-10:
        raise ValueError("Sistema singular")
    x = (atb[0] * ata[1][1] - atb[1] * ata[0][1]) / det
    y = (ata[0][0] * atb[1] - ata[1][0] * atb[0]) / det
    return x, y


def trilaterate(aps: list[AccessPoint]) -> TriangulationResult:
    known = [ap for ap in aps if ap.pos_x >= 0 and ap.distance_m > 0]

    if len(known) < 2:
        return TriangulationResult(method="insufficient_data")

    if len(known) == 2:
        a, b = known
        wa, wb = 1.0 / max(a.distance_m, 0.1), 1.0 / max(b.distance_m, 0.1)
        wt = wa + wb
        x, y = (a.pos_x * wa + b.pos_x * wb) / \
            wt, (a.pos_y * wa + b.pos_y * wb) / wt
        return TriangulationResult(
            x=x, y=y, confidence=30.0,
            error_radius=abs(a.distance_m - b.distance_m) / 2.0,
            aps_used=2, method="weighted_midpoint",
        )

    ref = known[0]
    rows_A: list[list[float]] = []
    rows_b: list[float] = []

    for ap in known[1:]:
        w = 1.0 / max(ap.distance_m, 0.3)
        # Linearised trilateration: subtract ref equation from each AP equation.
        # 2(xi-x0)x + 2(yi-y0)y = d0²-di² - x0²-y0² + xi²+yi²
        rows_A.append([
            2.0 * (ap.pos_x - ref.pos_x) * w,
            2.0 * (ap.pos_y - ref.pos_y) * w,
        ])
        rows_b.append((
            ref.distance_m ** 2 - ap.distance_m ** 2
            - ref.pos_x ** 2 - ref.pos_y ** 2
            + ap.pos_x ** 2 + ap.pos_y ** 2
        ) * w)

    try:
        x, y = _lstsq(rows_A, rows_b)
    except Exception:
        x, y = ref.pos_x, ref.pos_y

    residuals = [
        abs(math.sqrt((x - ap.pos_x) ** 2 + (y - ap.pos_y) ** 2) - ap.distance_m)
        for ap in known
    ]
    mean_res = sum(residuals) / len(residuals)
    confidence = max(0.0, min(100.0, 100.0 - mean_res * 6.0))

    return TriangulationResult(
        x=x, y=y,
        confidence=confidence,
        error_radius=mean_res,
        aps_used=len(known),
        method="wls",
    )


class WiFiScanner:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._cache: dict[str, AccessPoint] = {}
        self._si = 0
        self._os = platform.system()

    def _next_style(self) -> tuple[str, str]:
        color, icon = AP_STYLES[self._si % len(AP_STYLES)]
        self._si += 1
        return color, icon

    def scan(self) -> list[AccessPoint]:
        raw = {
            "Linux":   self._linux,
            "Darwin":  self._macos,
            "Windows": self._windows,
        }.get(self._os, lambda: [])()
        return self._build(raw)

    def _build(self, raw: list[Dict]) -> list[AccessPoint]:
        result: list[AccessPoint] = []
        for entry in raw:
            bssid = entry["bssid"].upper()
            rssi = float(entry["rssi"])

            if bssid in self._cache:
                ap = self._cache[bssid]
                ap.rssi_dbm = SMOOTH_ALPHA * rssi + \
                    (1.0 - SMOOTH_ALPHA) * ap.rssi_dbm
                ap.ssid = entry.get("ssid", ap.ssid) or ap.ssid
                ap.channel = entry.get("channel", ap.channel)
                ap.band = entry.get("band",    ap.band)
            else:
                color, icon = self._next_style()
                ap = AccessPoint(
                    ssid=entry.get("ssid", "<oculto>") or "<oculto>",
                    bssid=bssid,
                    rssi_dbm=rssi,
                    channel=entry.get("channel", 0),
                    band=entry.get("band", "2.4G"),
                    color=color,
                    icon=icon,
                )
                self._cache[bssid] = ap

            ap.history.append(ap.rssi_dbm)
            if len(ap.history) > 12:
                ap.history.pop(0)

            ap.distance_m = rssi_to_distance(
                ap.rssi_dbm, self._cfg.tx_power, self._cfg.path_loss_exp
            )

            if bssid in self._cfg.access_points:
                apc = self._cfg.access_points[bssid]
                ap.pos_x = apc.x
                ap.pos_y = apc.y
                ap.ssid = apc.ssid
            else:
                ap.pos_x = -1.0
                ap.pos_y = -1.0

            result.append(ap)

        return sorted(result, key=lambda a: a.rssi_dbm, reverse=True)

    # Linux
    def _linux(self) -> list[Dict]:
        return self._nmcli() or self._iwlist()

    def _nmcli(self) -> list[Dict]:
        try:
            raw = subprocess.check_output(
                [
                    "nmcli", "--mode", "multiline", "--fields",
                    "SSID,BSSID,SIGNAL,CHAN,FREQ", "dev", "wifi",
                    "list", "--rescan", "yes",
                ],
                timeout=10, stderr=subprocess.DEVNULL,
            ).decode(errors="replace")
        except Exception:
            return []

        entries: list[Dict] = []
        current: Dict = {}
        for line in raw.splitlines():
            m = re.match(r"^(\w+):\s*(.*)", line.strip())
            if not m:
                if current.get("BSSID"):
                    entries.append(current)
                    current = {}
                continue
            current[m.group(1)] = m.group(2).strip()
        if current.get("BSSID"):
            entries.append(current)

        result = []
        for e in entries:
            sig = int(e.get("SIGNAL", "0") or "0")
            freq = e.get("FREQ", "")
            chan = e.get("CHAN", "0") or "0"
            ssid = e.get("SSID", "") or ""
            if ssid in ("--", ""):
                ssid = "<oculto>"
            result.append({
                "ssid":    ssid,
                "bssid":   e["BSSID"],
                "rssi":    sig / 2.0 - 100.0,
                "channel": int(chan) if chan.isdigit() else 0,
                "band":    "5G" if freq.startswith("5") else "2.4G",
            })
        return result

    def _wlan_iface(self) -> str:
        try:
            out = subprocess.check_output(
                ["iw", "dev"], stderr=subprocess.DEVNULL
            ).decode()
            m = re.search(r"Interface\s+(\w+)", out)
            return m.group(1) if m else "wlan0"
        except Exception:
            return "wlan0"

    def _iwlist(self) -> list[Dict]:
        iface = self._wlan_iface()
        try:
            raw = subprocess.check_output(
                ["sudo", "iwlist", iface, "scan"],
                timeout=15, stderr=subprocess.DEVNULL,
            ).decode(errors="replace")
        except Exception:
            return []

        result = []
        for block in re.split(r"Cell \d+ -", raw)[1:]:
            ssid = re.search(r'ESSID:"([^"]*)"', block)
            bssid = re.search(r"Address:\s*([0-9A-Fa-f:]{17})", block)
            rssi = re.search(r"Signal level=(-?\d+)\s*dBm", block)
            if not rssi:
                pct = re.search(r"Signal level=(\d+)/100", block)
                if pct:
                    rssi_val: float = int(pct.group(1)) / 2.0 - 100.0
                else:
                    continue
            else:
                rssi_val = float(rssi.group(1))
            if not bssid:
                continue
            chan = re.search(r"Channel[:=](\d+)", block)
            result.append({
                "ssid":    (ssid.group(1) if ssid else "") or "<oculto>",
                "bssid":   bssid.group(1),
                "rssi":    rssi_val,
                "channel": int(chan.group(1)) if chan else 0,
                "band":    "2.4G",
            })
        return result

    # macOS
    def _macos(self) -> list[Dict]:
        airport = (
            "/System/Library/PrivateFrameworks/Apple80211.framework"
            "/Versions/Current/Resources/airport"
        )
        try:
            raw = subprocess.check_output(
                [airport, "-s"], timeout=12, stderr=subprocess.DEVNULL,
            ).decode(errors="replace")
        except Exception:
            return []

        result = []
        for line in raw.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                rssi = float(parts[2])
            except ValueError:
                continue
            try:
                ch = int(parts[3])
            except (ValueError, IndexError):
                ch = 0
            result.append({
                "ssid":    parts[0],
                "bssid":   parts[1],
                "rssi":    rssi,
                "channel": ch,
                "band":    "5G" if ch > 14 else "2.4G",
            })
        return result

    # Windows
    def _windows(self) -> list[Dict]:
        try:
            raw = subprocess.check_output(
                ["netsh", "wlan", "show", "networks", "mode=bssid"],
                timeout=10, stderr=subprocess.DEVNULL,
            ).decode("cp850", errors="replace")
        except Exception:
            return []

        result = []
        for block in re.split(r"(?m)^SSID\s+\d+\s*:", raw)[1:]:
            ssid = re.search(r"^\s*(.+)", block)
            bssid = re.search(r"BSSID\s+\d+\s*:\s*([0-9A-Fa-f:]+)", block)
            sig = re.search(r"Signal\s*:\s*(\d+)%", block)
            chan = re.search(r"Channel\s*:\s*(\d+)", block)
            if not (bssid and sig):
                continue
            ch = int(chan.group(1)) if chan else 0
            result.append({
                "ssid":    ssid.group(1).strip() if ssid else "<oculto>",
                "bssid":   bssid.group(1),
                "rssi":    int(sig.group(1)) / 2.0 - 100.0,
                "channel": ch,
                "band":    "5G" if ch > 14 else "2.4G",
            })
        return result


def _render_map(
    aps: list[AccessPoint],
    result: TriangulationResult,
    room_w: float,
    room_h: float,
) -> Text:
    W, H = MAP_W, MAP_H

    def to_map(wx: float, wy: float) -> tuple[int, int]:
        mx = max(1, min(W - 2, int(wx / room_w * (W - 3)) + 1))
        my = max(1, min(H - 2, int(wy / room_h * (H - 3)) + 1))
        return mx, my

    ch = [["·"] * W for _ in range(H)]
    sty = [["dim bright_black"] * W for _ in range(H)]

    for x in range(W):
        ch[0][x] = ch[H - 1][x] = "─"
        sty[0][x] = sty[H - 1][x] = "bright_black"
    for y in range(H):
        ch[y][0] = ch[y][W - 1] = "│"
        sty[y][0] = sty[y][W - 1] = "bright_black"
    ch[0][0] = "╔"
    ch[0][W - 1] = "╗"
    ch[H-1][0] = "╚"
    ch[H-1][W-1] = "╝"

    for ap in aps:
        if ap.pos_x < 0 or ap.distance_m <= 0:
            continue
        ax, ay = to_map(ap.pos_x, ap.pos_y)
        rx = max(1, int(ap.distance_m / room_w * (W - 2)))
        ry = max(1, int(ap.distance_m / room_h * (H - 2)))
        for deg in range(0, 360, 3):
            rad = math.radians(deg)
            cx = ax + int(rx * math.cos(rad))
            cy = ay + int(ry * math.sin(rad))
            if 1 <= cx < W - 1 and 1 <= cy < H - 1 and ch[cy][cx] == "·":
                sty[cy][cx] = f"{ap.color} dim"

    if result.aps_used >= 2 and 0.0 <= result.x <= room_w and 0.0 <= result.y <= room_h:
        px, py = to_map(result.x, result.y)
        err_rx = max(1, int(result.error_radius / room_w * (W - 2)))
        err_ry = max(1, int(result.error_radius / room_h * (H - 2)))
        for deg in range(0, 360, 8):
            rad = math.radians(deg)
            cx = px + int(err_rx * math.cos(rad))
            cy = py + int(err_ry * math.sin(rad))
            if 1 <= cx < W - 1 and 1 <= cy < H - 1 and ch[cy][cx] in ("·", " "):
                ch[cy][cx] = "○"
                sty[cy][cx] = "dim white"
        if 1 <= px < W - 1 and 1 <= py < H - 1:
            ch[py][px] = "◎"
            sty[py][px] = "bold bright_white"

    for ap in aps:
        if ap.pos_x < 0:
            continue
        ax, ay = to_map(ap.pos_x, ap.pos_y)
        ch[ay][ax] = ap.icon
        sty[ay][ax] = f"bold {ap.color}"

    t = Text()
    for y in range(H):
        for x in range(W):
            t.append(ch[y][x], style=sty[y][x])
        t.append("\n")
    return t


def _ap_table(aps: list[AccessPoint]) -> Table:
    t = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold bright_cyan",
        border_style="bright_black",
        expand=True,
        show_edge=False,
        padding=(0, 1),
    )
    t.add_column("",      width=3,  no_wrap=True)
    t.add_column("SSID",  min_width=14, style="bold")
    t.add_column("BSSID", style="bright_black", min_width=18)
    t.add_column("RSSI",  justify="right", width=12)
    t.add_column("Señal", width=8)
    t.add_column("Dist.", justify="right", width=9)
    t.add_column("CH",    justify="center", width=5)
    t.add_column("Banda", justify="center", width=6)
    t.add_column("Hist.", width=10)

    for ap in aps:
        spark = ""
        if len(ap.history) > 1:
            mn, mx = min(ap.history), max(ap.history)
            rng = mx - mn or 1.0
            bars = "▁▂▃▄▅▆▇█"
            spark = "".join(bars[int((v - mn) / rng * 7)]
                            for v in ap.history[-8:])

        pos_tag = (
            f"[bright_black]({ap.pos_x:.0f},{ap.pos_y:.0f})[/]"
            if ap.pos_x >= 0 else ""
        )
        t.add_row(
            f"[{ap.color}]{ap.icon}[/]",
            ap.ssid[:18],
            ap.bssid,
            f"[{ap.rssi_style()}]{ap.rssi_dbm:+.1f} dBm[/]",
            ap.signal_bar(),
            f"{ap.distance_m:.1f} m  {pos_tag}",
            str(ap.channel),
            ap.band,
            f"[bright_black]{spark}[/]",
        )
    return t


def _tri_panel(result: TriangulationResult) -> Panel:
    body = Text()
    if result.method == "insufficient_data":
        body.append("\n  ⚠  Sin anclas configuradas\n",   "yellow")
        body.append(
            "  Ejecuta  --setup  para asignar posiciones a los APs\n\n", "bright_black")
    elif result.method in ("wls", "weighted_midpoint"):
        c_style = (
            "bright_green" if result.confidence >= 70 else
            "yellow" if result.confidence >= 40 else
            "bright_red"
        )
        body.append("\n  Posición estimada\n\n", c_style)
        body.append(f"   X  {result.x:7.2f} m\n", "bold bright_white")
        body.append(f"   Y  {result.y:7.2f} m\n\n", "bold bright_white")
        body.append(
            f"   Confianza   [{c_style}]{result.confidence:.0f} %[/]\n", "white")
        body.append(
            f"   Error       ±{result.error_radius:.2f} m\n",            "white")
        body.append(
            f"   APs usados  {result.aps_used}\n",                       "white")
        body.append(
            f"   Método      {result.method}\n",                         "bright_black")
    return Panel(body, title="[bold]Trilateración[/]", border_style="bright_cyan", padding=(0, 1))


def _legend(aps: list[AccessPoint]) -> Text:
    t = Text()
    for ap in aps:
        if ap.pos_x >= 0:
            t.append(f" {ap.icon}", ap.color)
            t.append(f" {ap.ssid[:9]} ", "bright_black")
    t.append(" ◎", "bright_white")
    t.append(" estimado", "bright_black")
    t.append("  ○", "dim white")
    t.append(" ±error", "bright_black")
    return t


def _screen(
    aps: list[AccessPoint],
    result: TriangulationResult,
    cfg: Config,
    scan_n: int,
    iface: str,
) -> Group:
    ts = time.strftime("%H:%M:%S")
    title = Text()
    title.append("  Wi-Fi Triangulation  ", "bold bright_cyan")
    title.append(f"·  {iface}  ·  ", "dim bright_black")
    title.append(f"{ts}  #{scan_n}", "bright_black")

    has_anchors = any(ap.pos_x >= 0 for ap in aps)

    if has_anchors:
        mapa = _render_map(aps, result, cfg.room_w, cfg.room_h)
        map_panel = Panel(
            Align(mapa, "center"),
            title=f"[bold]Plano  {cfg.room_w:.0f} × {cfg.room_h:.0f} m[/]",
            border_style="cyan",
            subtitle=_legend(aps),
            padding=(0, 0),
        )
    else:
        map_panel = Panel(
            Align(
                Text(
                    "\n  Sin mapa — usa  --setup  para asignar posiciones a los APs\n",
                    "dim bright_black",
                ),
                "center", vertical="middle",
            ),
            title="[bold]Plano[/]",
            border_style="bright_black",
            height=6,
        )

    ap_panel = Panel(
        _ap_table(aps),
        title=f"[bold]Puntos de Acceso detectados  [{len(aps)}][/]",
        border_style="bright_black",
        padding=(0, 0),
    )
    tri_panel = _tri_panel(result)
    hint = Text(
        f"  Ctrl+C salir  ·  --setup configurar  ·  intervalo {cfg.scan_interval:.1f}s",
        "dim bright_black",
    )
    return Group(title, map_panel, ap_panel, tri_panel, hint)


def setup_wizard(cfg: Config, scanner: "WiFiScanner", console: Console) -> None:

    def ask(prompt: str, default: str) -> str:
        val = console.input(
            f"  [bright_cyan]{prompt}[/] [[bright_black]{default}[/]]: ").strip()
        return val if val else default

    console.print(Rule("[bold bright_cyan]Asistente de configuración[/]"))
    console.print()

    cfg.room_w = float(
        ask("Ancho de la sala (m)",               str(cfg.room_w)))
    cfg.room_h = float(
        ask("Alto de la sala (m)",                str(cfg.room_h)))
    cfg.tx_power = float(
        ask("TxPower a 1 m (dBm)",               str(cfg.tx_power)))
    cfg.path_loss_exp = float(ask("Exponente de pérdida n  [2=libre, 3.5=interior]",
                                  str(cfg.path_loss_exp)))
    cfg.scan_interval = float(
        ask("Intervalo de escaneo (s)",          str(cfg.scan_interval)))

    console.print()
    console.print("  [bright_black]Escaneando redes…[/]")
    aps = scanner.scan()

    if not aps:
        console.print("  [red]No se detectaron redes Wi-Fi.[/]")
        console.print(
            "  [bright_black]Verifica que la interfaz esté activa y los permisos.[/]")
        return

    console.print(f"  [bright_green]{len(aps)} redes detectadas[/]\n")
    for ap in aps:
        console.print(
            f"  [{ap.color}]{ap.icon}[/]  {ap.ssid:<20} {ap.bssid}  "
            f"[{ap.rssi_style()}]{ap.rssi_dbm:+.1f} dBm[/]"
        )

    console.print()
    console.print(
        "  Indica la posición física de cada AP que actuará como ancla.\n"
        "  [bright_black]Mide desde la esquina inferior-izquierda de la sala.\n"
        "  Deja en blanco para omitir un AP.[/]\n"
    )

    for ap in aps:
        ans = console.input(
            f"  [{ap.color}]{ap.icon}[/]  {ap.ssid} — ¿Asignar posición? [[bright_black]s/N[/]]: "
        ).strip().lower()
        if ans not in ("s", "si", "sí", "y", "yes"):
            continue
        try:
            x = float(ask(f"    X  (0 – {cfg.room_w} m)", "0.0"))
            y = float(ask(f"    Y  (0 – {cfg.room_h} m)", "0.0"))
        except ValueError:
            console.print("  [red]Valor inválido, AP omitido.[/]")
            continue
        cfg.access_points[ap.bssid] = APConfig(ssid=ap.ssid, x=x, y=y)
        console.print(f"  [bright_green]✔[/]  {ap.ssid} → ({x}, {y})")

    cfg.save()
    console.print(
        f"\n  [bright_green]Configuración guardada en[/]  {CONFIG_PATH}\n")


def _detect_iface() -> str:
    os_name = platform.system()
    if os_name == "Linux":
        try:
            out = subprocess.check_output(
                ["iw", "dev"], stderr=subprocess.DEVNULL
            ).decode()
            m = re.search(r"Interface\s+(\w+)", out)
            return m.group(1) if m else "wlan0"
        except Exception:
            return "wlan0"
    if os_name == "Darwin":
        return "en0"
    return "Wi-Fi"

#  MÓDULO SENTINEL — WiFiTriangulation
#  Uso:  WiFiTriangulation(sentinel).menu()


class WiFiTriangulation:
    _MODULE = "WiFi-Tri"

    def __init__(self, sentinel: object) -> None:
        self._s = sentinel
        self._con: Console = getattr(sentinel, "console", None) or Console()
        self._log = getattr(sentinel, "log", None)
        self._cfg_path = CONFIG_PATH
        self._cfg = Config.load(self._cfg_path)
        self._iface = _detect_iface()
        self._scanner = WiFiScanner(self._cfg)

    # Helpers privados
    def _info(self, msg: str) -> None:
        self._con.print(f"[cyan][{self._MODULE}][/cyan] {msg}")
        if self._log:
            self._log.info(msg, self._MODULE)

    def _warn(self, msg: str) -> None:
        self._con.print(f"[yellow][!][{self._MODULE}] {msg}[/yellow]")
        if self._log:
            self._log.warning(msg, self._MODULE)

    def _err(self, msg: str) -> None:
        self._con.print(f"[bold red][✗][{self._MODULE}] {msg}[/bold red]")
        if self._log:
            self._log.error(msg, self._MODULE)

    # API pública
    def menu(self) -> None:
        from rich.prompt import Prompt

        while True:
            self._con.print(Panel(
                "[1] Monitor en vivo\n"
                "[2] Asistente de configuración (setup)\n"
                "[3] Cambiar interfaz Wi-Fi\n"
                "[0] Volver",
                title=f"[bold cyan]📡  {self._MODULE}[/bold cyan]",
                border_style="cyan",
            ))
            opcion = Prompt.ask(
                f"[bold cyan]{self._MODULE}[/bold cyan]",
                choices=["0", "1", "2", "3"],
                default="1",
                console=self._con,
            )
            if opcion == "0":
                break
            elif opcion == "1":
                self._iniciar_monitor()
            elif opcion == "2":
                self._ejecutar_setup()
            elif opcion == "3":
                self._cambiar_iface()

    def _iniciar_monitor(self) -> None:
        self._info(
            f"Iniciando triangulación en vivo — "
            f"iface={self._iface}  intervalo={self._cfg.scan_interval:.1f}s"
        )
        try:
            with Live(
                console=self._con,
                refresh_per_second=4,
                screen=True,
            ) as live:
                n = 0
                while True:
                    aps = self._scanner.scan()
                    result = trilaterate(aps)
                    n += 1
                    live.update(
                        _screen(aps, result, self._cfg, n, self._iface))
                    time.sleep(self._cfg.scan_interval)
        except KeyboardInterrupt:
            self._con.print("\n[bold bright_cyan]  Monitoreo detenido.[/]")
        except Exception as exc:
            self._err(f"Error durante el monitoreo: {exc}")
            log.exception("WiFi-Tri monitor error")

    def _ejecutar_setup(self) -> None:
        self._info("Iniciando asistente de configuración…")
        try:
            setup_wizard(self._cfg, self._scanner, self._con)
            self._cfg = Config.load(self._cfg_path)   # recargar tras guardar
            self._scanner = WiFiScanner(self._cfg)
            self._info("Configuración recargada correctamente.")
        except Exception as exc:
            self._err(f"Error en setup: {exc}")
            log.exception("WiFi-Tri setup error")

    def _cambiar_iface(self) -> None:
        from rich.prompt import Prompt
        nueva = Prompt.ask(
            "Interfaz Wi-Fi",
            default=self._iface,
            console=self._con,
        ).strip()
        if nueva:
            self._iface = nueva
            self._info(f"Interfaz cambiada a: {self._iface}")
