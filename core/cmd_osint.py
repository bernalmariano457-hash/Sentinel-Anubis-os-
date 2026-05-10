from __future__ import annotations

from core.commands._base import _DomainBase
from core.validators import Validador


class OsintCommands(_DomainBase):

    def locate(self):
        s = self.s
        if not self._modulo_ok("locator"):
            return
        ip = Validador.pedir_ip(self.console, "IP objetivo")
        if ip:
            s.locator.rastrear_ip(ip)
            s.log.info(f"Locate en {ip}", "LocatorModule")

    def locate_p(self):
        s = self.s
        if not self._modulo_ok("adv_scanner") or not self._modulo_ok("geopreciose"):
            return
        redes = s.adv_scanner.obtener_redes_formateadas()
        s.geopreciose.triangular_posicion(redes)

    def geofoto(self):
        if not self._modulo_ok("exif"):
            return
        ruta = (self.console.input("[bold cyan]Ruta de imagen: [/bold cyan]")
                .strip().replace("'", "").replace('"', ""))
        if ruta:
            self.s.exif.analizar_foto(ruta)

    def osint(self):
        if not self._modulo_ok("osint"):
            return
        self.s.osint.menu()

    def cve(self):
        if not self._modulo_ok("cve"):
            return
        self.s.cve.busqueda_libre()
