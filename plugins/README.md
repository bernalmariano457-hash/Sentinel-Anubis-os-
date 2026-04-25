# AnubisOS — Plugin System

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
