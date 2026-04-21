from scapy.all import ARP, Ether, srp

class NetworkModule:
    # Este _init_ es el que recibe el 'self' que envías desde Main
    def __init__(self, sentinel):
        self.sentinel = sentinel

    def escanear_red(self):
        print(f"\n[{self.sentinel.nombre}] Iniciando escaneo de red...")
        rango = "192.168.1.1/24"
        solicitud = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=rango)
        try:
            anuncios = srp(solicitud, timeout=2, verbose=False)[0]
            print(f"{'IP':<15} | {'MAC':<20}")
            for _, recibido in anuncios:
                print(f"{recibido.psrc:<15} | {recibido.hwsrc:<20}")
        except:
            print("[!] Error: ¿Tienes permisos de Administrador?")