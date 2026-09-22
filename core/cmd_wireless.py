from __future__ import annotations

import threading

from core._base import _DomainBase
from core.validators import Validador


class WirelessCommands(_DomainBase):

    def wifi(self) -> None:
        s = self.s
        if not self._modulo_ok("bt"):
            return
        self.console.print("\n[1] Beacon Spam  [2] Deauth Attack")
        opt = self.console.input("[bold cyan] > [/bold cyan]").strip()
        if opt == "1":
            prefijo = self.console.input(
                "[bold cyan]Prefijo SSID: [/bold cyan]").strip()
            s.bt.beacon_spam(prefijo)
        elif opt == "2":
            mac_vic = Validador.pedir(
                self.console, "MAC Víctima", Validador.es_mac,
                "MAC inválida. Ej: AA:BB:CC:DD:EE:FF")
            mac_ap = Validador.pedir(
                self.console, "MAC AP", Validador.es_mac, "MAC inválida.")
            if mac_vic and mac_ap:
                s.bt.deauth(mac_vic, mac_ap)

    def eviltwin(self) -> None:
        s = self.s
        if not self._modulo_ok("wifi_attack"):
            return
        if s._evil_twin_server is None:
            self.console.print("[red][!] EvilTwinServer no disponible.[/red]")
            return
        ssid = self.console.input("[bold cyan] [?] SSID: [/bold cyan]").strip()
        if not ssid:
            return
        s.wifi_attack.crear_gemelo_malvado(ssid, 6)
        threading.Thread(target=s._evil_twin_server, daemon=True).start()
        input("[!] Presiona Enter para detener...")
        s.wifi_attack.detener_ataques()
