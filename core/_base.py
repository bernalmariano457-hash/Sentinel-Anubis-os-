from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

    from Main import ApexSentinel


class _DomainBase:
    def __init__(self, sentinel: ApexSentinel) -> None:
        self.s = sentinel

    @property
    def console(self) -> Console:
        return self.s.console

    def _modulo_ok(self, nombre_attr: str) -> bool:
        return self.s._modulo_ok(nombre_attr)
