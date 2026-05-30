from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

log = logging.getLogger("sentinel.proyectos")

_PROYECTOS_BASE = Path("data/proyectos")
_SUBCARPETAS = ("recon", "scanning", "exploitation",
                "evidence", "reports", "loot")
_TIPOS = ("red-interna", "web", "wireless", "forense", "osint", "general")
_COLORES_SEV = {"CRITICO": "red", "ALTO": "red",
                "MEDIO": "yellow", "BAJO": "cyan", "INFO": "dim"}


class Proyecto:
    """Workspace de operación — scope, evidencia y hallazgos en un mismo lugar."""

    def __init__(
        self,
        nombre: str,
        objetivo: str,
        scope: str,
        tipo: str = "general",
        notas: str = "",
    ) -> None:
        self.id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.nombre = nombre
        self.objetivo = objetivo
        self.scope = scope
        self.tipo = tipo
        self.notas = notas
        self.creado = datetime.now().isoformat()
        self.estado = "activo"
        self.evidencias: list[dict] = []
        self.hallazgos: list[dict] = []
        self.ruta = _PROYECTOS_BASE / f"{self.id}_{nombre}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":         self.id,
            "nombre":     self.nombre,
            "objetivo":   self.objetivo,
            "scope":      self.scope,
            "tipo":       self.tipo,
            "notas":      self.notas,
            "creado":     self.creado,
            "estado":     self.estado,
            "evidencias": self.evidencias,
            "hallazgos":  self.hallazgos,
            "ruta":       str(self.ruta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Proyecto:
        p = cls.__new__(cls)
        p.id = d["id"]
        p.nombre = d["nombre"]
        p.objetivo = d["objetivo"]
        p.scope = d["scope"]
        p.tipo = d.get("tipo", "general")
        p.notas = d.get("notas", "")
        p.creado = d["creado"]
        p.estado = d.get("estado", "activo")
        p.evidencias = d.get("evidencias", [])
        p.hallazgos = d.get("hallazgos", [])
        p.ruta = Path(d["ruta"])
        return p


class GestorProyectos:

    TIPOS = list(_TIPOS)

    def __init__(self, sentinel=None) -> None:
        self.sentinel = sentinel
        _PROYECTOS_BASE.mkdir(parents=True, exist_ok=True)
        self.proyecto_activo: Proyecto | None = None

        # Usar el Console del sentinel si está disponible;
        # crear uno propio solo como fallback de uso standalone.
        if sentinel is not None and hasattr(sentinel, "console"):
            self._console: Console = sentinel.console
        else:
            self._console = Console()

    # CRUD

    def crear_proyecto(self) -> Proyecto:
        self._console.print()
        self._console.print(Panel(
            "[bold cyan]NUEVO PROYECTO DE OPERACIÓN[/bold cyan]\n"
            "[dim]Define el scope antes de operar. Documenta todo.[/dim]",
            border_style="cyan",
        ))

        nombre = self._console.input(
            "[bold cyan][?] Nombre del proyecto: [/bold cyan]").strip()
        objetivo = self._console.input(
            "[bold cyan][?] IP / Dominio / Objetivo: [/bold cyan]").strip()
        scope = self._console.input(
            "[bold cyan][?] Scope autorizado (ej: 192.168.1.0/24): [/bold cyan]").strip()
        tipo = Prompt.ask("[?] Tipo de operación",
                          choices=self.TIPOS, default="general")
        notas = self._console.input(
            "[bold cyan][?] Notas iniciales (opcional): [/bold cyan]").strip()

        proyecto = Proyecto(nombre, objetivo, scope, tipo, notas)
        self._crear_estructura(proyecto)
        self._guardar(proyecto)

        self._console.print(Panel(
            f"[green]Proyecto creado:[/green] [bold]{proyecto.nombre}[/bold]\n"
            f"[cyan]ID:[/cyan]       {proyecto.id}\n"
            f"[cyan]Objetivo:[/cyan] {proyecto.objetivo}\n"
            f"[cyan]Scope:[/cyan]    {proyecto.scope}\n"
            f"[cyan]Tipo:[/cyan]     {proyecto.tipo}\n"
            f"[cyan]Ruta:[/cyan]     {proyecto.ruta}",
            title="[bold green]PROYECTO INICIADO[/bold green]",
            border_style="green",
        ))

        self.proyecto_activo = proyecto
        log.info(f"Proyecto creado: {proyecto.nombre} ({proyecto.id})")
        return proyecto

    def listar_proyectos(self) -> None:
        proyectos = self._cargar_todos()

        if not proyectos:
            self._console.print(Panel(
                "[dim]No hay proyectos guardados.[/dim]",
                title="PROYECTOS", border_style="dim",
            ))
            return

        tabla = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
                      show_edge=False, expand=True)
        tabla.add_column("#",        style="dim",
                         width=3,   justify="center")
        tabla.add_column("ID",       style="dim",    width=15,  no_wrap=True)
        tabla.add_column("Nombre",   style="white",  min_width=15)
        tabla.add_column("Objetivo", style="cyan",   min_width=15)
        tabla.add_column("Tipo",     style="yellow", width=12)
        tabla.add_column("Estado",   width=10,       justify="center")
        tabla.add_column("Creado",   style="dim",    width=12)

        for i, p in enumerate(proyectos, 1):
            if p.estado == "activo":
                estado_fmt = "[green]● activo[/green]"
            elif p.estado == "cerrado":
                estado_fmt = "[dim]○ cerrado[/dim]"
            else:
                estado_fmt = "[yellow]⊙ pausado[/yellow]"
            tabla.add_row(
                str(i), p.id, p.nombre, p.objetivo,
                p.tipo, estado_fmt, p.creado[:10],
            )

        self._console.print(Panel(tabla, title="[bold]PROYECTOS GUARDADOS[/bold]",
                                  border_style="cyan"))

    def cargar_proyecto(self) -> Proyecto | None:
        proyectos = self._cargar_todos()
        if not proyectos:
            self._console.print(
                "[yellow][!] No hay proyectos. Crea uno primero.[/yellow]")
            return None

        self.listar_proyectos()
        try:
            idx = int(self._console.input(
                "[bold cyan][?] Número de proyecto a cargar: [/bold cyan]"
            ).strip()) - 1
            if 0 <= idx < len(proyectos):
                self.proyecto_activo = proyectos[idx]
                self._console.print(
                    f"[green][+] Proyecto cargado:[/green] "
                    f"[bold]{self.proyecto_activo.nombre}[/bold]"
                )
                log.info(f"Proyecto cargado: {self.proyecto_activo.nombre}")
                return self.proyecto_activo
            self._console.print("[red][!] Número inválido.[/red]")
        except ValueError:
            self._console.print("[red][!] Ingresa un número válido.[/red]")
        return None

    def cerrar_proyecto(self) -> None:
        if not self.proyecto_activo:
            self._console.print("[yellow][!] No hay proyecto activo.[/yellow]")
            return
        self.proyecto_activo.estado = "cerrado"
        self._guardar(self.proyecto_activo)
        self._console.print(
            f"[green][+] Proyecto '[bold]{self.proyecto_activo.nombre}[/bold]' cerrado.[/green]"
        )
        log.info(f"Proyecto cerrado: {self.proyecto_activo.nombre}")
        self.proyecto_activo = None

    # Registro de evidencia y hallazgos

    def registrar_evidencia(
        self,
        tipo: str,
        descripcion: str,
        datos: dict | None = None,
        archivo: str = "",
    ) -> None:

        if not self.proyecto_activo:
            return

        evidencia = {
            "timestamp":   datetime.now().isoformat(),
            "tipo":        tipo,
            "descripcion": descripcion,
            "datos":       datos or {},
            "archivo":     archivo,
        }
        self.proyecto_activo.evidencias.append(evidencia)
        self._guardar(self.proyecto_activo)

        ruta_ev = (
            self.proyecto_activo.ruta
            / "evidence"
            / f"{tipo}_{datetime.now().strftime('%H%M%S')}.txt"
        )
        try:
            ruta_ev.write_text(
                f"TIMESTAMP: {evidencia['timestamp']}\n"
                f"TIPO:      {tipo}\n"
                f"DESC:      {descripcion}\n\n"
                + (json.dumps(datos, indent=2, ensure_ascii=False) if datos else ""),
                encoding="utf-8",
            )
        except OSError as e:
            log.warning(f"No se pudo escribir evidencia a disco: {e}")

        self._console.print(
            f"[dim][evidence] {tipo} registrado en '{self.proyecto_activo.nombre}'[/dim]"
        )

    def registrar_hallazgo(
        self,
        severidad: str,
        titulo: str,
        descripcion: str,
        recomendacion: str = "",
    ) -> None:
        if not self.proyecto_activo:
            return

        hallazgo = {
            "timestamp":     datetime.now().isoformat(),
            "severidad":     severidad.upper(),
            "titulo":        titulo,
            "descripcion":   descripcion,
            "recomendacion": recomendacion,
        }
        self.proyecto_activo.hallazgos.append(hallazgo)
        self._guardar(self.proyecto_activo)

        color = _COLORES_SEV.get(severidad.upper(), "white")
        self._console.print(
            f"[{color}][HALLAZGO {severidad.upper()}][/{color}] {titulo}")
        log.info(f"Hallazgo {severidad.upper()}: {titulo}")

    def mostrar_resumen(self) -> None:
        p = self.proyecto_activo
        if not p:
            self._console.print("[yellow][!] No hay proyecto activo.[/yellow]")
            return

        sev_count: dict[str, int] = {}
        for h in p.hallazgos:
            s = h["severidad"]
            sev_count[s] = sev_count.get(s, 0) + 1

        info = Table.grid(padding=(0, 2))
        info.add_column(style="dim cyan", justify="right")
        info.add_column(style="white")
        info.add_row("Proyecto",   p.nombre)
        info.add_row("Objetivo",   p.objetivo)
        info.add_row("Scope",      p.scope)
        info.add_row("Tipo",       p.tipo)
        info.add_row("Estado",     f"[green]{p.estado}[/green]")
        info.add_row("Evidencias", str(len(p.evidencias)))
        info.add_row("Hallazgos",  str(len(p.hallazgos)))
        info.add_row("Iniciado",   p.creado[:19])

        sev_txt = "  ".join([
            f"[red]CRITICO:{sev_count.get('CRITICO', 0)}[/red]",
            f"[red]ALTO:{sev_count.get('ALTO', 0)}[/red]",
            f"[yellow]MEDIO:{sev_count.get('MEDIO', 0)}[/yellow]",
            f"[cyan]BAJO:{sev_count.get('BAJO', 0)}[/cyan]",
        ])

        self._console.print(Panel(
            info,
            title=f"[bold cyan]PROYECTO: {p.nombre}[/bold cyan]",
            border_style="cyan",
        ))
        self._console.print(f"  Severidades: {sev_txt}\n")

        if p.hallazgos:
            tabla_h = Table(box=box.SIMPLE_HEAD, header_style="bold red",
                            show_edge=False, expand=True)
            tabla_h.add_column("Severidad", width=10, justify="center")
            tabla_h.add_column("Título",    style="white")
            tabla_h.add_column("Timestamp", style="dim", width=20)
            for h in p.hallazgos:
                c = _COLORES_SEV.get(h["severidad"], "white")
                tabla_h.add_row(
                    f"[{c}]{h['severidad']}[/{c}]",
                    h["titulo"],
                    h["timestamp"][:19],
                )
            self._console.print(
                Panel(tabla_h, title="HALLAZGOS", border_style="red"))

    # Workspace en disco

    def _crear_estructura(self, proyecto: Proyecto) -> None:
        for carpeta in _SUBCARPETAS:
            (proyecto.ruta / carpeta).mkdir(parents=True, exist_ok=True)

        readme = (
            f"# Proyecto: {proyecto.nombre}\n\n"
            f"- **ID:** {proyecto.id}\n"
            f"- **Objetivo:** {proyecto.objetivo}\n"
            f"- **Scope:** {proyecto.scope}\n"
            f"- **Tipo:** {proyecto.tipo}\n"
            f"- **Inicio:** {proyecto.creado[:19]}\n\n"
            f"## Notas\n{proyecto.notas}\n\n"
            f"## Advertencia legal\n"
            f"Esta operación se realiza con autorización expresa sobre el objetivo.\n"
        )
        try:
            (proyecto.ruta / "README.md").write_text(readme, encoding="utf-8")
        except OSError as e:
            log.warning(f"No se pudo escribir README: {e}")

    def _guardar(self, proyecto: Proyecto) -> None:
        ruta = proyecto.ruta / "proyecto.json"
        try:
            ruta.write_text(
                json.dumps(proyecto.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as e:
            log.error(f"Error guardando proyecto {proyecto.nombre}: {e}")
            self._console.print(
                f"[red][!] Error guardando proyecto: {e}[/red]")

    def _cargar_todos(self) -> list[Proyecto]:
        proyectos: list[Proyecto] = []
        try:
            for carpeta in sorted(_PROYECTOS_BASE.iterdir()):
                ruta_json = carpeta / "proyecto.json"
                if ruta_json.exists():
                    try:
                        proyectos.append(
                            Proyecto.from_dict(json.loads(
                                ruta_json.read_text(encoding="utf-8")))
                        )
                    except (json.JSONDecodeError, KeyError) as e:
                        log.warning(
                            f"Proyecto corrupto ignorado ({carpeta.name}): {e}")
        except OSError:
            pass
        return proyectos

    def ruta_workspace(self, subcarpeta: str = "") -> Path:
        base = self.proyecto_activo.ruta if self.proyecto_activo else Path(
            "data/evidence")
        ruta = base / subcarpeta if subcarpeta else base
        ruta.mkdir(parents=True, exist_ok=True)
        return ruta
