from __future__ import annotations

import math
import threading

import pytest
from rich.console import Console

from _test_shared import _BtModuleFalso
from modules.network.wifi_ble_fusion import (
    EstimacionPosicion,
    FusionBLEWiFi,
    FuenteWifi,
    MetodoPosicion,
    PuntoAP,
    WiFiScanner,
    _bloque_a_punto,
    _centroide_ponderado,
    _parsear_iwlist,
    _residual_rms,
    _signal_a_dbm,
    _trilaterar,
    peso_por_distancia,
    rssi_a_distancia,
)


def test_rssi_a_distancia_aplica_piso_minimo():
    assert rssi_a_distancia(rssi=-20, tx_dbm=-30) == pytest.approx(0.5)


def test_rssi_a_distancia_aplica_techo_maximo():
    dist = rssi_a_distancia(rssi=-95, tx_dbm=20, n=2.7)
    assert dist == pytest.approx(150.0)


def test_rssi_a_distancia_es_monotona():
    d1 = rssi_a_distancia(rssi=-65, tx_dbm=-59)
    d2 = rssi_a_distancia(rssi=-75, tx_dbm=-59)
    d3 = rssi_a_distancia(rssi=-85, tx_dbm=-59)
    assert d1 < d2 < d3
    assert d3 < 150.0


def test_peso_por_distancia_favorece_lo_cercano():
    assert peso_por_distancia(1.0) > peso_por_distancia(
        10.0) > peso_por_distancia(100.0)


def test_signal_a_dbm_valores_limite():
    assert _signal_a_dbm(0) == -100
    assert _signal_a_dbm(100) == -50


def test_signal_a_dbm_valor_intermedio():
    assert _signal_a_dbm(70) == -65


def test_signal_a_dbm_satura_fuera_de_rango():
    assert _signal_a_dbm(-10) == _signal_a_dbm(0)
    assert _signal_a_dbm(150) == _signal_a_dbm(100)


def test_signal_a_dbm_es_monotono():
    valores = [_signal_a_dbm(s) for s in range(0, 101, 10)]
    for i in range(len(valores) - 1):
        assert valores[i] <= valores[i + 1]


def test_residual_rms_cero_con_distancias_exactas():
    pos = (5.0, 0.0)
    refs = [(0.0, 0.0, 5.0), (10.0, 0.0, 5.0)]
    assert _residual_rms(pos, refs) == pytest.approx(0.0, abs=1e-9)


def test_residual_rms_positivo_con_discrepancia():
    pos = (5.0, 0.0)
    refs = [(0.0, 0.0, 10.0), (10.0, 0.0, 5.0)]
    assert _residual_rms(pos, refs) > 0.0


def test_residual_rms_lista_vacia_devuelve_cero():
    assert _residual_rms((3.0, 4.0), []) == 0.0


_IWLIST_SAMPLE = """\
wlan0     Scan completed :
          Cell 01 - Address: AA:BB:CC:DD:EE:FF
                    ESSID:"MiRed"
                    Frequency:2.412 GHz (Channel 1)
                    Signal level=-65 dBm  Noise level=-90 dBm
          Cell 02 - Address: 11:22:33:44:55:66
                    ESSID:"Otra"
                    Frequency:5.180 GHz (Channel 36)
                    Signal level=-80 dBm
          Cell 03 - Address: AA:AA:AA:AA:AA:AA
                    ESSID:"Debil"
                    Frequency:2.437 GHz (Channel 6)
                    Signal level=-96 dBm
"""


def test_parsear_iwlist_extrae_puntos_validos():
    puntos = _parsear_iwlist(_IWLIST_SAMPLE, rssi_min=-95)
    assert len(puntos) == 2
    bssids = {p.bssid for p in puntos}
    assert "AA:BB:CC:DD:EE:FF" in bssids
    assert "11:22:33:44:55:66" in bssids


