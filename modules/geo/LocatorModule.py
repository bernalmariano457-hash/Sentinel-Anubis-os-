from __future__ import annotations

import requests


class LocatorModule:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.api_url = "http://ip-api.com/json/"

    def rastrear_ip(self, ip_objetivo):
        self.sentinel.console.print(f"[cyan][*] Rastreando coordenadas para: {ip_objetivo}...[/cyan]")

        try:
            # Consultamos la API (no requiere registro para nivel básico)
            response = requests.get(f"{self.api_url}{ip_objetivo}")
            data = response.json()

            if data['status'] == 'success':
                self.sentinel.console.print("\n[green][+] LOCALIZACIÓN ENCONTRADA:[/green]")
                self.sentinel.console.print(f"    País:      {data['country']} ({data['countryCode']})")
                self.sentinel.console.print(f"    Región:    {data['regionName']}")
                self.sentinel.console.print(f"    Ciudad:    {data['city']}")
                self.sentinel.console.print(f"    Proveedor: {data['as']}")
                self.sentinel.console.print(f"    Lat/Lon:   {data['lat']}, {data['lon']}")

                # Generamos un link directo a Google Maps
                maps_url = f"https://www.google.com/maps?q={data['lat']},{data['lon']}"
                self.sentinel.console.print(f"    Mapa:      [link={maps_url}]{maps_url}[/link]")

                # Guardar en el reporte del Sentinel
                self.sentinel.reportes.registrar_evento(
                    "GEO-LOC", f"IP {ip_objetivo} ubicada en {data['city']}, {data['country']}")
            else:
                self.sentinel.console.print(f"[yellow][-] No se pudo localizar la IP: {data.get('message', 'Error desconocido')}[/yellow]")

        except Exception as e:
            self.sentinel.console.print(f"[red][-] Error de conexión: {e}[/red]")
