from __future__ import annotations

import logging
import math
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from modules.network.bt_module import BluetoothModule

log = logging.getLogger(__name__)

_PATH_LOSS_N_INDOOR = 2.7
_WIFI_TX_DBM = 20
_BLE_TX_DBM = -59
_RSSI_MIN = -95
_SCAN_TIMEOUT_SEC = 15
_PRECISION_BASE_M = 2.5
_PRECISION_FALLBACK = 8.0
_MONITOR_INTERVAL = 5.0
_MIN_DIST_M = 0.5
_MAX_DIST_M = 150.0
_COND_MAX = 1e6


class MetodoPosicion(str, Enum):
    TRILATERACION = "trilateration"
    CENTROIDE_PONDERADO = "weighted_centroid"
    UNICA_FUENTE = "single"

    def __str__(self) -> str:
        return self.value


class FuenteWifi(str, Enum):
    NMCLI = "nmcli"
    IWLIST = "iwlist"
    DESCONOCIDA = "desconocida"

    def __str__(self) -> str:
        return self.value


def rssi_a_distancia(
    rssi: int,
    tx_dbm: int,
    n: float = _PATH_LOSS_N_INDOOR,
    *,
    min_dist_m: float = _MIN_DIST_M,
    max_dist_m: float = _MAX_DIST_M,
) -> float:

    if rssi >= tx_dbm:
        return min_dist_m
    return min(10 ** ((tx_dbm - rssi) / (10.0 * n)), max_dist_m)


def peso_por_distancia(dist_m: float) -> float:

    return 1.0 / max(dist_m ** 2, 0.01)


@dataclass
class PuntoAP:
    bssid: str
    ssid: str
    rssi: int
    frecuencia: int
    canal: int
    distancia_m: float = 0.0
    pos_x: float | None = None
    pos_y: float | None = None
    fuente: FuenteWifi = FuenteWifi.DESCONOCIDA
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def tiene_posicion(self) -> bool:
        return self.pos_x is not None and self.pos_y is not None

    @property
    def banda(self) -> str:
        return "5 GHz" if self.frecuencia >= 5000 else "2.4 GHz"

    @property
    def calidad(self) -> str:
        if self.rssi >= -50:
            return "[bold green]Excelente[/bold green]"
        if self.rssi >= -65:
            return "[green]Buena[/green]"
        if self.rssi >= -75:
            return "[yellow]Regular[/yellow]"
        return "[dim]Débil[/dim]"

    def to_dict(self) -> dict:
        return {
            "bssid": self.bssid,
            "ssid": self.ssid,
            "rssi": self.rssi,
            "frecuencia": self.frecuencia,
            "canal": self.canal,
            "distancia_m": round(self.distancia_m, 2),
            "pos_x": self.pos_x,
            "pos_y": self.pos_y,
            "fuente": self.fuente,
            "timestamp": self.timestamp,
        }


@dataclass
class EstimacionPosicion:
    x: float
    y: float
    precision_m: float
    metodo: MetodoPosicion
    fuentes_wifi: int
    fuentes_ble: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def fuentes_total(self) -> int:
        return self.fuentes_wifi + self.fuentes_ble

    @property
    def confianza(self) -> str:
        if self.metodo == MetodoPosicion.TRILATERACION and self.fuentes_total >= 4:
            return "[bold green]Alta[/bold green]"
        if self.metodo == MetodoPosicion.TRILATERACION:
            return "[yellow]Media[/yellow]"
        return "[dim]Baja[/dim]"

    def to_dict(self) -> dict:
        return {
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "precision_m": round(self.precision_m, 2),
            "metodo": self.metodo,
            "fuentes_wifi": self.fuentes_wifi,
            "fuentes_ble": self.fuentes_ble,
            "timestamp": self.timestamp,
        }


def _residual_rms(pos: tuple[float, float], referencias: list[tuple[float, float, float]]) -> float:

    x_est, y_est = pos
    num, den = 0.0, 0.0
    for xi, yi, di in referencias:
        w = peso_por_distancia(di)
        pred = math.hypot(x_est - xi, y_est - yi)
        num += w * (pred - di) ** 2
        den += w
    return math.sqrt(num / den) if den > 1e-9 else 0.0


