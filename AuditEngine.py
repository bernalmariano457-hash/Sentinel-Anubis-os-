import subprocess
from rich.panel import Panel


class AuditEngine:
    def __init__(self, main_app):
        self.main_app = main_app

    # --- FASE 3: DETECCIÓN DE FALLAS (Nmap NSE) ---
    def escaneo_vulnerabilidades(self, target):
        self.main_app.animar_barra(f"Buscando fallas críticas en {target}...")
        # Usamos scripts de vulnerabilidad por defecto de Nmap
        cmd = ["nmap", "-sV", "--script", "vuln", target]
        try:
            process = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300)
            return process.stdout
        except Exception as e:
            return f"Error en escaneo: {e}"

    # --- FASE 4: AUDITORÍA WEB (SQLmap) ---
    def auditoria_sql(self, url):
        self.main_app.animar_barra(f"Analizando inyección SQL en {url}...")
        # --batch para que no pida confirmaciones manuales y fluya en el Sentinel
        cmd = ["sqlmap", "-u", url, "--batch", "--banner"]
        try:
            process = subprocess.run(cmd, capture_output=True, text=True)
            return process.stdout
        except Exception as e:
            return f"Error en SQLmap: {e}"

    # --- FASE 5: CONTROL DE EXPLOITS (MSFRPCD) ---
    def conectar_metasploit(self):
        # Aquí conectaríamos con el demonio de Metasploit vía RPC
        # Por ahora, verificamos si el servicio está activo
        self.main_app.console.print(
            "[bold yellow][*] Sincronizando con Metasploit RPC Daemon...[/bold yellow]")
        # Lógica de conexión API aquí
