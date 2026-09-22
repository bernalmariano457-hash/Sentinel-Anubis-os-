from __future__ import annotations

import json
import math
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from rich.console import Console

from _test_shared import _BtModuleFalso, _DispositivoBLEFalso
from modules.network.geo_export import (
    GeoExporter,
    _circulo_coords,
    _circulo_geojson,
    _circulo_kml,
    _etiquetar_si_sin_gps,
    _local_a_geo,
    _mac_a_angulo,
    _proximidad,
    _sanitizar_prefijo,
)
from modules.network.wifi_ble_fusion import EstimacionPosicion, FuenteWifi, MetodoPosicion, PuntoAP

_KML_NS = "http://www.opengis.net/kml/2.2"


def test_sanitizar_prefijo_quita_separadores_de_ruta():
    limpio = _sanitizar_prefijo("../../etc/cron.d/malicioso")
    assert "/" not in limpio
    assert ".." not in limpio


def test_sanitizar_prefijo_conserva_nombre_simple():
    assert _sanitizar_prefijo("mi_escaneo-1") == "mi_escaneo-1"


def test_sanitizar_prefijo_vacio_usa_default():
    assert _sanitizar_prefijo("") == "ble_map"
    assert _sanitizar_prefijo("///") == "ble_map"


def test_mac_a_angulo_es_deterministico():
    a1 = _mac_a_angulo("AA:BB:CC:DD:EE:FF")
    a2 = _mac_a_angulo("AA:BB:CC:DD:EE:FF")
    assert a1 == a2


def test_mac_a_angulo_en_rango_valido():
    angulo = _mac_a_angulo("11:22:33:44:55:66")
    assert 0.0 <= angulo < 2 * math.pi


def test_local_a_geo_mover_al_norte_aumenta_latitud():
    lat0, lon0 = 10.0, 20.0
    lat, lon = _local_a_geo(x_m=0.0, y_m=100.0, lat0=lat0, lon0=lon0)
    assert lat > lat0
    assert lon == pytest.approx(lon0)


def test_local_a_geo_mover_al_este_aumenta_longitud():
    lat0, lon0 = 10.0, 20.0
    lat, lon = _local_a_geo(x_m=100.0, y_m=0.0, lat0=lat0, lon0=lon0)
    assert lon > lon0
    assert lat == pytest.approx(lat0)


def test_etiquetar_sin_gps_marca_nombre_y_agrega_advertencia():
    nombre, props = _etiquetar_si_sin_gps("Mi AP", {"ssid": "Mi AP"}, tiene_gps=False)
    assert nombre.startswith("[SIN GPS]")
    assert "_advertencia" in props


def test_etiquetar_con_gps_no_modifica_nada():
    original = {"ssid": "Mi AP"}
    nombre, props = _etiquetar_si_sin_gps("Mi AP", original, tiene_gps=True)
    assert nombre == "Mi AP"
    assert "_advertencia" not in props


def test_etiquetar_sin_gps_no_muta_el_dict_original():
    original = {"ssid": "Mi AP"}
    _etiquetar_si_sin_gps("Mi AP", original, tiene_gps=False)
    assert "_advertencia" not in original


def test_proximidad_clasifica_correctamente():
    assert _proximidad(-40) == "MUY CERCA"
    assert _proximidad(-50) == "MUY CERCA"
    assert _proximidad(-51) == "CERCA"
    assert _proximidad(-65) == "CERCA"
    assert _proximidad(-66) == "MEDIO"
    assert _proximidad(-80) == "MEDIO"
    assert _proximidad(-81) == "LEJOS"
    assert _proximidad(-95) == "LEJOS"


def test_circulo_coords_cierra_el_anillo():
    coords = _circulo_coords(10.0, 20.0, 50.0)
    assert coords[0] == coords[-1]


def test_circulo_coords_tiene_pasos_mas_uno_puntos():
    pasos = 24
    coords = _circulo_coords(0.0, 0.0, 10.0, pasos=pasos)
    assert len(coords) == pasos + 1


def test_circulo_kml_cierra_el_anillo():
    coords_str = _circulo_kml(10.0, 20.0, 50.0)
    partes = coords_str.split()
    assert partes[0] == partes[-1]


def test_circulo_kml_formato_lon_lat_altitud():
    coords_str = _circulo_kml(0.0, 0.0, 10.0, pasos=4)
    primer_punto = coords_str.split()[0]
    partes = primer_punto.split(",")
    assert len(partes) == 3
    assert partes[2] == "0"


def test_circulo_geojson_cierra_el_anillo():
    ring = _circulo_geojson(10.0, 20.0, 50.0)
    assert ring[0] == ring[-1]


