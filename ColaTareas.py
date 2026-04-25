import threading
import time
import uuid
from datetime import datetime
from enum import Enum
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


class EstadoTarea(Enum):
    PENDIENTE = "pendiente"
    CORRIENDO = "corriendo"
    COMPLETADA = "completada"
    ERROR = "error"
    CANCELADA = "cancelada"


class Tarea:
    """Representa una tarea que corre en background."""

    def __init__(self, nombre: str, funcion, args: tuple = (), kwargs: dict = None):
        self.id = str(uuid.uuid4())[:8].upper()
        self.nombre = nombre
        self.funcion = funcion
        self.args = args
        self.kwargs = kwargs or {}
        self.estado = EstadoTarea.PENDIENTE
        self.creada = datetime.now()
        self.iniciada = None
        self.finalizada = None
        self.resultado = None
        self.error = None
        self._hilo = None
        self._cancelar = threading.Event()

    def duracion(self) -> str:
        if not self.iniciada:
            return "—"
        fin = self.finalizada or datetime.now()
        seg = int((fin - self.iniciada).total_seconds())
        return f"{seg}s"

    def to_dict(self) -> dict:
        return {
            "id":       self.id,
            "nombre":   self.nombre,
            "estado":   self.estado.value,
            "creada":   self.creada.strftime("%H:%M:%S"),
            "duracion": self.duracion(),
            "error":    str(self.error) if self.error else None,
        }


class ColaTareas:
    """
    Gestor de tareas en background.
    Permite correr funciones largas sin bloquear el prompt.
    """

    MAX_HISTORIAL = 20

    def __init__(self):
        self._tareas: dict[str, Tarea] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # API PÚBLICA
    # ------------------------------------------------------------------

    def agregar(self, nombre: str, funcion, args: tuple = (),
                kwargs: dict = None, autostart: bool = True) -> Tarea:
        """
        Agrega una tarea a la cola y opcionalmente la inicia.

        Uso:
            cola.agregar("PortScan 192.168.1.1", self._cmd_portscan,
                         args=(ip,), autostart=True)
        """
        tarea = Tarea(nombre, funcion, args, kwargs or {})

        with self._lock:
            self._tareas[tarea.id] = tarea

        console.print(
            f"[dim][job #{tarea.id}][/dim] [cyan]{nombre}[/cyan] → "
            f"[yellow]en cola[/yellow]"
        )

        if autostart:
            self._iniciar(tarea)

        return tarea

    def cancelar(self, job_id: str) -> bool:
        """Cancela una tarea por su ID."""
        tarea = self._tareas.get(job_id.upper())
        if not tarea:
            console.print(f"[red][!] Job #{job_id} no encontrado.[/red]")
            return False

        if tarea.estado == EstadoTarea.CORRIENDO:
            tarea._cancelar.set()
            tarea.estado = EstadoTarea.CANCELADA
            console.print(f"[yellow][!] Job #{job_id} cancelado.[/yellow]")
            return True

        console.print(
            f"[yellow][!] Job #{job_id} no está corriendo "
            f"(estado: {tarea.estado.value}).[/yellow]"
        )
        return False

    def resultado(self, job_id: str):
        """Muestra el resultado de una tarea completada."""
        tarea = self._tareas.get(job_id.upper())
        if not tarea:
            console.print(f"[red][!] Job #{job_id} no encontrado.[/red]")
            return

        estado_color = {
            EstadoTarea.COMPLETADA: "green",
            EstadoTarea.ERROR:      "red",
            EstadoTarea.CANCELADA:  "yellow",
            EstadoTarea.CORRIENDO:  "cyan",
            EstadoTarea.PENDIENTE:  "dim",
        }
        color = estado_color.get(tarea.estado, "white")

        info = (
            f"[cyan]Job:[/cyan]     #{tarea.id}\n"
            f"[cyan]Nombre:[/cyan]  {tarea.nombre}\n"
            f"[cyan]Estado:[/cyan]  [{color}]{tarea.estado.value}[/{color}]\n"
            f"[cyan]Duración:[/cyan] {tarea.duracion()}\n"
        )

        if tarea.resultado is not None:
            info += f"[cyan]Resultado:[/cyan]\n{tarea.resultado}\n"
        if tarea.error:
            info += f"[red]Error:[/red] {tarea.error}\n"

        console.print(
            Panel(info, title=f"JOB #{tarea.id}", border_style=color))

    def listar(self):
        """Muestra todas las tareas activas e historial reciente."""
        with self._lock:
            tareas = list(self._tareas.values())

        if not tareas:
            console.print("[dim]No hay tareas en cola.[/dim]")
            return

        tabla = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
                      show_edge=False, expand=True)
        tabla.add_column("Job ID",   style="dim",
                         width=8,  justify="center")
        tabla.add_column("Nombre",   style="white",  min_width=25)
        tabla.add_column("Estado",   width=12,       justify="center")
        tabla.add_column("Inicio",   style="dim",
                         width=10, justify="center")
        tabla.add_column("Duración", style="yellow",
                         width=10, justify="center")

        colores = {
            EstadoTarea.PENDIENTE:  ("dim",    "○ pendiente"),
            EstadoTarea.CORRIENDO:  ("cyan",   "● corriendo"),
            EstadoTarea.COMPLETADA: ("green",  "✔ completada"),
            EstadoTarea.ERROR:      ("red",    "✖ error"),
            EstadoTarea.CANCELADA:  ("yellow", "⊘ cancelada"),
        }

        for t in sorted(tareas, key=lambda x: x.creada, reverse=True):
            color, label = colores.get(t.estado, ("white", t.estado.value))
            inicio = t.iniciada.strftime("%H:%M:%S") if t.iniciada else "—"
            tabla.add_row(
                f"#{t.id}",
                t.nombre,
                f"[{color}]{label}[/{color}]",
                inicio,
                t.duracion()
            )

        corriendo = sum(1 for t in tareas if t.estado == EstadoTarea.CORRIENDO)
        console.print(Panel(
            tabla,
            title=f"[bold]COLA DE TAREAS[/bold] — [cyan]{corriendo} activa(s)[/cyan]",
            border_style="cyan"
        ))

    def esperar(self, job_id: str):
        """Bloquea hasta que la tarea termine (para uso interno)."""
        tarea = self._tareas.get(job_id.upper())
        if tarea and tarea._hilo:
            tarea._hilo.join()

    def limpiar_completadas(self):
        """Elimina del historial las tareas terminadas."""
        with self._lock:
            eliminadas = [
                k for k, t in self._tareas.items()
                if t.estado in (EstadoTarea.COMPLETADA,
                                EstadoTarea.ERROR,
                                EstadoTarea.CANCELADA)
            ]
            for k in eliminadas:
                del self._tareas[k]
        console.print(
            f"[dim]Cola limpiada: {len(eliminadas)} tareas eliminadas.[/dim]")

    # ------------------------------------------------------------------
    # INTERNO
    # ------------------------------------------------------------------

    def _iniciar(self, tarea: Tarea):
        """Lanza la tarea en un hilo separado."""
        def _runner():
            tarea.estado = EstadoTarea.CORRIENDO
            tarea.iniciada = datetime.now()

            console.print(
                f"\n[dim][job #{tarea.id}][/dim] "
                f"[cyan]{tarea.nombre}[/cyan] → [green]iniciado[/green]"
            )

            try:
                tarea.resultado = tarea.funcion(
                    *tarea.args,
                    cancelar_event=tarea._cancelar,
                    **tarea.kwargs
                )
                if tarea.estado != EstadoTarea.CANCELADA:
                    tarea.estado = EstadoTarea.COMPLETADA
                    console.print(
                        f"\n[dim][job #{tarea.id}][/dim] "
                        f"[green]✔ {tarea.nombre} completado[/green] "
                        f"[dim]({tarea.duracion()})[/dim]"
                    )
            except Exception as e:
                tarea.error = e
                tarea.estado = EstadoTarea.ERROR
                console.print(
                    f"\n[dim][job #{tarea.id}][/dim] "
                    f"[red]✖ {tarea.nombre} error: {e}[/red]"
                )
            finally:
                tarea.finalizada = datetime.now()
                self._limpiar_si_excede()

        hilo = threading.Thread(target=_runner, daemon=True)
        tarea._hilo = hilo
        hilo.start()

    def _limpiar_si_excede(self):
        """Mantiene el historial bajo el límite."""
        with self._lock:
            completadas = [
                k for k, t in self._tareas.items()
                if t.estado in (EstadoTarea.COMPLETADA,
                                EstadoTarea.ERROR,
                                EstadoTarea.CANCELADA)
            ]
            if len(completadas) > self.MAX_HISTORIAL:
                for k in completadas[:-self.MAX_HISTORIAL]:
                    del self._tareas[k]


