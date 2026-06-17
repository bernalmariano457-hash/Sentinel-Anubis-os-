from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class EstadoTarea(Enum):
    PENDIENTE = "pendiente"
    CORRIENDO = "corriendo"
    COMPLETADA = "completada"
    ERROR = "error"
    CANCELADA = "cancelada"


class Tarea:

    def __init__(
        self,
        nombre: str,
        funcion: Callable[..., Any],
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
        prioridad: int = 3,
    ):
        self.id = str(uuid.uuid4())[:8].upper()
        self.nombre = nombre
        self.funcion = funcion
        self.args = args
        self.kwargs = kwargs or {}
        self.prioridad = prioridad
        self.estado = EstadoTarea.PENDIENTE
        self.creada = datetime.now()
        self.iniciada:   datetime | None = None
        self.finalizada: datetime | None = None
        self.resultado:  Any = None
        self.error:      Exception | None = None
        self._hilo:      threading.Thread | None = None
        self._cancelar = threading.Event()

    def duracion(self) -> str:
        if not self.iniciada:
            return "—"
        fin = self.finalizada or datetime.now()
        seg = int((fin - self.iniciada).total_seconds())
        m, s = divmod(seg, 60)
        return f"{m}m{s:02d}s" if m else f"{s}s"

    def to_dict(self) -> dict:
        return {
            "id":        self.id,
            "nombre":    self.nombre,
            "estado":    self.estado.value,
            "prioridad": self.prioridad,
            "creada":    self.creada.strftime("%H:%M:%S"),
            "duracion":  self.duracion(),
            "error":     str(self.error) if self.error else None,
        }


