"""
core/config_manager.py — Carga y persistencia de config.json
═════════════════════════════════════════════════════════════
Responsabilidad única: leer/escribir la configuración del sistema.
Sin dependencias de Console, Rich ni del sentinel completo.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.log_sistema import LogSistema

_DEFAULT_VERSION = "2.3"


class ConfigManager:
    """
    Lee config.json al arrancar y lo persiste cuando el estado cambia
    (p. ej. primer_arranque → False).

    Uso:
        mgr = ConfigManager(version="2.3", log=self.log)
        config = mgr.cargar()
        mgr.guardar(config)
    """

    def __init__(
        self,
        version: str = _DEFAULT_VERSION,
        log: "LogSistema | None" = None,
    ) -> None:
        self._version = version
        self._log = log

    def cargar(self) -> dict:
        """Devuelve el dict de configuración. Crea uno por defecto si no existe."""
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {
                "sistema": {
                    "nombre": "Sentinel",
                    "version": self._version,
                    "primer_arranque": True,
                }
            }
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    def guardar(self, config: dict) -> None:
        """Persiste el dict de configuración en config.json."""
        try:
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except OSError as e:
            if self._log:
                self._log.warning(f"No se pudo guardar config.json: {e}", "Config")
