from __future__ import annotations

import contextlib
import hashlib
import html
import io
import json
import logging
import math
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

from rich import box
from rich.table import Table

from modules.network.wifi_ble_fusion import rssi_a_distancia

if TYPE_CHECKING:
    from modules.network.bt_module import BluetoothModule, DispositivoBLE
    from modules.network.bt_mapa import DeviceTrack
    from modules.network.wifi_ble_fusion import EstimacionPosicion, PuntoAP

log = logging.getLogger(__name__)

_BLE_TX_DBM = -59
_M_POR_GRADO_LAT = 111_111.0

_SIN_GPS_PREFIJO = "[SIN GPS] "
_SIN_GPS_ADVERTENCIA = (
    "Sin origen GPS: lat/lon de este punto son directamente los metros "
    "locales relativos al escáner, NO coordenadas geográficas reales."
)

_PREFIJO_SEGURO_RE = re.compile(r"[^A-Za-z0-9_-]+")

_KML_COLORES = {
    "MUY CERCA": "ff0000ff",
    "CERCA":     "ff00aaff",
    "MEDIO":     "ff00ff00",
    "LEJOS":     "ff888888",
    "WIFI":      "ffff6600",
    "SCANNER":   "ff00ffff",
}

_GEOJSON_COLORES = {
    "MUY CERCA": "#ff0000",
    "CERCA":     "#ff8800",
    "MEDIO":     "#00cc00",
    "LEJOS":     "#888888",
    "WIFI":      "#0088ff",
    "SCANNER":   "#ffff00",
}

_KML_ICONOS = {
    "MUY CERCA": "http://maps.google.com/mapfiles/ms/icons/red-dot.png",
    "CERCA":     "http://maps.google.com/mapfiles/ms/icons/orange-dot.png",
    "MEDIO":     "http://maps.google.com/mapfiles/ms/icons/green-dot.png",
    "LEJOS":     "http://maps.google.com/mapfiles/ms/icons/ltblue-dot.png",
    "WIFI":      "http://maps.google.com/mapfiles/ms/icons/blue-dot.png",
    "SCANNER":   "http://maps.google.com/mapfiles/ms/icons/yellow-dot.png",
}


def _sanitizar_prefijo(prefijo: str) -> str:
    limpio = _PREFIJO_SEGURO_RE.sub("_", prefijo).strip("_")
    return limpio or "ble_map"


def _mac_a_angulo(address: str) -> float:
    digest = int(hashlib.md5(address.encode(),
                 usedforsecurity=False).hexdigest()[:8], 16)
    return (digest % 360) * math.pi / 180.0


def _local_a_geo(x_m: float, y_m: float, lat0: float, lon0: float) -> tuple[float, float]:
    lat = lat0 + y_m / _M_POR_GRADO_LAT
    lon = lon0 + x_m / (_M_POR_GRADO_LAT * math.cos(math.radians(lat0)))
    return round(lat, 8), round(lon, 8)


def _proximidad(rssi: int) -> str:
    if rssi >= -50:
        return "MUY CERCA"
    if rssi >= -65:
        return "CERCA"
    if rssi >= -80:
        return "MEDIO"
    return "LEJOS"


def _etiquetar_si_sin_gps(nombre: str, propiedades: dict, tiene_gps: bool) -> tuple[str, dict]:
    if tiene_gps:
        return nombre, propiedades
    propiedades = dict(propiedades)
    propiedades["_advertencia"] = _SIN_GPS_ADVERTENCIA
    return f"{_SIN_GPS_PREFIJO}{nombre}", propiedades


@dataclass
class PuntoGeo:
    nombre: str
    lat: float
    lon: float
    categoria: str
    proximidad: str
    propiedades: dict

    @property
    def color_kml(self) -> str:
        return _KML_COLORES.get(self.proximidad, _KML_COLORES["LEJOS"])

    @property
    def color_geojson(self) -> str:
        return _GEOJSON_COLORES.get(self.proximidad, _GEOJSON_COLORES["LEJOS"])

    @property
    def icono_kml(self) -> str:
        return _KML_ICONOS.get(self.proximidad, _KML_ICONOS["LEJOS"])


