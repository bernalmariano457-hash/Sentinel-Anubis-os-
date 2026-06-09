from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class ForensicReader:

    def __init__(self, main_app):
        self.main_app = main_app
        self.console: Console = main_app.console

    # Formateo de timestamps

    def formatear_fecha_wa(self, timestamp: int | float) -> str:
        try:
            if timestamp > 1_000_000_000_000:
                ts = timestamp / 1000
            elif timestamp < 500_000_000:
                ts = timestamp + 978_307_200
            else:
                ts = float(timestamp)
            return datetime.fromtimestamp(ts).strftime("%H:%M")
        except (OSError, OverflowError, ValueError):
            return "??:??"

    def formatear_fecha_chrome(self, webkit_timestamp: int) -> str:
        try:
            epoch_start = datetime(1601, 1, 1)
            delta = timedelta(microseconds=webkit_timestamp)
            return (epoch_start + delta).strftime("%d/%m %H:%M")
        except (OverflowError, ValueError):
            return "Desconocida"

    # Lectores

    def leer_whatsapp_mensajes(self, db_path: str) -> None:
        _QUERY_IOS = (
            "SELECT ZFROMJID, ZTEXT, ZMESSAGEDATE, ZISFROMME "
            "FROM ZWAMESSAGE WHERE ZTEXT IS NOT NULL "
            "ORDER BY ZMESSAGEDATE DESC LIMIT 15"
        )
        _QUERY_ANDROID = (
            "SELECT key_remote_jid, data, timestamp, key_from_me "
            "FROM messages WHERE data IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT 15"
        )

        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute(_QUERY_IOS)
                except sqlite3.OperationalError:
                    cursor.execute(_QUERY_ANDROID)

                rows = cursor.fetchall()
                self.console.print(
                    "\n[bold green]-- REGISTRO DE COMUNICACIONES --[/bold green]")

                for row in reversed(rows):
                    remitente_raw, mensaje, fecha_raw, es_mio = row
                    contacto = str(remitente_raw).split("@")[0]
                    hora = self.formatear_fecha_wa(fecha_raw)

                    if es_mio == 1:
                        panel = Panel(
                            Text(str(mensaje), style="white"),
                            title=f"[bold blue]YO [{hora}][/bold blue]",
                            border_style="blue",
                            expand=False,
                        )
                        self.console.print(panel, justify="right")
                    else:
                        panel = Panel(
                            Text(str(mensaje), style="white"),
                            title=f"[bold yellow]{contacto} [{hora}][/bold yellow]",
                            border_style="yellow",
                            expand=False,
                        )
                        self.console.print(panel, justify="left")

        except sqlite3.Error as e:
            self.console.print(
                f"[bold red][!] Error en WhatsApp Reader: {e}[/bold red]")

    def leer_historial_chrome(self, db_path: str) -> None:
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT url, title, last_visit_time "
                    "FROM urls ORDER BY last_visit_time DESC LIMIT 15"
                )
                rows = cursor.fetchall()

                table = Table(
                    title="[bold blue]HISTORIAL DE NAVEGACIÓN (CHROME)[/bold blue]")
                table.add_column("Fecha", style="dim")
                table.add_column("Título", style="yellow")
                table.add_column("URL", style="blue")

                for url, title, ts in rows:
                    fecha = self.formatear_fecha_chrome(ts)
                    titulo = (
                        str(title)[:40] + "...") if title and len(str(title)) > 40 else str(title)
                    url_corta = str(url)[:40] + "..."
                    table.add_row(fecha, titulo, url_corta)

                self.console.print(table)

        except sqlite3.Error as e:
            self.console.print(
                f"[bold red][!] Error en Chrome Reader: {e}[/bold red]")
