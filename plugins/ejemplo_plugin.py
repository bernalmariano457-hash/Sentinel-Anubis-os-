from core.PluginSystem import PluginBase


class EjemploPlugin(PluginBase):
    NOMBRE = "ejemplo"
    VERSION = "2.3"
    DESCRIPCION = "Plugin de demostración del sistema"
    AUTOR = "AnubisOS"
    COMANDOS = ["hola", "ejemplo"]

    def ejecutar(self, comando: str, args: list = None):
        if comando == "hola":
            self.console.print(
                "[green]¡Hola desde el plugin de ejemplo![/green]")
        elif comando == "ejemplo":
            self.console.print(
                f"[cyan]Plugin:[/cyan] {self.NOMBRE} v{self.VERSION}\n"
                f"[cyan]Args:[/cyan]   {args}"
            )
            # Registrar evidencia si hay proyecto activo
            if self.sentinel.gp.proyecto_activo:
                self.sentinel.gp.registrar_evidencia(
                    "plugin_ejemplo", "Comando de ejemplo ejecutado", {
                        "args": args}
                )
