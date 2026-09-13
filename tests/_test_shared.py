from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class _DispositivoBLEFalso:
    address: str
    rssi: int
    nombre: str = ""
    fabricante: str | None = None
    servicios: list = field(default_factory=list)
    primera_vez: str = ""
    ultima_vez: str = ""
    veces_visto: int = 1


class _BtModuleFalso:
    def __init__(
        self,
        dispositivos: dict | None = None,
        console=None,
    ) -> None:
        self._dispositivos: dict = dispositivos or {}
        self._lock = threading.Lock()
        self.console = console
