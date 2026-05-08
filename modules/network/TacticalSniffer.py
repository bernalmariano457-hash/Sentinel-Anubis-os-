from scapy.all import sniff, IP, TCP, UDP, Raw
import time


class TacticalSniffer:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.sniffing = False

    def procesar_paquete(self, paquete):
        """Analiza cada paquete capturado en tiempo real."""
        if paquete.haslayer(IP):
            ip_src = paquete[IP].src
            ip_dst = paquete[IP].dst

            # Filtro para tráfico con datos (Raw)
            if paquete.haslayer(Raw):
                payload = paquete[Raw].load.decode(errors='ignore')

                # Buscamos palabras clave interesantes
                keywords = ["user", "pass", "login", "v1/geolocate", "http"]
                for key in keywords:
                    if key in payload.lower():
                        print(
                            f"\n\033[1;33m[!] DATA DETECTADA [{ip_src} -> {ip_dst}]:\033[0m")
                        # Mostramos solo el inicio por seguridad
                        print(f"    {payload[:100]}...")
                        self.sentinel.reportes.registrar_evento(
                            "SNIFFER", f"Captura de datos de {ip_src}")

    def iniciar_captura(self, interface=None, filtro="", duracion=30):
        """Arranca el bucle de escucha."""
        self.sniffing = True
        print(
            f"[*] Iniciando escucha en {interface if interface else 'Default'}...")
        print(f"[*] Filtro aplicado: '{filtro}' | Duración: {duracion}s")

        try:
            sniff(
                iface=interface,
                prn=self.procesar_paquete,
                filter=filtro,
                timeout=duracion,
                store=0  # No guardar en RAM para no saturar el Sentinel
            )
        except Exception as e:
            print(f"[!] Error en Sniffer: {e}")

        self.sniffing = False
        print("\n[*] Sesión de captura finalizada.")