class ColaTareas:

    MAX_HISTORIAL:   int = 30
    MAX_CONCURRENTES: int = 3

    def __init__(self, sentinel=None):
        self.sentinel = sentinel

        if sentinel is not None and hasattr(sentinel, "console"):
            self._console: Console = sentinel.console
        else:
            self._console = Console()

        self._tareas:   dict[str, Tarea] = {}
        self._lock = threading.Lock()
        self._semaforo = threading.Semaphore(self.MAX_CONCURRENTES)

    def _log(self, msg: str, estilo: str = "dim") -> None:
        log.debug("%s", msg)
        if threading.current_thread() is threading.main_thread():
            try:
                self._console.print(msg, style=estilo)
            except Exception:
                pass

    def _log_bg(self, msg: str) -> None:
        log.info("%s", msg)

    def agregar(
        self,
        nombre: str,
        funcion: Callable[..., Any],
        args: tuple = (),
        kwargs: dict[str, Any] | None = None,
        autostart: bool = True,
        prioridad: int = 3,
    ) -> Tarea:
        tarea = Tarea(nombre, funcion, args, kwargs or {}, prioridad)

        with self._lock:
            completadas = [
                t for t in self._tareas.values()
                if t.estado in (
                    EstadoTarea.COMPLETADA,
                    EstadoTarea.ERROR,
                    EstadoTarea.CANCELADA,
                )
            ]
            if len(self._tareas) >= self.MAX_HISTORIAL and completadas:
                mas_vieja = min(completadas, key=lambda t: t.creada)
                del self._tareas[mas_vieja.id]

            self._tareas[tarea.id] = tarea

        prio_tag = {
            1: "[red]ALTA[/red]",
            2: "[yellow]MEDIA-ALTA[/yellow]",
            3: "[cyan]MEDIA[/cyan]",
            4: "[dim]MEDIA-BAJA[/dim]",
            5: "[dim]BAJA[/dim]",
        }.get(prioridad, "[cyan]MEDIA[/cyan]")

        self._log(
            f"[dim][[/dim][bold cyan]job #{tarea.id}[/bold cyan][dim]][/dim] "
            f"[cyan]{nombre}[/cyan] → [yellow]en cola[/yellow] "
            f"[dim](prioridad: {prio_tag})[/dim]"
        )

        if autostart:
            self._iniciar(tarea)

        return tarea

    def cancelar(self, job_id: str) -> bool:
        with self._lock:
            tarea = self._tareas.get(job_id.upper())
        if not tarea:
            self._log(f"[yellow][!] Job #{job_id} no encontrado.[/yellow]")
            return False

        tarea._cancelar.set()
        if tarea.estado == EstadoTarea.PENDIENTE:
            tarea.estado = EstadoTarea.CANCELADA
            tarea.finalizada = datetime.now()
        self._log(f"[yellow][!] Job #{job_id} cancelado.[/yellow]")
        return True

    def resultado(self, job_id: str) -> Any:
        with self._lock:
            tarea = self._tareas.get(job_id.upper())
        if not tarea:
            self._log(f"[red][!] Job #{job_id} no encontrado.[/red]")
            return None
        if tarea.estado == EstadoTarea.COMPLETADA:
            self._log(
                f"[green][✔] Job #{job_id} ({tarea.nombre}):[/green]\n"
                f"    {tarea.resultado}"
            )
            return tarea.resultado
        if tarea.estado == EstadoTarea.ERROR:
            self._log(
                f"[red][✖] Job #{job_id} terminó con error: {tarea.error}[/red]")
            return None
        self._log(
            f"[dim][~] Job #{job_id} está en estado: {tarea.estado.value}[/dim]"
        )
        return None

    def listar(self) -> None:
        with self._lock:
            tareas = sorted(
                self._tareas.values(),
                key=lambda t: t.creada,
                reverse=True,
            )

        if not tareas:
            self._log("[dim]No hay tareas en cola.[/dim]")
            return

        tabla = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            show_edge=False,
            expand=True,
        )
        tabla.add_column("ID",       style="dim cyan",
                         min_width=8,  no_wrap=True)
        tabla.add_column("Nombre",   style="white",     min_width=24)
        tabla.add_column("Estado",   justify="center",  min_width=12)
        tabla.add_column("Duración", justify="right",   min_width=8)
        tabla.add_column("P",        justify="center",  min_width=3)

        _COLORES_ESTADO = {
            EstadoTarea.PENDIENTE:  "[yellow]⏳ pendiente[/yellow]",
            EstadoTarea.CORRIENDO:  "[bold cyan]⟳ corriendo[/bold cyan]",
            EstadoTarea.COMPLETADA: "[green]✔ completada[/green]",
            EstadoTarea.ERROR:      "[red]✖ error[/red]",
            EstadoTarea.CANCELADA:  "[dim]⊘ cancelada[/dim]",
        }

        for t in tareas:
            tabla.add_row(
                f"#{t.id}",
                t.nombre[:40],
                _COLORES_ESTADO.get(t.estado, t.estado.value),
                t.duracion(),
                str(t.prioridad),
            )

        self._console.print(Panel(
            tabla,
            title="[bold cyan]◈ COLA DE TAREAS[/bold cyan]",
            subtitle=f"[dim]{len(tareas)} tareas[/dim]",
            border_style="cyan",
            box=box.HEAVY_HEAD,
        ))

    def limpiar_completadas(self) -> int:
        with self._lock:
            antes = len(self._tareas)
            self._tareas = {
                k: v for k, v in self._tareas.items()
                if v.estado in (EstadoTarea.PENDIENTE, EstadoTarea.CORRIENDO)
            }
            eliminadas = antes - len(self._tareas)
        if eliminadas:
            self._log(
                f"[dim]Cola limpiada: {eliminadas} tareas eliminadas.[/dim]")
        return eliminadas

    def activas(self) -> list[Tarea]:
        with self._lock:
            return [t for t in self._tareas.values()
                    if t.estado == EstadoTarea.CORRIENDO]

    def _iniciar(self, tarea: Tarea) -> None:
        def _runner() -> None:
            self._semaforo.acquire()
            try:
                if tarea._cancelar.is_set():
                    return

                tarea.estado = EstadoTarea.CORRIENDO
                tarea.iniciada = datetime.now()

                tarea.resultado = tarea.funcion(*tarea.args, **tarea.kwargs)
                tarea.estado = EstadoTarea.COMPLETADA

                self._log_bg(
                    f"[✔ job #{tarea.id}] {tarea.nombre} → completada "
                    f"({tarea.duracion()})"
                )

            except Exception as exc:
                tarea.estado = EstadoTarea.ERROR
                tarea.error = exc
                self._log_bg(
                    f"[✖ job #{tarea.id}] {tarea.nombre} → error: {exc}"
                )
                log.exception(
                    "Excepción no manejada en job #%s (%s)", tarea.id, tarea.nombre)

            finally:
                tarea.finalizada = datetime.now()
                self._semaforo.release()

        hilo = threading.Thread(
            target=_runner, daemon=True, name=f"job-{tarea.id}")
        tarea._hilo = hilo
        hilo.start()
