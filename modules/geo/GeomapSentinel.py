from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

log = logging.getLogger("sentinel.geomap")

_FOLIUM_OK = False
try:
    import folium
    _FOLIUM_OK = True
except ImportError:
    pass

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _requests      = None  # type: ignore[assignment]
    _REQUESTS_OK   = False

if TYPE_CHECKING:
    from Main import ApexSentinel

_MAP_DIR  = Path("data/evidence/geo")
_MAP_NAME = "mapa_sentinel.html"

_TILE_DARK   = "CartoDB dark_matter"
_TILE_SIMPLE = "OpenStreetMap"

_COLORES_VENDOR: dict[str, str] = {
    "Apple":        "#00CFFF",
    "Samsung":      "#FFD700",
    "Raspberry Pi": "#FF6600",
    "Espressif":    "#00FF99",
    "Microsoft":    "#0078D4",
}
_COLOR_CONOCIDO   = "#00FF00"
_COLOR_DESCONOCIDO = "#FFFF00"
_COLOR_OPERADOR    = "#FF3333"


# ══════════════════════════════════════════════════════════════════════
# CLASE PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class GeomapSentinel:

    def __init__(self, sentinel: ApexSentinel) -> None:
        self._s        = sentinel
        self._console  = sentinel.console
        self._log      = sentinel.log
        self._lat:  float = 0.0
        self._lon:  float = 0.0
        self._mapa: Path  = _MAP_DIR / _MAP_NAME
        _MAP_DIR.mkdir(parents=True, exist_ok=True)

        if not _FOLIUM_OK:
            self._log.warning(
                "folium no instalado — mapa visual desactivado. "
                "Instala con: pip install folium",
                "GeomapSentinel",
            )

        self._lat, self._lon = self._obtener_ubicacion_ip()

    # ── API pública ───────────────────────────────────────────────────

    def generar_mapa(self, targets: dict[str, dict[str, Any]]) -> Path | None:
        if not _FOLIUM_OK:
            self._mostrar_fallback_tabla(targets)
            return None

        if not targets:
            self._console.print("[yellow][!] Sin objetivos para mapear.[/yellow]")
            return None

        mapa = self._crear_mapa_base()
        self._añadir_posicion_operador(mapa)
        self._añadir_objetivos(mapa, targets)

        mapa.save(str(self._mapa))
        self._log.info(
            f"Mapa generado: {self._mapa} — {len(targets)} objetivo(s)",
            "GeomapSentinel",
        )

        if self._s.gp and self._s.gp.proyecto_activo:
            self._s.gp.registrar_evidencia(
                "geomap",
                f"Mapa táctico generado — {len(targets)} dispositivos",
                {"ruta": str(self._mapa), "objetivos": len(targets)},
            )

        return self._mapa

    def abrir_mapa(self) -> None:
        if not self._mapa.exists():
            self._console.print("[red][!] El mapa no existe. Genera uno primero.[/red]")
            return

        from core.platform import detect
        info = detect()

        if info.is_tty and not info.is_uconsole:
            # TTY puro sin entorno gráfico — mostrar ruta
            self._console.print(
                f"\n[dim]Mapa guardado en:[/dim] "
                f"[bold cyan]{self._mapa.resolve()}[/bold cyan]\n"
                "[dim]Ábrelo en un navegador copiando la ruta.[/dim]"
            )
        else:
            import subprocess
            url = f"file://{self._mapa.resolve()}"
            try:
                subprocess.run(["xdg-open", url], check=False, timeout=5)
                self._console.print(f"[green][OK] Mapa abierto: {url}[/green]")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._console.print(
                    f"[yellow][!] xdg-open no disponible.[/yellow]\n"
                    f"[dim]Ruta: {self._mapa.resolve()}[/dim]"
                )

    # ── Construcción del mapa ─────────────────────────────────────────

    def _crear_mapa_base(self) -> folium.Map:
        tiles = _TILE_DARK if _FOLIUM_OK else _TILE_SIMPLE
        return folium.Map(
            location=[self._lat, self._lon],
            zoom_start=18,
            tiles=tiles,
        )

    def _añadir_posicion_operador(self, mapa: folium.Map) -> None:
        folium.Marker(
            location=[self._lat, self._lon],
            popup=folium.Popup("◉ APEX SENTINEL (YOU)", max_width=200),
            icon=folium.Icon(color="red", icon="home", prefix="fa"),
        ).add_to(mapa)

    def _añadir_objetivos(
        self,
        mapa:    folium.Map,
        targets: dict[str, dict[str, Any]],
    ) -> None:
        for idx, (mac, data) in enumerate(targets.items()):
            t_lat, t_lon = self._estimar_posicion(data, idx, len(targets))
            vendor       = data.get("vendor", "Desconocido")
            rssi         = data.get("rssi", -80)
            color        = _COLORES_VENDOR.get(
                vendor,
                _COLOR_CONOCIDO if vendor != "Desconocido" else _COLOR_DESCONOCIDO,
            )
            popup_html = (
                f"<b>MAC:</b> {mac}<br>"
                f"<b>Vendor:</b> {vendor}<br>"
                f"<b>RSSI:</b> {rssi} dBm"
            )
            folium.CircleMarker(
                location=[t_lat, t_lon],
                radius=max(4, min(12, 90 + rssi)),  # más fuerte = más grande
                popup=folium.Popup(popup_html, max_width=220),
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.65,
                tooltip=f"{vendor} | {rssi} dBm",
            ).add_to(mapa)

    # ── Estimación de posición ────────────────────────────────────────

    def _estimar_posicion(
        self,
        data:  dict[str, Any],
        idx:   int,
        total: int,
    ) -> tuple[float, float]:
        rssi = data.get("rssi", -80)

        # Distancia estimada: modelo de path loss simplificado
        # d ≈ 10 ^ ((RSSI_ref - RSSI) / (10 * n)) con n=2, RSSI_ref=-30 dBm a 1m
        path_loss_exp = 2.0
        rssi_ref_1m   = -30
        distancia_m   = 10 ** ((rssi_ref_1m - rssi) / (10 * path_loss_exp))

        # Distribuir en ángulos distintos para cada dispositivo
        angulo_rad = math.radians(
            (360 / max(total, 1)) * idx + data.get("angle", idx * 37.0)
        )

        # Convertir metros a grados (aproximación plana local)
        metros_por_grado_lat = 111_320.0
        metros_por_grado_lon = 111_320.0 * math.cos(math.radians(self._lat))

        offset_lat = (distancia_m * math.cos(angulo_rad)) / metros_por_grado_lat
        offset_lon = (distancia_m * math.sin(angulo_rad)) / metros_por_grado_lon

        return (self._lat + offset_lat, self._lon + offset_lon)

    # ── Geolocalización IP ────────────────────────────────────────────

    def _obtener_ubicacion_ip(self) -> tuple[float, float]:
        if not _REQUESTS_OK:
            log.warning("requests no disponible — ubicación por IP desactivada.")
            return 0.0, 0.0
        try:
            resp = _requests.get("https://ipapi.co/json/", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                lat  = float(data.get("latitude",  0.0))
                lon  = float(data.get("longitude", 0.0))
                log.info(f"Ubicación IP obtenida: {lat:.5f}, {lon:.5f}")
                return lat, lon
        except Exception as exc:
            log.warning(f"Geolocalización IP falló: {exc}")
        return 0.0, 0.0

    # ── Fallback sin folium ───────────────────────────────────────────

    def _mostrar_fallback_tabla(self, targets: dict[str, dict[str, Any]]) -> None:
        from rich.table import Table
        from rich import box

        tabla = Table(
            title=f"[bold green]RADAR — {len(targets)} objetivo(s)[/bold green]",
            box=box.ROUNDED,
            border_style="green",
        )
        tabla.add_column("MAC",    style="cyan",       no_wrap=True)
        tabla.add_column("Vendor", style="white")
        tabla.add_column("RSSI",   style="bold yellow", justify="right")

        for mac, data in targets.items():
            rssi   = data.get("rssi", "?")
            vendor = data.get("vendor", "Desconocido")
            tabla.add_row(mac, vendor, f"{rssi} dBm")

        self._console.print(tabla)
        self._console.print(
            "[dim][!] Instala folium para mapa visual: "
            "pip install folium[/dim]"
        )
