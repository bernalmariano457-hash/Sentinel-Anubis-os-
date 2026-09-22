from __future__ import annotations

import signal
import sys
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from core.log_sistema import LogSistema


class SignalManager:
    def __init__(self, log: "LogSistema | None" = None) -> None:
        self._log = log
        self._handlers: list[Callable[[], None]] = []

    def registrar_cleanup(self, fn: Callable[[], None]) -> None:
        self._handlers.append(fn)

    def registrar(self, on_signal: "Callable[[str], None] | None" = None) -> None:
        def _handler(signum, frame):
            sig = "SIGINT" if signum == getattr(
                signal, "SIGINT", 2) else "SIGTERM"
            if on_signal:
                on_signal(sig)
            self.cleanup()
            sys.exit(0)

        signal.signal(signal.SIGINT, _handler)
        term = getattr(signal, "SIGTERM", None)
        if term:
            signal.signal(term, _handler)

    def cleanup(self) -> None:
        if self._log:
            self._log.info("Sesión terminada.", "ApexSentinel")
        for fn in self._handlers:
            try:
                fn()
            except Exception:
                pass
