from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from rich.markup import escape as _esc
from rich.prompt import Prompt

if TYPE_CHECKING:
    from Main import ApexSentinel


class Session:
    def __init__(self, sentinel: "ApexSentinel") -> None:
        self._s = sentinel

    # Helpers internos

    def _console(self):
        return self._s.console

    def _banner(self) -> None:
        from core.bootscreen import mostrar_banner
        s = self._s
        proy = (
            s.gp.proyecto_activo.nombre
            if getattr(s, "gp", None) and getattr(s.gp, "proyecto_activo", None)
            else None
        )
        mostrar_banner(
            s.console, s.nombre, s.version, s._iface(), proyecto=proy
        )

    def _prompt_str(self) -> str:
        s = self._s
        plab = (
            f"[{_esc(str(s.gp.proyecto_activo.nombre))}]"
            if getattr(s, "gp", None) and s.gp.proyecto_activo
            else ""
        )
        return (
            f"[bold green]AnubisOS[/bold green]"
            f"[dim white]@[/dim white]"
            f"[bold cyan]Sentinel[/bold cyan]"
            f"[dim]{plab}[/dim]"
            f"[bold white]~#[/bold white]"
        )

    # Tabla de despacho

    def _construir_tabla(self) -> dict[str, Any]:

        s = self._s
        c = s._cmd

        # importaciones de bootscreen diferidas para no romper fallback
        try:
            from core.bootscreen import COMANDOS_HELP, mostrar_ayuda
        except ImportError:
            COMANDOS_HELP = {}

            def mostrar_ayuda(con, ver, cmds=None):
                con.print("[dim]Sin ayuda.[/dim]")

        return {
            # Sistema
            "help": lambda: mostrar_ayuda(s.console, s.version, COMANDOS_HELP),
            "?": lambda: mostrar_ayuda(s.console, s.version, COMANDOS_HELP),
            "status":    c.status,
            "hora": lambda: s.console.print(
                f"[cyan]Hora:[/cyan] {time.strftime('%H:%M:%S')}"),
            "clear":     self._banner,
            "cls":       self._banner,
            "logs":      s.log.mostrar_historial,
            "files":     c.files,
            # Red
            "scan":      c.scan,
            "netscan":   c.scan,
            "advscan":   c.advscan,
            "portscan":  c.portscan,
            "sweep":     c.sweep,
            "sniff":     c.sniff,
            "radar":     c.radar,
            "audit":     c.audit,
            "vulnscan":  c.vulnscan,
            "sqlcheck":  c.sqlcheck,
            # Wireless
            "wifi":      c.wifi,
            "eviltwin":  c.eviltwin,
            "btjumper": lambda: (
                s.bt.iniciar_jumper() if s._modulo_ok("bt") else None),
            # RF
            "rfscan":    c.rfscan,
            "rfmenu":    c.rfmenu,
            "rfbarrido": c.rfbarrido,
            "rfbandas":  c.rfbandas,
            "rfdb":      c.rfdb,
            "rfstats":   c.rfstats,
            "rfstatus":  c.rfestado,
            "radio":     c.radio,
            "rfgrabar":  c.rfgrabar,
            "rfplay":    c.rfplay,
            "adsb":      c.adsb,
            # Mobile / Forense
            "mobile":      c.mobile,
            "mobile-deep": c.mobile_deep,
            "view":        c.view,
            # OSINT / Geo
            "geofoto":   c.geofoto,
            "osint":     c.osint,
            "cve":       c.cve,
            # Ofensivo
            "phishing":  c.phishing,
            "ducky":     c.ducky,
            "stealth":   c.stealth,
            "panic":     c.panic,
        }

    # Despacho

    def despachar(self, entrada: str) -> bool:
        partes = entrada.strip().lower().split()
        if not partes:
            return True
        cmd, args = partes[0], partes[1:]
        s = self._s
        c = s._cmd

        # Comandos con subargumentos — no encajan en la tabla simple
        if cmd == "proyecto":
            c.proyecto(args)
            return True
        if cmd == "reporte":
            c.reporte(args)
            return True
        if cmd in ("job", "jobs"):
            c.jobs(args)
            return True
        if cmd in ("plugin", "plugins"):
            c.plugins(args)
            return True
        if cmd == "locate":
            (c.locate_p if "-p" in args else c.locate)()
            return True

        tabla = self._construir_tabla()
        if cmd in tabla:
            try:
                tabla[cmd]()
            except Exception as exc:
                s.console.print(f"[red][!] Error en '{cmd}': {exc}[/red]")
                s.log.error(str(exc), f"cmd:{cmd}")
            return True

        # Plugins registrados dinámicamente
        if getattr(s, "plugins", None) and s.plugins.tiene_comando(cmd):
            s.plugins.ejecutar_comando(cmd, args)
            return True

        return False

    # Bucle principal

    def ejecutar(self) -> None:
        s = self._s

        if not s.auth.solicitar_acceso():
            s.console.print(
                "[red][!] Acceso denegado. Sistema bloqueado.[/red]")
            s.log.warning(
                "Sistema bloqueado por intentos fallidos.", "GestorAuth")
            return

        if getattr(s, "checker", None):
            s.checker.verificar_dependencias()

        s.log.verificar_y_limpiar()

        if getattr(s, "stealth", None):
            s.stealth.verificar_identidad()

        s.log.info("Sistema iniciado correctamente.", "ApexSentinel")

        if getattr(s, "rf", None):
            rf_tag = (
                f"[green]{s.rf.hw_nombre}[/green]"
                if s.rf.hw_disponible
                else f"[yellow]{s.rf.hw_nombre}[/yellow]"
            )
            s.console.print(f"\n[dim][RF] Hardware: {rf_tag}[/dim]")

        if getattr(s, "gp", None) and not s.gp.proyecto_activo:
            s.console.print(
                "\n[dim][tip] Usa [bold white]proyecto nuevo[/bold white] "
                "para crear un workspace de operación.[/dim]\n"
            )

        while True:
            try:
                entrada = Prompt.ask(self._prompt_str(), default="").strip()
                if not entrada:
                    continue

                if entrada.lower() == "exit":
                    s.console.print(
                        "[yellow][!] Desconectando Sentinel...[/yellow]")
                    s.log.info("Sesión cerrada por el operador.",
                               "ApexSentinel")
                    s._signals.cleanup()
                    time.sleep(0.5)
                    break

                if not self.despachar(entrada):
                    s.console.print(
                        f"[yellow][?] Comando '[bold]{entrada}[/bold]' no "
                        f"reconocido. Escribe [bold white]help[/bold white] "
                        f"para ver opciones.[/yellow]"
                    )

            except EOFError:
                s._signals.cleanup()
                break
            except Exception as exc:
                s.console.print(f"[red][!] Error inesperado: {exc}[/red]")
                s.log.error(str(exc), "Bucle principal")
