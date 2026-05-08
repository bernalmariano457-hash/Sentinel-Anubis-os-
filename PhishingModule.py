import os
import sys
import subprocess


class PhishingModule:
    """
    Compatible con Windows (Git Bash), Linux, Termux y uConsole.
    Detecta el sistema operativo automáticamente.
    """

    ZPHISHER_REPO = "https://github.com/htr-tech/zphisher.git"

    def __init__(self, sentinel=None):
        self.sentinel = sentinel
        self.console = getattr(sentinel, "console", None)
        self.log = getattr(sentinel, "log",     None)

        self.script_path = os.path.join(
            os.getcwd(), "tools", "zphisher", "zphisher.sh"
        )

        # Bash según plataforma
        if sys.platform == "win32":
            posibles = [
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files (x86)\Git\bin\bash.exe",
                os.path.expandvars(
                    r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
            ]
            self.bash_path = next(
                (p for p in posibles if os.path.exists(p)), None
            )
        else:
            self.bash_path = "bash"

    # ── helpers ──────────────────────────────────────────────────────

    def _print(self, msg: str):
        if self.console:
            self.console.print(msg)
        else:
            import re
            print(re.sub(r"\[.*?\]", "", msg))

    def _log_error(self, msg: str):
        if self.log:
            self.log.error(msg, "PhishingModule")

    def _log_audit(self, msg: str):
        if self.log:
            self.log.audit(msg, "PhishingModule")

    def _zphisher_instalado(self) -> bool:
        return os.path.exists(self.script_path)

    def _instalar_zphisher(self) -> bool:
        destino = os.path.join(os.getcwd(), "tools", "zphisher")
        self._print(
            "[yellow][!] zphisher no encontrado. Clonando desde GitHub...[/yellow]")
        try:
            os.makedirs(os.path.join(os.getcwd(), "tools"), exist_ok=True)
            subprocess.run(
                ["git", "clone", self.ZPHISHER_REPO, destino],
                check=True, timeout=60
            )
            if sys.platform != "win32":
                subprocess.run(["chmod", "+x", self.script_path], check=True)
            self._print("[green][+] zphisher instalado correctamente.[/green]")
            return True
        except subprocess.TimeoutExpired:
            self._print("[red][!] Timeout. Verifica tu conexión.[/red]")
        except Exception as e:
            self._print(f"[red][!] Error al instalar zphisher: {e}[/red]")
            self._log_error(f"Install: {e}")
        return False

    def _verificar_bash_windows(self) -> bool:
        if self.bash_path is None:
            self._print(
                "[red][!] Git Bash no encontrado en Windows.[/red]\n"
                "[dim]Instala Git desde:[/dim] [cyan]https://git-scm.com[/cyan]"
            )
            return False
        return True

    # ── API pública ───────────────────────────────────────────────────

    def lanzar(self):
        """Lanza zphisher detectando el OS automáticamente."""
        if not self._zphisher_instalado():
            if not self._instalar_zphisher():
                return

        if sys.platform == "win32" and not self._verificar_bash_windows():
            return

        self._print(
            "\n[bold red][!][/bold red] Iniciando Suite de Phishing...")
        self._log_audit("Suite de phishing iniciada")

        try:
            if sys.platform == "win32":
                subprocess.run([self.bash_path, self.script_path], check=True)
            else:
                subprocess.run(["bash", self.script_path], check=True)

        except KeyboardInterrupt:
            self._print(
                "\n[yellow][!] Phishing detenido por el operador.[/yellow]")
        except FileNotFoundError:
            self._print(
                "[red][!] bash no encontrado.[/red]\n"
                "[dim]En Termux: pkg install bash[/dim]"
            )
            self._log_error("bash no encontrado")
        except subprocess.CalledProcessError as e:
            self._print(f"[red][!] zphisher terminó con error: {e}[/red]")
            self._log_error(f"zphisher: {e}")
        except Exception as e:
            self._print(f"[red][!] Error inesperado: {e}[/red]")
            self._log_error(f"Launch: {e}")

    def estado(self):
        """Muestra el estado del módulo."""
        instalado = self._zphisher_instalado()
        self._print(
            f"[cyan]zphisher:[/cyan]   {'[green]Instalado[/green]' if instalado else '[red]No instalado[/red]'}\n"
            f"[cyan]Script:[/cyan]     {self.script_path}\n"
            f"[cyan]Bash:[/cyan]       {self.bash_path or 'No encontrado'}\n"
            f"[cyan]Plataforma:[/cyan] {sys.platform}"
        )
