from __future__ import annotations

import subprocess
import os


class DatabaseExtractor:
    def __init__(self, adb_path: str = "adb") -> None:
        self.adb = adb_path
        from rich.console import Console
        self.console = Console()

    def extraer_whatsapp(self, save_path):
        self.console.print(
            "[cyan][*] Localizando base de datos de WhatsApp...[/cyan]")
        remote_path = "/data/data/com.whatsapp/databases/msgstore.db"
        local_file = os.path.join(save_path, "whatsapp_messages.db")

        cmd_copy = f"su -c 'cp {remote_path} /sdcard/msgstore.db && chmod 777 /sdcard/msgstore.db'"
        subprocess.run([self.adb, "shell", cmd_copy])
        result = subprocess.run(
            [self.adb, "pull", "/sdcard/msgstore.db", local_file])

        if result.returncode == 0:
            self.console.print(
                f"[green][+] WhatsApp DB extraída: {local_file}[/green]")
            subprocess.run([self.adb, "shell", "rm /sdcard/msgstore.db"])
        else:
            self.console.print(
                "[red][-] No se pudo acceder a WhatsApp DB (¿Falta Root?)[/red]")

    def extraer_whatsapp_key(self, save_path):
        self.console.print(
            "[cyan][*] Accediendo al Enclave de llaves WhatsApp...[/cyan]")
        remote_key_path = "/data/data/com.whatsapp/files/key"
        local_key_file = os.path.join(save_path, "whatsapp.key")

        cmd = f"su -c 'cp {remote_key_path} /sdcard/key_export && chmod 777 /sdcard/key_export'"
        subprocess.run([self.adb, "shell", cmd])

        result = subprocess.run(
            [self.adb, "pull", "/sdcard/key_export", local_key_file])

        if result.returncode == 0:
            self.console.print(
                f"[green][+] LLAVE EXTRAÍDA: {local_key_file}[/green]")
            subprocess.run([self.adb, "shell", "rm /sdcard/key_export"])
            return local_key_file
        else:
            self.console.print(
                "[red][-] FALLO: No se pudo obtener la llave (se requiere Root).[/red]")
            return None

    def extraer_historial_chrome(self, save_path):
        pass
