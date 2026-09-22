from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.log_sistema import LogSistema

log = logging.getLogger("sentinel.config")

_CONFIG_PATH = Path("config.json")
_DEFAULT_VERSION = "2.3"


class ConfigManager:
    def __init__(
        self,
        version: str = _DEFAULT_VERSION,
        log_sistema: LogSistema | None = None,
    ) -> None:
        self._version = version
        self._log_sistema = log_sistema

    def cargar(self) -> dict:
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "sistema": {
                    "nombre":          "Sentinel",
                    "version":         self._version,
                    "primer_arranque": True,
                }
            }
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    def guardar(self, config: dict) -> None:
        try:
            _CONFIG_PATH.write_text(
                json.dumps(config, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            msg = f"No se pudo guardar config.json: {e}"
            if self._log_sistema:
                self._log_sistema.warning(msg, "Config")
            else:
                log.warning(msg)
