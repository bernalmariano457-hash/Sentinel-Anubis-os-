"""
AnubisOS — PhishingModule
Lanzador de zphisher compatible con Windows, Linux y Termux.
Detecta el sistema operativo automáticamente.
"""

import os
import sys
import subprocess


class PhishingModule:
    """
    Módulo de lanzamiento de zphisher.
    Compatible con Windows (Git Bash), Linux y Termux/Android.
    Acepta sentinel como argumento opcional para integrarse con ApexSentinel.
    """

    ZPHISHER_REPO = "https://github.com/htr-tech/zphisher.git"

    def _init_(self, sentinel=None):
        self.sentinel = sentinel

        # Ruta del script
        self.script_path = os.path.join(
            os.getcwd(), "tools", "zphisher", "zphisher.sh"
        )

        # Ruta de bash según el sistema operativo
        if sys.platform == "win32":
            # Windows — buscar Git Bash en rutas comunes
            posibles = [
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files (x86)\Git\bin\bash.exe",
                os.path.expanduser(
                    r"~\AppData\Local\Programs\Git\bin\bash.exe"),
            ]
            self.bash_path = next(
                (p for p in posibles if os.path.exists(p)), None
            )
        else:
            # Linux / Termux / uConsole — bash nativo
            self.bash_path = "bash"

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def lanzar(self):
        """Lanza zphisher con detección automática de entorno."""
        self._verificar_instalacion()

        if not os.path.exists(self.script_path):
            self._mostrar_error_instalacion()
            return False

        if sys.platform == "win32" and not self.bash_path:
            self._mostrar_error_bash()
            return False

        try:
            self._log("[!] Iniciando Suite de Phishing...")
            subprocess.run([self.bash_path, self.script_path], check=True)
            return True

        except subprocess.CalledProcessError as e:
            self._log(f"[!] zphisher terminó con error: {e}")
            return False

        except FileNotFoundError:
            self._log("[!] No se encontró el intérprete bash.")
            if sys.platform == "win32":
                self._mostrar_error_bash()
            return False

        except Exception as e:
            self._log(f"[!] Error inesperado al lanzar phishing: {e}")
            return False

    def instalar(self):
        """Clona zphisher si no está instalado."""
        ruta_tools = os.path.join(os.getcwd(), "tools")
        ruta_dest = os.path.join(ruta_tools, "zphisher")

        if os.path.exists(self.script_path):
            self._log("[+] zphisher ya está instalado.")
            return True

        os.makedirs(ruta_tools, exist_ok=True)
        self._log("[*] Descargando zphisher...")

        try:
            subprocess.run(
                ["git", "clone", self.ZPHISHER_REPO, ruta_dest],
                check=True
            )
            # Dar permisos de ejecución en Linux/Termux
            if sys.platform != "win32":
                subprocess.run(
                    ["chmod", "+x", self.script_path], check=True
                )
            self._log("[+] zphisher instalado correctamente.")
            return True

        except subprocess.CalledProcessError as e:
            self._log(f"[!] Error al clonar zphisher: {e}")
            return False

        except FileNotFoundError:
            self._log("[!] Git no está instalado. Instálalo primero.")
            return False

    def estado(self) -> dict:
        """Retorna el estado actual del módulo."""
        return {
            "instalado":   os.path.exists(self.script_path),
            "script_path": self.script_path,
            "bash_path":   self.bash_path,
            "plataforma":  sys.platform,
        }

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _verificar_instalacion(self):
        """Ofrece instalar zphisher si no está presente."""
        if not os.path.exists(self.script_path):
            self._log(
                f"[!] zphisher no encontrado en: {self.script_path}\n"
                f"    Ejecuta: git clone {self.ZPHISHER_REPO} tools/zphisher"
            )

    def _mostrar_error_instalacion(self):
        self._log(
            "[!] zphisher no está instalado.\n"
            "    Instálalo con:\n"
            f"    git clone {self.ZPHISHER_REPO} tools/zphisher"
        )

    def _mostrar_error_bash(self):
        self._log(
            "[!] Git Bash no encontrado en Windows.\n"
            "    Descárgalo desde: https://git-scm.com/download/win\n"
            "    O instala WSL para usar bash nativo."
        )

    def _log(self, mensaje: str):
        """Usa el logger del sentinel si está disponible, sino print."""
        if self.sentinel and hasattr(self.sentinel, "log"):
            self.sentinel.log.info(mensaje, "PhishingModule")
        elif self.sentinel and hasattr(self.sentinel, "console"):
            self.sentinel.console.print(f"[red]{mensaje}[/red]")
        else:
            print(mensaje)
