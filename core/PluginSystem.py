from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from Main import ApexSentinel

log = logging.getLogger("sentinel.plugins")

_PLUGINS_PATH = Path("plugins")

_PLUGIN_EJEMPLO = '''\
from core.PluginSystem import PluginBase

class EjemploPlugin(PluginBase):
    NOMBRE      = "ejemplo"
    VERSION     = "1.0"
    DESCRIPCION = "Plugin de demostración del sistema"
    AUTOR       = "AnubisOS"
    COMANDOS    = ["hola", "ejemplo"]

    def ejecutar(self, comando: str, args: list[str] | None = None) -> None:
        if comando == "hola":
            self.console.print("[green]¡Hola desde el plugin de ejemplo![/green]")
        elif comando == "ejemplo":
            self.console.print(
                f"[cyan]Plugin:[/cyan] {self.NOMBRE} v{self.VERSION}\\n"
                f"[cyan]Args:[/cyan]   {args}"
            )
            if self.sentinel.gp.proyecto_activo:
                self.sentinel.gp.registrar_evidencia(
                    "plugin_ejemplo", "Comando de ejemplo ejecutado", {"args": args}
                )
'''


class PluginBase:

    NOMBRE = "plugin_base"
    VERSION = "1.0"
    DESCRIPCION = "Plugin base sin descripción"
    AUTOR = "Anónimo"
    COMANDOS:   list[str] = []

    def __init__(self, sentinel: ApexSentinel) -> None:
        self.sentinel = sentinel
        self.console = sentinel.console

    def ejecutar(self, comando: str, args: list[str] | None = None) -> None:
        raise NotImplementedError(
            f"El plugin '{self.NOMBRE}' debe implementar ejecutar()")

    def ayuda(self) -> str:
        cmds = ", ".join(self.COMANDOS) if self.COMANDOS else "ninguno"
        return (
            f"Plugin: {self.NOMBRE} v{self.VERSION}\n"
            f"Autor:  {self.AUTOR}\n"
            f"Desc:   {self.DESCRIPCION}\n"
            f"Cmds:   {cmds}"
        )


