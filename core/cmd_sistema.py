"""
core/commands/cmd_sistema.py — Comandos de gestión del sistema Sentinel
"""
from __future__ import annotations

from rich.panel import Panel

from core.commands._base import _DomainBase


class SistemaCommands(_DomainBase):

    def proyecto(self, args: list):
        if not self._modulo_ok("gp"):
            return
        sub = args[0] if args else ""
        acciones = {
            "nuevo":  self.s.gp.crear_proyecto,
            "cargar": self.s.gp.cargar_proyecto,
            "lista":  self.s.gp.listar_proyectos,
            "list":   self.s.gp.listar_proyectos,
            "estado": self.s.gp.mostrar_resumen,
            "cerrar": self.s.gp.cerrar_proyecto,
        }
        accion = acciones.get(sub)
        if accion:
            accion()
        else:
            self.console.print(
                "[dim]Subcomandos: [bold white]nuevo | cargar | lista | estado | cerrar"
                "[/bold white][/dim]")

    def reporte(self, args: list):
        if not self._modulo_ok("motor_rep"):
            return
        sub = args[0] if args else ""
        if sub == "resumen":
            self.s.motor_rep.generar_resumen_ejecutivo()
        elif sub == "timeline":
            self.s.motor_rep.generar_timeline()
        else:
            self.s.motor_rep.generar_reporte_completo()

    def jobs(self, args: list):
        if not self._modulo_ok("cola"):
            return
        sub = args[0] if args else ""
        if sub == "resultado" and len(args) > 1:
            self.s.cola.resultado(args[1])
        elif sub == "cancelar" and len(args) > 1:
            self.s.cola.cancelar(args[1])
        elif sub == "limpiar":
            self.s.cola.limpiar_completadas()
        else:
            self.s.cola.listar()

    def plugins(self, args: list):
        s = self.s
        if not self._modulo_ok("plugins"):
            return
        sub = args[0] if args else ""
        if sub == "reload":
            s.plugins.recargar()
        elif sub == "ayuda" and len(args) > 1:
            p = s.plugins._plugins.get(args[1])
            if p:
                self.console.print(Panel(p.ayuda(), border_style="green"))
            else:
                self.console.print(f"[red][!] Plugin '{args[1]}' no encontrado.[/red]")
        else:
            s.plugins.listar()
