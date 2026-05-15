from __future__ import annotations


import os
import json
import time
import logging
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich import box

console = Console()

LOG_PATH = "data/logs/sentinel.log"
HISTORIAL_PATH = "data/logs/historial.json"


# --- Niveles y sus estilos visuales ---
ESTILOS = {
    "INFO":    ("cyan",   "ℹ"),
    "WARNING": ("yellow", "⚠"),
    "ERROR":   ("red",    "✖"),
    "SUCCESS": ("green",  "✔"),
    "AUDIT":   ("magenta", "⚑"),
}


class LogVisual:
    """
    Sistema de logging con salida visual enriquecida.
    Escribe en archivo JSON estructurado + archivo .log plano.
    """

    def __init__(self):
        os.makedirs("data/logs", exist_ok=True)
        self._entradas: list[dict] = self._cargar_historial()

        # Logger plano para el archivo .log
        logging.basicConfig(
            filename=LOG_PATH,
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self._logger = logging.getLogger("AnubisOS")

    # ------------------------------------------------------------------
    # API pública de logging
    # ------------------------------------------------------------------
    def info(self, mensaje: str, modulo: str = "Sistema"):
        self._registrar("INFO", mensaje, modulo)

    def warning(self, mensaje: str, modulo: str = "Sistema"):
        self._registrar("WARNING", mensaje, modulo)

    def error(self, mensaje: str, modulo: str = "Sistema"):
        self._registrar("ERROR", mensaje, modulo)

    def success(self, mensaje: str, modulo: str = "Sistema"):
        self._registrar("SUCCESS", mensaje, modulo)

    def audit(self, mensaje: str, modulo: str = "Auditoría"):
        self._registrar("AUDIT", mensaje, modulo)

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------
    def _registrar(self, nivel: str, mensaje: str, modulo: str):
        entrada = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nivel":     nivel,
            "modulo":    modulo,
            "mensaje":   mensaje,
        }
        self._entradas.append(entrada)
        self._guardar_historial()

        # Log plano
        getattr(self._logger, nivel.lower(), self._logger.info)(
            f"[{modulo}] {mensaje}"
        )

        # Feedback visual inmediato en consola
        color, icono = ESTILOS.get(nivel, ("white", "·"))
        console.print(
            f"[dim]{entrada['timestamp']}[/dim] "
            f"[{color}]{icono} {nivel:<8}[/{color}] "
            f"[cyan]{modulo:<18}[/cyan] {mensaje}"
        )

    def _cargar_historial(self) -> list:
        try:
            with open(HISTORIAL_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _guardar_historial(self):
        try:
            with open(HISTORIAL_PATH, "w", encoding="utf-8") as f:
                json.dump(self._entradas[-500:], f,
                          indent=2, ensure_ascii=False)
        except OSError as e:
            self._logger.error(f"No se pudo guardar historial: {e}")

    # ------------------------------------------------------------------
    # Visualización del historial
    # ------------------------------------------------------------------
    def mostrar_historial(self, ultimas: int = 50, filtro_nivel: str = None):
        """Muestra el historial en una tabla visual con filtros."""
        entradas = self._entradas[-ultimas:]

        if filtro_nivel:
            entradas = [e for e in entradas if e["nivel"]
                        == filtro_nivel.upper()]

        if not entradas:
            console.print(Panel(
                "[dim]No hay registros disponibles.[/dim]",
                title="HISTORIAL",
                border_style="dim green"
            ))
            return

        # --- Resumen estadístico ---
        conteos = {}
        for e in self._entradas:
            conteos[e["nivel"]] = conteos.get(e["nivel"], 0) + 1

        resumen = Table.grid(padding=(0, 3))
        resumen.add_row(*[
            f"[{ESTILOS.get(n, ('white', ''))[0]}]{icono} {n}: {conteos.get(n, 0)}[/{ESTILOS.get(n, ('white', ''))[0]}]"
            for n, (_, icono) in ESTILOS.items()
        ])

        console.print()
        console.print(Panel(
            resumen,
            title="[bold]RESUMEN DE ACTIVIDAD[/bold]",
            border_style="dim green",
            box=box.SIMPLE,
        ))

        # --- Tabla de entradas ---
        tabla = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            show_edge=False,
            expand=True,
        )
        tabla.add_column("Timestamp",  style="dim",
                         min_width=19, no_wrap=True)
        tabla.add_column("Nivel",      min_width=9,     no_wrap=True)
        tabla.add_column("Módulo",     style="cyan",    min_width=16)
        tabla.add_column("Mensaje",    style="white")

        for entrada in entradas:
            nivel = entrada["nivel"]
            color, icono = ESTILOS.get(nivel, ("white", "·"))
            nivel_fmt = Text(f"{icono} {nivel}", style=color)
            tabla.add_row(
                entrada["timestamp"],
                nivel_fmt,
                entrada["modulo"],
                entrada["mensaje"],
            )

        console.print(Panel(
            tabla,
            title=f"[bold]HISTORIAL — últimas {len(entradas)} entradas[/bold]",
            border_style="green",
            box=box.HEAVY_EDGE,
        ))
        console.print()

    def limpiar_historial(self, confirmar: bool = False):
        """Limpia el historial con confirmación."""
        if not confirmar:
            console.print(
                "[yellow][!] Usa limpiar_historial(confirmar=True) para confirmar.[/yellow]")
            return
        self._entradas = []
        self._guardar_historial()
        console.print("[green][+] Historial limpiado.[/green]")
        self._logger.info("Historial limpiado manualmente.")

    def verificar_y_limpiar(self, max_entradas: int = 500):
        """Limita el tamaño del historial automáticamente."""
        if len(self._entradas) > max_entradas:
            self._entradas = self._entradas[-max_entradas:]
            self._guardar_historial()
            self._logger.info(
                f"Historial recortado a {max_entradas} entradas.")


# --- Prueba directa ---
if __name__ == "__main__":
    log = LogVisual()
    log.info("Sistema iniciado correctamente", "ApexSentinel")
    log.success("Contraseña verificada", "GestorAutenticacion")
    log.warning("Módulo BluetoothModule no disponible", "Inicialización")
    log.error("Fallo al conectar con objetivo 192.168.1.5", "TacticalSniffer")
    log.audit("Escaneo de puertos en 192.168.1.1", "PortScan")
    log.info("Sesión cerrada por el operador", "ApexSentinel")

    print()
    log.mostrar_historial()
