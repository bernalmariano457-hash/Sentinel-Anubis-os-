from __future__ import annotations

import re

_MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}$")

class VendorResolver:
    # Tabla OUI local
    _LOCAL: dict[str, str] = {
        # Apple
        "8C:64:A2": "Apple",        "3C:D9:2B": "Apple",        "00:17:F2": "Apple",
        # Samsung
        "58:CB:52": "Samsung",      "90:7A:58": "Samsung",      "B0:72:BF": "Samsung",
        # Huawei
        "D8:24:BD": "Huawei",       "00:E0:FC": "Huawei",       "6C:4B:90": "Huawei",
        # Intel
        "64:16:7F": "Intel",        "48:51:B7": "Intel",        "A4:C3:F0": "Intel",
        # Virtualización
        "00:0C:29": "VMware",       "08:00:27": "VirtualBox",   "00:50:56": "VMware ESXi",
        # Raspberry Pi
        "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi 4", "E4:5F:01": "Raspberry Pi 5",
        # Networking / enterprise
        "18:60:24": "Cisco",        "00:1A:A0": "Dell",
        # Móviles
        "FC:EC:DA": "Xiaomi",       "64:09:80": "Xiaomi",       "F4:60:E2": "Motorola",
        "78:02:F8": "OnePlus",      "AC:37:43": "HTC",
        # Microsoft
        "00:50:F2": "Microsoft",    "28:18:78": "Microsoft",    "00:15:5D": "Microsoft",
        # Fitbit / wearables
        "00:1D:FE": "Fitbit",       "88:B4:A6": "Fitbit",
        # Espressif (ESP32, ESP8266 — IoT / BLE)
        "A4:C1:38": "Espressif",    "30:AE:A4": "Espressif",    "24:6F:28": "Espressif",
        # Apple — MACs adicionales BLE
        "00:1A:7D": "Apple",        "AC:DE:48": "Apple",
        "F0:18:98": "Apple",        "00:1B:63": "Apple",
        # Samsung — MACs adicionales BLE
        "00:1B:DC": "Samsung",      "8C:71:F8": "Samsung",
    }

    _cache: dict[str, str] = {}

    # API pública (lazy import)
    _API_URL = "https://api.macvendors.com/{mac}"
    _USER_AGENT = "ApexSentinel/2.3"

    @classmethod
    def resolve(cls, mac: str) -> str:
        if not mac:
            return "Desconocido"

        mac_upper = mac.upper()

        # 1 — Caché
        if mac_upper in cls._cache:
            return cls._cache[mac_upper]

        vendor = cls._lookup(mac_upper)
        cls._cache[mac_upper] = vendor
        return vendor

    @classmethod
    def _lookup(cls, mac_upper: str) -> str:
        # 2 — Tabla local
        prefijo = mac_upper[:8]
        if prefijo in cls._LOCAL:
            return cls._LOCAL[prefijo]

        # 3 — MAC aleatorizada (bit U/L del primer octeto)
        try:
            if int(mac_upper.split(":")[0], 16) & 0x02:
                return "MAC aleatorizada"
        except (ValueError, IndexError):
            pass

        # 4 — API remota
        return cls._api_lookup(mac_upper)

    @classmethod
    def _api_lookup(cls, mac: str) -> str:
        try:
            import requests  # importación diferida — no disponible en todos los entornos
            r = requests.get(
                cls._API_URL.format(mac=mac),
                timeout=3,
                headers={"User-Agent": cls._USER_AGENT},
            )
            return r.text.strip() if r.status_code == 200 else "Desconocido"
        except Exception:
            return "Desconocido"

    @classmethod
    def clear_cache(cls) -> None:
        """Vacía el caché en memoria (útil en tests)."""
        cls._cache.clear()

    @classmethod
    def is_valid_mac(cls, mac: str) -> bool:
        return bool(_MAC_RE.match(mac))
