import folium
import requests
import webbrowser
import os


class GeomapSentinel:
    def __init__(self):
        self.lat, self.lon = self.obtener_ubicacion_ip()
        self.mapa_path = "mapa_sentinel.html"

    def obtener_ubicacion_ip(self):
        try:
            # Consultamos un servicio de geolocalización gratuito
            response = requests.get('https://ipapi.co/json/')
            data = response.json()
            return data.get('latitude', 0), data.get('longitude', 0)
        except:
            return 0, 0  # Ubicación por defecto si falla el internet

    def generar_mapa(self, targets):
        # Creamos el mapa con un estilo oscuro tipo "Pentest"
        m = folium.Map(
            location=[self.lat, self.lon],
            zoom_start=18,
            tiles="CartoDB dark_matter"
        )

        # Marcador de tu posición
        folium.Marker(
            [self.lat, self.lon],
            popup="APEX SENTINEL (YOU)",
            icon=folium.Icon(color="red", icon="screenshot")
        ).add_to(m)

        # Dibujamos cada objetivo detectado por el radar
        for mac, data in targets.items():
            # Estimación táctica: calculamos un pequeño desvío basado en el RSSI
            # Cuanto más débil la señal (ej -80), más lejos ponemos el punto
            offset = (abs(data['rssi']) - 30) * 0.00001
            t_lat = self.lat + (offset * data['angle'] / 10)
            t_lon = self.lon + (offset * data['angle'] / 10)

            folium.CircleMarker(
                location=[t_lat, t_lon],
                radius=8,
                popup=f"MAC: {mac}<br>Vendor: {data['vendor']}<br>RSSI: {data['rssi']}",
                color="#00FF00" if data['vendor'] != "Desconocido" else "yellow",
                fill=True,
                fill_opacity=0.6
            ).add_to(m)

        m.save(self.mapa_path)

    def abrir_mapa(self):
        # Abre el mapa automáticamente en el navegador
        url = "file://" + os.path.realpath(self.mapa_path)
        webbrowser.open(url)