class GestorPlugins:

    def __init__(self, sentinel: ApexSentinel) -> None:
        self.sentinel = sentinel
        # Usar el Console del sentinel — no crear uno global a nivel de módulo.
        self._console: Console = sentinel.console
        self._plugins:  dict[str, PluginBase] = {}
        self._comandos: dict[str, PluginBase] = {}
        _PLUGINS_PATH.mkdir(parents=True, exist_ok=True)
        self._crear_readme_plugins()

    def cargar_todos(self) -> int:
        cargados = con_error = 0
        for archivo in sorted(_PLUGINS_PATH.glob("*.py")):
            if archivo.name.startswith("_"):
                continue
            if self._cargar_archivo(archivo):
                cargados += 1
            else:
                con_error += 1
        self._console.print(
            f"[dim][plugins] {cargados} cargados, {con_error} con error.[/dim]")
        return cargados

    def recargar(self) -> None:
        self._plugins.clear()
        self._comandos.clear()
        n = self.cargar_todos()
        self._console.print(f"[green][+] Plugins recargados: {n}[/green]")

    def _cargar_archivo(self, ruta: Path) -> bool:
        nombre_modulo = ruta.stem
        try:
            spec = importlib.util.spec_from_file_location(nombre_modulo, ruta)
            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)

            clase_plugin = None
            for attr_name in dir(modulo):
                attr = getattr(modulo, attr_name)
                if (isinstance(attr, type)
                        and issubclass(attr, PluginBase)
                        and attr is not PluginBase):
                    clase_plugin = attr
                    break

            if clase_plugin is None:
                self._console.print(
                    f"[yellow][!] {ruta.name}: no contiene clase que herede PluginBase.[/yellow]")
                return False

            instancia = clase_plugin(self.sentinel)
            self._plugins[instancia.NOMBRE] = instancia

            for cmd in instancia.COMANDOS:
                if cmd in self._comandos:
                    self._console.print(
                        f"[yellow][!] Conflicto: comando '{cmd}' ya registrado. "
                        f"Plugin '{ruta.name}' no lo sobrescribe.[/yellow]")
                else:
                    self._comandos[cmd] = instancia

            self._console.print(
                f"[dim][plugin][/dim] [green]{instancia.NOMBRE}[/green] "
                f"v{instancia.VERSION} — {instancia.DESCRIPCION}"
            )
            log.info(
                f"Plugin cargado: {instancia.NOMBRE} v{instancia.VERSION}")
            return True

        except Exception as e:
            self._console.print(
                f"[red][!] Error cargando {ruta.name}: {e}[/red]")
            log.warning(f"Error cargando plugin {ruta.name}: {e}")
            return False

    def tiene_comando(self, comando: str) -> bool:
        return comando in self._comandos

    def ejecutar_comando(self, comando: str, args: list[str] | None = None) -> bool:
        if comando not in self._comandos:
            return False
        try:
            self._comandos[comando].ejecutar(comando, args or [])
        except KeyboardInterrupt:
            self._console.print("\n[yellow][!] Plugin cancelado.[/yellow]")
        except Exception as e:
            self._console.print(
                f"[red][!] Error en plugin '{comando}': {e}[/red]")
            log.error(f"Plugin '{comando}' error: {e}")
        return True

    def listar(self) -> None:
        if not self._plugins:
            self._console.print(Panel(
                f"[dim]No hay plugins cargados.\n"
                f"Coloca archivos .py en la carpeta '{_PLUGINS_PATH}/'[/dim]",
                title="PLUGINS", border_style="dim",
            ))
            return

        tabla = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
                      show_edge=False, expand=True)
        tabla.add_column("Plugin",      style="green",  min_width=15)
        tabla.add_column("Versión",     style="dim",
                         width=8,  justify="center")
        tabla.add_column("Comandos",    style="yellow", min_width=15)
        tabla.add_column("Descripción", style="white")
        tabla.add_column("Autor",       style="dim",    min_width=10)

        for p in self._plugins.values():
            cmds = ", ".join(p.COMANDOS) if p.COMANDOS else "—"
            tabla.add_row(p.NOMBRE, p.VERSION, cmds, p.DESCRIPCION, p.AUTOR)

        self._console.print(Panel(tabla, title="[bold]PLUGINS CARGADOS[/bold]",
                                  border_style="green"))

    def _crear_readme_plugins(self) -> None:
        readme = _PLUGINS_PATH / "README.md"
        if not readme.exists():
            readme.write_text(
                "# AnubisOS — Plugin System\n\n"
                "Coloca tus plugins en esta carpeta. Se cargan automáticamente al iniciar.\n\n"
                "## Estructura mínima\n\n"
                "```python\n"
                "from core.PluginSystem import PluginBase\n\n"
                "class MiPlugin(PluginBase):\n"
                "    NOMBRE      = \"mi_plugin\"\n"
                "    VERSION     = \"1.0\"\n"
                "    DESCRIPCION = \"Hace algo útil\"\n"
                "    AUTOR       = \"Tu nombre\"\n"
                "    COMANDOS    = [\"micomando\"]\n\n"
                "    def ejecutar(self, comando: str, args: list[str] | None = None):\n"
                "        self.console.print(f\"Hola desde {self.NOMBRE}\")\n"
                "```\n\n"
                "## Comandos de gestión\n\n"
                "- `plugins`               → Lista plugins cargados\n"
                "- `plugins reload`        → Recarga sin reiniciar\n"
                "- `plugins ayuda <nombre>` → Ayuda de un plugin\n",
                encoding="utf-8",
            )

        ejemplo = _PLUGINS_PATH / "ejemplo_plugin.py"
        if not ejemplo.exists():
            ejemplo.write_text(_PLUGIN_EJEMPLO, encoding="utf-8")