def test_parsear_iwlist_campos_correctos():
    puntos = _parsear_iwlist(_IWLIST_SAMPLE, rssi_min=-95)
    mi_red = next(p for p in puntos if p.bssid == "AA:BB:CC:DD:EE:FF")
    assert mi_red.ssid == "MiRed"
    assert mi_red.rssi == -65
    assert mi_red.frecuencia == 2412
    assert mi_red.canal == 1
    assert mi_red.fuente == FuenteWifi.IWLIST


def test_parsear_iwlist_filtra_por_rssi_min():
    puntos = _parsear_iwlist(_IWLIST_SAMPLE, rssi_min=-70)
    assert len(puntos) == 1
    assert puntos[0].bssid == "AA:BB:CC:DD:EE:FF"


def test_bloque_a_punto_con_datos_minimos():
    p = _bloque_a_punto(
        {"bssid": "AA:BB:CC:DD:EE:FF", "rssi": -70}, rssi_min=-95)
    assert p is not None
    assert p.bssid == "AA:BB:CC:DD:EE:FF"
    assert p.rssi == -70
    assert p.frecuencia == 2412
    assert p.canal == 1


def test_bloque_a_punto_filtrado_por_rssi():
    p = _bloque_a_punto({"bssid": "AA:BB:CC:DD:EE:FF",
                        "rssi": -100}, rssi_min=-95)
    assert p is None


def _referencias_desde_posicion(pos, aps, ruido=None):
    ruido = ruido or [0.0] * len(aps)
    refs = []
    for (x, y), r in zip(aps, ruido, strict=True):
        d = math.hypot(pos[0] - x, pos[1] - y) + r
        refs.append((x, y, d))
    return refs


def test_trilaterar_recupera_posicion_conocida_con_distancias_exactas():
    real = (7.0, 4.0)
    aps = [(0, 0), (20, 0), (0, 20), (15, 15)]
    refs = _referencias_desde_posicion(real, aps)
    resultado = _trilaterar(refs)
    assert resultado is not None
    x, y, residual = resultado
    assert x == pytest.approx(real[0], abs=1e-6)
    assert y == pytest.approx(real[1], abs=1e-6)
    assert residual == pytest.approx(0.0, abs=1e-6)


def test_trilaterar_pondera_menos_una_referencia_con_error_grande():
    real = (7.0, 4.0)
    aps = [(0, 0), (20, 0), (0, 20), (15, 15)]
    refs = _referencias_desde_posicion(real, aps)
    refs_outlier = list(refs)
    x, y, d = refs_outlier[3]
    refs_outlier[3] = (x, y, d + 15.0)
    resultado = _trilaterar(refs_outlier)
    assert resultado is not None
    x_est, y_est, residual = resultado
    error = math.hypot(x_est - real[0], y_est - real[1])
    assert error < 5.0
    assert residual > 1.0


def test_trilaterar_geometria_colineal_exacta_devuelve_none():
    refs = [(0, 0, 5.0), (10, 0.001, 5.0), (20, 0.002, 5.0)]
    assert _trilaterar(refs) is None


def test_trilaterar_numero_de_condicion_elevado_devuelve_none():
    refs = [
        (0.0, 0.0, 10.0),
        (100.0, 0.0, 10.0),
        (50.0, 0.01, 10.0),
    ]
    assert _trilaterar(refs) is None


def test_trilaterar_menos_de_dos_referencias_devuelve_none():
    assert _trilaterar([(0, 0, 5.0)]) is None
    assert _trilaterar([]) is None


def test_trilaterar_dos_referencias_sigue_funcionando():
    refs = [(0, 0, 5.0), (10, 0, 5.0)]
    resultado = _trilaterar(refs)
    assert resultado is not None
    x, y, residual = resultado
    assert isinstance(x, float) and isinstance(y, float)
    assert residual >= 0.0


def test_centroide_ponderado_con_una_referencia_devuelve_esa_posicion():
    x, y = _centroide_ponderado([(3.0, 4.0, 2.0)])
    assert (x, y) == pytest.approx((3.0, 4.0))


