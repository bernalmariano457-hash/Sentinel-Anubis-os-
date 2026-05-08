from typing import Optional

# ════════════════════════════════════════════════════════════════════
# BASE DE DATOS DE BANDAS RF
# ════════════════════════════════════════════════════════════════════
# Formato: (freq_min_MHz, freq_max_MHz, nombre, tipo, descripción, táctica)
# táctica: True = actividad requiere atención en campo

BANDAS_RF: list[tuple] = [
    # ── VHF Broadcast ───────────────────────────────────────────────
    (76.0,    88.0,   "FM Japón",         "BROADCAST",
     "Radio FM banda japonesa",              False),
    (87.5,   108.0,   "FM Radio",         "BROADCAST",
     "Radio FM comercial",                   False),
    # ── Aviación ────────────────────────────────────────────────────
    (108.0,  118.0,   "VOR/ILS",          "AVIATION",
     "Radionavegación aérea civil",          False),
    (118.0,  137.0,   "ATC VHF",          "AVIATION",
     "Control tráfico aéreo — AM",           True),
    (960.0, 1215.0,   "TACAN/DME",        "AVIATION",
     "Navegación TACAN/DME",                 False),
    (1090.0, 1090.1,   "ADS-B",            "AVIATION",
     "Transponders aeronaves 1090ES",        True),
    # ── Meteorología y satélites ─────────────────────────────────────
    (137.0,  138.0,   "NOAA/MetSat",      "SATELLITE",
     "Satélites meteorológicos NOAA",        False),
    (400.0,  406.0,   "Radiosondas",      "SATELLITE",
     "Sondeos meteorológicos",               False),
    (406.0,  406.1,   "EPIRB/PLB",        "SAFETY",
     "Balizas de emergencia internacionales", True),
    (1525.0, 1559.0,   "Iridium/Inmarsat", "SATELLITE",
     "Comunicaciones satelitales L-Band",    True),
    # ── Amateur ─────────────────────────────────────────────────────
    (144.0,  148.0,   "VHF Amateur",      "AMATEUR",
     "Radio amateur 2m",                     False),
    (430.0,  440.0,   "UHF Amateur",      "AMATEUR",
     "Radio amateur 70cm",                   False),
    # ── PMR / Radios profesionales ───────────────────────────────────
    (148.0,  174.0,   "VHF PMR",          "PMR",
     "Radio móvil profesional VHF",          False),
    (446.0,  446.2,   "PMR446",           "PMR",
     "Walkie-talkies civiles Europa",         False),
    (450.0,  470.0,   "UHF PMR",          "PMR",
     "Radio móvil profesional UHF",          False),
    # ── Militar ─────────────────────────────────────────────────────
    (138.0,  144.0,   "Militar VHF",      "MILITARY",
     "Comunicaciones militares VHF",         True),
    (225.0,  400.0,   "Militar UHF/AM",   "MILITARY",
     "SATCOM/datos militares",               True),
    # ── ISM ─────────────────────────────────────────────────────────
    (315.0,  315.1,   "ISM 315 MHz",      "ISM",
     "Mandos distancia EEUU 315 MHz",        False),
    (433.0,  435.0,   "ISM 433 MHz",      "ISM",
     "IoT, sensores, mandos EU 433 MHz",     False),
    (862.0,  870.0,   "ISM 868 MHz",      "ISM",
     "LoRa, Zigbee, alarmas EU",             False),
    (902.0,  928.0,   "ISM 915 MHz",      "ISM",
     "LoRa US, RFID, Z-Wave",                False),
    # ── Celular ─────────────────────────────────────────────────────
    (806.0,  869.0,   "LTE 800 DL",       "CELLULAR",
     "Downlink LTE banda 20",                False),
    (824.0,  849.0,   "GSM 850 UL",       "CELLULAR",
     "Uplink GSM/CDMA 850",                  False),
    (869.0,  894.0,   "GSM 850 DL",       "CELLULAR",
     "Downlink GSM/CDMA 850",                False),
    (928.0,  960.0,   "GSM 900 DL",       "CELLULAR",
     "Downlink GSM 900",                     False),
    (1710.0, 1785.0,   "GSM 1800 UL",      "CELLULAR",
     "Uplink GSM 1800",                      False),
    (1805.0, 1880.0,   "GSM 1800 DL",      "CELLULAR",
     "Downlink GSM 1800",                    False),
    (2500.0, 2690.0,   "LTE 2600",         "CELLULAR",
     "LTE banda 7/41 2.6 GHz",               False),
    # ── GNSS ────────────────────────────────────────────────────────
    (1176.0, 1176.5,   "GPS L5",           "GNSS",
     "GPS señal L5",                         False),
    (1227.6, 1227.7,   "GPS L2",           "GNSS",
     "GPS señal L2 (semimilitar)",            True),
    (1559.0, 1610.0,   "GNSS L1",          "GNSS",
     "GPS/GLONASS/Galileo L1",               False),
    (1575.4, 1575.5,   "GPS L1 C/A",       "GNSS",
     "GPS civil — señal principal",           False),
    (1602.0, 1616.0,   "GLONASS L1",       "GNSS",
     "GLONASS señal L1",                     False),
    # ── Wi-Fi / BT ──────────────────────────────────────────────────
    (2400.0, 2484.0,   "ISM 2.4 GHz",      "WIRELESS",
     "Wi-Fi b/g/n + Bluetooth",              False),
    (5150.0, 5850.0,   "Wi-Fi 5 GHz",      "WIRELESS",
     "Wi-Fi a/n/ac/ax 5 GHz",               False),
    # ── PAGER / Misc ─────────────────────────────────────────────────
    (929.0,  932.0,   "POCSAG/FLEX",      "PAGER",
     "Paginadores POCSAG/FLEX",              False),
    (300.0,  400.0,   "UHF Baja",         "MISC",
     "Bandas UHF bajas diversas",            False),
    (896.0,  901.0,   "SMR 900",          "PMR",
     "Motorola iDEN SMR",                    False),
]

