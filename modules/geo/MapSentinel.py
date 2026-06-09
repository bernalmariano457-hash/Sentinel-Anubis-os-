from __future__ import annotations

import logging
import warnings
from typing import Any

log = logging.getLogger(__name__)

_DEPRECATION_MSG = (
    "MapSentinel está obsoleto y será eliminado en la próxima versión mayor. "
    "Usa GeomapSentinel.generar_mapa() en su lugar."
)


class MapSentinel:
    # Adaptador de compatibilidad — delega en GeomapSentinel.
    # La implementación original era un prototipo sin integración con el sistema
    # de consola ni manejo de errores. GeomapSentinel es la versión completa y
    # mantenida. Este stub existe únicamente para no romper código externo que
    # instancie MapSentinel directamente.

    def __init__(self, sentinel=None, lat_inicial: float = 0.0, lon_inicial: float = 0.0):
        self._sentinel = sentinel
        self._lat = lat_inicial
        self._lon = lon_inicial
        warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
        log.warning(_DEPRECATION_MSG)

    def actualizar_mapa(self, targets: dict[str, dict[str, Any]] | None = None) -> None:
        geomap = getattr(self._sentinel, "geomap", None) if self._sentinel else None
        if geomap is None:
            log.error(
                "GeomapSentinel no disponible; no se puede generar el mapa. "
                "Verifica que el módulo 'geomap' esté cargado."
            )
            return
        geomap.generar_mapa(targets or {})
