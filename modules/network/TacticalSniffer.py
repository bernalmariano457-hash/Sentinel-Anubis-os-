from __future__ import annotations

from scapy.all import sniff, IP, TCP, UDP, Raw
import time


class TacticalSniffer:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.sniffing = False

    def procesar_paquete(self, paquete):
        if paquete.haslayer(IP):
            ip_src = paquete[IP].src
            ip_dst = paquete[IP].dst

            # Filtro para tráfico con datos (Raw)
            if paquete.haslayer(Raw):
                payload = paquete[Raw].load.decode(errors='ignore')

                # Buscamos palabras clave interesantes
                keywords = ["user", "pass", "login", "v1/geolocate", "http"]
                for key in keywords:
                    if key in payload.lower():
                        self.sentinel.console.print(f"\n[yellow][!] DATA DETECTADA [{ip_src} → {ip_dst}]:[/yellow]")
                        # Mostramos solo el inicio por seguridad
                        self.sentinel.console.print(f"    [dim]{payload[:100]}...[/dim]")
                        self.sentinel.reportes.registrar_evento(
                            "SNIFFER", f"Captura de datos de {ip_src}")

    def iniciar_captura(self, interface=None, filtro="", duracion=30):
        self.sniffing = True
        self.sentinel.console.print(f"[cyan][*] Escucha en {interface or 'Default'}...[/cyan]")
        self.sentinel.console.print(f"[dim]Filtro: '{filtro}' | Duración: {duracion}s[/dim]")

        try:
            sniff(
                iface=interface,
                prn=self.procesar_paquete,
                filter=filtro,
                timeout=duracion,
                store=0  # No guardar en RAM para no saturar el Sentinel
            )
        except Exception as e:
            self.sentinel.console.print(f"[red][!] Error en Sniffer: {e}[/red]")

        self.sniffing = False
        self.sentinel.console.print("\n[cyan][*] Sesión de captura finalizada.[/cyan]")
