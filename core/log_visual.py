from __future__ import annotations

import logging
import warnings
from typing import Any

log = logging.getLogger("sentinel.log_visual")

# Estilos heredados — mismos que ESTILOS_LOG en bootscreen/log_sistema
ESTILOS = {
    "INFO":    ("cyan",    "ℹ"),
    "WARNING": ("yellow",  "⚠"),
    "ERROR":   ("red",     "✖"),
    "SUCCESS": ("green",   "✔"),
    "AUDIT":   ("magenta", "⚑"),
}


class LogVisual:
    def __init__(self) -> None:
        warnings.warn(
            "LogVisual está deprecado. Usa LogSistema directamente.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Intentar obtener el Console del sentinel si está en el proceso
        try:
            from rich.console import Console
            self._console = Console()
        except ImportError:
            self._console = None  # type: ignore[assignment]

        self._entradas: list[dict] = []
        log.warning("LogVisual instanciado — migrar a LogSistema.")

    # API pública

    def info(self, mensaje: str, modulo: str = "Sistema") -> None:
        self._registrar("INFO", mensaje, modulo)

    def warning(self, mensaje: str, modulo: str = "Sistema") -> None:
        self._registrar("WARNING", mensaje, modulo)

    def error(self, mensaje: str, modulo: str = "Sistema") -> None:
        self._registrar("ERROR", mensaje, modulo)

    def success(self, mensaje: str, modulo: str = "Sistema") -> None:
        self._registrar("SUCCESS", mensaje, modulo)

    def audit(self, mensaje: str, modulo: str = "Auditoría") -> None:
        self._registrar("AUDIT", mensaje, modulo)

    def mostrar_historial(self, ultimas: int = 50, filtro_nivel: str | None = None) -> None:
        entradas = self._entradas[-ultimas:]
        if filtro_nivel:
            entradas = [e for e in entradas if e["nivel"]
                        == filtro_nivel.upper()]
        if not entradas:
            if self._console:
                self._console.print("[dim]No hay registros disponibles.[/dim]")
            return
        for e in entradas:
            color, icono = ESTILOS.get(e["nivel"], ("white", "·"))
            if self._console:
                self._console.print(
                    f"[dim]{e['timestamp']}[/dim] "
                    f"[{color}]{icono} {e['nivel']:<8}[/{color}] "
                    f"[cyan]{e['modulo']:<18}[/cyan] {e['mensaje']}"
                )

    def verificar_y_limpiar(self, max_entradas: int = 500) -> None:
        if len(self._entradas) > max_entradas:
            self._entradas = self._entradas[-max_entradas:]

    # Internos

    def _registrar(self, nivel: str, mensaje: str, modulo: str) -> None:
        from datetime import datetime
        entrada: dict[str, Any] = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nivel":     nivel,
            "modulo":    modulo,
            "mensaje":   mensaje,
        }
        self._entradas.append(entrada)
        color, icono = ESTILOS.get(nivel, ("white", "·"))
        if self._console:
            self._console.print(
                f"[dim]{entrada['timestamp']}[/dim] "
                f"[{color}]{icono} {nivel:<8}[/{color}] "
                f"[cyan]{modulo:<18}[/cyan] {mensaje}"
            )
        getattr(log, nivel.lower() if nivel.lower() in ("info", "warning", "error", "debug") else "info")(
            f"[{modulo}] {mensaje}"
        )
