from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

if TYPE_CHECKING:
    from core.Security import SecurityModule

log = logging.getLogger("sentinel.recovery")

# Archivos sensibles por defecto (rutas relativas al CWD del proyecto)
_ARCHIVOS_DEFAULT: list[Path] = [
    Path("config.json"),
    Path("data/logs/sentinel.log"),
    Path("data/evidence"),
    Path("core/data/logs"),
]


def _expandir_rutas(rutas: list[Path]) -> list[Path]:
    resultado: list[Path] = []
    for r in rutas:
        if r.is_dir():
            resultado.extend(f for f in r.rglob("*") if f.is_file())
        elif r.exists():
            resultado.append(r)
    return resultado


class SentinelRecovery:
    def __init__(self, security_module: "SecurityModule") -> None:
        if security_module is None:
            raise ValueError(
                "SentinelRecovery requiere una instancia de SecurityModule. "
                "Asegúrate de que el módulo de seguridad cargó correctamente."
            )
        self._sec = security_module
        _sentinel = getattr(security_module, "sentinel", None)
        self._console: Console = (
            _sentinel.console
            if _sentinel and hasattr(_sentinel, "console")
            else Console()
        )

    def ejecutar_rescate(self, archivos: list[Path] | None = None) -> int:
        self._console.print(
            Panel(
                "[bold yellow]⚠  PROTOCOLO DE RECUPERACIÓN INICIADO[/bold yellow]\n"
                "[dim]Usando SecurityModule (anubis_master.key)[/dim]",
                border_style="yellow",
                box=box.HEAVY,
            )
        )

        rutas = _expandir_rutas(
            archivos if archivos is not None else _ARCHIVOS_DEFAULT
        )

        if not rutas:
            self._console.print(
                "[yellow][!] No se encontraron archivos para recuperar.[/yellow]"
            )
            return 0

        tabla = Table(box=box.SIMPLE_HEAD,
                      header_style="bold cyan", show_edge=False)
        tabla.add_column("Archivo", style="white", min_width=40)
        tabla.add_column("Estado",  justify="center", min_width=14)

        restaurados = 0
        for ruta in rutas:
            ok = self._sec.desencriptar_archivo(ruta)
            if ok:
                restaurados += 1
                estado = "[bold green]✔ Restaurado[/bold green]"
            else:
                estado = "[bold red]✖ Error[/bold red]"
            tabla.add_row(str(ruta), estado)

        self._console.print(tabla)

        if restaurados > 0:
            self._console.print(
                f"\n[bold green][+] {restaurados}/{len(rutas)} archivos restaurados.[/bold green]"
            )
            log.info(
                f"Recovery: {restaurados}/{len(rutas)} archivos restaurados.")
        else:
            self._console.print(
                "\n[bold red][-] No se restauró ningún archivo.[/bold red]")
            log.warning("Recovery: ningún archivo restaurado.")

        return restaurados

    def listar_archivos_cifrables(self) -> list[Path]:
        return _expandir_rutas(_ARCHIVOS_DEFAULT)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from core.Security import SecurityModule

    class _FakeSentinel:
        console = Console()

    sec = SecurityModule(_FakeSentinel())
    recovery = SentinelRecovery(sec)
    archivos_arg = [Path(a)
                    for a in sys.argv[1:]] if len(sys.argv) > 1 else None
    recovery.ejecutar_rescate(archivos_arg)
