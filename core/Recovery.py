import os
from cryptography.fernet import Fernet

class SentinelRecovery:
    def __init__(self):
        self.llave_panico = "panic.key"
        self.archivos_sensibles = [
            "config.json", 
            "sentinel_activity.log", 
            "capturas.pcap",
            "reportes.txt"
        ]

    def cargar_llave(self):
        """Busca y carga la llave de pánico."""
        if not os.path.exists(self.llave_panico):
            print(f"[-] Error: No se encontró el archivo '{self.llave_panico}'.")
            print("[-] No se puede revertir el cifrado sin esta llave.")
            return None
        
        with open(self.llave_panico, "rb") as f:
            llave = f.read()
        return Fernet(llave)

    def descifrar_archivos(self, f):
        """Restaura los archivos a su estado original."""
        archivos_restaurados = 0
        for archivo in self.archivos_sensibles:
            if os.path.exists(archivo):
                try:
                    with open(archivo, "rb") as target:
                        datos_cifrados = target.read()
                    
                    datos_descifrados = f.decrypt(datos_cifrados)
                    
                    with open(archivo, "wb") as target:
                        target.write(datos_descifrados)
                    
                    print(f"  [+] {archivo} restaurado con éxito.")
                    archivos_restaurados += 1
                except Exception as e:
                    print(f"  [-] Error al descifrar {archivo}: {e}")
            else:
                print(f"  [?] {archivo} no encontrado. Saltando...")
        
        return archivos_restaurados

    def ejecutar_rescate(self):
        print("\n[+] INICIANDO PROTOCOLO DE RECUPERACIÓN [+]")
        f = self.cargar_llave()
        
        if f:
            print("[*] Llave cargada. Descifrando datos...")
            exito = self.descifrar_archivos(f)
            
            if exito > 0:
                print("\n[!] ARCHIVOS RESTAURADOS. DESTRUYENDO LLAVE DE PÁNICO...")
                # Por seguridad, borramos la llave después de usarla
                os.remove(self.llave_panico)
                print("[+] Sistema de archivos devuelto a la normalidad.")
            else:
                print("\n[-] No se restauró ningún archivo.")

if __name__ == "__main__":
    recovery = SentinelRecovery()
    recovery.ejecutar_rescate()