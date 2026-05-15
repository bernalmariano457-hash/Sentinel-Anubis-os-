from __future__ import annotations

import subprocess
import os


class DatabaseExtractor:
    def __init__(self, adb_path="adb"):
        self.adb = adb_path

    # --- TUS MÉTODOS DE EXTRACCIÓN ---

    def extraer_whatsapp(self, save_path):
        print("[*] Localizando base de datos de WhatsApp...")
        remote_path = "/data/data/com.whatsapp/databases/msgstore.db"
        local_file = os.path.join(save_path, "whatsapp_messages.db")

        cmd_copy = f"su -c 'cp {remote_path} /sdcard/msgstore.db && chmod 777 /sdcard/msgstore.db'"
        subprocess.run([self.adb, "shell", cmd_copy])
        result = subprocess.run(
            [self.adb, "pull", "/sdcard/msgstore.db", local_file])

        if result.returncode == 0:
            print(f"[+] WhatsApp DB extraída con éxito en: {local_file}")
            subprocess.run([self.adb, "shell", "rm /sdcard/msgstore.db"])
        else:
            print("[-] Error: No se pudo acceder a la DB de WhatsApp (¿Falta Root?)")

    # AQUÍ ES DONDE VA TU CÓDIGO NUEVO
    def extraer_whatsapp_key(self, save_path):
        print("[*] Intentando acceso al 'Enclave' de llaves de WhatsApp...")
        remote_key_path = "/data/data/com.whatsapp/files/key"
        local_key_file = os.path.join(save_path, "whatsapp.key")

        # Comando táctico: copia y cambio de permisos
        cmd = f"su -c 'cp {remote_key_path} /sdcard/key_export && chmod 777 /sdcard/key_export'"
        subprocess.run([self.adb, "shell", cmd])

        result = subprocess.run(
            [self.adb, "pull", "/sdcard/key_export", local_key_file])

        if result.returncode == 0:
            print(f"\033[1;32m[+] LLAVE EXTRAÍDA: {local_key_file}\033[0m")
            subprocess.run([self.adb, "shell", "rm /sdcard/key_export"])
            return local_key_file
        else:
            print(
                "\033[1;31m[-] FALLO CRÍTICO: No se pudo obtener la llave. Se requiere Root.\033[0m")
            return None

    def extraer_historial_chrome(self, save_path):
        # ... (aquí iría el resto de tus métodos si los usas)
        pass
