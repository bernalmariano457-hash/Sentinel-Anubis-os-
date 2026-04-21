import math
import random
import threading
import time
from scapy.all import *
from rich.panel import Panel


class RadarSentinel:
    def __init__(self, interface="wlan0mon"):
        self.interface = interface
        self.targets = {}  # MAC: {'rssi': int, 'angle': float, 'last_seen': float, 'ssid': str}
        self.radius_max = 12  # Tamaño visual
        self.fabricantes = {
            "8C:64:A2": "Apple", "3C:D9:2B": "Apple", "00:17:F2": "Apple",
            "58:CB:52": "Samsung", "90:7A:58": "Samsung",
            "D8:24:BD": "Huawei", "00:E0:FC": "Huawei",
            "64:16:7F": "Intel", "48:51:B7": "Intel",
            "00:0C:29": "VMware", "08:00:27": "VirtualBox",
            "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi 4",
            "E4:5F:01": "Raspberry Pi 5"
        }

    def obtener_fabricante(self, mac):
        prefix = mac.upper()[:8]
        return self.fabricantes.get(prefix, "Desconocido")

    def update_target(self, mac, rssi, ssid):
        fabricante = self.obtener_fabricante(mac)
        if mac not in self.targets:
            self.targets[mac] = {
                'angle': random.uniform(0, 2 * math.pi),
                'ssid': ssid,
                'vendor': fabricante
            }
        self.targets[mac]['rssi'] = rssi
        self.targets[mac]['last_seen'] = time.time()

    def packet_callback(self, pkt):
        # Captura paquetes de radiofrecuencia Wi-Fi
        if pkt.haslayer(Dot11):
            mac = pkt.addr2
            if mac:
                try:
                    # Extraemos la potencia de la señal
                    rssi = pkt.dBm_AntSignal
                except:
                    rssi = -90

                # Identificamos si es un Router o un Celular
                ssid = pkt.info.decode(errors="ignore") if pkt.haslayer(
                    Dot11Elt) and pkt.info else "Dispositivo Oculto"
                self.update_target(mac, rssi, ssid)

    def update_target(self, mac, rssi, ssid):
        if mac not in self.targets:
            # Asignamos un ángulo aleatorio fijo para que el punto no salte por toda la pantalla
            self.targets[mac] = {
                'angle': random.uniform(0, 2 * math.pi),
                'ssid': ssid
            }
        self.targets[mac]['rssi'] = rssi
        self.targets[mac]['last_seen'] = time.time()

    def start_sniffing(self):
        # Hilo secundario para que el escaneo no congele la interfaz
        t = threading.Thread(target=lambda: sniff(
            iface=self.interface, prn=self.packet_callback, store=0))
        t.daemon = True
        t.start()

    def render_radar(self):
        # Limpieza de objetivos viejos (si no se ven en 30 segundos, desaparecen)
        now = time.time()
        self.targets = {m: d for m, d in self.targets.items()
                        if now - d['last_seen'] < 30}

        grid_size = self.radius_max * 2 + 1
        grid = [[" " for _ in range(grid_size)] for _ in range(grid_size)]
        center = self.radius_max

        # Dibujar anillos de radar (estético)
        for r in [4, 8, 12]:
            for a in range(0, 360, 10):
                rad = math.radians(a)
                x = int(center + r * math.cos(rad))
                y = int(center + r * math.sin(rad))
                if 0 <= x < grid_size and 0 <= y < grid_size:
                    grid[y][x] = "."

        # Dibujar tu posición
        grid[center][center] = "[bold cyan]@[/bold cyan]"

        # Dibujar objetivos detectados
        for mac, data in self.targets.items():
            # Mapeamos RSSI (-30 a -90) a distancia (0 a radius_max)
            dist = max(1, min(self.radius_max, (abs(data['rssi']) - 20) // 5))

            x = int(center + dist * math.cos(data['angle']))
            y = int(center + dist * math.sin(data['angle']))

            if 0 <= x < grid_size and 0 <= y < grid_size:
                # Si es una señal fuerte, brilla más
                color = "red" if data['rssi'] > -50 else "yellow"
                grid[y][x] = f"[bold {color}]X[/bold {color}]"

        radar_text = "\n".join([" ".join(row) for row in grid])
        return Panel(radar_text, title="[bold green]RADAR DE INTERCEPCIÓN WI-FI[/bold green]", subtitle=f"[white]Nodos: {len(self.targets)}[/white]")
