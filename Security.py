from cryptography.fernet import Fernet
import os

class SecurityModule:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.llave_ruta = "anubis_master.key"
        self.cargar_llave()

    def cargar_llave(self):
        if not os.path.exists(self.llave_ruta):
            llave = Fernet.generate_key()
            with open(self.llave_ruta, "wb") as f: f.write(llave)
        with open(self.llave_ruta, "rb") as f: self.fernet = Fernet(f.read())

    def encriptar_archivo(self, ruta):
        try:
            with open(ruta, "rb") as f: datos = f.read()
            encriptado = self.fernet.encrypt(datos)
            with open(ruta, "wb") as f: f.write(encriptado)
            return True
        except: return False

    def desencriptar_archivo(self, ruta):
        try:
            with open(ruta, "rb") as f: datos = f.read()
            original = self.fernet.decrypt(datos)
            with open(ruta, "wb") as f: f.write(original)
            return True
        except: return False