def _trilaterar(referencias: list[tuple[float, float, float]]) -> tuple[float, float, float] | None:

    if len(referencias) < 2:
        return None

    x0, y0, d0 = referencias[0]
    A_rows, b_vals, pesos = [], [], []

    for xi, yi, di in referencias[1:]:
        A_rows.append([2.0 * (xi - x0), 2.0 * (yi - y0)])
        b_vals.append(xi**2 - x0**2 + yi**2 - y0**2 + d0**2 - di**2)
        pesos.append(peso_por_distancia(di))

    if len(A_rows) == 1:
        a0, a1 = A_rows[0]
        denom = a0**2 + a1**2
        if denom < 1e-9:
            return None
        t = b_vals[0] / denom
        x_est, y_est = x0 + t * a0, y0 + t * a1
        return x_est, y_est, _residual_rms((x_est, y_est), referencias)

    AtA = [[0.0, 0.0], [0.0, 0.0]]
    Atb = [0.0, 0.0]
    for row, bv, w in zip(A_rows, b_vals, pesos, strict=True):
        for j in range(2):
            Atb[j] += w * row[j] * bv
            for k in range(2):
                AtA[j][k] += w * row[j] * row[k]

    det = AtA[0][0] * AtA[1][1] - AtA[0][1] * AtA[1][0]
    if abs(det) < 1e-9:
        return None

    traza = AtA[0][0] + AtA[1][1]
    disc = math.sqrt(
        max(((AtA[0][0] - AtA[1][1]) / 2.0) ** 2 + AtA[0][1] ** 2, 0.0))
    lambda_min = traza / 2.0 - disc
    lambda_max = traza / 2.0 + disc
    if lambda_min <= 1e-9 or (lambda_max / lambda_min) > _COND_MAX:
        return None

    inv = [
        [AtA[1][1] / det, -AtA[0][1] / det],
        [-AtA[1][0] / det, AtA[0][0] / det],
    ]
    dx = inv[0][0] * Atb[0] + inv[0][1] * Atb[1]
    dy = inv[1][0] * Atb[0] + inv[1][1] * Atb[1]
    x_est, y_est = x0 + dx, y0 + dy

    return x_est, y_est, _residual_rms((x_est, y_est), referencias)


def _centroide_ponderado(referencias: list[tuple[float, float, float]]) -> tuple[float, float]:
    total_w, wx, wy = 0.0, 0.0, 0.0
    for xi, yi, di in referencias:
        w = peso_por_distancia(di)
        wx += xi * w
        wy += yi * w
        total_w += w
    if total_w < 1e-9:
        return 0.0, 0.0
    return wx / total_w, wy / total_w