# ════════════════════════════════════════════════════════════════════
# COLORES POR TIPO (compatible con Rich markup)
# ════════════════════════════════════════════════════════════════════

COLORES_TIPO: dict[str, str] = {
    "BROADCAST": "cyan",
    "AVIATION":  "blue",
    "SATELLITE": "magenta",
    "AMATEUR":   "green",
    "PMR":       "yellow",
    "ISM":       "orange3",
    "CELLULAR":  "red",
    "GNSS":      "bright_cyan",
    "WIRELESS":  "bright_green",
    "MILITARY":  "bold red",
    "SAFETY":    "bold yellow",
    "PAGER":     "dim cyan",
    "MISC":      "dim",
}


# ════════════════════════════════════════════════════════════════════
# FUNCIONES DE CLASIFICACIÓN
# ════════════════════════════════════════════════════════════════════

def identify_band(freq_mhz: float) -> Optional[dict]:
    """
    Identifica la banda más específica que contiene `freq_mhz`.
    "Más específica" = menor rango de frecuencias.

    Returns:
        dict con nombre, tipo, desc, peligro, color, rango_mhz
        o None si no hay coincidencia.
    """
    candidates = []
    for fmin, fmax, nombre, tipo, desc, peligro in BANDAS_RF:
        if fmin <= freq_mhz <= fmax:
            candidates.append({
                "nombre":    nombre,
                "tipo":      tipo,
                "desc":      desc,
                "peligro":   peligro,
                "color":     COLORES_TIPO.get(tipo, "dim"),
                "rango_mhz": fmax - fmin,
                "freq_min":  fmin,
                "freq_max":  fmax,
            })

    if not candidates:
        return None

    return min(candidates, key=lambda x: x["rango_mhz"])


def bands_in_range(freq_min_mhz: float, freq_max_mhz: float) -> list[dict]:
    """
    Retorna todas las bandas que se solapan con el rango dado.
    Útil para etiquetado de barridos.
    """
    result = []
    for fmin, fmax, nombre, tipo, desc, peligro in BANDAS_RF:
        if fmax >= freq_min_mhz and fmin <= freq_max_mhz:
            result.append({
                "nombre":  nombre,
                "tipo":    tipo,
                "desc":    desc,
                "peligro": peligro,
                "color":   COLORES_TIPO.get(tipo, "dim"),
                "freq_min": fmin,
                "freq_max": fmax,
            })
    return result


def tactical_bands() -> list[dict]:
    """Retorna solo las bandas marcadas como tácticas."""
    return [
        {
            "nombre":  n,
            "tipo":    t,
            "desc":    d,
            "color":   COLORES_TIPO.get(t, "dim"),
            "freq_min": fmin,
            "freq_max": fmax,
        }
        for fmin, fmax, n, t, d, peligro in BANDAS_RF if peligro
    ]
