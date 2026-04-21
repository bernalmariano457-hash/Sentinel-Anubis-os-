import os
import subprocess


class PhishingModule:
    def __init__(self):
        # Buscamos la ruta de ZPhisher
        self.script_path = os.path.join(
            os.getcwd(), "tools", "zphisher", "zphisher.sh")
        # En Windows, necesitamos indicar dónde está el ejecutable de Bash
        # Normalmente está en esta ruta estándar:
        self.bash_path = r"C:\Program Files\Git\bin\bash.exe"

    def lanzar(self):
        if os.path.exists(self.script_path):
            try:
                # Le decimos a Windows: "Usa Bash para ejecutar este script .sh"
                subprocess.run([self.bash_path, self.script_path], check=True)
            except Exception as e:
                print(f"Error: Asegúrate de tener Git Bash instalado. {e}")
        else:
            print(f"[!] No se encontró ZPhisher en: {self.script_path}")
