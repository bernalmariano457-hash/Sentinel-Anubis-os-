from __future__ import annotations

import os
import time
import json
import subprocess


class ReportManager:
    def __init__(self):
        self.archivo_reportes = "reportes.txt"
        self.archivo_log = "sentinel_activity.log"
        self.limite_mb = 5  # Umbral de 5MB

    def verificar_y_limpiar(self):
        if os.path.exists(self.archivo_reportes):
            tamaño_bytes = os.path.getsize(self.archivo_reportes)
            tamaño_mb = tamaño_bytes / (1024 * 1024)

            if tamaño_mb > self.limite_mb:
                print(
                    f"\n[!] ALERTA: Archivo de reportes excedió {self.limite_mb}MB.")
                self.comprimir_y_rotar()

    def comprimir_y_rotar(self):
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        nombre_zip = f"backup_reportes_{timestamp}.zip"
        password = "Apex_Sentinel_Admin"  # Puedes cambiar esto o pedirlo por config

        print(f"[*] Comprimiendo reportes en {nombre_zip}...")

        # Usamos comando de sistema para cifrado rápido en Linux
        try:
            # zip -P [password] [destino] [origen]
            comando = f"zip -P {password} {nombre_zip} {self.archivo_reportes} {self.archivo_log}"
            subprocess.run(comando, shell=True, check=True,
                           stdout=subprocess.DEVNULL)

            # Si la compresión fue exitosa, vaciamos los archivos originales
            with open(self.archivo_reportes, "w") as f:
                f.write(f"--- NUEVO CICLO: {timestamp} ---\n")
            with open(self.archivo_log, "w") as f:
                f.write(f"--- LOG REINICIADO: {timestamp} ---\n")

            print(f"[+] Limpieza completada. Backup protegido con contraseña.")
            self.registrar_evento(
                "SISTEMA", f"Auto-Limpieza ejecutada. Backup: {nombre_zip}")

        except Exception as e:
            print(f"[-] Error en auto-limpieza: {e}")

    def registrar_evento(self, modulo, mensaje):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{modulo.upper()}] {mensaje}\n"
        with open(self.archivo_log, "a") as f:
            f.write(log_entry)

    def mostrar_historial(self):
        print(f"\n\033[1;34m--- HISTORIAL DE EVENTOS SEGURIDAD ---\033[0m")
        try:
            if os.path.exists(self.archivo_log):
                with open(self.archivo_log, "r") as f:
                    contenido = f.read()
                    if contenido:
                        print(contenido)
                    else:
                        print("[!] El log está vacío.")
            else:
                print("[-] No se encontró el archivo de logs.")
        except Exception as e:
            print(f"[!] Error al leer logs: {e}")
        print(f"\033[1;34m{'-'*40}\033[0m")

    def guardar_auditoria(self, tipo, datos):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.archivo_reportes, "a") as f:
            f.write(f"\n{'='*50}\n")
            f.write(f"AUDITORÍA: {tipo}\n")
            f.write(f"FECHA: {timestamp}\n")
            f.write(f"{'-'*50}\n")

            if isinstance(datos, dict) or isinstance(datos, list):
                f.write(json.dumps(datos, indent=4))
            else:
                f.write(str(datos))

            f.write(f"\n{'='*50}\n")
        print(f"[+] Hallazgos guardados en {self.archivo_reportes}")