class WiFiScanner:
    IFACE_DEFAULT = "wlan0"

    def __init__(self, iface: str = IFACE_DEFAULT, tx_dbm: int = _WIFI_TX_DBM):
        self.iface = iface
        self.tx_dbm = tx_dbm
        self._posiciones: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def registrar_posicion(self, bssid: str, x: float, y: float) -> None:
        with self._lock:
            self._posiciones[bssid.upper()] = (x, y)

    def cargar_posiciones(self, mapa: dict[str, tuple[float, float]]) -> None:
        for bssid, (x, y) in mapa.items():
            self.registrar_posicion(bssid, x, y)

    def escanear(self) -> list[PuntoAP]:
        puntos = self._nmcli() or self._iwlist()
        with self._lock:
            posiciones = dict(self._posiciones)
        for p in puntos:
            p.distancia_m = rssi_a_distancia(p.rssi, self.tx_dbm)
            pos = posiciones.get(p.bssid.upper())
            if pos:
                p.pos_x, p.pos_y = pos
        return puntos

    def _nmcli(self) -> list[PuntoAP]:
        try:
            nmcli_bin = shutil.which("nmcli") or "nmcli"
            r = subprocess.run(
                [nmcli_bin, "-t", "-f", "BSSID,SSID,SIGNAL,FREQ,CHAN",
                 "device", "wifi", "list", "--rescan", "yes"],
                capture_output=True, text=True, timeout=_SCAN_TIMEOUT_SEC,
            )
            if r.returncode != 0:
                return []
            puntos = []
            for line in r.stdout.strip().splitlines():
                partes = re.split(r"(?<!\\):", line)
                if len(partes) < 5:
                    continue
                try:
                    bssid = partes[0].replace("\\:", ":").strip()
                    ssid = partes[1].replace("\\:", ":").strip()
                    sig = int(partes[2].strip())
                    freq = int(partes[3].replace("MHz", "").strip())
                    chan = int(partes[4].strip())
                    rssi = _signal_a_dbm(sig)
                    if rssi < _RSSI_MIN:
                        continue
                    puntos.append(PuntoAP(bssid=bssid, ssid=ssid, rssi=rssi,
                                          frecuencia=freq, canal=chan,
                                          fuente=FuenteWifi.NMCLI))
                except (ValueError, IndexError):
                    continue
            return puntos
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.debug("nmcli no disponible: %s", exc)
            return []

    def _iwlist(self) -> list[PuntoAP]:
        try:
            sudo_bin = shutil.which("sudo") or "sudo"
            iwlist_bin = shutil.which("iwlist") or "iwlist"
            r = subprocess.run(
                [sudo_bin, "-n", iwlist_bin, self.iface, "scan"],
                capture_output=True, text=True, timeout=_SCAN_TIMEOUT_SEC,
            )
            if r.returncode != 0:
                if "password" in r.stderr.lower():
                    log.warning(
                        "iwlist requiere contraseña de sudo interactiva; "
                        "configurá NOPASSWD para 'iwlist' en sudoers, o "
                        "dale CAP_NET_ADMIN/CAP_NET_RAW al binario con "
                        "setcap para no depender de sudo."
                    )
                return []
            return _parsear_iwlist(r.stdout, _RSSI_MIN)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            log.debug("iwlist no disponible: %s", exc)
            return []


