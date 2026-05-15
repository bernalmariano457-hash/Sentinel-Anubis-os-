from __future__ import annotations




# ════════════════════════════════════════════════════════════════════
# BASE DE DATOS DE BANDAS RF
# ════════════════════════════════════════════════════════════════════
# (freq_min_MHz, freq_max_MHz, nombre, tipo, descripcion, tactica)
# tactica: True = banda de alto interés operacional

BANDAS_RF: list[tuple] = [
    # ── Broadcast ───────────────────────────────────────────────────
    (76.0,    88.0,   "FM Japon",          "BROADCAST",
     "Radio FM banda japonesa",                        False),
    (87.5,   108.0,   "FM Radio",          "BROADCAST",
     "Radio FM comercial",                             False),
    (162.4,  162.55,  "NOAA Weather",      "BROADCAST",
     "Radio meteorologica NOAA (USA)",                 False),
    # ── Aviacion ────────────────────────────────────────────────────
    (108.0,  118.0,   "VOR/ILS",           "AVIATION",
     "Radionavegacion aerea civil VOR/ILS",            False),
    (118.0,  137.0,   "ATC VHF",           "AVIATION",
     "Control trafico aereo — AM",                     True),
    (960.0, 1215.0,   "TACAN/DME",         "AVIATION",
     "Navegacion TACAN/DME",                           False),
    (1090.0, 1090.1,  "ADS-B",             "AVIATION",
     "Transponders aeronaves 1090ES",                  True),
    (978.0,  978.1,   "UAT ADS-B",         "AVIATION",
     "ADS-B Universal Access Transceiver (978MHz)",    True),
    # ── Meteorologia y satelites ─────────────────────────────────────
    (137.0,  138.0,   "NOAA/MetSat",       "SATELLITE",
     "Satelites meteorologicos NOAA/METEOR",           False),
    (400.0,  406.0,   "Radiosondas",       "SATELLITE",
     "Sondeos meteorologicos",                         False),
    (406.0,  406.1,   "EPIRB/PLB",         "SAFETY",
     "Balizas de emergencia internacionales",          True),
    (1525.0, 1559.0,  "Inmarsat/Iridium",  "SATELLITE",
     "Comunicaciones satelitales L-Band",              True),
    # ── Amateur ─────────────────────────────────────────────────────
    (144.0,  148.0,   "VHF Amateur",       "AMATEUR",
     "Radio amateur 2m",                               False),
    (430.0,  440.0,   "UHF Amateur",       "AMATEUR",
     "Radio amateur 70cm",                             False),
    (1240.0, 1300.0,  "SHF Amateur 23cm",  "AMATEUR",
     "Radio amateur 23cm",                             False),
    # ── PMR / Profesional movil ──────────────────────────────────────
    (148.0,  174.0,   "VHF PMR",           "PMR",
     "Radio movil profesional VHF",                    False),
    (446.0,  446.2,   "PMR446",            "PMR",
     "Walkie-talkies civiles Europa",                  False),
    (450.0,  470.0,   "UHF PMR",           "PMR",
     "Radio movil profesional UHF",                    False),
    (380.0,  400.0,   "TETRA Publica",     "PMR",
     "TETRA autoridades de seguridad publica",         True),
    (806.0,  869.0,   "TETRA/LMR 800",     "PMR",
     "Radio digital TETRA / P25",                      True),
    # ── Militar ─────────────────────────────────────────────────────
    (138.0,  144.0,   "Militar VHF",       "MILITARY",
     "Comunicaciones militares VHF",                   True),
    (225.0,  400.0,   "Militar UHF/AM",    "MILITARY",
     "SATCOM/datos militares HAVE QUICK / SINCGARS",   True),
    (1350.0, 1390.0,  "Radar L-Band",      "MILITARY",
     "Radar de vigilancia L-Band",                     True),
    # ── ISM ─────────────────────────────────────────────────────────
    (315.0,  315.1,   "ISM 315 MHz",       "ISM",
     "Mandos distancia EEUU 315 MHz",                  False),
    (433.0,  435.0,   "ISM 433 MHz",       "ISM",
     "IoT, sensores, mandos EU 433 MHz",               False),
    (862.0,  870.0,   "ISM 868 MHz",       "ISM",
     "LoRa, Zigbee, alarmas EU",                       False),
    (902.0,  928.0,   "ISM 915 MHz",       "ISM",
     "LoRa US, RFID, Z-Wave",                          False),
    # ── Celular ─────────────────────────────────────────────────────
    (699.0,  716.0,   "LTE 700 UL",        "CELLULAR",
     "Uplink LTE banda 12/17",                         False),
    (729.0,  746.0,   "LTE 700 DL",        "CELLULAR",
     "Downlink LTE banda 12/17",                       False),
    (824.0,  849.0,   "GSM 850 UL",        "CELLULAR",
     "Uplink GSM/CDMA 850",                            False),
    (869.0,  894.0,   "GSM 850 DL",        "CELLULAR",
     "Downlink GSM/CDMA 850",                          False),
    (890.0,  915.0,   "GSM 900 UL",        "CELLULAR",
     "Uplink GSM 900",                                 False),
    (935.0,  960.0,   "GSM 900 DL",        "CELLULAR",
     "Downlink GSM 900",                               False),
    (1710.0, 1785.0,  "GSM 1800 UL",       "CELLULAR",
     "Uplink GSM 1800",                                False),
    (1805.0, 1880.0,  "GSM 1800 DL",       "CELLULAR",
     "Downlink GSM 1800",                              False),
    (1920.0, 1980.0,  "UMTS/LTE UL",       "CELLULAR",
     "Uplink 3G/4G IMT",                               False),
    (2110.0, 2170.0,  "UMTS/LTE DL",       "CELLULAR",
     "Downlink 3G/4G IMT",                             False),
    (2500.0, 2690.0,  "LTE 2600",          "CELLULAR",
     "LTE banda 7/41 2.6 GHz",                         False),
    (3400.0, 3800.0,  "5G NR n77/n78",     "CELLULAR",
     "5G NR banda media C-band",                       False),
    # ── GNSS ────────────────────────────────────────────────────────
    (1176.4, 1176.5,  "GPS L5",            "GNSS",
     "GPS señal L5 / Galileo E5a",                     False),
    (1227.6, 1227.7,  "GPS L2",            "GNSS",
     "GPS señal L2 (semimilitar)",                     True),
    (1559.0, 1610.0,  "GNSS L1",           "GNSS",
     "GPS/GLONASS/Galileo L1",                         False),
    (1575.42, 1575.43, "GPS L1 C/A",       "GNSS",
     "GPS civil señal principal",                      False),
    (1602.0, 1616.0,  "GLONASS L1",        "GNSS",
     "GLONASS señal L1 FDMA",                          False),
    # ── Wi-Fi / BT ──────────────────────────────────────────────────
    (2400.0, 2484.0,  "ISM 2.4 GHz",       "WIRELESS",
     "Wi-Fi b/g/n + Bluetooth + Zigbee",               False),
    (5150.0, 5850.0,  "Wi-Fi 5 GHz",       "WIRELESS",
     "Wi-Fi a/n/ac/ax 5 GHz",                          False),
    (5925.0, 7125.0,  "Wi-Fi 6 GHz",       "WIRELESS",
     "Wi-Fi 6E banda 6 GHz",                           False),
    # ── PAGER / Misc ─────────────────────────────────────────────────
    (929.0,  932.0,   "POCSAG/FLEX",       "PAGER",
     "Paginadores POCSAG/FLEX",                        False),
    (26.9,   27.4,    "CB Radio",          "PMR",
     "Banda ciudadana 27 MHz",                         False),
    (300.0,  400.0,   "UHF Baja",          "MISC",
     "Bandas UHF bajas diversas",                      False),
    (896.0,  901.0,   "iDEN SMR",          "PMR",
     "Motorola iDEN SMR",                              False),
]