# ------------------------------------------------------------------
# DECORADOR para hacer cualquier función compatible con la cola
# ------------------------------------------------------------------

def tarea_background(nombre: str):
    """
    Decorador que adapta una función para correr en background.
    La función decorada debe aceptar cancelar_event como kwarg.

    Uso:
        @tarea_background("Mi Scan")
        def mi_scan(ip, cancelar_event=None):
            for i in range(100):
                if cancelar_event and cancelar_event.is_set():
                    return "Cancelado"
                time.sleep(0.1)
            return "Completado"
    """
    def decorator(func):
        func._es_tarea_background = True
        func._nombre_tarea = nombre
        return func
    return decorator


# --- Prueba directa ---
if __name__ == "__main__":
    import time

    cola = ColaTareas()

    @tarea_background("Scan de prueba")
    def scan_prueba(objetivo, cancelar_event=None):
        for i in range(10):
            if cancelar_event and cancelar_event.is_set():
                return "Cancelado por el operador"
            time.sleep(0.5)
        return f"Scan de {objetivo} completado: 5 puertos abiertos"

    t1 = cola.agregar("PortScan 192.168.1.1",
                      scan_prueba, args=("192.168.1.1",))
    t2 = cola.agregar("PortScan 192.168.1.2",
                      scan_prueba, args=("192.168.1.2",))

    time.sleep(1)
    cola.listar()

    time.sleep(4)
    cola.listar()
    cola.resultado(t1.id)