def _signal_a_dbm(signal: int) -> int:
    return -100 + (max(0, min(100, signal)) // 2)


def _parsear_iwlist(output: str, rssi_min: int) -> list[PuntoAP]:
    puntos: list[PuntoAP] = []
    bloque: dict = {}

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Cell"):
            if bloque:
                p = _bloque_a_punto(bloque, rssi_min)
                if p:
                    puntos.append(p)
            bloque = {}
            m = re.search(r"Address:\s*([\dA-Fa-f:]+)", line)
            if m:
                bloque["bssid"] = m.group(1).upper()
        elif "ESSID:" in line:
            m = re.search(r'ESSID:"(.*?)"', line)
            bloque["ssid"] = m.group(1) if m else ""
        elif "Signal level=" in line:
            m = re.search(r"Signal level=(-?\d+)", line)
            if m:
                bloque["rssi"] = int(m.group(1))
        elif "Frequency:" in line:
            m = re.search(r"Frequency:([\d.]+)\s*GHz", line)
            if m:
                bloque["freq"] = int(float(m.group(1)) * 1000)
            m2 = re.search(r"Channel\s*(\d+)", line)
            if m2:
                bloque["chan"] = int(m2.group(1))

    if bloque:
        p = _bloque_a_punto(bloque, rssi_min)
        if p:
            puntos.append(p)
    return puntos


def _bloque_a_punto(b: dict, rssi_min: int) -> PuntoAP | None:
    try:
        rssi = b.get("rssi", -99)
        if rssi < rssi_min:
            return None
        return PuntoAP(
            bssid=b.get("bssid", "??:??:??:??:??:??"),
            ssid=b.get("ssid", ""),
            rssi=rssi,
            frecuencia=b.get("freq", 2412),
            canal=b.get("chan", 1),
            fuente=FuenteWifi.IWLIST,
        )
    except Exception:
        return None


class FusionBLEWiFi:
    def __init__(self, bt_module: BluetoothModule, wifi_scanner: WiFiScanner | None = None):
        self.bt = bt_module
        self.console: Console = getattr(bt_module, "console", Console())
        self._own_lock = threading.Lock()
        self._fusion_lock = threading.Lock()
        self.wifi = wifi_scanner or WiFiScanner()
        self._beacons_ble: dict[str, tuple[float, float]] = {}
        self._ultima_est: EstimacionPosicion | None = None
        self._ultimos_aps: list[PuntoAP] = []

    @property
    def _lock(self) -> threading.Lock:
        return getattr(self.bt, "_lock", self._own_lock)

    @property
    def _disp(self) -> dict:
        return getattr(self.bt, "_dispositivos", {})

    def _info(self, msg: str) -> None:
        log_sys = getattr(self.bt, "log", None)
        if log_sys:
            log_sys.info(msg, "FusionBLEWiFi")
        else:
            self.console.print(f"[cyan][*][/cyan] {msg}")

    def registrar_beacon_ble(self, address: str, x: float, y: float) -> None:
        with self._fusion_lock:
            self._beacons_ble[address.upper()] = (x, y)

    def estimar_posicion(self, aps: list[PuntoAP] | None = None) -> EstimacionPosicion | None:
        if aps is None:
            aps = self.wifi.escanear()
        self._ultimos_aps = aps

        refs_wifi: list[tuple[float, float, float]] = []
        for ap in aps:
            if ap.tiene_posicion:
                refs_wifi.append((ap.pos_x, ap.pos_y, ap.distancia_m))

        with self._lock:
            disp_snapshot = list(self._disp.items())
        with self._fusion_lock:
            beacons_snapshot = dict(self._beacons_ble)

        refs_ble: list[tuple[float, float, float]] = []
        for addr, disp in disp_snapshot:
            pos = beacons_snapshot.get(addr.upper())
            if pos:
                dist = rssi_a_distancia(disp.rssi, _BLE_TX_DBM)
                refs_ble.append((pos[0], pos[1], dist))

        todas = refs_wifi + refs_ble
        n_wifi = len(refs_wifi)
        n_ble = len(refs_ble)

        if not todas:
            self._info("Sin referencias con posición conocida.")
            return None

        if len(todas) >= 2:
            resultado = _trilaterar(todas)
            if resultado:
                x_est, y_est, residual = resultado
                metodo = MetodoPosicion.TRILATERACION
                prec = _PRECISION_BASE_M + \
                    max(0, 3 - len(todas)) * 1.5 + residual
            else:
                x_est, y_est = _centroide_ponderado(todas)
                metodo = MetodoPosicion.CENTROIDE_PONDERADO
                prec = _PRECISION_FALLBACK
        else:
            x_est, y_est = _centroide_ponderado(todas)
            metodo = MetodoPosicion.UNICA_FUENTE
            prec = _PRECISION_FALLBACK * 1.5

        est = EstimacionPosicion(
            x=round(x_est, 3),
            y=round(y_est, 3),
            precision_m=round(prec, 2),
            metodo=metodo,
            fuentes_wifi=n_wifi,
            fuentes_ble=n_ble,
        )
        self._ultima_est = est

        gp = getattr(self.bt, "gp", None)
        if gp:
            try:
                gp.registrar_evidencia(
                    "wifi_ble_fusion",
                    f"Fusión BLE+WiFi: ({x_est:.2f}, {y_est:.2f}) m ±{prec:.1f} m",
                    {
                        "estimacion": est.to_dict(),
                        "aps": [a.to_dict() for a in aps],
                        "beacons_ble": n_ble,
                    },
                )
            except Exception as exc:
                log.warning("Error registrando evidencia fusión: %s", exc)

        return est

    def _panel_wifi(self, aps: list[PuntoAP]) -> Panel:
        if not aps:
            return Panel("[dim]Sin APs detectados.[/dim]",
                         title="[bold cyan]WI-FI[/bold cyan]", border_style="cyan")

        tb = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
                   show_edge=False, expand=True)
        tb.add_column("SSID", style="white", min_width=16, no_wrap=True)
        tb.add_column("BSSID", style="dim", min_width=18, no_wrap=True)
        tb.add_column("RSSI", justify="right", min_width=9)
        tb.add_column("Distancia", justify="right", min_width=9)
        tb.add_column("Banda", justify="center",
                      min_width=7, style="dim yellow")
        tb.add_column("Calidad", min_width=11)
        tb.add_column("Posición", min_width=14, style="dim cyan")

        for ap in sorted(aps, key=lambda a: a.rssi, reverse=True):
            rssi_s = (
                "bold red" if ap.rssi >= -50 else
                "yellow" if ap.rssi >= -65 else
                "green" if ap.rssi >= -75 else "dim"
            )
            pos_str = f"({ap.pos_x:.1f}, {ap.pos_y:.1f})" if ap.tiene_posicion else "—"
            tb.add_row(
                ap.ssid or "<oculto>",
                ap.bssid,
                f"[{rssi_s}]{ap.rssi} dBm[/{rssi_s}]",
                f"{ap.distancia_m:.1f} m",
                ap.banda,
                ap.calidad,
                pos_str,
            )

        return Panel(tb, title="[bold cyan]WI-FI — ACCESS POINTS[/bold cyan]",
                     border_style="cyan", box=box.HEAVY_EDGE)

    def _panel_estimacion(self, est: EstimacionPosicion | None) -> Panel:
        if not est:
            return Panel("[dim]Sin estimación disponible.[/dim]",
                         title="[bold cyan]POSICIÓN ESTIMADA[/bold cyan]",
                         border_style="dim")

        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim cyan", justify="right", min_width=18)
        g.add_column(style="bold white", min_width=20)

        g.add_row("X (este)", f"{est.x:.3f} m")
        g.add_row("Y (norte)", f"{est.y:.3f} m")
        g.add_row("Precisión", f"±{est.precision_m:.2f} m")
        g.add_row("Método", str(est.metodo))
        g.add_row("Confianza", est.confianza)
        g.add_row("Fuentes WiFi", str(est.fuentes_wifi))
        g.add_row("Fuentes BLE", str(est.fuentes_ble))
        g.add_row("Total", str(est.fuentes_total))
        g.add_row("Timestamp", est.timestamp[11:19])

        return Panel(g, title="[bold cyan]POSICIÓN ESTIMADA[/bold cyan]",
                     border_style="cyan", box=box.ROUNDED)

    def mostrar_panel(self) -> None:
        aps = self.wifi.escanear()
        est = self.estimar_posicion(aps)
        self.console.print(Columns(
            [self._panel_wifi(aps), self._panel_estimacion(est)],
            expand=True,
        ))

    def monitoreo(self, duracion_seg: int = 60) -> None:
        self._info(f"Fusión BLE+WiFi iniciada — {duracion_seg}s")
        inicio = time.monotonic()

        try:
            with Live(console=self.console, refresh_per_second=2,
                      screen=False) as live:
                while True:
                    if time.monotonic() - inicio >= duracion_seg:
                        break

                    aps = self.wifi.escanear()
                    est = self.estimar_posicion(aps)

                    ts = datetime.now().strftime("%H:%M:%S")
                    elapsed = int(time.monotonic() - inicio)
                    pie = (f"[dim]WiFi: {len(aps)} APs  |  "
                           f"BLE: {len(self._disp)}  |  "
                           f"{elapsed}/{duracion_seg}s  |  {ts}[/dim]")

                    live.update(Panel(
                        Columns(
                            [self._panel_wifi(
                                aps), self._panel_estimacion(est)],
                            expand=True,
                        ),
                        title="[bold cyan]FUSIÓN BLE + WI-FI[/bold cyan]",
                        subtitle=pie,
                        border_style="cyan",
                    ))

                    restante = duracion_seg - (time.monotonic() - inicio)
                    if restante > 0:
                        time.sleep(min(_MONITOR_INTERVAL, restante))

        except KeyboardInterrupt:
            self.console.print("\n[yellow][!] Monitoreo detenido.[/yellow]")
        except Exception as exc:
            self.console.print(
                f"[red][!] Error en monitoreo fusión: {exc}[/red]")
            log.exception("FusionBLEWiFi monitoreo error")

    def ultima_estimacion(self) -> EstimacionPosicion | None:
        return self._ultima_est

    def ultimos_aps(self) -> list[PuntoAP]:
        return list(self._ultimos_aps)
