from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Main import ApexSentinel


class _DomainBase:
    def __init__(self, sentinel: "ApexSentinel"):
        self.s = sentinel

    @property
    def console(self):
        return self.s.console

    def _modulo_ok(self, nombre_attr: str) -> bool:
        return self.s._modulo_ok(nombre_attr)
