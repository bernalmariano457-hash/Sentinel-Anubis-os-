from __future__ import annotations

import os
from pathlib import Path
import time

from rich import box
from rich.table import Table

from core._base import _DomainBase


class GeneralCommands(_DomainBase):

    def status(self) -> None:
        from rich.panel import Panel
        s = self.s
        proy = s.gp.proyecto_activo.nombre if s.gp and s.gp.proyecto_activo else "Ninguno"
        rf_state = getattr(s.rf, "hw_nombre",
                           "No disponible") if s.rf else "No disponible"
        self.console.print(Panel(
            f"[cyan]Sistema:[/cyan]  {s.nombre}\n"
            f"[cyan]Versión:[/cyan]  {s.version}\n"
            f"[cyan]Estado:[/cyan]   [green]Operacional[/green]\n"
            f"[cyan]Hora:[/cyan]     {time.strftime('%H:%M:%S')}\n"
            f"[cyan]Iface:[/cyan]    {s._iface()}\n"
            f"[cyan]Proyecto:[/cyan] [green]{proy}[/green]\n"
            f"[cyan]RF HW:[/cyan]    {rf_state}",
            title="STATUS", border_style="cyan"
        ))

    def files(self) -> None:
        s = self.s
        s.animar_barra("EXPLORANDO DIRECTORIO LOCAL...")
        tabla = Table(header_style="bold cyan",
                      box=box.SIMPLE_HEAD, show_edge=False)
        tabla.add_column("Nombre", style="white")
        tabla.add_column("Tamaño", style="yellow", justify="right")
        tabla.add_column("Tipo",   style="green",  justify="center")
        try:
            for entry in sorted(Path(".").iterdir(), key=lambda e: e.name):
                try:
                    tabla.add_row(
                        entry.name,
                        f"{entry.stat().st_size:,} bytes",
                        "DIR" if entry.is_dir() else "FILE",
                    )
                except OSError:
                    tabla.add_row(f, "N/A", "?")
            self.console.print(tabla)
        except Exception as e:
            s.log.error(f"files: {e}", "Sistema")
