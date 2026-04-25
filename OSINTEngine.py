import os
import json
import socket
import requests
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.rule import Rule
from rich import box

console = Console()
TIMEOUT = 5


class OSINTEngine:
    """
    Motor de reconocimiento pasivo.
    Usa únicamente APIs públicas y gratuitas.
    """

    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.console = sentinel.console
        self.gp = getattr(sentinel, "gp", None)
        self._sesion = requests.Session()
        self._sesion.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; research-tool)"
        })

    # ------------------------------------------------------------------
    # IP INTELLIGENCE
    # ------------------------------------------------------------------

    def analizar_ip(self, ip: str):
        """Análisis completo de una IP: geolocalización, ASN, reputación."""
        self.console.print(
            f"\n[bold cyan]OSINT → Analizando IP: {ip}[/bold cyan]")
        self.console.print(Rule(style="dim cyan"))

        datos = {}

        # 1. Geolocalización (ip-api.com — gratuito, sin key)
        self.console.print("[dim]  [1/3] Geolocalización...[/dim]")
        geo = self._geo_ip(ip)
        if geo:
            datos["geo"] = geo
            self._mostrar_geo(geo)

        # 2. ASN / Organización (ipinfo.io — gratuito hasta 50k/mes)
        self.console.print("[dim]  [2/3] ASN e ISP...[/dim]")
        asn = self._asn_ip(ip)
        if asn:
            datos["asn"] = asn
            self._mostrar_asn(asn)

        # 3. DNS reverso
        self.console.print("[dim]  [3/3] DNS reverso...[/dim]")
        rdns = self._rdns(ip)
        datos["rdns"] = rdns
        self.console.print(f"  [cyan]rDNS:[/cyan] {rdns}")

        # Registrar en proyecto
        if self.gp:
            self.gp.registrar_evidencia(
                "osint_ip", f"Análisis OSINT de {ip}", datos
            )

        return datos

    def _geo_ip(self, ip: str) -> dict | None:
        try:
            r = self._sesion.get(
                f"http://ip-api.com/json/{ip}"
                f"?fields=status,country,regionName,city,zip,lat,lon,"
                f"timezone,isp,org,as,mobile,proxy,hosting",
                timeout=TIMEOUT
            )
            if r.status_code == 200:
                d = r.json()
                if d.get("status") == "success":
                    return d
        except Exception:
            pass
        return None

    def _asn_ip(self, ip: str) -> dict | None:
        try:
            r = self._sesion.get(
                f"https://ipinfo.io/{ip}/json", timeout=TIMEOUT
            )
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def _rdns(self, ip: str) -> str:
        try:
            return socket.gethostbyaddr(ip)[0]
        except Exception:
            return "Sin registro rDNS"

    def _mostrar_geo(self, geo: dict):
        tabla = Table(box=box.SIMPLE, show_header=False,
                      show_edge=False, padding=(0, 2))
        tabla.add_column(style="dim cyan", justify="right", min_width=15)
        tabla.add_column(style="white")

        campos = [
            ("País",        geo.get("country", "—")),
            ("Región",      geo.get("regionName", "—")),
            ("Ciudad",      geo.get("city", "—")),
            ("Coordenadas", f"{geo.get('lat', '?')}, {geo.get('lon', '?')}"),
            ("Zona horaria", geo.get("timezone", "—")),
            ("ISP",         geo.get("isp", "—")),
            ("Org",         geo.get("org", "—")),
            ("ASN",         geo.get("as", "—")),
            ("Proxy",       "[red]SÍ[/red]" if geo.get("proxy")
             else "[green]NO[/green]"),
            ("Hosting",
             "[yellow]SÍ[/yellow]" if geo.get("hosting") else "NO"),
            ("Móvil",       "SÍ" if geo.get("mobile") else "NO"),
        ]
        for k, v in campos:
            tabla.add_row(k, str(v))

        self.console.print(Panel(tabla, title="GEOLOCALIZACIÓN",
                                 border_style="cyan"))

    def _mostrar_asn(self, asn: dict):
        tabla = Table(box=box.SIMPLE, show_header=False,
                      show_edge=False, padding=(0, 2))
        tabla.add_column(style="dim cyan", justify="right", min_width=15)
        tabla.add_column(style="white")
        for k, v in asn.items():
            if k not in ("ip", "readme"):
                tabla.add_row(k.capitalize(), str(v))
        self.console.print(Panel(tabla, title="ASN / ORGANIZACIÓN",
                                 border_style="dim cyan"))

    # ------------------------------------------------------------------
    # DOMINIO INTELLIGENCE
    # ------------------------------------------------------------------

    def analizar_dominio(self, dominio: str):
        """Reconocimiento de un dominio: WHOIS, DNS, subdominios."""
        self.console.print(
            f"\n[bold cyan]OSINT → Analizando dominio: {dominio}[/bold cyan]"
        )
        self.console.print(Rule(style="dim cyan"))

        datos = {}

        # 1. Resolución DNS básica
        self.console.print("[dim]  [1/3] Registros DNS...[/dim]")
        dns = self._resolver_dns(dominio)
        datos["dns"] = dns
        self._mostrar_dns(dominio, dns)

        # 2. WHOIS vía API pública
        self.console.print("[dim]  [2/3] WHOIS...[/dim]")
        whois = self._whois_api(dominio)
        if whois:
            datos["whois"] = whois
            self._mostrar_whois(whois)

        # 3. Encabezados HTTP
        self.console.print("[dim]  [3/3] Tecnologías web...[/dim]")
        headers = self._headers_http(dominio)
        if headers:
            datos["headers"] = headers
            self._mostrar_headers(headers)

        if self.gp:
            self.gp.registrar_evidencia(
                "osint_dominio", f"Reconocimiento de {dominio}", datos
            )

        return datos

    def _resolver_dns(self, dominio: str) -> dict:
        resultado = {}
        try:
            resultado["A"] = socket.gethostbyname_ex(dominio)[2]
        except Exception:
            resultado["A"] = []
        return resultado

    def _whois_api(self, dominio: str) -> dict | None:
        try:
            r = self._sesion.get(
                f"https://api.whois.vu/?q={dominio}", timeout=TIMEOUT
            )
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return None

    def _headers_http(self, dominio: str) -> dict | None:
        try:
            r = self._sesion.get(
                f"https://{dominio}", timeout=TIMEOUT, verify=False
            )
            return dict(r.headers)
        except Exception:
            try:
                r = self._sesion.get(
                    f"http://{dominio}", timeout=TIMEOUT
                )
                return dict(r.headers)
            except Exception:
                return None

    def _mostrar_dns(self, dominio: str, dns: dict):
        tabla = Table(box=box.SIMPLE, show_header=False,
                      show_edge=False, padding=(0, 2))
        tabla.add_column(style="dim cyan", justify="right", min_width=10)
        tabla.add_column(style="white")
        for tipo, valores in dns.items():
            for v in (valores if isinstance(valores, list) else [valores]):
                tabla.add_row(tipo, str(v))
        self.console.print(Panel(tabla, title=f"DNS — {dominio}",
                                 border_style="cyan"))

    def _mostrar_whois(self, whois: dict):
        tabla = Table(box=box.SIMPLE, show_header=False,
                      show_edge=False, padding=(0, 2))
        tabla.add_column(style="dim cyan", justify="right", min_width=15)
        tabla.add_column(style="white")
        for k, v in list(whois.items())[:10]:
            if v and str(v).strip():
                tabla.add_row(str(k), str(v)[:80])
        self.console.print(Panel(tabla, title="WHOIS",
                                 border_style="dim cyan"))

    def _mostrar_headers(self, headers: dict):
        interesantes = [
            "Server", "X-Powered-By", "X-Frame-Options",
            "Content-Security-Policy", "Strict-Transport-Security",
            "X-Content-Type-Options", "Set-Cookie"
        ]
        tabla = Table(box=box.SIMPLE, show_header=False,
                      show_edge=False, padding=(0, 2))
        tabla.add_column(style="dim cyan", justify="right", min_width=20)
        tabla.add_column(style="white")

        for header in interesantes:
            valor = headers.get(header)
            if valor:
                tabla.add_row(header, str(valor)[:80])

        self.console.print(Panel(tabla, title="HEADERS HTTP",
                                 border_style="dim cyan"))

    # ------------------------------------------------------------------
    # MENÚ INTERACTIVO
    # ------------------------------------------------------------------

    def menu(self):
        """Menú principal del motor OSINT."""
        self.console.print()
        self.console.print(Panel(
            "[bold cyan]OSINT ENGINE[/bold cyan]\n"
            "[dim]Reconocimiento pasivo — solo APIs públicas[/dim]\n\n"
            "[green][1][/green] Analizar IP\n"
            "[green][2][/green] Analizar dominio\n"
            "[green][3][/green] Ambos (IP + dominio del mismo objetivo)",
            border_style="cyan"
        ))

        opcion = self.console.input(
            "[bold cyan][?] Opción: [/bold cyan]"
        ).strip()

        if opcion == "1":
            ip = self.console.input(
                "[bold cyan][?] IP a analizar: [/bold cyan]"
            ).strip()
            if ip:
                self.analizar_ip(ip)

        elif opcion == "2":
            dominio = self.console.input(
                "[bold cyan][?] Dominio (ej: ejemplo.com): [/bold cyan]"
            ).strip()
            if dominio:
                self.analizar_dominio(dominio)

        elif opcion == "3":
            objetivo = self.console.input(
                "[bold cyan][?] Dominio o IP: [/bold cyan]"
            ).strip()
            if objetivo:
                # Resolver IP del dominio primero
                try:
                    ip = socket.gethostbyname(objetivo)
                    self.analizar_ip(ip)
                except Exception:
                    pass
                self.analizar_dominio(objetivo)
        else:
            self.console.print("[red][!] Opción inválida.[/red]")
