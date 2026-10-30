from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class EventoCaptura:
    ssid: str
    password: str
    total: int


HandlerCaptura = Callable[[EventoCaptura], None]


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
            with contextlib.suppress(Exception):
                handler(evento)
