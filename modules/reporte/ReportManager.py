from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path


class ReportManager:

    LIMITE_MB: float = 5.0

    def __init__(self, config=None):
        from rich.console import Console
        self.console = Console()

        base = Path(config.workspace) if config and hasattr(
            config, "workspace") else Path(".")
        self.archivo_reportes = base / "reportes.txt"
        self.archivo_log = base / "sentinel_activity.log"

    # API pública

    def verificar_y_limpiar(self) -> None:
        if not self.archivo_reportes.exists():
            return
        tamaño_mb = self.archivo_reportes.stat().st_size / (1024 * 1024)
        if tamaño_mb > self.LIMITE_MB:
            self.console.print(
                f"[yellow][!] Archivo de reportes superó {self.LIMITE_MB:.0f} MB. Rotando...[/yellow]"
            )
            self._comprimir_y_rotar()

    def registrar_evento(self, modulo: str, mensaje: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entrada = f"[{timestamp}] [{modulo.upper()}] {mensaje}\n"
        with self.archivo_log.open("a", encoding="utf-8") as fh:
            fh.write(entrada)

    def mostrar_historial(self) -> None:
        self.console.rule("[bold cyan]HISTORIAL DE EVENTOS[/bold cyan]")
        try:
            if self.archivo_log.exists():
                contenido = self.archivo_log.read_text(encoding="utf-8")
                if contenido:
                    self.console.print(contenido)
                else:
                    self.console.print("[dim][!] El log está vacío.[/dim]")
            else:
                self.console.print(
                    "[yellow][-] No se encontró el archivo de logs.[/yellow]")
        except OSError as e:
            self.console.print(f"[red][!] Error al leer logs: {e}[/red]")
        self.console.rule()

    def guardar_auditoria(self, tipo: str, datos) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.archivo_reportes.open("a", encoding="utf-8") as fh:
            fh.write(f"\n{'=' * 50}\n")
            fh.write(f"AUDITORÍA: {tipo}\n")
            fh.write(f"FECHA: {timestamp}\n")
            fh.write(f"{'-' * 50}\n")
            if isinstance(datos, (dict, list)):
                fh.write(json.dumps(datos, indent=4, ensure_ascii=False))
            else:
                fh.write(str(datos))
            fh.write(f"\n{'=' * 50}\n")
        self.console.print(
            f"[green][+] Hallazgos guardados en {self.archivo_reportes}[/green]")

    # Internos

    def _comprimir_y_rotar(self) -> None:
        from core.config import cargar_config
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        nombre_zip = self.archivo_reportes.parent / \
            f"backup_reportes_{timestamp}.zip"

        try:
            cfg = cargar_config()
            password = cfg.get("backup_password") or ""
        except Exception:
            password = ""

        self.console.print(
            f"[cyan][*] Comprimiendo reportes en {nombre_zip.name}...[/cyan]")

        try:
            if password:
                cmd = [
                    "zip",
                    "--password", password,
                    str(nombre_zip),
                    str(self.archivo_reportes),
                    str(self.archivo_log),
                ]
            else:
                cmd = [
                    "zip",
                    str(nombre_zip),
                    str(self.archivo_reportes),
                    str(self.archivo_log),
                ]

            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            self.archivo_reportes.write_text(
                f"--- NUEVO CICLO: {timestamp} ---\n", encoding="utf-8"
            )
            self.archivo_log.write_text(
                f"--- LOG REINICIADO: {timestamp} ---\n", encoding="utf-8"
            )

            self.console.print(
                "[green][+] Backup completado y archivos reiniciados.[/green]")
            self.registrar_evento(
                "SISTEMA", f"Auto-limpieza ejecutada. Backup: {nombre_zip.name}")

        except subprocess.CalledProcessError as e:
            self.console.print(
                f"[red][-] Error en auto-limpieza (zip): {e}[/red]")
        except FileNotFoundError:
            self.console.print(
                "[red][-] 'zip' no encontrado en PATH. Instala con: sudo apt install zip[/red]")
        except OSError as e:
            self.console.print(
                f"[red][-] Error al escribir archivos rotados: {e}[/red]")
