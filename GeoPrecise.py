import requests
import json


class GeoPrecise:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        # Endpoint de Mozilla (Gratuito para pruebas de auditoría)
        self.url = "https://location.services.mozilla.com/v1/geolocate?key=test"

    def triangular_posicion(self, redes_cercanas):
        """
        Recibe una lista de diccionarios con BSSID y RSSI (potencia).
        Formato: [{'macAddress': '00:11:22...', 'signalStrength': -60}, ...]
        """
        if not redes_cercanas:
            print(
                "\033[1;31m[!] Error: No hay suficientes redes Wi-Fi para triangular.\033[0m")
            return

        payload = {
            "wifiAccessPoints": redes_cercanas
        }

        try:
            print(
                f"[*] Enviando {len(redes_cercanas)} puntos de acceso a la base de datos...")
            response = requests.post(self.url, json=payload, timeout=5)

            if response.status_code == 200:
                data = response.json()
                lat = data['location']['lat']
                lng = data['location']['lng']
                accuracy = data['accuracy']

                print(f"\n\033[1;32m[+] GEOLOCALIZACIÓN COMPLETADA\033[0m")
                print(f" > Latitud:  {lat}")
                print(f" > Longitud: {lng}")
                print(f" > Precisión: {accuracy} metros")
                print(
                    f" > Google Maps: https://www.google.com/maps?q={lat},{lng}")

                # Registrar en logs
                self.sentinel.reportes.registrar_evento(
                    "GEO", f"Triangulación exitosa: {lat}, {lng}")
            else:
                print(f"[-] Error de API: {response.status_code}")

        except Exception as e:
            print(f"\033[1;31m[!] Fallo en el módulo GeoPrecise: {e}\033[0m")
