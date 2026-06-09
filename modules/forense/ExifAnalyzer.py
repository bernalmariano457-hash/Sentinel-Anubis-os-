from __future__ import annotations

from datetime import datetime

import piexif
from rich.panel import Panel


class ExifAnalyzer:

    def __init__(self, main_app):
        self.main_app = main_app

    # Internos

    def _to_decimal(self, coords, ref: str) -> float:
        d = coords[0][0] / coords[0][1]
        m = coords[1][0] / coords[1][1]
        s = coords[2][0] / coords[2][1]
        decimal = d + (m / 60.0) + (s / 3600.0)
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal

    def obtener_coordenadas(self, gps_info: dict) -> tuple[float, float] | None:
        try:
            lat = self._to_decimal(
                gps_info[piexif.GPSIFD.GPSLatitude],
                gps_info[piexif.GPSIFD.GPSLatitudeRef].decode(),
            )
            lon = self._to_decimal(
                gps_info[piexif.GPSIFD.GPSLongitude],
                gps_info[piexif.GPSIFD.GPSLongitudeRef].decode(),
            )
            return lat, lon
        except (KeyError, ZeroDivisionError, AttributeError, piexif.InvalidImageDataError):
            return None

    # API pública

    def analizar_foto(self, ruta: str) -> None:
        try:
            exif_data = piexif.load(ruta)
        except (FileNotFoundError, piexif.InvalidImageDataError, ValueError) as e:
            self.main_app.console.print(
                f"[bold red][!] No se pudo leer EXIF de '{ruta}': {e}[/bold red]"
            )
            return

        zeroth = exif_data.get("0th", {})

        make = zeroth.get(piexif.ImageIFD.Make, b"Desconocido").decode(
            errors="replace").strip()
        model = zeroth.get(piexif.ImageIFD.Model, b"Desconocido").decode(
            errors="replace").strip()
        software = zeroth.get(piexif.ImageIFD.Software,
                              b"N/A").decode(errors="replace").strip()
        date_str = zeroth.get(
            piexif.ImageIFD.DateTime, b"0000:00:00 00:00:00"
        ).decode(errors="replace")

        gps_info = exif_data.get("GPS")
        coordenadas = self.obtener_coordenadas(gps_info) if gps_info else None

        resumen = (
            f"[bold cyan]📱 DISPOSITIVO:[/bold cyan] {make} {model}\n"
            f"[bold cyan]⚙️  SOFTWARE:[/bold cyan]   {software}\n"
            f"[bold cyan]📅 FECHA/HORA:[/bold cyan]  {date_str}\n"
            f"{'─' * 40}\n"
        )

        if coordenadas:
            lat, lon = coordenadas
            url_maps = f"https://www.google.com/maps?q={lat},{lon}"
            resumen += (
                f"[bold green]📍 UBICACIÓN GPS:[/bold green]\n"
                f"Latitud:  {lat}\n"
                f"Longitud: {lon}\n"
                f"[bold yellow]🔗 GOOGLE MAPS:[/bold yellow] {url_maps}"
            )
        else:
            resumen += "[bold red][!] Sin datos GPS en los metadatos.[/bold red]"

        self.main_app.console.print(
            Panel(resumen, title="🔍 ANÁLISIS FORENSE DE IMAGEN",
                  border_style="magenta")
        )
