from __future__ import annotations

import os
import subprocess
from pathlib import Path

from core.evidence_bridge import register_evidence


class DatabaseExtractor:
    def __init__(self, sentinel=None, adb_path: str = "adb") -> None:
        self.adb = adb_path
        self.sentinel = sentinel
        from rich.console import Console
        self.console = Console()
        self.workspace = getattr(
            sentinel, "workspace", Path.cwd()) if sentinel else Path.cwd()
        self.operator_id = getattr(
            sentinel, "operator_id", "op-mariano") if sentinel else "op-mariano"

    def _get_device_serial(self) -> str:
        try:
            result = subprocess.run(
                [self.adb, "get-serialno"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            serial = result.stdout.strip()
            if serial and "unknown" not in serial.lower():
                return serial
        except Exception:
            pass
        return "unknown"

    def _registrar_log(self, mensaje: str) -> None:
        if self.sentinel and hasattr(self.sentinel, "reportes"):
            self.sentinel.reportes.registrar_evento("FORENSE", mensaje)
        else:
            self.console.print(f"[dim][LOG] {mensaje}[/dim]")

    def _registrar_archivo_forense(
        self,
        archivo: Path,
        tipo: str,
        descripcion: str,
        detalles_extra: dict | None = None,
    ) -> None:
        try:
            details = {
                "description": descripcion,
                "device_serial": self._get_device_serial(),
                "extraction_method": "adb_pull",
            }
            if detalles_extra:
                details.update(detalles_extra)

            final_dir = register_evidence(
                workspace=self.workspace,
                operator_id=self.operator_id,
                artifact_path=archivo,
                artifact_type=tipo,
                details=details,
            )
            self.console.print(
                f"[bold green][+] Evidencia firmada en custodia: {final_dir.name}[/bold green]")
        except Exception as e:
            self.console.print(
                f"[bold red][!] ERROR FORENSE: El archivo se extrajo pero no pudo firmarse: {e}[/bold red]")

    def extraer_whatsapp(self, save_path: str | Path) -> Path | None:
        self.console.print(
            "[cyan][*] Localizando base de datos de WhatsApp...[/cyan]")

        save_path = Path(save_path)
        save_path.mkdir(parents=True, exist_ok=True)

        remote_path = "/data/data/com.whatsapp/databases/msgstore.db"
        local_file = save_path / "whatsapp_messages.db"

        if local_file.exists():
            self.console.print(
                f"[red][-] El archivo ya existe, evitando sobrescribir evidencia: {local_file}[/red]")
            return None

        cmd_copy = f"su -c 'cp {remote_path} /sdcard/msgstore.db && chmod 777 /sdcard/msgstore.db'"
        subprocess.run([self.adb, "shell", cmd_copy])
        result = subprocess.run(
            [self.adb, "pull", "/sdcard/msgstore.db", str(local_file)]
        )

        if result.returncode == 0 and local_file.exists():
            self.console.print(
                f"[green][+] WhatsApp DB extraída: {local_file}[/green]")
            subprocess.run([self.adb, "shell", "rm /sdcard/msgstore.db"])

            self.console.print(
                "[cyan][*] Registrando en cadena de custodia...[/cyan]")
            self._registrar_archivo_forense(
                archivo=local_file,
                tipo="whatsapp_db_plain",
                descripcion="Base de datos de WhatsApp sin cifrar extraída vía ADB",
                detalles_extra={"source_path": remote_path},
            )
            self._registrar_log(f"WhatsApp DB extraída: {local_file.name}")

            return local_file
        else:
            self.console.print(
                "[red][-] No se pudo acceder a WhatsApp DB (¿Falta Root?)[/red]")
            return None

    def extraer_whatsapp_key(self, save_path: str | Path) -> Path | None:
        self.console.print(
            "[cyan][*] Accediendo al Enclave de llaves WhatsApp...[/cyan]")

        save_path = Path(save_path)
        save_path.mkdir(parents=True, exist_ok=True)

        remote_key_path = "/data/data/com.whatsapp/files/key"
        local_key_file = save_path / "whatsapp.key"

        if local_key_file.exists():
            self.console.print(
                f"[red][-] El archivo ya existe, evitando sobrescribir evidencia: {local_key_file}[/red]")
            return None

        cmd = f"su -c 'cp {remote_key_path} /sdcard/key_export && chmod 777 /sdcard/key_export'"
        subprocess.run([self.adb, "shell", cmd])

        result = subprocess.run(
            [self.adb, "pull", "/sdcard/key_export", str(local_key_file)]
        )

        if result.returncode == 0 and local_key_file.exists():
            self.console.print(
                f"[green][+] LLAVE EXTRAÍDA: {local_key_file}[/green]")
            subprocess.run([self.adb, "shell", "rm /sdcard/key_export"])

            self.console.print(
                "[cyan][*] Registrando llave en cadena de custodia...[/cyan]")
            self._registrar_archivo_forense(
                archivo=local_key_file,
                tipo="whatsapp_key_raw",
                descripcion="Llave de cifrado de WhatsApp (158 bytes)",
                detalles_extra={"source_path": remote_key_path},
            )
            self._registrar_log(
                f"WhatsApp Key extraída: {local_key_file.name}")

            return local_key_file
        else:
            self.console.print(
                "[red][-] FALLO: No se pudo obtener la llave (se requiere Root).[/red]")
            return None

    def extraer_historial_chrome(self, save_path: str | Path) -> None:
        self.console.print(
            "[yellow][!] Extracción de historial de Chrome aún no implementada.[/yellow]")
        pass
