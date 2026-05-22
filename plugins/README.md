# plugins/

```python
from core.PluginSystem import PluginBase

class MiPlugin(PluginBase):
    nombre   = "mi_plugin"
    version  = "1.0"
    comandos = {"micomando": "Descripción breve"}

    def ejecutar(self, comando: str, args: list[str]) -> None:
        self.console.print(f"[green]Ejecutando {comando}[/green]")
```

## Recargar sin reiniciar

```
AnubisOS@Sentinel~# plugins reload
```

Ver documentación completa en el [README principal](../README.md).
