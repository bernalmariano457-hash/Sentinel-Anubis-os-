import os
import sys
import importlib
import importlib.util
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()
PLUGINS_PATH = "plugins"


class PluginBase:
    """
    Clase base que todo plugin debe heredar.
    Define la interfaz mínima requerida.
    """
    NOMBRE = "plugin_base"
    VERSION = "1.0"
    DESCRIPCION = "Plugin base sin descripción"
    AUTOR = "Anónimo"
    COMANDOS: list[str] = []     # Comandos que expone este plugin

    def __init__(self, sentinel):
        """sentinel es la instancia de ApexSentinel (acceso a todos los módulos)."""
        self.sentinel = sentinel
        self.console = sentinel.console

    def ejecutar(self, comando: str, args: list = None):
        """
        Punto de entrada del plugin.
        El sistema llama esto cuando el usuario escribe uno de los COMANDOS.
        """
        raise NotImplementedError(
            f"El plugin '{self.NOMBRE}' debe implementar ejecutar()")

    def ayuda(self) -> str:
        """Retorna texto de ayuda para este plugin."""
        cmds = ", ".join(self.COMANDOS) if self.COMANDOS else "ninguno"
        return (
            f"Plugin: {self.NOMBRE} v{self.VERSION}\n"
            f"Autor:  {self.AUTOR}\n"
            f"Desc:   {self.DESCRIPCION}\n"
            f"Cmds:   {cmds}"
        )


