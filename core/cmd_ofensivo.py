from __future__ import annotations

import os
import subprocess
import sys

from core._base import _DomainBase


class OfensivoCommands(_DomainBase):

    def phishing(self):
        s = self.s
        s._limpiar()
        self.console.print(
            "[bold red][!][/bold red] Iniciando Suite de Phishing...")
        ruta_z = "./tools/zphisher/zphisher.sh"
        if not os.path.exists(ruta_z):
            self.console.print(
                "[red][!] zphisher no encontrado en ./tools/zphisher/[/red]\n"
                "[dim]  git clone https://github.com/htr-tech/zphisher.git tools/zphisher[/dim]"
            )
            return
        try:
            if sys.platform == "win32":
                bash_path = r"C:\Program Files\Git\bin\bash.exe"
                if not os.path.exists(bash_path):
                    self.console.print(
                        "[red][!] Git Bash no encontrado.[/red]")
                    return
                subprocess.run([bash_path, ruta_z], check=True)
            else:
                subprocess.run(["bash", ruta_z], check=True)
        except Exception as e:
            self.console.print(f"[red]Error al lanzar: {e}[/red]")
            s.log.error(f"Phishing: {e}", "PhishingModule")

    def ducky(self):
        if not self._modulo_ok("ducky"):
            return
        with self.s.ducky:
            self.s.ducky.ejecutar_payload()

    def stealth(self):
        if not self._modulo_ok("stealth"):
            return
        self.s.stealth.verificar_identidad()

    def panic(self):
        if not self._modulo_ok("stealth"):
            return
        self.s.stealth.activar_panico()