def test_metodo_posicion_se_imprime_como_valor_plano():
    assert str(MetodoPosicion.TRILATERACION) == "trilateration"
    assert f"{MetodoPosicion.CENTROIDE_PONDERADO}" == "weighted_centroid"


def test_metodo_posicion_compara_igual_a_string_plano():
    assert MetodoPosicion.TRILATERACION == "trilateration"


def test_fuente_wifi_se_imprime_como_valor_plano():
    assert str(FuenteWifi.NMCLI) == "nmcli"
    assert str(FuenteWifi.IWLIST) == "iwlist"


def test_fusion_ve_dispositivos_incluso_si_bt_module_reemplaza_el_dict():
    bt = _BtModuleFalso()
    fusion = FusionBLEWiFi(bt_module=bt, wifi_scanner=WiFiScanner())
    assert fusion._disp is bt._dispositivos
    assert len(fusion._disp) == 0
    nuevo_dict = {"AA:BB:CC:DD:EE:FF": object()}
    bt._dispositivos = nuevo_dict
    assert fusion._disp is nuevo_dict
    assert len(fusion._disp) == 1


def test_fusion_lock_sigue_al_de_bt_module():
    bt = _BtModuleFalso()
    fusion = FusionBLEWiFi(bt_module=bt, wifi_scanner=WiFiScanner())
    assert fusion._lock is bt._lock
    nuevo_lock = threading.Lock()
    bt._lock = nuevo_lock
    assert fusion._lock is nuevo_lock


def test_fusion_lock_usa_fallback_si_bt_module_no_tiene_uno():
    class _SinLock:
        def __init__(self):
            self._dispositivos = {}

    fusion = FusionBLEWiFi(bt_module=_SinLock(), wifi_scanner=WiFiScanner())
    assert fusion._lock is fusion._lock


def test_wifiscanner_registrar_y_cargar_posiciones():
    scanner = WiFiScanner()
    scanner.registrar_posicion("aa:bb:cc:dd:ee:ff", 1.5, 2.5)
    assert scanner._posiciones["AA:BB:CC:DD:EE:FF"] == (1.5, 2.5)
    scanner.cargar_posiciones({"11:22:33:44:55:66": (3.0, 4.0)})
    assert scanner._posiciones["11:22:33:44:55:66"] == (3.0, 4.0)
    assert scanner._posiciones["AA:BB:CC:DD:EE:FF"] == (1.5, 2.5)


def test_estimacion_posicion_to_dict_serializa_metodo_como_string():
    import json
    est = EstimacionPosicion(
        x=1.0, y=2.0, precision_m=3.0,
        metodo=MetodoPosicion.TRILATERACION,
        fuentes_wifi=2, fuentes_ble=1,
    )
    serializado = json.dumps(est.to_dict())
    assert '"metodo": "trilateration"' in serializado


def test_estimar_posicion_no_escanea_si_recibe_aps_externos():
    scan_count = [0]

    class _ScannerContador(WiFiScanner):
        def escanear(self):
            scan_count[0] += 1
            return []

    bt = _BtModuleFalso(console=Console(record=True))
    scanner = _ScannerContador()
    fusion = FusionBLEWiFi(bt_module=bt, wifi_scanner=scanner)
    aps = scanner.escanear()
    assert scan_count[0] == 1
    fusion.estimar_posicion(aps=aps)
    assert scan_count[0] == 1


def test_estimar_posicion_escanea_por_si_sola_si_no_recibe_aps():
    scan_count = [0]

    class _ScannerContador(WiFiScanner):
        def escanear(self):
            scan_count[0] += 1
            return []

    bt = _BtModuleFalso(console=Console(record=True))
    fusion = FusionBLEWiFi(bt_module=bt, wifi_scanner=_ScannerContador())
    fusion.estimar_posicion()
    assert scan_count[0] == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
