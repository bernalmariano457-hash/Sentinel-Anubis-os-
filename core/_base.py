"""
core/commands/_base.py — Clase base para todos los dominios de comandos
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentinel import ApexSentinel


class _DomainBase:
    """
    Clase base ligera que todos los dominios heredan.
    Provee acceso a sentinel, console y _modulo_ok sin repetición.
    """

    def __init__(self, sentinel: "ApexSentinel"):
        self.s = sentinel

    @property
    def console(self):
        return self.s.console

    def _modulo_ok(self, nombre_attr: str) -> bool:
        return self.s._modulo_ok(nombre_attr)
