import os
import time
import requests
from cryptography.fernet import Fernet


class StealthModule:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.archivos_sensibles = [
            "config.json",
            "sentinel_activity.log",
            "capturas.pcap",
            "reportes.txt"
        ]
        self.llave_panico = "panic.key"

    def verificar_identidad(self):
        """Verifica la IP pública y determina si el operador está protegido."""
        print("\n[*] Verificando máscara de identidad digital...")

        try:
            # Consultamos los detalles de la conexión actual
            url = "http://ip-api.com/json/?fields=status,country,city,isp,query,as"
            response = requests.get(url, timeout=5)
            data = response.json()

            if data['status'] == 'success':
                ip_publica = data['query']
                proveedor = data['isp']

                print(
                    f"[+] IP Pública detectada: \033[1;37m{ip_publica}\033[0m")
                print(f"[+] Proveedor (ISP): {proveedor}")
                print(
                    f"[+] Ubicación reportada: {data['city']}, {data['country']}")

                # Lógica de detección de protección (VPN/Proxy/Tor)
                # Buscamos palabras clave comunes en proveedores de seguridad
                seguro = any(x in proveedor.upper() for x in [
                             "VPN", "PROXY", "DATACENTER", "CLOUDFLARE", "HOSTING"])

                if seguro:
                    print(
                        "\033[1;32m[ESTADO: PROTEGIDO] - Túnel de red detectado.\033[0m")
                else:
                    print(
                        "\033[1;31m[ESTADO: EXPUESTO] - Operando desde red doméstica real.\033[0m")

                # Registrar el estado en el ReportManager
                self.sentinel.reportes.registrar_evento(
                    "STEALTH-INIT",
                    f"Sesión iniciada desde {ip_publica} ({proveedor})"
                )
            else:
                print("[-] Error: El satélite de identidad no responde.")

        except Exception as e:
            print(f"[-] Error de conexión (Posible falta de internet): {e}")

    def generar_llave(self):
        """Genera una llave de un solo uso para bloquear todo."""
        llave = Fernet.generate_key()
        with open(self.llave_panico, "wb") as f:
            f.write(llave)
        return Fernet(llave)

    def cifrar_archivos(self, f):
        """Cifra el contenido de los archivos críticos con la llave generada."""
        for archivo in self.archivos_sensibles:
            if os.path.exists(archivo):
                try:
                    with open(archivo, "rb") as target:
                        datos = target.read()
                    with open(archivo, "wb") as target:
                        target.write(f.encrypt(datos))
                    print(f"  [+] {archivo} bloqueado y cifrado.")
                except Exception as e:
                    print(f"  [-] Error asegurando {archivo}: {e}")

    def limpiar_historial(self):
        """Borra el historial de bash en Linux (Raspberry Pi/Debian)."""
        try:
            os.system("history -c")
            os.system("cat /dev/null > ~/.bash_history")
            print("  [+] Historial de terminal purgado.")
        except Exception:
            print("  [-] No se pudo limpiar el historial (¿Estás en Windows?)")

    def activar_panico(self):
        """Ejecuta la secuencia de autodestrucción lógica."""
        print("\n[!!!] INICIANDO PROTOCOLO DE PÁNICO [!!!]")
        time.sleep(0.5)

        print("[*] Generando cifrado de emergencia...")
        f = self.generar_llave()

        print("[*] Asegurando datos tácticos...")
        self.cifrar_archivos(f)

        print("[*] Eliminando huellas del sistema...")
        self.limpiar_historial()

        print("\n[!!!] RASTROS ELIMINADOS. CERRANDO APEX SENTINEL [!!!]")
        # Fuerza el cierre inmediato del programa en Python
        os._exit(0)
