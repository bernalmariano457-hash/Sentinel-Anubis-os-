from __future__ import annotations

import piexif
from rich.panel import Panel
from datetime import datetime


class ExifAnalyzer:
    def __init__(self, main_app):
        self.main_app = main_app

    def obtener_coordenadas(self, gps_info):
        try:
            def to_decimal(coords, ref):
                d = coords[0][0] / coords[0][1]
                m = coords[1][0] / coords[1][1]
                s = coords[2][0] / coords[2][1]
                decimal = d + (m / 60.0) + (s / 3600.0)
                if ref in ['S', 'W']:
                    decimal = -decimal
                return decimal

            lat = to_decimal(gps_info[piexif.GPSIFD.GPSLatitude],
                             gps_info[piexif.GPSIFD.GPSLatitudeRef].decode())
            lon = to_decimal(gps_info[piexif.GPSIFD.GPSLongitude],
                             gps_info[piexif.GPSIFD.GPSLongitudeRef].decode())
            return lat, lon
        except:
            return None

    def analizar_foto(self, ruta):
        try:
            exif_data = piexif.load(ruta)

            # 1. Extraer Información del Dispositivo
            make = exif_data.get("0th", {}).get(
                piexif.ImageIFD.Make, b"Desconocido").decode().strip()
            model = exif_data.get("0th", {}).get(
                piexif.ImageIFD.Model, b"Desconocido").decode().strip()
            software = exif_data.get("0th", {}).get(
                piexif.ImageIFD.Software, b"N/A").decode().strip()

            # 2. Extraer Fecha y Hora
            date_str = exif_data.get("0th", {}).get(
                piexif.ImageIFD.DateTime, b"0000:00:00 00:00:00").decode()

            # 3. Extraer Coordenadas
            gps_info = exif_data.get("GPS")
            coordenadas = self.obtener_coordenadas(
                gps_info) if gps_info else None

            # Construir el Panel de Resultados
            resumen = f"[bold cyan]📱 DISPOSITIVO:[/bold cyan] {make} {model}\n"
            resumen += f"[bold cyan]⚙️ SOFTWARE:[/bold cyan] {software}\n"
            resumen += f"[bold cyan]📅 FECHA/HORA:[/bold cyan] {date_str}\n"
            resumen += "----------------------------------------\n"

            if coordenadas:
                lat, lon = coordenadas
                url_maps = f"https://www.google.com/maps?q={lat},{lon}"
                resumen += f"[bold green]📍 UBICACIÓN GPS:[/bold green]\n"
                resumen += f"Latitud: {lat}\nLongitud: {lon}\n"
                resumen += f"[bold yellow]🔗 GOOGLE MAPS:[/bold yellow] {url_maps}"
            else:
                resumen += "[bold red][!] Sin datos GPS en los metadatos.[/bold red]"

            self.main_app.console.print(
                Panel(resumen, title="🔍 ANÁLISIS FORENSE DE IMAGEN", border_style="magenta"))

        except Exception as e:
            self.main_app.console.print(
                f"[bold red][!] Error analizando la imagen: {e}[/bold red]")
