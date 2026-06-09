from __future__ import annotations

import logging
import warnings

log = logging.getLogger(__name__)

_DEPRECATION_MSG = (
    "LocatorModule está obsoleto y será eliminado en la próxima versión mayor. "
    "Usa OSINTEngine.analizar_ip() en su lugar."
)


class LocatorModule:
    # Adaptador de compatibilidad — delega en OSINTEngine.

    def __init__(self, sentinel):
        self._sentinel = sentinel
        warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
        log.warning(_DEPRECATION_MSG)

    def rastrear_ip(self, ip: str) -> None:
        osint = getattr(self._sentinel, "osint", None)
        if osint is None:
            self._sentinel.console.print(
                "[red][!] OSINTEngine no disponible. "
                "Verifica que el módulo 'osint' esté cargado.[/red]"
            )
            return
        osint.analizar_ip(ip)
