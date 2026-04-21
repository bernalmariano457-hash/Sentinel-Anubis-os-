import sqlite3
from datetime import datetime, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text


class ForensicReader:
    def __init__(self, main_app):
        self.main_app = main_app
        self.console = Console()

    def formatear_fecha_wa(self, timestamp):
        """Timestamp de WhatsApp (iOS/Android)"""
        try:
            if timestamp > 1000000000000:
                ts = timestamp / 1000
            elif timestamp < 500000000:
                ts = timestamp + 978307200
            else:
                ts = timestamp
            return datetime.fromtimestamp(ts).strftime('%H:%M')
        except:
            return "??:??"

    def formatear_fecha_chrome(self, webkit_timestamp):
        """Convierte Microsegundos WebKit (Chrome) a legible"""
        try:
            epoch_start = datetime(1601, 1, 1)
            delta = timedelta(microseconds=webkit_timestamp)
            return (epoch_start + delta).strftime('%d/%m %H:%M')
        except:
            return "Desconocida"

    def leer_whatsapp_mensajes(self, db_path):
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                try:
                    query = "SELECT ZFROMJID, ZTEXT, ZMESSAGEDATE, ZISFROMME FROM ZWAMESSAGE WHERE ZTEXT IS NOT NULL ORDER BY ZMESSAGEDATE DESC LIMIT 15"
                    cursor.execute(query)
                except:
                    query = "SELECT key_remote_jid, data, timestamp, key_from_me FROM messages WHERE data IS NOT NULL ORDER BY timestamp DESC LIMIT 15"
                    cursor.execute(query)

                rows = cursor.fetchall()
                self.console.print(
                    f"\n[bold green]-- REGISTRO DE COMUNICACIONES --[/bold green]")

                for row in reversed(rows):
                    remitente_raw, mensaje, fecha_raw, es_mio = row
                    contacto = str(remitente_raw).split('@')[0]
                    hora = self.formatear_fecha_wa(fecha_raw)

                    if es_mio == 1:
                        p = Panel(Text(f"{mensaje}", style="white"),
                                  title=f"[bold blue]YO [{hora}][/bold blue]", border_style="blue", expand=False)
                        self.console.print(p, justify="right")
                    else:
                        p = Panel(Text(f"{mensaje}", style="white"),
                                  title=f"[bold yellow]{contacto} [{hora}][/bold yellow]", border_style="yellow", expand=False)
                        self.console.print(p, justify="left")
        except Exception as e:
            self.console.print(
                f"[bold red][!] Error en WhatsApp Reader: {e}[/bold red]")

    def leer_historial_chrome(self, db_path):
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT url, title, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 15")
                rows = cursor.fetchall()

                table = Table(
                    title="[bold blue]HISTORIAL DE NAVEGACIÓN (CHROME)[/bold blue]")
                table.add_column("Fecha", style="dim")
                table.add_column("Título", style="yellow")
                table.add_column("URL", style="blue")

                for row in rows:
                    fecha = self.formatear_fecha_chrome(row[2])
                    titulo = (
                        str(row[1])[:40] + "...") if row[1] and len(row[1]) > 40 else str(row[1])
                    url = str(row[0])[:40] + "..."
                    table.add_row(fecha, titulo, url)

                self.console.print(table)
        except Exception as e:
            self.console.print(
                f"[bold red][!] Error en Chrome Reader: {e}[/bold red]")
