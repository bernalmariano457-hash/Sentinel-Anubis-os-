from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from rich import box
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

if TYPE_CHECKING:
    from Main import ApexSentinel

# Constantes
# La clave de pánico va en el mismo directorio que la maestra de SecurityModule.
# No generamos una clave paralela — StealthModule reutiliza SecurityModule.
_SECURITY_DIR = Path("data/security")

_ISP_KEYWORDS_SEGUROS: frozenset[str] = frozenset({
    "VPN", "PROXY", "DATACENTER", "CLOUDFLARE",
    "HOSTING", "MULLVAD", "NORDVPN", "TOR", "ANONIMIZADOR",
})

# Archivos que el protocolo de pánico debe cifrar antes de cerrar.
# Usamos rutas relativas al CWD del proyecto.
_ARCHIVOS_SENSIBLES: tuple[str, ...] = (
    "config.json",
    "sentinel_activity.log",
    "capturas.pcap",
    "reportes.txt",
    "core/data/logs/sentinel.log",
    "core/data/security/.credentials",
    "capturas_anubis.txt",
)


class StealthModule:
    def __init__(self, sentinel: ApexSentinel) -> None:
        self.sentinel = sentinel
        self._console = sentinel.console
        self._log = sentinel.log
        _SECURITY_DIR.mkdir(parents=True, exist_ok=True)

    # Verificación de identidad digital

    def verificar_identidad(self) -> dict[str, str | bool]:
        self._console.print(
            "\n[dim][stealth] Verificando máscara de identidad digital...[/dim]")

        try:
            import requests  # noqa: PLC0415
            campos = "status,country,city,isp,query,as,proxy,hosting,mobile"
            data = requests.get(
                f"http://ip-api.com/json/?fields={campos}", timeout=5
            ).json()
        except Exception as exc:
            self._console.print(
                f"[red][!] Stealth: sin acceso a la red — {exc}[/red]")
            self._log.warning(
                "verificar_identidad: sin conexión.", "StealthModule")
            return {}

        if data.get("status") != "success":
            self._console.print(
                "[red][!] El servicio de identidad no responde.[/red]")
            return {}

        ip = data.get("query",   "?")
        proveedor = data.get("isp",    "?")
        ciudad = data.get("city",    "?")
        pais = data.get("country", "?")
        es_proxy = data.get("proxy",   False)
        es_host = data.get("hosting", False)
        es_movil = data.get("mobile",  False)

        protegido = (
            es_proxy
            or es_host
            or any(k in proveedor.upper() for k in _ISP_KEYWORDS_SEGUROS)
        )

        color = "green" if protegido else "red"
        estado = (
            "[bold green]PROTEGIDO[/bold green] — Túnel activo."
            if protegido else
            "[bold red]EXPUESTO[/bold red] — Red real visible."
        )

        tabla = Table(box=box.SIMPLE, show_header=False,
                      show_edge=False, padding=(0, 1))
        tabla.add_column(style="dim", width=16)
        tabla.add_column()
        tabla.add_row("IP pública",  f"[bold white]{ip}[/bold white]")
        tabla.add_row("ISP",          proveedor)
        tabla.add_row("Ubicación",   f"{ciudad}, {pais}")
        tabla.add_row("Proxy/VPN",   _bool_tag(es_proxy))
        tabla.add_row("Datacenter",  _bool_tag(es_host))
        tabla.add_row("Red móvil",   _bool_tag(es_movil, invertir=False))
        tabla.add_row("Estado",       estado)

        self._console.print(Panel(
            tabla,
            title="[bold blue]Identidad digital[/bold blue]",
            border_style=color,
            expand=False,
        ))

        if protegido:
            self._log.info(
                f"Identidad: {ip} ({proveedor}) — PROTEGIDO", "StealthModule")
        else:
            self._log.warning(
                f"Identidad: {ip} ({proveedor}) — EXPUESTO", "StealthModule")
            self._console.print(
                "[yellow][!] Conecta una VPN antes de operar.[/yellow]\n")

        return {
            "ip": ip, "isp": proveedor,
            "ciudad": ciudad, "pais": pais,
            "protegido": protegido,
        }

    # Cifrado de archivos sensibles

    def cifrar_archivos(self) -> tuple[int, int]:
        sec = getattr(self.sentinel, "security", None)
        if sec is None:
            self._console.print(
                "[red][!] SecurityModule no disponible para cifrar.[/red]")
            return 0, 0

        ok = err = 0
        for ruta_str in _ARCHIVOS_SENSIBLES:
            ruta = Path(ruta_str)
            if not ruta.exists():
                continue
            if sec.encriptar_archivo(ruta):
                self._console.print(
                    f"  [green][+][/green] [dim]{ruta}[/dim] cifrado.")
                ok += 1
            else:
                self._console.print(
                    f"  [red][-][/red] [dim]{ruta}[/dim] — error al cifrar.")
                err += 1
        return ok, err

    # Limpieza de historial de terminal

    def limpiar_historial(self) -> bool:
        if sys.platform == "win32":
            self._console.print(
                "  [yellow][!][/yellow] Limpieza de historial no soportada en Windows.")
            return False
        try:
            subprocess.run(["bash", "-c", "history -c"],
                           capture_output=True, timeout=5)
            for hist_file in (Path.home() / ".bash_history", Path.home() / ".zsh_history"):
                if hist_file.exists():
                    hist_file.write_text("", encoding="utf-8")
            self._console.print(
                "  [green][+][/green] Historial de terminal purgado.")
            return True
        except Exception as exc:
            self._console.print(
                f"  [red][-][/red] Error purgando historial: {exc}")
            return False

    # Borrado de temporales

    def limpiar_temporales(self) -> int:
        eliminados = 0
        for patron in ("*.pyc", "__pycache__", ".pytest_cache", "htmlcov", ".coverage"):
            for ruta in Path(".").rglob(patron):
                try:
                    shutil.rmtree(ruta) if ruta.is_dir() else ruta.unlink()
                    eliminados += 1
                except Exception:
                    pass
        return eliminados

    # Protocolo de pánico completo

    def activar_panico(self) -> None:
        with _barra_progreso(self._console) as pg:
            tk = pg.add_task("Activando protocolo de pánico...", total=3)

            pg.update(tk, description="Cifrando archivos tácticos...")
            ok, err = self.cifrar_archivos()
            pg.advance(tk)

            pg.update(tk, description="Purgando historial del sistema...")
            self.limpiar_historial()
            pg.advance(tk)

            pg.update(tk, description="Limpiando temporales...")
            eliminados = self.limpiar_temporales()
            pg.advance(tk)

        self._log.audit(
            f"Protocolo de pánico completado — "
            f"{ok} archivos cifrados, {eliminados} temporales eliminados.",
            "StealthModule",
        )

        self._console.print(Panel(
            f"[bold green]Protocolo completado.[/bold green]\n\n"
            f"  Archivos cifrados : [white]{ok}[/white]"
            + (f"  ([red]{err} errores[/red])" if err else "") + "\n"
            f"  Temporales eliminados : [white]{eliminados}[/white]\n"
            f"  Clave de descifrado : [dim]SecurityModule (anubis_master.key)[/dim]\n\n"
            f"[dim]Usa el comando 'recovery' para restaurar los archivos.[/dim]",
            title="[bold red]PÁNICO — COMPLETO[/bold red]",
            border_style="red", expand=False,
        ))

        try:
            self.sentinel._cleanup()
        except Exception:
            pass

        sys.exit(0)

# Helpers privados de módulo


def _bool_tag(valor: bool, invertir: bool = True) -> str:
    """Formatea un bool como markup Rich con color verde/rojo."""
    if invertir:
        return "[green]Sí[/green]" if valor else "[red]No[/red]"
    return "[white]Sí[/white]" if valor else "[dim]No[/dim]"


def _barra_progreso(console: object) -> Progress:
    return Progress(
        SpinnerColumn(style="bold red"),
        TextColumn("[red]{task.description}[/red]"),
        BarColumn(bar_width=20, complete_style="bold red"),
        console=console,  # type: ignore[arg-type]
        transient=True,
    )
