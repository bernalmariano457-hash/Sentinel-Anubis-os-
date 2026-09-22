from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich import box
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

if TYPE_CHECKING:
    from rich.console import Console

    from core.log_sistema import LogSistema
    from core.GestorProyectos import GestorProyectos


def animar_barra(
    console: Console,
    tarea: str,
    pasos: int = 20,
    delay: float = 0.05,
) -> None:

    with Progress(
        SpinnerColumn(style="bold green"),
        TextColumn("[green]{task.description}[/green]"),
        BarColumn(bar_width=24, complete_style="bold green"),
        TextColumn("[bold green]{task.percentage:>3.0f}%[/bold green]"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as pg:
        tk = pg.add_task(tarea, total=pasos)
        for _ in range(pasos):
            time.sleep(delay)
            pg.advance(tk)

    console.print(f"[bold green][OK][/bold green] {tarea}")


def mostrar_dashboard_exito(
    console: Console,
    log: LogSistema,
    ip: str,
    servicio: str,
    credencial: str,
    gp: GestorProyectos | None = None,
) -> None:

    tabla = Table(
        title="ACCESO OBTENIDO",
        header_style="bold green",
        box=box.ROUNDED,
    )
    tabla.add_column("Objetivo",           style="cyan",
                     justify="center")
    tabla.add_column("Protocolo",          style="yellow",
                     justify="center")
    tabla.add_column("Credenciales (U:P)",
                     style="bold white", justify="center")
    tabla.add_row(ip, servicio.upper(), credencial)

    console.print(
        Panel(
            tabla,
            title="[bold green]MISSION ACCOMPLISHED[/bold green]",
            border_style="bright_green",
            expand=False,
        )
    )

    log.audit(f"Acceso obtenido en {ip} vía {servicio}", "Hydra")

    if gp is not None:
        gp.registrar_hallazgo(
            "CRITICO",
            f"Credenciales obtenidas en {ip}:{servicio}",
            f"Credenciales válidas: {credencial}",
            "Cambiar credenciales inmediatamente.",
        )
