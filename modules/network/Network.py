from __future__ import annotations

from scapy.all import ARP, Ether, srp

class NetworkModule:
    # Este _init_ es el que recibe el 'self' que envías desde Main
    def __init__(self, sentinel):
        self.sentinel = sentinel

    def escanear_red(self):
        self.sentinel.console.print(f"\n[cyan][*] Iniciando escaneo de red...[/cyan]")
        rango = "192.168.1.1/24"
        solicitud = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=rango)
        try:
            anuncios = srp(solicitud, timeout=2, verbose=False)[0]
            self.sentinel.console.print(f"[bold]  {'IP':<15}   {'MAC':<20}[/bold]")
            for _, recibido in anuncios:
                self.sentinel.console.print(f"  {recibido.psrc:<15}   {recibido.hwsrc:<20}")
        except:
            self.sentinel.console.print("[red][!] Error: ¿Tienes permisos de Administrador?[/red]")