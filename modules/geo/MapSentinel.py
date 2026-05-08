import folium
from flask import Flask, render_template_string
import threading


class MapSentinel:
    def __init__(self, lat_inicial=0, lon_inicial=0):
        self.lat = lat_inicial
        self.lon = lon_inicial
        self.targets = {}  # MAC: {lat, lon, vendor, rssi}

    def actualizar_mapa(self):
        # Creamos el mapa centrado en tu posición
        m = folium.Map(location=[self.lat, self.lon],
                       zoom_start=19, tiles="CartoDB dark_matter")

        # Marcador de tu posición (El Sentinel)
        folium.Marker([self.lat, self.lon], popup="SENTINEL", icon=folium.Icon(
            color="red", icon="info-sign")).add_to(m)

        # Añadimos los dispositivos detectados
        for mac, data in self.targets.items():
            # Estimamos la posición basada en el RSSI (esto es una aproximación táctica)
            # Factor de conversión simple
            distancia_aprox = abs(data['rssi']) / 100000
            t_lat = self.lat + (distancia_aprox * data['offset_n'])
            t_lon = self.lon + (distancia_aprox * data['offset_e'])

            folium.CircleMarker(
                location=[t_lat, t_lon],
                radius=10,
                popup=f"{data['vendor']} ({data['rssi']}dBm)",
                color="cyan",
                fill=True
            ).add_to(m)

        m.save("mapa_sentinel.html")
