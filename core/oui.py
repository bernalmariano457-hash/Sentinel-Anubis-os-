from __future__ import annotations

# Prefijos OUI de 3 octetos (XX:XX:XX) → fabricante
_OUI_LOCAL: dict[str, str] = {
    "8C:64:A2": "Apple",          "3C:D9:2B": "Apple",       "00:17:F2": "Apple",
    "58:CB:52": "Samsung",        "90:7A:58": "Samsung",     "B0:72:BF": "Samsung",
    "D8:24:BD": "Huawei",         "00:E0:FC": "Huawei",      "6C:4B:90": "Huawei",
    "64:16:7F": "Intel",          "48:51:B7": "Intel",       "A4:C3:F0": "Intel",
    "00:0C:29": "VMware",         "08:00:27": "VirtualBox",
    "B8:27:EB": "Raspberry Pi",   "DC:A6:32": "Raspberry Pi 4",
    "E4:5F:01": "Raspberry Pi 5",
    "00:50:56": "VMware ESXi",    "18:60:24": "Cisco",       "00:1A:A0": "Dell",
    "FC:EC:DA": "Xiaomi",         "64:09:80": "Xiaomi",      "F4:60:E2": "Motorola",
    "78:02:F8": "OnePlus",        "AC:37:43": "HTC",
}


class OUIResolver:
    def __init__(self, version: str = "2.3") -> None:
        self._version = version
        self._cache: dict[str, str] = {}

    def obtener_fabricante(self, mac: str) -> str:
        mac_upper = mac.upper()

        # 1. Caché caliente
        if mac_upper in self._cache:
            return self._cache[mac_upper]

        # 2. Tabla local (sin red)
        prefijo = mac_upper[:8]
        if prefijo in _OUI_LOCAL:
            vendor = _OUI_LOCAL[prefijo]
            self._cache[mac_upper] = vendor
            return vendor

        # 3. Bit U/L → MAC aleatorizada (sin red)
        try:
            if int(mac.split(":")[0], 16) & 0x02:
                self._cache[mac_upper] = "MAC aleatorizada"
                return "MAC aleatorizada"
        except (ValueError, IndexError):
            pass

        # 4. API externa (fallback con timeout corto)
        try:
            import requests
            r = requests.get(
                f"https://api.macvendors.com/{mac}",
                timeout=3,
                headers={"User-Agent": f"ApexSentinel/{self._version}"},
            )
            vendor = r.text.strip() if r.status_code == 200 else "Desconocido"
        except Exception:
            vendor = "Desconocido"

        self._cache[mac_upper] = vendor
        return vendor
