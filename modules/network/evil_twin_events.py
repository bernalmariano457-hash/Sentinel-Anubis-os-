from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class EventoCaptura:
    ssid: str
    password: str
    total: int


type HandlerCaptura = Callable[[EventoCaptura], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[HandlerCaptura] = []
        self._lock = threading.Lock()

    def suscribir(self, handler: HandlerCaptura) -> None:
        with self._lock:
            if handler not in self._handlers:
                self._handlers.append(handler)

    def desuscribir(self, handler: HandlerCaptura) -> None:
        with self._lock:
            self._handlers = [h for h in self._handlers if h is not handler]

    def emitir(self, evento: EventoCaptura) -> None:
        with self._lock:
            handlers = list(self._handlers)
        for handler in handlers:
            try:
                handler(evento)
            except Exception:
                pass