class GestorPlugins:
    """
    Carga, registra y despacha plugins desde la carpeta plugins/.
    Los plugins se cargan en caliente: no requieren reiniciar el sistema.
    """

    def __init__(self, sentinel):
        self.sentinel = sentinel
        self._plugins: dict[str, PluginBase] = {}   # nombre → instancia
        self._comandos: dict[str, PluginBase] = {}   # comando → instancia
        os.makedirs(PLUGINS_PATH, exist_ok=True)
        self._crear_readme_plugins()

    # ------------------------------------------------------------------
    # CARGA
    # ------------------------------------------------------------------

    def cargar_todos(self):
        """Escanea plugins/ y carga todos los archivos .py válidos."""
        cargados = 0
        con_error = 0

        archivos = [
            f for f in os.listdir(PLUGINS_PATH)
            if f.endswith(".py") and not f.startswith("_")
        ]

        for archivo in archivos:
            resultado = self._cargar_archivo(archivo)
            if resultado:
                cargados += 1
            else:
                con_error += 1

        console.print(
            f"[dim][plugins] {cargados} cargados, {con_error} con error.[/dim]"
        )
        return cargados

    def recargar(self):
        """Recarga todos los plugins en caliente sin reiniciar el sistema."""
        self._plugins.clear()
        self._comandos.clear()
        n = self.cargar_todos()
        console.print(f"[green][+] Plugins recargados: {n}[/green]")

    def _cargar_archivo(self, archivo: str) -> bool:
        """Carga un archivo .py como plugin."""
        ruta = os.path.join(PLUGINS_PATH, archivo)
        nombre_modulo = archivo[:-3]

        try:
            spec = importlib.util.spec_from_file_location(nombre_modulo, ruta)
            modulo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modulo)

            # Buscar la clase Plugin en el módulo
            clase_plugin = None
            for attr_name in dir(modulo):
                attr = getattr(modulo, attr_name)
                if (isinstance(attr, type) and
                        issubclass(attr, PluginBase) and
                        attr is not PluginBase):
                    clase_plugin = attr
                    break

            if clase_plugin is None:
                console.print(
                    f"[yellow][!] {archivo}: no contiene clase que herede PluginBase.[/yellow]"
                )
                return False

            instancia = clase_plugin(self.sentinel)

            # Registrar plugin
            self._plugins[instancia.NOMBRE] = instancia

            # Registrar sus comandos
            for cmd in instancia.COMANDOS:
                if cmd in self._comandos:
                    console.print(
                        f"[yellow][!] Conflicto: comando '{cmd}' ya registrado. "
                        f"Plugin '{archivo}' no lo sobrescribe.[/yellow]"
                    )
                else:
                    self._comandos[cmd] = instancia

            console.print(
                f"[dim][plugin][/dim] [green]{instancia.NOMBRE}[/green] "
                f"v{instancia.VERSION} — {instancia.DESCRIPCION}"
            )
            return True

        except Exception as e:
            console.print(f"[red][!] Error cargando {archivo}: {e}[/red]")
            return False

    # ------------------------------------------------------------------
    # DESPACHO
    # ------------------------------------------------------------------

    def tiene_comando(self, comando: str) -> bool:
        return comando in self._comandos

    def ejecutar_comando(self, comando: str, args: list = None) -> bool:
        """
        Ejecuta el comando si algún plugin lo maneja.
        Retorna True si fue manejado, False si no.
        """
        if comando in self._comandos:
            try:
                self._comandos[comando].ejecutar(comando, args or [])
            except KeyboardInterrupt:
                console.print("\n[yellow][!] Plugin cancelado.[/yellow]")
            except Exception as e:
                console.print(
                    f"[red][!] Error en plugin '{comando}': {e}[/red]")
            return True
        return False

    # ------------------------------------------------------------------
    # LISTADO
    # ------------------------------------------------------------------

    def listar(self):
        """Muestra todos los plugins cargados."""
        if not self._plugins:
            console.print(Panel(
                "[dim]No hay plugins cargados.\n"
                f"Coloca archivos .py en la carpeta '{PLUGINS_PATH}/'[/dim]",
                title="PLUGINS", border_style="dim"
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

        for nombre, p in self._plugins.items():
            cmds = ", ".join(p.COMANDOS) if p.COMANDOS else "—"
            tabla.add_row(nombre, p.VERSION, cmds, p.DESCRIPCION, p.AUTOR)

        console.print(Panel(tabla, title="[bold]PLUGINS CARGADOS[/bold]",
                            border_style="green"))

    # ------------------------------------------------------------------
    # README para desarrolladores de plugins
    # ------------------------------------------------------------------

    def _crear_readme_plugins(self):
        readme = os.path.join(PLUGINS_PATH, "README.md")
        if os.path.exists(readme):
            return
        contenido = '''# AnubisOS — Plugin System

Coloca tus plugins en esta carpeta. Se cargan automáticamente al iniciar.

## Estructura mínima de un plugin

```python
from PluginSystem import PluginBase

class MiPlugin(PluginBase):
    NOMBRE      = "mi_plugin"
    VERSION     = "1.0"
    DESCRIPCION = "Hace algo útil"
    AUTOR       = "Tu nombre"
    COMANDOS    = ["micomando", "mc"]   # Comandos que activan este plugin

    def ejecutar(self, comando: str, args: list = None):
        self.console.print(f"[green]Ejecutando {comando} con args: {args}[/green]")
        # Tu lógica aquí

    def ayuda(self) -> str:
        return "Descripción de uso de mi plugin"
```

## Comandos del sistema relacionados

- `plugins`        → Lista todos los plugins cargados
- `plugins reload` → Recarga plugins sin reiniciar el sistema
- `plugins ayuda <nombre>` → Ayuda de un plugin específico

## Acceso a módulos del sistema

Desde el plugin tienes acceso completo a `self.sentinel`:

```python
# Acceder al logger
self.sentinel.log.info("Mensaje", "MiPlugin")

# Acceder al proyecto activo
proyecto = self.sentinel.gp.proyecto_activo

# Registrar evidencia
self.sentinel.gp.registrar_evidencia("mi_tipo", "descripción", datos={})
```
'''
        with open(readme, "w", encoding="utf-8") as f:
            f.write(contenido)


# ------------------------------------------------------------------
# PLUGIN DE EJEMPLO — guarda en plugins/ejemplo_plugin.py
# ------------------------------------------------------------------

PLUGIN_EJEMPLO = '''"""
Plugin de ejemplo para AnubisOS.
Archivo: plugins/ejemplo_plugin.py
"""
from PluginSystem import PluginBase

class EjemploPlugin(PluginBase):
    NOMBRE      = "ejemplo"
    VERSION     = "1.0"
    DESCRIPCION = "Plugin de demostración del sistema"
    AUTOR       = "AnubisOS"
    COMANDOS    = ["hola", "ejemplo"]

    def ejecutar(self, comando: str, args: list = None):
        if comando == "hola":
            self.console.print("[green]¡Hola desde el plugin de ejemplo![/green]")
        elif comando == "ejemplo":
            self.console.print(
                f"[cyan]Plugin:[/cyan] {self.NOMBRE} v{self.VERSION}\\n"
                f"[cyan]Args:[/cyan]   {args}"
            )
            # Registrar evidencia si hay proyecto activo
            if self.sentinel.gp.proyecto_activo:
                self.sentinel.gp.registrar_evidencia(
                    "plugin_ejemplo", "Comando de ejemplo ejecutado", {"args": args}
                )
'''


def crear_plugin_ejemplo():
    """Crea el plugin de ejemplo si no existe."""
    os.makedirs(PLUGINS_PATH, exist_ok=True)
    ruta = os.path.join(PLUGINS_PATH, "ejemplo_plugin.py")
    if not os.path.exists(ruta):
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(PLUGIN_EJEMPLO)
        console.print(f"[dim]Plugin de ejemplo creado en {ruta}[/dim]")
