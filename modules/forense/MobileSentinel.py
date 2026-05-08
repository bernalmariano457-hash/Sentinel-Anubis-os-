# modules/forensics/db_extractor.py
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
        """Intenta extraer la base de datos de mensajes de WhatsApp."""
        print("[*] Localizando base de datos de WhatsApp...")
        # Ruta estándar en Android rooteado
        remote_path = "/data/data/com.whatsapp/databases/msgstore.db"
        local_file = os.path.join(save_path, "whatsapp_messages.db")

        # Comando: Usar 'su' para copiar a un lugar accesible y luego hacer 'pull'
        cmd_copy = f"su -c 'cp {remote_path} /sdcard/msgstore.db && chmod 777 /sdcard/msgstore.db'"
        subprocess.run([self.adb, "shell", cmd_copy])
        result = subprocess.run(
            [self.adb, "pull", "/sdcard/msgstore.db", local_file])

        if result.returncode == 0:
            print(f"[+] WhatsApp DB extraída con éxito en: {local_file}")
            # Limpieza en el dispositivo
            subprocess.run([self.adb, "shell", "rm /sdcard/msgstore.db"])
        else:
            print("[-] Error: No se pudo acceder a la DB de WhatsApp (¿Falta Root?)")

    def extraer_historial_chrome(self, save_path):
        """Extrae el historial de navegación de Google Chrome."""
        print("[*] Localizando historial de Chrome...")
        remote_path = "/data/data/com.android.chrome/app_chrome/Default/History"
        local_file = os.path.join(save_path, "chrome_history.db")

        cmd_copy = f"su -c 'cp {remote_path} /sdcard/chrome_history && chmod 777 /sdcard/chrome_history'"
        subprocess.run([self.adb, "shell", cmd_copy])
        subprocess.run(
            [self.adb, "pull", "/sdcard/chrome_history", local_file])
        print(f"[+] Historial de Chrome guardado.")

    def extraer_sms_system(self, save_path):
        """Extrae la base de datos de SMS nativa del sistema."""
        print("[*] Localizando base de datos de SMS...")
        remote_path = "/data/data/com.android.providers.telephony/databases/mmssms.db"
        local_file = os.path.join(save_path, "system_sms.db")

        cmd_copy = f"su -c 'cp {remote_path} /sdcard/sms.db && chmod 777 /sdcard/sms.db'"
        subprocess.run([self.adb, "shell", cmd_copy])
        subprocess.run([self.adb, "pull", "/sdcard/sms.db", local_file])
        print(f"[+] Base de datos de SMS extraída.")

    def preparar_directorio(self, dispositivo):
        fecha = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.evidence_path, f"{dispositivo}_{fecha}")
        os.makedirs(path, exist_ok=True)
        return path

    # --- SECCIÓN ANDROID ---
    def triage_android(self):
        print("\n[!] Intentando conexión con Android vía ADB...")
        # Verificar si hay dispositivos
        check = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True)

        if "device" in check.stdout.split('\n')[1]:
            path = self.preparar_directorio("Android")
            print(
                f"[+] Dispositivo detectado. Extrayendo triaje inicial en {path}...")

            # 1. Información del Sistema
            with open(f"{path}/sys_info.txt", "w") as f:
                subprocess.run(["adb", "shell", "getprop"], stdout=f)

            # 2. Lista de aplicaciones instaladas (detectar apps de mensajería cifrada)
            with open(f"{path}/apps_list.txt", "w") as f:
                subprocess.run(["adb", "shell", "pm", "list",
                               "packages", "-f"], stdout=f)

            # 3. Extracción de Logs (Logcat) - Útil para ver actividad reciente
            print("[*] Capturando Logcat (eventos recientes)...")
            with open(f"{path}/activity_logs.txt", "w") as f:
                subprocess.run(["adb", "logcat", "-d"], stdout=f)

            print(f"[OK] Triaje completado. Revisa la carpeta {path}")
        else:
            print("[-] No se detectó ningún Android con Depuración USB activa.")

    # --- SECCIÓN iOS ---
    def triage_ios(self):
        print("\n[!] Intentando comunicación con dispositivo iOS...")
        try:
            # Obtener el UDID del iPhone
            udid_proc = subprocess.run(
                ["idevice_id", "-l"], capture_output=True, text=True)
            udid = udid_proc.stdout.strip()

            if udid:
                path = self.preparar_directorio(f"iPhone_{udid[:8]}")
                print(
                    f"[+] iPhone detectado (UDID: {udid}). Extrayendo info básica...")

                # Extraer Info General (Modelo, Versión, Serial)
                with open(f"{path}/iphone_info.xml", "w") as f:
                    subprocess.run(["ideviceinfo", "-x"], stdout=f)

                print(f"[OK] Datos de identificación guardados en {path}")
                print(
                    "[i] Nota: Para acceso a archivos se requiere 'Confiar' en este equipo.")
            else:
                print("[-] No se detectó ningún iPhone conectado por USB.")
        except Exception as e:
            print(f"[!] Error en módulo iOS: {e}")
