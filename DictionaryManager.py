import os
from rich.console import Console

console = Console()


class DictionaryManager:
    def __init__(self):
        self.base_path = "/usr/share/wordlists"
        self.dict_map = {
            "ssh": "metasploit/unix_passwords.txt",
            "ftp": "metasploit/ftp_default_pass.txt",
            "http-post-form": "dirbuster/directory-list-2.3-small.txt",
            "http-get": "dirbuster/directory-list-2.3-small.txt",
            "mysql": "metasploit/mysql_default_pass.txt",
            "telnet": "metasploit/mirai_pass.txt",
            "default": "rockyou.txt"
        }

    def obtener_ruta_diccionario(self, protocolo):
        """
        Analiza el protocolo y devuelve la ruta absoluta del mejor diccionario disponible.
        """
        # 1. Buscar la ruta óptima en el mapa, o usar 'default' si es un protocolo desconocido
        sub_ruta = self.dict_map.get(
            protocolo.lower(), self.dict_map["default"])
        full_path = os.path.join(self.base_path, sub_ruta)

        # 2. Verificar si el archivo específico realmente existe en el sistema
        if os.path.exists(full_path):
            return full_path
        else:
            # 3. Fallback (Plan B): Si no está el específico, intentamos con el RockYou genérico
            ruta_rockyou = os.path.join(self.base_path, "rockyou.txt")
            if os.path.exists(ruta_rockyou):
                return ruta_rockyou
            else:
                # 4. Fallback extremo (Plan C): Por si estás probando en una máquina limpia sin wordlists
                console.print(
                    "\n[bold red][!] Advertencia: No se encontraron los diccionarios estándar en /usr/share/wordlists/[/bold red]")
                console.print(
                    "[yellow][!] Utilizando diccionario local 'local_pass.txt' (asegúrate de crearlo en esta carpeta).[/yellow]")
                return "local_pass.txt"
