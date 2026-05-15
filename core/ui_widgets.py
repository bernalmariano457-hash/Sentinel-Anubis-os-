from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

if TYPE_CHECKING:
    from rich.console import Console
    from core.log_sistema import LogSistema


class UIWidgets:
    def __init__(self, console: "Console") -> None:
        self._console = console

    # ── Barra de progreso ─────────────────────────────────────────────

    def animar_barra(self, tarea: str, pasos: int = 20) -> None:
        with Progress(
            SpinnerColumn(style="bold green"),
            TextColumn("[green]{task.description}[/green]"),
            BarColumn(bar_width=24, complete_style="bold green"),
            TextColumn("[bold green]{task.percentage:>3.0f}%[/bold green]"),
            TimeElapsedColumn(),
            console=self._console,
            transient=True,
        ) as pg:
            tk = pg.add_task(tarea, total=pasos)
            for _ in range(pasos):
                time.sleep(0.05)
                pg.advance(tk)
        self._console.print(f"[bold green][OK][/bold green] {tarea}")

    # ── Dashboard de éxito (Hydra) ────────────────────────────────────

    def mostrar_dashboard_exito(
        self,
        ip: str,
        servicio: str,
        credencial: str,
        *,
        log: "LogSistema | None" = None,
        gp=None,
    ) -> None:

        from rich import box
        from rich.table import Table

        tabla = Table(title="ACCESO OBTENIDO",
                      header_style="bold green", box=box.ROUNDED)
        tabla.add_column("Objetivo",           style="cyan",
                         justify="center")
        tabla.add_column("Protocolo",          style="yellow",
                         justify="center")
        tabla.add_column("Credenciales (U:P)",
                         style="bold white", justify="center")
        tabla.add_row(ip, servicio.upper(), credencial)

        self._console.print(
            Panel(
                tabla,
                title="[bold green]MISSION ACCOMPLISHED[/bold green]",
                border_style="bright_green",
                expand=False,
            )
        )

        if log:
            log.audit(f"Acceso obtenido en {ip} vía {servicio}", "Hydra")

        if gp:
            gp.registrar_hallazgo(
                "CRITICO",
                f"Credenciales obtenidas en {ip}:{servicio}",
                f"Credenciales válidas: {credencial}",
                "Cambiar credenciales inmediatamente.",
            )
