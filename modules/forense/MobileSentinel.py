from __future__ import annotations

import subprocess
import os
import datetime


class MobileSentinel:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.evidence_path = "./data/evidence/mobile/"

    class DatabaseExtractor:

        def __init__(self, adb_path="adb"):
            self.adb = adb_path

    def extraer_whatsapp(self, save_path):
        self.sentinel.console.print("[cyan][*] Localizando base de datos de WhatsApp...[/cyan]")
        # Ruta estándar en Android rooteado
        remote_path = "/data/data/com.whatsapp/databases/msgstore.db"
        local_file = os.path.join(save_path, "whatsapp_messages.db")

        # Comando: Usar 'su' para copiar a un lugar accesible y luego hacer 'pull'
        cmd_copy = f"su -c 'cp {remote_path} /sdcard/msgstore.db && chmod 777 /sdcard/msgstore.db'"
        subprocess.run([self.adb, "shell", cmd_copy])
        result = subprocess.run(
            [self.adb, "pull", "/sdcard/msgstore.db", local_file])

        if result.returncode == 0:
            self.sentinel.console.print(f"[green][+] WhatsApp DB extraída: {local_file}[/green]")
            # Limpieza en el dispositivo
            subprocess.run([self.adb, "shell", "rm /sdcard/msgstore.db"])
        else:
            self.sentinel.console.print("[red][-] No se pudo acceder a WhatsApp DB (¿Falta Root?)[/red]")

    def extraer_historial_chrome(self, save_path):
        self.sentinel.console.print("[cyan][*] Localizando historial de Chrome...[/cyan]")
        remote_path = "/data/data/com.android.chrome/app_chrome/Default/History"
        local_file = os.path.join(save_path, "chrome_history.db")

        cmd_copy = f"su -c 'cp {remote_path} /sdcard/chrome_history && chmod 777 /sdcard/chrome_history'"
        subprocess.run([self.adb, "shell", cmd_copy])
        subprocess.run(
            [self.adb, "pull", "/sdcard/chrome_history", local_file])
        self.sentinel.console.print("[green][+] Historial de Chrome guardado.[/green]")

    def extraer_sms_system(self, save_path):
        self.sentinel.console.print("[cyan][*] Localizando base de datos de SMS...[/cyan]")
        remote_path = "/data/data/com.android.providers.telephony/databases/mmssms.db"
        local_file = os.path.join(save_path, "system_sms.db")

        cmd_copy = f"su -c 'cp {remote_path} /sdcard/sms.db && chmod 777 /sdcard/sms.db'"
        subprocess.run([self.adb, "shell", cmd_copy])
        subprocess.run([self.adb, "pull", "/sdcard/sms.db", local_file])
        self.sentinel.console.print("[green][+] Base de datos de SMS extraída.[/green]")

    def preparar_directorio(self, dispositivo):
        fecha = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.evidence_path, f"{dispositivo}_{fecha}")
        os.makedirs(path, exist_ok=True)
        return path

    # --- SECCIÓN ANDROID ---
    def triage_android(self):
        self.sentinel.console.print("\n[yellow][!] Intentando conexión con Android vía ADB...[/yellow]")
        # Verificar si hay dispositivos
        check = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True)

        if "device" in check.stdout.split('\n')[1]:
            path = self.preparar_directorio("Android")
            self.sentinel.console.print(f"[green][+] Dispositivo detectado. Triaje en: {path}[/green]")

            # 1. Información del Sistema
            with open(f"{path}/sys_info.txt", "w") as f:
                subprocess.run(["adb", "shell", "getprop"], stdout=f)

            # 2. Lista de aplicaciones instaladas (detectar apps de mensajería cifrada)
            with open(f"{path}/apps_list.txt", "w") as f:
                subprocess.run(["adb", "shell", "pm", "list",
                               "packages", "-f"], stdout=f)

            # 3. Extracción de Logs (Logcat) - Útil para ver actividad reciente
            self.sentinel.console.print("[cyan][*] Capturando Logcat...[/cyan]")
            with open(f"{path}/activity_logs.txt", "w") as f:
                subprocess.run(["adb", "logcat", "-d"], stdout=f)

            self.sentinel.console.print(f"[green][OK] Triaje completado: {path}[/green]")
        else:
            self.sentinel.console.print("[yellow][-] No se detectó Android con Depuración USB.[/yellow]")

    # --- SECCIÓN iOS ---
    def triage_ios(self):
        self.sentinel.console.print("\n[yellow][!] Intentando comunicación con iOS...[/yellow]")
        try:
            # Obtener el UDID del iPhone
            udid_proc = subprocess.run(
                ["idevice_id", "-l"], capture_output=True, text=True)
            udid = udid_proc.stdout.strip()

            if udid:
                path = self.preparar_directorio(f"iPhone_{udid[:8]}")
                self.sentinel.console.print(f"[green][+] iPhone detectado (UDID: {udid}).[/green]")

                # Extraer Info General (Modelo, Versión, Serial)
                with open(f"{path}/iphone_info.xml", "w") as f:
                    subprocess.run(["ideviceinfo", "-x"], stdout=f)

                self.sentinel.console.print(f"[green][OK] Datos guardados en: {path}[/green]")
                self.sentinel.console.print("[dim][i] Para acceso a archivos: 'Confiar' en este equipo.[/dim]")
            else:
                self.sentinel.console.print("[yellow][-] No se detectó iPhone por USB.[/yellow]")
        except Exception as e:
            self.sentinel.console.print(f"[red][!] Error en módulo iOS: {e}[/red]")
