from __future__ import annotations

import requests


class LocatorModule:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.api_url = "http://ip-api.com/json/"

    def rastrear_ip(self, ip_objetivo):
        print(f"[*] Rastreando coordenadas para: {ip_objetivo}...")

        try:
            # Consultamos la API (no requiere registro para nivel básico)
            response = requests.get(f"{self.api_url}{ip_objetivo}")
            data = response.json()

            if data['status'] == 'success':
                print(f"\n[+] LOCALIZACIÓN ENCONTRADA:")
                print(
                    f"    País:      {data['country']} ({data['countryCode']})")
                print(f"    Región:    {data['regionName']}")
                print(f"    Ciudad:    {data['city']}")
                print(f"    Proveedor: {data['as']}")
                print(f"    Lat/Lon:   {data['lat']}, {data['lon']}")

                # Generamos un link directo a Google Maps
                maps_url = f"https://www.google.com/maps?q={data['lat']},{data['lon']}"
                print(f"    Mapa:      {maps_url}")

                # Guardar en el reporte del Sentinel
                self.sentinel.reportes.registrar_evento(
                    "GEO-LOC", f"IP {ip_objetivo} ubicada en {data['city']}, {data['country']}")
            else:
                print(
                    f"[-] No se pudo localizar la IP: {data.get('message', 'Error desconocido')}")

        except Exception as e:
            print(f"[-] Error de conexión con el satélite de rastreo: {e}")
