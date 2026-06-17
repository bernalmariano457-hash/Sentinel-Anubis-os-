from __future__ import annotations

import bisect
from typing import Final, NamedTuple


class BandRecord(NamedTuple):
    freq_min:    float
    freq_max:    float
    nombre:      str
    tipo:        str
    desc:        str
    tactical:    bool


BANDAS_RF: Final[tuple[BandRecord, ...]] = (
    BandRecord(76.0,     88.0,    "FM Japon",         "BROADCAST", "Radio FM banda japonesa",                       False),
    BandRecord(87.5,    108.0,    "FM Radio",          "BROADCAST", "Radio FM comercial",                            False),
    BandRecord(162.4,   162.55,   "NOAA Weather",      "BROADCAST", "Radio meteorologica NOAA (USA)",                False),
    BandRecord(108.0,   118.0,    "VOR/ILS",           "AVIATION",  "Radionavegacion aerea civil VOR/ILS",           False),
    BandRecord(118.0,   137.0,    "ATC VHF",           "AVIATION",  "Control trafico aereo — AM",                   True),
    BandRecord(960.0,  1215.0,    "TACAN/DME",         "AVIATION",  "Navegacion TACAN/DME",                          False),
    BandRecord(1090.0, 1090.1,    "ADS-B",             "AVIATION",  "Transponders aeronaves 1090ES",                 True),
    BandRecord(978.0,   978.1,    "UAT ADS-B",         "AVIATION",  "ADS-B Universal Access Transceiver (978MHz)",   True),
    BandRecord(137.0,   138.0,    "NOAA/MetSat",       "SATELLITE", "Satelites meteorologicos NOAA/METEOR",          False),
    BandRecord(400.0,   406.0,    "Radiosondas",       "SATELLITE", "Sondeos meteorologicos",                        False),
    BandRecord(406.0,   406.1,    "EPIRB/PLB",         "SAFETY",    "Balizas de emergencia internacionales",         True),
    BandRecord(1525.0, 1559.0,    "Inmarsat/Iridium",  "SATELLITE", "Comunicaciones satelitales L-Band",             True),
    BandRecord(144.0,   148.0,    "VHF Amateur",       "AMATEUR",   "Radio amateur 2m",                              False),
    BandRecord(430.0,   440.0,    "UHF Amateur",       "AMATEUR",   "Radio amateur 70cm",                            False),
    BandRecord(1240.0, 1300.0,    "SHF Amateur 23cm",  "AMATEUR",   "Radio amateur 23cm",                            False),
    BandRecord(148.0,   174.0,    "VHF PMR",           "PMR",       "Radio movil profesional VHF",                   False),
    BandRecord(446.0,   446.2,    "PMR446",            "PMR",       "Walkie-talkies civiles Europa",                  False),
    BandRecord(450.0,   470.0,    "UHF PMR",           "PMR",       "Radio movil profesional UHF",                   False),
    BandRecord(380.0,   400.0,    "TETRA Publica",     "PMR",       "TETRA autoridades de seguridad publica",         True),
    BandRecord(806.0,   869.0,    "TETRA/LMR 800",     "PMR",       "Radio digital TETRA / P25",                     True),
    BandRecord(138.0,   144.0,    "Militar VHF",       "MILITARY",  "Comunicaciones militares VHF",                  True),
    BandRecord(225.0,   400.0,    "Militar UHF/AM",    "MILITARY",  "SATCOM/datos militares HAVE QUICK / SINCGARS",  True),
    BandRecord(1350.0, 1390.0,    "Radar L-Band",      "MILITARY",  "Radar de vigilancia L-Band",                    True),
    BandRecord(315.0,   315.1,    "ISM 315 MHz",       "ISM",       "Mandos distancia EEUU 315 MHz",                 False),
    BandRecord(433.0,   435.0,    "ISM 433 MHz",       "ISM",       "IoT, sensores, mandos EU 433 MHz",              False),
    BandRecord(862.0,   870.0,    "ISM 868 MHz",       "ISM",       "LoRa, Zigbee, alarmas EU",                      False),
    BandRecord(902.0,   928.0,    "ISM 915 MHz",       "ISM",       "LoRa US, RFID, Z-Wave",                         False),
    BandRecord(699.0,   716.0,    "LTE 700 UL",        "CELLULAR",  "Uplink LTE banda 12/17",                        False),
    BandRecord(729.0,   746.0,    "LTE 700 DL",        "CELLULAR",  "Downlink LTE banda 12/17",                      False),
    BandRecord(824.0,   849.0,    "GSM 850 UL",        "CELLULAR",  "Uplink GSM/CDMA 850",                           False),
    BandRecord(869.0,   894.0,    "GSM 850 DL",        "CELLULAR",  "Downlink GSM/CDMA 850",                         False),
    BandRecord(890.0,   915.0,    "GSM 900 UL",        "CELLULAR",  "Uplink GSM 900",                                False),
    BandRecord(935.0,   960.0,    "GSM 900 DL",        "CELLULAR",  "Downlink GSM 900",                              False),
    BandRecord(1710.0, 1785.0,    "GSM 1800 UL",       "CELLULAR",  "Uplink GSM 1800",                               False),
    BandRecord(1805.0, 1880.0,    "GSM 1800 DL",       "CELLULAR",  "Downlink GSM 1800",                             False),
    BandRecord(1920.0, 1980.0,    "UMTS/LTE UL",       "CELLULAR",  "Uplink 3G/4G IMT",                              False),
    BandRecord(2110.0, 2170.0,    "UMTS/LTE DL",       "CELLULAR",  "Downlink 3G/4G IMT",                            False),
    BandRecord(2500.0, 2690.0,    "LTE 2600",          "CELLULAR",  "LTE banda 7/41 2.6 GHz",                        False),
    BandRecord(3400.0, 3800.0,    "5G NR n77/n78",     "CELLULAR",  "5G NR banda media C-band",                      False),
    BandRecord(1176.4, 1176.5,    "GPS L5",            "GNSS",      "GPS señal L5 / Galileo E5a",                   False),
    BandRecord(1227.6, 1227.7,    "GPS L2",            "GNSS",      "GPS señal L2 (semimilitar)",                   True),
    BandRecord(1559.0, 1610.0,    "GNSS L1",           "GNSS",      "GPS/GLONASS/Galileo L1",                        False),
    BandRecord(1575.42, 1575.43,  "GPS L1 C/A",        "GNSS",      "GPS civil señal principal",                    False),
    BandRecord(1602.0, 1616.0,    "GLONASS L1",        "GNSS",      "GLONASS señal L1 FDMA",                        False),
    BandRecord(2400.0, 2484.0,    "ISM 2.4 GHz",       "WIRELESS",  "Wi-Fi b/g/n + Bluetooth + Zigbee",              False),
    BandRecord(5150.0, 5850.0,    "Wi-Fi 5 GHz",       "WIRELESS",  "Wi-Fi a/n/ac/ax 5 GHz",                         False),
    BandRecord(5925.0, 7125.0,    "Wi-Fi 6 GHz",       "WIRELESS",  "Wi-Fi 6E banda 6 GHz",                          False),
    BandRecord(929.0,   932.0,    "POCSAG/FLEX",       "PAGER",     "Paginadores POCSAG/FLEX",                       False),
    BandRecord(26.9,    27.4,     "CB Radio",          "PMR",       "Banda ciudadana 27 MHz",                        False),
    BandRecord(300.0,   400.0,    "UHF Baja",          "MISC",      "Bandas UHF bajas diversas",                     False),
    BandRecord(896.0,   901.0,    "iDEN SMR",          "PMR",       "Motorola iDEN SMR",                             False),
)

