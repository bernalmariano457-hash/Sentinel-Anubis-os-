from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from rich import box
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table

from core._base import _DomainBase
from core.validators import Validador

_ZPHISHER = Path("tools/zphisher/zphisher.sh")

_ISP_KEYWORDS_SEGUROS = frozenset({
    "VPN", "PROXY", "DATACENTER", "CLOUDFLARE",
    "HOSTING", "MULLVAD", "NORDVPN", "TOR",
})


class OfensivoCommands(_DomainBase):

    # Phishing

    def phishing(self) -> None:
        """Lanza zphisher con validaciones previas de entorno."""
        s = self.s
        self.console.print(
            Rule("[bold red]SUITE DE PHISHING[/bold red]", style="red"))

        if not _ZPHISHER.exists():
            self.console.print(Panel(
                "[red]zphisher no encontrado.[/red]\n\n"
                "[dim]Instálalo con:\n"
                "  git clone https://github.com/htr-tech/zphisher.git tools/zphisher[/dim]",
                title="[red]ERROR[/red]", border_style="red", expand=False,
            ))
            return

        if not _verificar_bash():
            self.console.print(
                "[red][!] bash no disponible en este sistema.[/red]")
            return

        self.console.print("[dim][*] Iniciando zphisher...[/dim]")
        s.log.audit("Lanzamiento de suite de phishing (zphisher)", "Phishing")

        try:
            cmd = (
                [r"C:\Program Files\Git\bin\bash.exe", str(_ZPHISHER)]
                if sys.platform == "win32"
                else ["bash", str(_ZPHISHER)]
            )
            subprocess.run(cmd, check=True)
            s.log.info("Sesión de phishing completada.", "Phishing")
            if s.gp and s.gp.proyecto_activo:
                s.gp.registrar_evidencia(
                    "phishing", "Sesión de phishing ejecutada vía zphisher", {})
        except subprocess.CalledProcessError as exc:
            self.console.print(
                f"[red][!] zphisher terminó con código {exc.returncode}[/red]")
            s.log.error(f"Phishing CalledProcessError: {exc}", "Phishing")
        except FileNotFoundError:
            self.console.print("[red][!] bash no encontrado en el PATH.[/red]")
        except Exception as exc:
            self.console.print(f"[red][!] Error inesperado: {exc}[/red]")
            s.log.error(str(exc), "Phishing")

    # Rubber Ducky

    def ducky(self) -> None:
        s = self.s
        if not self._modulo_ok("ducky"):
            return

        self.console.print(
            Rule("[bold yellow]RUBBER DUCKY[/bold yellow]", style="yellow"))

        estado = s.ducky.estado() if hasattr(s.ducky, "estado") else {}
        hid_ok = estado.get("hid_disponible", False)

        tabla_estado = Table(
            box=box.SIMPLE, show_header=False, show_edge=False)
        tabla_estado.add_column(style="dim", width=20)
        tabla_estado.add_column()
        tabla_estado.add_row(
            "Dispositivo HID",
            f"[green]{s.ducky.hid_path}[/green]"
            if hid_ok else f"[red]{s.ducky.hid_path} (no disponible)[/red]",
        )
        tabla_estado.add_row("Delay por defecto",
                             f"{s.ducky.DEFAULT_DELAY * 1000:.0f} ms")
        self.console.print(Panel(tabla_estado, title="Estado",
                           border_style="yellow", expand=False))

        if not hid_ok:
            self.console.print(
                "[yellow][!] HID no disponible. "
                "Verifica que /dev/hidg0 exista y tengas permisos.[/yellow]")
            return

        payloads = _listar_payloads()
        if not payloads:
            self.console.print(
                "[yellow][!] No hay payloads en tools/payloads/. "
                "Crea un .txt con sintaxis DuckyScript.[/yellow]")
            return

        self.console.print("\n[bold]Payloads disponibles:[/bold]")
        for i, p in enumerate(payloads, 1):
            self.console.print(f"  [cyan]{i}[/cyan]. {p.name}")

        eleccion = Validador.pedir(
            self.console, "Selecciona payload [n]",
            validador=lambda v: v.isdigit() and 1 <= int(v) <= len(payloads),
            error=f"Número entre 1 y {len(payloads)}.",
        )
        if not eleccion:
            return

        payload_path = payloads[int(eleccion) - 1]
        if not Confirm.ask(
            f"[yellow][!] Ejecutar [bold]{payload_path.name}[/bold] — "
            f"¿objetivo correcto?[/yellow]"
        ):
            self.console.print("[dim]Cancelado.[/dim]")
            return

        s.log.audit(
            f"Ejecución de payload Ducky: {payload_path.name}", "DuckyModule")

        try:
            s.ducky.ejecutar_payload(str(payload_path))
            self.console.print(
                f"[green][OK] Payload '[bold]{payload_path.name}[/bold]' enviado.[/green]")
            s.log.info(f"Payload enviado: {payload_path.name}", "DuckyModule")
            if s.gp and s.gp.proyecto_activo:
                s.gp.registrar_hallazgo(
                    "MEDIO", "Payload HID ejecutado",
                    f"Archivo: {payload_path.name}",
                    "Revisar respuesta del objetivo.",
                )
        except PermissionError:
            self.console.print(
                "[red][!] Permiso denegado al escribir en el HID. Ejecuta como root.[/red]")
        except Exception as exc:
            self.console.print(f"[red][!] Error en payload: {exc}[/red]")
            s.log.error(str(exc), "DuckyModule")

    # Stealth

    def stealth(self) -> None:
        # Delega en StealthModule.verificar_identidad() — sin reimplementación inline.
        s = self.s
        if not self._modulo_ok("stealth"):
            return
        self.console.print(
            Rule("[bold blue]STEALTH — IDENTIDAD DIGITAL[/bold blue]", style="blue"))
        s.animar_barra("Consultando máscara de red...", pasos=12)
        s.stealth.verificar_identidad()

    # Panic

    def panic(self) -> None:
        s = self.s
        if not self._modulo_ok("stealth"):
            return

        self.console.print(Panel(
            "[bold red]MODO PÁNICO[/bold red]\n\n"
            "[white]Cifrará todos los archivos sensibles y limpiará el historial.\n"
            "Esta operación [bold]no se puede deshacer[/bold] sin la clave.[/white]",
            border_style="red", expand=False,
        ))

        if not Confirm.ask("[bold red][!] ¿Confirmas activación del modo pánico?[/bold red]"):
            self.console.print("[dim]Operación cancelada.[/dim]")
            return

        if Prompt.ask("[bold red]Escribe PANICO para confirmar[/bold red]").strip() != "PANICO":
            self.console.print(
                "[yellow][!] Confirmación incorrecta. Cancelado.[/yellow]")
            return

        s.log.audit(
            "MODO PÁNICO ACTIVADO — cifrado de emergencia iniciado.", "StealthModule")
        self.console.print("\n[bold red][!] ACTIVANDO...[/bold red]")

        try:
            s.stealth.activar_panico()
        except Exception as exc:
            self.console.print(
                f"[red][!] Error durante el pánico: {exc}[/red]")
            s.log.error(str(exc), "StealthModule — panic")

    # Evil Twin

    def eviltwin(self) -> None:
        s = self.s
        servidor_fn = getattr(s, "_evil_twin_server", None)

        if servidor_fn is None:
            self.console.print(Panel(
                "[red]EvilTwinServer no disponible.[/red]\n\n"
                "[dim]Verifica que Flask esté instalado:\n"
                "  pip install flask[/dim]",
                title="[red]ERROR[/red]", border_style="red", expand=False,
            ))
            return

        self.console.print(Rule(
            "[bold magenta]EVIL TWIN — PORTAL CAUTIVO[/bold magenta]", style="magenta"))
        self.console.print(Panel(
            "[yellow]Esta herramienta es para auditorías wireless autorizadas.\n"
            "Úsala únicamente en redes propias o con permiso escrito del propietario.[/yellow]",
            border_style="yellow", expand=False,
        ))

        ssid = Validador.pedir(
            self.console,
            "SSID del portal cautivo",
            validador=lambda v: 1 <= len(v) <= 32,
            error="El SSID debe tener entre 1 y 32 caracteres.",
        )
        if not ssid:
            return

        if not Confirm.ask(
            f"[magenta][!] Iniciar portal cautivo con SSID '[bold]{ssid}[/bold]'?[/magenta]"
        ):
            self.console.print("[dim]Cancelado.[/dim]")
            return

        s.log.audit(f"Evil Twin iniciado — SSID: {ssid}", "EvilTwin")

        hilo = threading.Thread(
            target=servidor_fn, daemon=True, name="evil-twin-server")
        hilo.start()
        time.sleep(0.5)

        if not hilo.is_alive():
            self.console.print(
                "[red][!] El servidor no pudo iniciarse. ¿Otra app usa el puerto 80?[/red]")
            s.log.error("EvilTwin: servidor no arrancó.", "EvilTwin")
            return

        self.console.print(Panel(
            f"[green]Portal activo en [bold]http://0.0.0.0:80[/bold][/green]\n"
            f"[dim]SSID: {ssid}[/dim]\n\n"
            "[dim]Presiona [bold white]ENTER[/bold white] para detener.[/dim]",
            title="[bold magenta]EN VIVO[/bold magenta]",
            border_style="magenta", expand=False,
        ))

        try:
            input()
        except (KeyboardInterrupt, EOFError):
            pass

        self.console.print("[yellow][!] Deteniendo portal cautivo...[/yellow]")
        s.log.audit("Evil Twin detenido.", "EvilTwin")

        if s.gp and s.gp.proyecto_activo:
            s.gp.registrar_evidencia(
                "evil_twin",
                f"Portal cautivo ejecutado — SSID: {ssid}",
                {"ssid": ssid},
            )

# Helpers privados de módulo


def _verificar_bash() -> bool:
    if sys.platform == "win32":
        return Path(r"C:\Program Files\Git\bin\bash.exe").exists()
    try:
        subprocess.run(["bash", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _listar_payloads() -> list[Path]:
    directorio = Path("tools/payloads")
    if not directorio.exists():
        return []
    return sorted(directorio.glob("*.txt"))