def test_circulo_geojson_formato_lon_lat():
    ring = _circulo_geojson(0.0, 0.0, 10.0, pasos=4)
    assert all(len(p) == 2 for p in ring)


def test_exportar_ve_dispositivos_incluso_si_bt_module_reemplaza_el_dict():
    bt = _BtModuleFalso()
    exporter = GeoExporter(bt_module=bt)
    assert exporter._disp is bt._dispositivos
    nuevo = {"AA:AA:AA:AA:AA:AA": _DispositivoBLEFalso("AA:AA:AA:AA:AA:AA", rssi=-60)}
    bt._dispositivos = nuevo
    assert exporter._disp is nuevo


def test_exportar_kml_y_geojson_de_extremo_a_extremo_con_cdata_real():
    disp_normal = _DispositivoBLEFalso(
        address="AA:BB:CC:DD:EE:FF", rssi=-55, nombre="Auriculares",
        fabricante="Acme", servicios=["audio"],
    )
    disp_raro = _DispositivoBLEFalso(
        address="11:22:33:44:55:66", rssi=-70,
        nombre='<script>alert(1)</script> y ]]> raro & "cosas"',
    )
    bt = _BtModuleFalso({
        disp_normal.address: disp_normal,
        disp_raro.address: disp_raro,
    })
    exporter = GeoExporter(bt_module=bt)

    ap = PuntoAP(
        bssid="DE:AD:BE:EF:00:01", ssid="Red_Casa & Cia",
        rssi=-60, frecuencia=2437, canal=6, distancia_m=8.0,
        fuente=FuenteWifi.NMCLI,
    )
    estimacion = EstimacionPosicion(
        x=1.0, y=2.0, precision_m=3.5,
        metodo=MetodoPosicion.TRILATERACION,
        fuentes_wifi=1, fuentes_ble=1,
    )

    with tempfile.TemporaryDirectory() as tmp:
        rutas = exporter.exportar(
            lat_origen=19.0, lon_origen=-99.0,
            estimacion=estimacion, aps=[ap],
            directorio=tmp, prefijo="test/../evil",
        )

        assert Path(rutas["kml"]).parent == Path(tmp)
        assert Path(rutas["geojson"]).parent == Path(tmp)

        kml_texto = Path(rutas["kml"]).read_text(encoding="utf-8")

        assert "<![CDATA[" in kml_texto
        assert "&lt;![CDATA[" not in kml_texto

        root = ET.fromstring(kml_texto)

        descripciones = [
            d.text for d in root.iter(f"{{{_KML_NS}}}description")
        ]
        assert any(desc and "]]&gt;" in desc for desc in descripciones)

        geo = json.loads(Path(rutas["geojson"]).read_text(encoding="utf-8"))
        assert geo["type"] == "FeatureCollection"
        assert len(geo["features"]) >= 2


def test_exportar_sin_gps_etiqueta_puntos_como_sin_gps():
    disp = _DispositivoBLEFalso(address="AA:AA:AA:AA:AA:AA", rssi=-65, nombre="Beacon")
    bt = _BtModuleFalso({disp.address: disp})
    exporter = GeoExporter(bt_module=bt)

    with tempfile.TemporaryDirectory() as tmp:
        rutas = exporter.exportar(directorio=tmp, prefijo="sin_gps")
        geo = json.loads(Path(rutas["geojson"]).read_text(encoding="utf-8"))
        nombres = [f["properties"]["_nombre"] for f in geo["features"]]
        assert any(n.startswith("[SIN GPS]") for n in nombres)


def test_exportar_dos_veces_no_pisa_archivos():
    bt = _BtModuleFalso()
    exporter = GeoExporter(bt_module=bt)
    with tempfile.TemporaryDirectory() as tmp:
        r1 = exporter.exportar(directorio=tmp, prefijo="dup")
        r2 = exporter.exportar(directorio=tmp, prefijo="dup")
        assert r1["kml"] != r2["kml"]
        assert Path(r1["kml"]).exists() and Path(r2["kml"]).exists()


def test_resumen_renderiza_tabla_con_dispositivos():
    disp = _DispositivoBLEFalso("AA:AA:AA:AA:AA:AA", rssi=-55)
    console = Console(record=True)
    bt = _BtModuleFalso({"AA:AA:AA:AA:AA:AA": disp}, console=console)
    exporter = GeoExporter(bt_module=bt)
    exporter.resumen()
    txt = console.export_text()
    assert "BLE Total" in txt
    assert "1" in txt


def test_resumen_sin_console_no_explota():
    bt = _BtModuleFalso()
    exporter = GeoExporter(bt_module=bt)
    exporter.resumen()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