COLORES_TIPO: Final[dict[str, str]] = {
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

TACTICAL_SCORE: Final[dict[str, int]] = {
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


class _BandDict(NamedTuple):
    nombre:         str
    tipo:           str
    desc:           str
    tactical:       bool
    color:          str
    tactical_score: int
    rango_mhz:      float
    freq_min:       float
    freq_max:       float


def _make_band_dict(b: BandRecord, include_range: bool = True) -> dict:
    base_score = TACTICAL_SCORE.get(b.tipo, 0)
    out: dict = {
        "nombre":         b.nombre,
        "tipo":           b.tipo,
        "desc":           b.desc,
        "tactical":       b.tactical,
        "color":          COLORES_TIPO.get(b.tipo, "dim"),
        "tactical_score": base_score + (50 if b.tactical else 0),
        "freq_min":       b.freq_min,
        "freq_max":       b.freq_max,
    }
    if include_range:
        out["rango_mhz"] = b.freq_max - b.freq_min
    return out


_SORTED_BY_MAX:  Final[tuple[BandRecord, ...]] = tuple(
    sorted(BANDAS_RF, key=lambda b: b.freq_max)
)
_FMAX_KEYS:      Final[tuple[float, ...]] = tuple(b.freq_max for b in _SORTED_BY_MAX)

_TACTICAL_CACHE: Final[tuple[dict, ...]] = tuple(
    sorted(
        (_make_band_dict(b) for b in BANDAS_RF if b.tactical),
        key=lambda d: -d["tactical_score"],
    )
)

_BY_TYPE_CACHE: Final[dict[str, tuple[dict, ...]]] = {
    tipo: tuple(
        {
            "nombre":   b.nombre,
            "tipo":     b.tipo,
            "desc":     b.desc,
            "tactical": b.tactical,
            "color":    COLORES_TIPO.get(b.tipo, "dim"),
            "freq_min": b.freq_min,
            "freq_max": b.freq_max,
        }
        for b in BANDAS_RF
        if b.tipo == tipo
    )
    for tipo in {b.tipo for b in BANDAS_RF}
}


def identify_band(freq_mhz: float) -> dict | None:
    start = bisect.bisect_left(_FMAX_KEYS, freq_mhz)
    candidates: list[dict] = []

    for idx in range(start, len(_SORTED_BY_MAX)):
        b = _SORTED_BY_MAX[idx]
        if b.freq_min > freq_mhz:
            break
        if b.freq_min <= freq_mhz <= b.freq_max:
            candidates.append(_make_band_dict(b))

    if not candidates:
        return None

    return min(candidates, key=lambda d: (d["rango_mhz"], -d["tactical_score"]))


def bands_in_range(freq_min_mhz: float, freq_max_mhz: float) -> list[dict]:
    start = bisect.bisect_left(_FMAX_KEYS, freq_min_mhz)
    result: list[dict] = []

    for idx in range(start, len(_SORTED_BY_MAX)):
        b = _SORTED_BY_MAX[idx]
        if b.freq_min > freq_max_mhz:
            break
        if b.freq_max >= freq_min_mhz and b.freq_min <= freq_max_mhz:
            result.append(_make_band_dict(b, include_range=False))

    return result


def tactical_bands() -> list[dict]:
    return list(_TACTICAL_CACHE)


def bands_by_type(tipo: str) -> list[dict]:
    return list(_BY_TYPE_CACHE.get(tipo.upper(), ()))