class GeoExporter:
    def __init__(self, bt_module: BluetoothModule):
        self.bt = bt_module
        self._own_lock = threading.Lock()

    @property
    def _lock(self) -> threading.Lock:
        return getattr(self.bt, "_lock", self._own_lock)

    @property
    def _disp(self) -> dict:
        return getattr(self.bt, "_dispositivos", {})

    def exportar(
        self,
        lat_origen: float | None = None,
        lon_origen: float | None = None,
        estimacion: EstimacionPosicion | None = None,
        aps: list[PuntoAP] | None = None,
        tracks: dict[str, DeviceTrack] | None = None,
        directorio: str = ".",
        prefijo: str = "ble_map",
    ) -> dict[str, str]:
        prefijo = _sanitizar_prefijo(prefijo)
        Path(directorio).mkdir(parents=True, exist_ok=True)

        tiene_gps = lat_origen is not None and lon_origen is not None
        lat0 = lat_origen or 0.0
        lon0 = lon_origen or 0.0

        with self._lock:
            dispositivos = list(self._disp.values())

        puntos = self._construir_puntos(
            dispositivos, aps or [], tracks or {},
            lat0, lon0, tiene_gps, estimacion,
        )

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        nombre_base = f"{prefijo}_{ts}"

        ruta_kml = str(Path(directorio) / f"{nombre_base}.kml")
        ruta_geojson = str(Path(directorio) / f"{nombre_base}.geojson")

        try:
            self._exportar_kml(puntos, ruta_kml, lat0,
                               lon0, tiene_gps, estimacion)
            self._exportar_geojson(puntos, ruta_geojson,
                                   lat0, lon0, tiene_gps, estimacion)
        except OSError:
            log.exception(
                "Falló la exportación geo (KML/GeoJSON) en %s", directorio)
            raise

        log.info("Exportación geo completa: kml=%s geojson=%s",
                 ruta_kml, ruta_geojson)

        console = getattr(self.bt, "console", None)
        if console:
            console.print(
                f"[bold cyan][✓] Exportación completa[/bold cyan]\n"
                f"[dim]    KML:     {ruta_kml}\n"
                f"    GeoJSON: {ruta_geojson}[/dim]"
            )

        return {"kml": ruta_kml, "geojson": ruta_geojson}

    def _construir_puntos(
        self,
        dispositivos: list[DispositivoBLE],
        aps: list[PuntoAP],
        tracks: dict[str, DeviceTrack],
        lat0: float,
        lon0: float,
        tiene_gps: bool,
        estimacion: EstimacionPosicion | None,
    ) -> list[PuntoGeo]:
        puntos: list[PuntoGeo] = []

        if tiene_gps:
            if estimacion:
                lat_sc, lon_sc = _local_a_geo(
                    estimacion.x, estimacion.y, lat0, lon0)
                desc_sc = (f"({estimacion.x:.2f}, {estimacion.y:.2f}) m "
                           f"±{estimacion.precision_m:.1f} m [{estimacion.metodo}]")
            else:
                lat_sc, lon_sc = lat0, lon0
                desc_sc = "Posición GPS del escáner"

            puntos.append(PuntoGeo(
                nombre="Escáner",
                lat=lat_sc, lon=lon_sc,
                categoria="SCANNER", proximidad="SCANNER",
                propiedades={
                    "tipo": "scanner",
                    "descripcion": desc_sc,
                    "timestamp": datetime.now().isoformat(),
                },
            ))

        for d in dispositivos:
            tr = tracks.get(d.address)
            rssi_ema = round(tr.ema_rssi) if tr else d.rssi
            dist_m = rssi_a_distancia(rssi_ema, _BLE_TX_DBM)
            angulo = _mac_a_angulo(d.address)
            x_m = dist_m * math.cos(angulo)
            y_m = dist_m * math.sin(angulo)

            if tiene_gps:
                lat, lon = _local_a_geo(x_m, y_m, lat0, lon0)
            else:
                lat, lon = y_m, x_m

            prox = _proximidad(rssi_ema)
            propiedades = {
                "tipo": "ble_device",
                "nombre": d.nombre or "",
                "mac": d.address,
                "rssi_dBm": rssi_ema,
                "rssi_raw": d.rssi,
                "distancia_m": round(dist_m, 2),
                "fabricante": d.fabricante,
                "servicios": d.servicios[:5],
                "primera_vez": d.primera_vez,
                "ultima_vez": d.ultima_vez,
                "veces_visto": d.veces_visto,
                "proximidad": prox,
            }
            if tr:
                propiedades["tendencia"] = tr.tendencia()
                propiedades["ema_rssi"] = round(tr.ema_rssi, 1)
                propiedades["tipo_disp"] = tr.tipo

            nombre, propiedades = _etiquetar_si_sin_gps(
                d.nombre or d.address, propiedades, tiene_gps)
            puntos.append(PuntoGeo(
                nombre=nombre,
                lat=lat, lon=lon,
                categoria="BLE", proximidad=prox,
                propiedades=propiedades,
            ))

        for ap in aps:
            if ap.tiene_posicion:
                if tiene_gps:
                    lat, lon = _local_a_geo(ap.pos_x, ap.pos_y, lat0, lon0)
                else:
                    lat, lon = ap.pos_y or 0.0, ap.pos_x or 0.0
            else:
                angulo = _mac_a_angulo(ap.bssid)
                x_m = ap.distancia_m * math.cos(angulo)
                y_m = ap.distancia_m * math.sin(angulo)
                if tiene_gps:
                    lat, lon = _local_a_geo(x_m, y_m, lat0, lon0)
                else:
                    lat, lon = y_m, x_m

            propiedades = {
                "tipo": "wifi_ap",
                "ssid": ap.ssid,
                "bssid": ap.bssid,
                "rssi_dBm": ap.rssi,
                "distancia_m": round(ap.distancia_m, 2),
                "frecuencia": ap.frecuencia,
                "canal": ap.canal,
                "banda": ap.banda,
                "pos_x": ap.pos_x,
                "pos_y": ap.pos_y,
                "fuente": ap.fuente,
                "timestamp": ap.timestamp,
            }
            nombre, propiedades = _etiquetar_si_sin_gps(
                ap.ssid or ap.bssid, propiedades, tiene_gps)

            puntos.append(PuntoGeo(
                nombre=nombre,
                lat=round(lat, 8), lon=round(lon, 8),
                categoria="WIFI", proximidad="WIFI",
                propiedades=propiedades,
            ))

        return puntos

    def _exportar_kml(
        self,
        puntos: list[PuntoGeo],
        ruta: str,
        lat0: float,
        lon0: float,
        tiene_gps: bool,
        estimacion: EstimacionPosicion | None,
    ) -> None:
        kml = Element("kml", xmlns="http://www.opengis.net/kml/2.2")
        doc = SubElement(kml, "Document")
        SubElement(
            doc, "name").text = f"BLE Map — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        SubElement(doc, "description").text = (
            f"GPS: {'Sí' if tiene_gps else 'No'} | "
            f"BLE: {sum(1 for p in puntos if p.categoria == 'BLE')} | "
            f"WiFi: {sum(1 for p in puntos if p.categoria == 'WIFI')}"
        )

        for clave, color in _KML_COLORES.items():
            style = SubElement(doc, "Style", id=f"style_{clave}")
            icon_style = SubElement(style, "IconStyle")
            SubElement(icon_style, "color").text = color
            SubElement(icon_style, "scale").text = "1.1" if clave in (
                "MUY CERCA", "SCANNER") else "0.9"
            icon = SubElement(icon_style, "Icon")
            SubElement(icon, "href").text = _KML_ICONOS.get(
                clave, _KML_ICONOS["LEJOS"])
            label_style = SubElement(style, "LabelStyle")
            SubElement(label_style, "scale").text = "0.8"

        carpetas: dict[str, Element] = {}
        for categoria, nombre_carpeta in [
            ("SCANNER", "Escáner"),
            ("WIFI", "Wi-Fi APs"),
            ("BLE", "Dispositivos BLE"),
        ]:
            folder = SubElement(doc, "Folder")
            SubElement(folder, "name").text = nombre_carpeta
            SubElement(folder, "visibility").text = "1"
            carpetas[categoria] = folder

        cdata_bloques: dict[str, str] = {}

        for p in puntos:
            carpeta = carpetas.get(p.categoria, carpetas["BLE"])
            pm = SubElement(carpeta, "Placemark")
            SubElement(pm, "name").text = p.nombre[:40]
            SubElement(pm, "styleUrl").text = f"#style_{p.proximidad}"

            filas_html = "".join(
                f"<tr><td><b>{html.escape(str(k))}</b></td><td>{html.escape(str(v))}</td></tr>"
                for k, v in p.propiedades.items()
                if v not in (None, "", [], {})
            )

            tabla_html = f"<table>{filas_html}</table>".replace(
                "]]>", "]]]]><![CDATA[>")
            marcador = f"@@CDATA_{uuid.uuid4().hex}@@"
            cdata_bloques[marcador] = tabla_html
            SubElement(pm, "description").text = marcador

            ext = SubElement(pm, "ExtendedData")
            for k, v in p.propiedades.items():
                if v is None:
                    continue
                data = SubElement(ext, "Data", name=str(k))
                SubElement(data, "value").text = str(v)

            point = SubElement(pm, "Point")
            SubElement(point, "coordinates").text = f"{p.lon},{p.lat},0"

        if estimacion and tiene_gps:
            folder_unc = SubElement(doc, "Folder")
            SubElement(folder_unc, "name").text = "Incertidumbre"
            lat_sc, lon_sc = _local_a_geo(
                estimacion.x, estimacion.y, lat0, lon0)
            coords = _circulo_kml(lat_sc, lon_sc, estimacion.precision_m)
            pm_c = SubElement(folder_unc, "Placemark")
            SubElement(
                pm_c, "name").text = f"Radio ±{estimacion.precision_m:.1f} m"
            style_c = SubElement(pm_c, "Style")
            line_s = SubElement(style_c, "LineStyle")
            SubElement(line_s, "color").text = "ffaaffaa"
            SubElement(line_s, "width").text = "2"
            poly_s = SubElement(style_c, "PolyStyle")
            SubElement(poly_s, "color").text = "2200ff00"
            polygon = SubElement(pm_c, "Polygon")
            outer = SubElement(polygon, "outerBoundaryIs")
            ring = SubElement(outer, "LinearRing")
            SubElement(ring, "coordinates").text = coords

        tree = ElementTree(kml)
        with contextlib.suppress(TypeError):
            indent(tree, space="  ")

        buf = io.BytesIO()
        tree.write(buf, xml_declaration=True, encoding="utf-8")
        xml_str = buf.getvalue().decode("utf-8")
        for marcador, bloque in cdata_bloques.items():
            xml_str = xml_str.replace(marcador, f"<![CDATA[{bloque}]]>")

        with open(ruta, "w", encoding="utf-8") as f:
            f.write(xml_str)

    def _exportar_geojson(
        self,
        puntos: list[PuntoGeo],
        ruta: str,
        lat0: float,
        lon0: float,
        tiene_gps: bool,
        estimacion: EstimacionPosicion | None,
    ) -> None:
        features = []

        for p in puntos:
            props = dict(p.propiedades)
            props["_nombre"] = p.nombre
            props["_categoria"] = p.categoria
            props["_color"] = p.color_geojson
            props["_icono"] = p.proximidad.lower().replace(" ", "_")

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [p.lon, p.lat],
                },
                "properties": props,
            })

        if estimacion and tiene_gps:
            lat_sc, lon_sc = _local_a_geo(
                estimacion.x, estimacion.y, lat0, lon0)
            coords_ring = _circulo_geojson(
                lat_sc, lon_sc, estimacion.precision_m)
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coords_ring],
                },
                "properties": {
                    "_nombre": f"Radio ±{estimacion.precision_m:.1f} m",
                    "_categoria": "INCERTIDUMBRE",
                    "_color": "#00ff88",
                    "precision_m": estimacion.precision_m,
                    "metodo": estimacion.metodo,
                    "fuentes": estimacion.fuentes_total,
                },
            })

        coleccion = {
            "type": "FeatureCollection",
            "metadata": {
                "generado": datetime.now().isoformat(),
                "gps": tiene_gps,
                "lat_origen": lat0 if tiene_gps else None,
                "lon_origen": lon0 if tiene_gps else None,
                "ble_total": sum(1 for p in puntos if p.categoria == "BLE"),
                "wifi_total": sum(1 for p in puntos if p.categoria == "WIFI"),
                "estimacion": estimacion.to_dict() if estimacion else None,
            },
            "features": features,
        }

        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(coleccion, f, ensure_ascii=False, indent=2, default=str)

    def resumen(self) -> None:
        console = getattr(self.bt, "console", None)
        if not console:
            return
        with self._lock:
            total = len(self._disp)
            por_prox = {}
            for d in self._disp.values():
                p = _proximidad(d.rssi)
                por_prox[p] = por_prox.get(p, 0) + 1

        tb = Table(title="[bold cyan]GeoExporter — Resumen[/bold cyan]",
                   box=box.ROUNDED, border_style="cyan")
        tb.add_column("Categoría", style="cyan")
        tb.add_column("Cantidad", justify="right", style="bold white")
        tb.add_row("BLE Total", str(total))
        for prox, n in sorted(por_prox.items(), key=lambda x: x[1], reverse=True):
            tb.add_row(f"  {prox}", str(n))
        console.print(tb)


def _circulo_coords(
    lat_c: float, lon_c: float, radio_m: float, pasos: int = 36
) -> list[tuple[float, float]]:
    return [
        _local_a_geo(
            radio_m * math.cos(2 * math.pi * i / pasos),
            radio_m * math.sin(2 * math.pi * i / pasos),
            lat_c, lon_c,
        )
        for i in range(pasos + 1)
    ]


def _circulo_kml(lat_c: float, lon_c: float, radio_m: float, pasos: int = 36) -> str:
    return " ".join(
        f"{lon},{lat},0"
        for lat, lon in _circulo_coords(lat_c, lon_c, radio_m, pasos)
    )


def _circulo_geojson(lat_c: float, lon_c: float, radio_m: float, pasos: int = 36) -> list[list[float]]:
    return [[lon, lat] for lat, lon in _circulo_coords(lat_c, lon_c, radio_m, pasos)]
