from scapy.all import ARP, Ether, srp
import time


class SweepModule:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        # Base de datos OUI (Primeros 3 bloques MAC) de fabricantes de riesgo
        self.lista_negra_oui = {
            "A4:C1:38": "Tuya Smart (Módulos IoT / Cámaras Ocultas)",
            "48:8A:D2": "Shenzhen (Hardware genérico chino / Micrófonos)",
            "24:0A:C4": "Espressif (ESP32 - Frecuente en hardware espía casero)",
            "5C:CF:7F": "Espressif (ESP8266 - Módulos de audio ocultos)",
            "00:1A:C1": "3Com (Posible hardware legado de transmisión)",
            "B0:4E:26": "Sony (Posible lente/cámara IP)",
            "00:1D:6D": "OvisLink (Cámaras de vigilancia de bajo perfil)",
            "8C:CE:4E": "Hikvision (Sistemas de cámaras CCTV/IP)"
        }

    def escanear_perimetro(self, ip_rango="192.168.1.0/24"):
        print(
            "\n[*] Iniciando Protocolo TSCM (Búsqueda de hardware de vigilancia)...")
        print(f"[*] Escaneando espectro local: {ip_rango}\n")

        # Construcción del radar ARP
        arp = ARP(pdst=ip_rango)
        ether = Ether(dst="ff:ff:ff:ff:ff:ff")
        paquete = ether/arp

        try:
            # Enviamos la señal y escuchamos respuestas (timeout de 3 segundos)
            resultado = srp(paquete, timeout=3, verbose=0)[0]
        except Exception as e:
            print(f"[-] Error al inicializar la tarjeta de red: {e}")
            return

        dispositivos = [{'ip': r.psrc, 'mac': r.hwsrc.upper()}
                        for s, r in resultado]
        amenazas_detectadas = 0

        print(
            f"[+] {len(dispositivos)} dispositivos encontrados en el perímetro.")
        print("-" * 50)

        for d in dispositivos:
            mac = d['mac']
            prefix = mac[:8]  # Extraemos el OUI (XX:XX:XX)

            # Cruzamos los datos con nuestra base de datos
            if prefix in self.lista_negra_oui:
                amenazas_detectadas += 1
                print(
                    f"\033[1;31m[!] ADVERTENCIA: Hardware sospechoso detectado!\033[0m")
                print(f"    IP:   {d['ip']}")
                print(f"    MAC:  {mac}")
                print(f"    Tipo: {self.lista_negra_oui[prefix]}")
                print("-" * 50)

                # Registramos el hallazgo en el historial del Sentinel
                self.sentinel.reportes.registrar_evento(
                    "TSCM-ALERT",
                    f"Posible vigilancia: {mac} ({self.lista_negra_oui[prefix]}) en IP {d['ip']}"
                )

        if amenazas_detectadas == 0:
            print(
                "\033[1;32m[+] Perímetro limpio. No se detectó hardware IoT/Espía conocido.\033[0m")
        else:
            print(
                f"\033[1;31m[-] Escaneo finalizado: {amenazas_detectadas} posibles amenazas.\033[0m")
