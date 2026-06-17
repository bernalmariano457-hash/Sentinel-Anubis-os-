from __future__ import annotations

import threading


class CapturaStore:
    def __init__(self) -> None:
        self._capturas: list[str] = []
        self._lock = threading.Lock()

    def agregar(self, password: str) -> int:
        with self._lock:
            self._capturas.append(password)
            return len(self._capturas)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._capturas)

    def total(self) -> int:
        with self._lock:
            return len(self._capturas)
