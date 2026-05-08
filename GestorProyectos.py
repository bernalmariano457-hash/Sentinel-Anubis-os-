import os
import json
import time
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from rich import box

console = Console()
PROYECTOS_PATH = "data/proyectos"


class Proyecto:
    """Representa una operación/sesión de trabajo."""

    def __init__(self, nombre: str, objetivo: str, scope: str,
                 tipo: str = "general", notas: str = ""):
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
        self.ruta = os.path.join(PROYECTOS_PATH, f"{self.id}_{nombre}")

    def to_dict(self) -> dict:
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
            "ruta":       self.ruta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Proyecto":
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
        p.ruta = d["ruta"]
        return p


class GestorProyectos:
    """
    Maneja creación, carga, guardado y listado de proyectos.
    Cada proyecto tiene su propio workspace en disco.
    """

    TIPOS = ["red-interna", "web", "wireless", "forense", "osint", "general"]

    def __init__(self, sentinel=None):
        self.sentinel = sentinel
        os.makedirs(PROYECTOS_PATH, exist_ok=True)
        self.proyecto_activo: Proyecto | None = None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def crear_proyecto(self) -> Proyecto:
        """Guía al operador para crear un nuevo proyecto."""
        console.print()
        console.print(Panel(
            "[bold cyan]NUEVO PROYECTO DE OPERACIÓN[/bold cyan]\n"
            "[dim]Define el scope antes de operar. Documenta todo.[/dim]",
            border_style="cyan"
        ))

        nombre = console.input(
            "[bold cyan][?] Nombre del proyecto: [/bold cyan]").strip()
        objetivo = console.input(
            "[bold cyan][?] IP / Dominio / Objetivo: [/bold cyan]").strip()
        scope = console.input(
            "[bold cyan][?] Scope autorizado (ej: 192.168.1.0/24): [/bold cyan]").strip()
        tipo = Prompt.ask("[?] Tipo de operación",
                          choices=self.TIPOS, default="general")
        notas = console.input(
            "[bold cyan][?] Notas iniciales (opcional): [/bold cyan]").strip()

        proyecto = Proyecto(nombre, objetivo, scope, tipo, notas)
        self._crear_estructura(proyecto)
        self._guardar(proyecto)

        console.print(Panel(
            f"[green]Proyecto creado:[/green] [bold]{proyecto.nombre}[/bold]\n"
            f"[cyan]ID:[/cyan]       {proyecto.id}\n"
            f"[cyan]Objetivo:[/cyan] {proyecto.objetivo}\n"
            f"[cyan]Scope:[/cyan]    {proyecto.scope}\n"
            f"[cyan]Tipo:[/cyan]     {proyecto.tipo}\n"
            f"[cyan]Ruta:[/cyan]     {proyecto.ruta}",
            title="[bold green]PROYECTO INICIADO[/bold green]",
            border_style="green"
        ))

        self.proyecto_activo = proyecto
        return proyecto

    def listar_proyectos(self):
        """Muestra todos los proyectos guardados."""
        proyectos = self._cargar_todos()

        if not proyectos:
            console.print(Panel("[dim]No hay proyectos guardados.[/dim]",
                                title="PROYECTOS", border_style="dim"))
            return

        tabla = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
                      show_edge=False, expand=True)
        tabla.add_column("#",         style="dim",
                         width=3,  justify="center")
        tabla.add_column("ID",        style="dim",    width=15, no_wrap=True)
        tabla.add_column("Nombre",    style="white",  min_width=15)
        tabla.add_column("Objetivo",  style="cyan",   min_width=15)
        tabla.add_column("Tipo",      style="yellow", width=12)
        tabla.add_column("Estado",    width=10,       justify="center")
        tabla.add_column("Creado",    style="dim",    width=12)

        for i, p in enumerate(proyectos, 1):
            estado_fmt = (
                "[green]● activo[/green]" if p.estado == "activo" else
                "[dim]○ cerrado[/dim]" if p.estado == "cerrado" else
                "[yellow]⊙ pausado[/yellow]"
            )
            creado = p.creado[:10] if p.creado else "—"
            tabla.add_row(str(i), p.id, p.nombre, p.objetivo,
                          p.tipo, estado_fmt, creado)

        console.print(Panel(tabla, title="[bold]PROYECTOS GUARDADOS[/bold]",
                            border_style="cyan"))

    def cargar_proyecto(self) -> Proyecto | None:
        """Permite al operador seleccionar un proyecto existente."""
        proyectos = self._cargar_todos()
        if not proyectos:
            console.print(
                "[yellow][!] No hay proyectos. Crea uno primero.[/yellow]")
            return None

        self.listar_proyectos()
        try:
            idx = int(console.input(
                "[bold cyan][?] Número de proyecto a cargar: [/bold cyan]"
            ).strip()) - 1
            if 0 <= idx < len(proyectos):
                self.proyecto_activo = proyectos[idx]
                console.print(
                    f"[green][+] Proyecto cargado:[/green] "
                    f"[bold]{self.proyecto_activo.nombre}[/bold]"
                )
                return self.proyecto_activo
            else:
                console.print("[red][!] Número inválido.[/red]")
        except ValueError:
            console.print("[red][!] Ingresa un número válido.[/red]")
        return None

    def cerrar_proyecto(self):
        """Marca el proyecto activo como cerrado."""
        if not self.proyecto_activo:
            console.print("[yellow][!] No hay proyecto activo.[/yellow]")
            return
        self.proyecto_activo.estado = "cerrado"
        self._guardar(self.proyecto_activo)
        console.print(
            f"[green][+] Proyecto '[bold]{self.proyecto_activo.nombre}[/bold]' cerrado.[/green]"
        )
        self.proyecto_activo = None

    # ------------------------------------------------------------------
    # EVIDENCIA Y HALLAZGOS
    # ------------------------------------------------------------------

    def registrar_evidencia(self, tipo: str, descripcion: str,
                            datos: dict = None, archivo: str = None):
        """
        Registra un resultado dentro del proyecto activo.
        Llamar desde cualquier módulo después de obtener resultados.
        """
        if not self.proyecto_activo:
            return

        evidencia = {
            "timestamp":   datetime.now().isoformat(),
            "tipo":        tipo,
            "descripcion": descripcion,
            "datos":       datos or {},
            "archivo":     archivo or "",
        }
        self.proyecto_activo.evidencias.append(evidencia)
        self._guardar(self.proyecto_activo)

        # Guardar también en archivo de texto plano en el workspace
        ruta_ev = os.path.join(
            self.proyecto_activo.ruta, "evidence",
            f"{tipo}_{datetime.now().strftime('%H%M%S')}.txt"
        )
        try:
            with open(ruta_ev, "w", encoding="utf-8") as f:
                f.write(f"TIMESTAMP: {evidencia['timestamp']}\n")
                f.write(f"TIPO:      {tipo}\n")
                f.write(f"DESC:      {descripcion}\n\n")
                if datos:
                    f.write(json.dumps(datos, indent=2, ensure_ascii=False))
        except OSError:
            pass

        console.print(
            f"[dim][evidence] {tipo} registrado en proyecto "
            f"'{self.proyecto_activo.nombre}'[/dim]"
        )

    def registrar_hallazgo(self, severidad: str, titulo: str,
                           descripcion: str, recomendacion: str = ""):
        """
        Registra un hallazgo de seguridad con severidad.
        severidad: CRITICO | ALTO | MEDIO | BAJO | INFO
        """
        if not self.proyecto_activo:
            return

        hallazgo = {
            "timestamp":      datetime.now().isoformat(),
            "severidad":      severidad.upper(),
            "titulo":         titulo,
            "descripcion":    descripcion,
            "recomendacion":  recomendacion,
        }
        self.proyecto_activo.hallazgos.append(hallazgo)
        self._guardar(self.proyecto_activo)

        colores = {"CRITICO": "red", "ALTO": "red", "MEDIO": "yellow",
                   "BAJO": "cyan", "INFO": "dim"}
        color = colores.get(severidad.upper(), "white")
        console.print(
            f"[{color}][HALLAZGO {severidad.upper()}][/{color}] {titulo}"
        )

    def mostrar_resumen(self):
        """Muestra el resumen del proyecto activo."""
        p = self.proyecto_activo
        if not p:
            console.print("[yellow][!] No hay proyecto activo.[/yellow]")
            return

        # Conteo de hallazgos por severidad
        sev_count = {}
        for h in p.hallazgos:
            s = h["severidad"]
            sev_count[s] = sev_count.get(s, 0) + 1

        info = Table.grid(padding=(0, 2))
        info.add_column(style="dim cyan", justify="right")
        info.add_column(style="white")
        info.add_row("Proyecto",    p.nombre)
        info.add_row("Objetivo",    p.objetivo)
        info.add_row("Scope",       p.scope)
        info.add_row("Tipo",        p.tipo)
        info.add_row("Estado",      f"[green]{p.estado}[/green]")
        info.add_row("Evidencias",  str(len(p.evidencias)))
        info.add_row("Hallazgos",   str(len(p.hallazgos)))
        info.add_row("Iniciado",    p.creado[:19])

        sev_txt = "  ".join([
            f"[red]CRITICO:{sev_count.get('CRITICO', 0)}[/red]",
            f"[red]ALTO:{sev_count.get('ALTO', 0)}[/red]",
            f"[yellow]MEDIO:{sev_count.get('MEDIO', 0)}[/yellow]",
            f"[cyan]BAJO:{sev_count.get('BAJO', 0)}[/cyan]",
        ])

        console.print(Panel(
            info,
            title=f"[bold cyan]PROYECTO: {p.nombre}[/bold cyan]",
            border_style="cyan"
        ))
        console.print(f"  Severidades: {sev_txt}\n")

        if p.hallazgos:
            tabla_h = Table(box=box.SIMPLE_HEAD, header_style="bold red",
                            show_edge=False, expand=True)
            tabla_h.add_column("Severidad", width=10, justify="center")
            tabla_h.add_column("Título",    style="white")
            tabla_h.add_column("Timestamp", style="dim", width=20)

            colores = {"CRITICO": "red", "ALTO": "red", "MEDIO": "yellow",
                       "BAJO": "cyan", "INFO": "dim"}
            for h in p.hallazgos:
                c = colores.get(h["severidad"], "white")
                tabla_h.add_row(
                    f"[{c}]{h['severidad']}[/{c}]",
                    h["titulo"], h["timestamp"][:19]
                )
            console.print(Panel(tabla_h, title="HALLAZGOS",
                                border_style="red"))

    # ------------------------------------------------------------------
    # WORKSPACE EN DISCO
    # ------------------------------------------------------------------

    def _crear_estructura(self, proyecto: Proyecto):
        """Crea la estructura de carpetas del workspace."""
        carpetas = [
            "recon", "scanning", "exploitation",
            "evidence", "reports", "loot"
        ]
        for carpeta in carpetas:
            os.makedirs(os.path.join(proyecto.ruta, carpeta), exist_ok=True)

        # README inicial del proyecto
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
        with open(os.path.join(proyecto.ruta, "README.md"), "w") as f:
            f.write(readme)

    def _guardar(self, proyecto: Proyecto):
        ruta = os.path.join(proyecto.ruta, "proyecto.json")
        try:
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(proyecto.to_dict(), f, indent=2, ensure_ascii=False)
        except OSError as e:
            console.print(f"[red][!] Error guardando proyecto: {e}[/red]")

    def _cargar_todos(self) -> list[Proyecto]:
        proyectos = []
        try:
            for carpeta in sorted(os.listdir(PROYECTOS_PATH)):
                ruta_json = os.path.join(
                    PROYECTOS_PATH, carpeta, "proyecto.json")
                if os.path.exists(ruta_json):
                    with open(ruta_json, "r", encoding="utf-8") as f:
                        proyectos.append(Proyecto.from_dict(json.load(f)))
        except Exception:
            pass
        return proyectos

    def ruta_workspace(self, subcarpeta: str = "") -> str:
        """Retorna la ruta del workspace activo para guardar archivos."""
        if not self.proyecto_activo:
            base = "data/evidence"
        else:
            base = self.proyecto_activo.ruta
        ruta = os.path.join(base, subcarpeta) if subcarpeta else base
        os.makedirs(ruta, exist_ok=True)
        return ruta


# --- Prueba directa ---
if __name__ == "__main__":
    gp = GestorProyectos()
    p = gp.crear_proyecto()
    gp.registrar_evidencia("portscan", "Puerto 22 abierto en 192.168.1.1",
                           {"puerto": 22, "servicio": "SSH"})
    gp.registrar_hallazgo("ALTO", "SSH expuesto sin restricción de IP",
                          "El servicio SSH está accesible desde cualquier origen.",
                          "Restringir acceso SSH por IP en firewall.")
    gp.mostrar_resumen()