# ════════════════════════════════════════════════════════════════════
# COLORES RICH POR TIPO
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

# Puntuacion tactica por tipo (mayor = mas relevante en campo)
TACTICAL_SCORE: dict[str, int] = {
    "MILITARY":  100,
    "AVIATION":   80,
    "SATELLITE":  60,
    "SAFETY":     70,
    "PMR":        40,
    "GNSS":       30,
    "CELLULAR":   20,
    "ISM":        10,
    "AMATEUR":    10,
    "BROADCAST":   5,
    "WIRELESS":    5,
    "PAGER":       5,
    "MISC":        1,
}


# ════════════════════════════════════════════════════════════════════
# FUNCIONES DE CLASIFICACIÓN
# ════════════════════════════════════════════════════════════════════

def identify_band(freq_mhz: float) -> dict | None:
    candidates = []
    for fmin, fmax, nombre, tipo, desc, peligro in BANDAS_RF:
        if fmin <= freq_mhz <= fmax:
            candidates.append({
                "nombre":        nombre,
                "tipo":          tipo,
                "desc":          desc,
                "peligro":       peligro,
                "color":         COLORES_TIPO.get(tipo, "dim"),
                "tactical_score": TACTICAL_SCORE.get(tipo, 0) + (50 if peligro else 0),
                "rango_mhz":     fmax - fmin,
                "freq_min":      fmin,
                "freq_max":      fmax,
            })

    if not candidates:
        return None

    # Más específica primero (menor rango), luego mayor puntuacion tactica
    return min(candidates, key=lambda x: (x["rango_mhz"], -x["tactical_score"]))


def bands_in_range(freq_min_mhz: float,
                   freq_max_mhz: float) -> list[dict]:
    result = []
    for fmin, fmax, nombre, tipo, desc, peligro in BANDAS_RF:
        if fmax >= freq_min_mhz and fmin <= freq_max_mhz:
            result.append({
                "nombre":        nombre,
                "tipo":          tipo,
                "desc":          desc,
                "peligro":       peligro,
                "color":         COLORES_TIPO.get(tipo, "dim"),
                "tactical_score": TACTICAL_SCORE.get(tipo, 0),
                "freq_min":      fmin,
                "freq_max":      fmax,
            })
    return result


def tactical_bands() -> list[dict]:
    return sorted(
        [
            {
                "nombre":        n,
                "tipo":          t,
                "desc":          d,
                "color":         COLORES_TIPO.get(t, "dim"),
                "tactical_score": TACTICAL_SCORE.get(t, 0) + 50,
                "freq_min":      fmin,
                "freq_max":      fmax,
            }
            for fmin, fmax, n, t, d, peligro in BANDAS_RF if peligro
        ],
        key=lambda x: -x["tactical_score"],
    )


def bands_by_type(tipo: str) -> list[dict]:
    return [
        {
            "nombre":   n,
            "tipo":     t,
            "desc":     d,
            "peligro":  peligro,
            "color":    COLORES_TIPO.get(t, "dim"),
            "freq_min": fmin,
            "freq_max": fmax,
        }
        for fmin, fmax, n, t, d, peligro in BANDAS_RF
        if t.upper() == tipo.upper()
    ]
