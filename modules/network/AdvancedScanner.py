from __future__ import annotations

import socket
import os
import subprocess
import re
from datetime import datetime


class AdvancedScanner:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.redes_detectadas = []  # Lista para almacenar BSSIDs cercanos
        self.servicios = {
            21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
            53: "DNS", 80: "HTTP", 443: "HTTPS", 3306: "MySQL",
            3389: "RDP", 8080: "HTTP-Proxy"
        }

    def escanear_wifi_perimetro(self):
        self.redes_detectadas = []
        self.sentinel.console.print("[cyan][*] Escaneando espacio radioeléctrico...[/cyan]")

        try:
            if os.name == 'nt':  # Windows
                comando = subprocess.check_output(
                    ['netsh', 'wlan', 'show', 'networks', 'mode=bssid'], encoding='cp850')
                # Extraemos BSSIDs y Señales usando Regex
                bssids = re.findall(
                    r"BSSID\s+\d+\s+:\s+([0-9a-fA-F:]{17})", comando)
                señales = re.findall(r"Señal\s+:\s+(\d+)%", comando)

                for bssid, señal in zip(bssids, señales):
                    # Convertimos porcentaje a dBm aproximado para la API
                    dbm = (int(señal) / 2) - 100
                    self.redes_detectadas.append(
                        {'bssid': bssid, 'signal': dbm})
            else:  # Linux (requiere nmcli o iwlist)
                self.sentinel.console.print("[yellow][!] Escaneo Wi-Fi en Linux requiere nmcli.[/yellow]")

            return self.redes_detectadas
        except Exception as e:
            self.sentinel.console.print(f"[red][!] Error escaneando Wi-Fi: {e}[/red]")
            return []

    def obtener_redes_formateadas(self):
        # Si la lista está vacía, intentamos escanear primero
        if not self.redes_detectadas:
            self.escanear_wifi_perimetro()

        lista_api = []
        for red in self.redes_detectadas:
            lista_api.append({
                "macAddress": red['bssid'],
                "signalStrength": int(red['signal'])
            })
        return lista_api

    def escanear_objetivo(self, ip):
        self.sentinel.console.print(f"\n[cyan][*] Analizando objetivo: {ip}[/cyan]")
        self.sentinel.reportes.registrar_evento(
            "SCANNER", f"Escaneando puertos en {ip}")

        hallazgos = []
        puertos_a_probar = [21, 22, 23, 25, 53, 80, 443, 3306, 3389, 8080]

        for puerto in puertos_a_probar:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            resultado = sock.connect_ex((ip, puerto))

            if resultado == 0:
                servicio = self.servicios.get(puerto, "Desconocido")
                hallazgos.append(
                    {"puerto": puerto, "servicio": servicio, "estado": "ABIERTO"})
                self.sentinel.console.print(f"  [green][+] Puerto {puerto} ({servicio}): ABIERTO[/green]")
            sock.close()

        if hallazgos:
            self.sentinel.reportes.guardar_auditoria(
                f"MAPA DE PUERTOS: {ip}", hallazgos)
        return hallazgos
