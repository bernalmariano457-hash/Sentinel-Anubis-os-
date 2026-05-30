from __future__ import annotations

import logging
import os
import socket
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests
from rich import box
from rich.columns import Columns
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from Main import ApexSentinel

log = logging.getLogger("sentinel.osint")

# Configuración
_TIMEOUT    = int(os.getenv("OSINT_TIMEOUT", "8"))
_MAX_WHOIS  = int(os.getenv("OSINT_WHOIS_FIELDS", "14"))

# Rutas
_EVIDENCE_DIR = Path("data/evidence/osint")

# APIs
_URL_GEO     = (
    "https://ip-api.com/json/{ip}"
    "?fields=status,country,regionName,city,lat,lon,timezone,"
    "isp,org,as,mobile,proxy,hosting"
)
_URL_ASN     = "https://ipinfo.io/{ip}/json"
_URL_WHOIS   = "https://api.whois.vu/?q={dominio}"
_URL_ABUSE   = "https://api.abuseipdb.com/api/v2/check"

# Headers HTTP de interés para fingerprinting
_HEADERS_RELEVANTES: tuple[str, ...] = (
    "Server", "X-Powered-By", "X-Frame-Options",
    "Content-Security-Policy", "Strict-Transport-Security",
    "X-Content-Type-Options", "X-Generator", "Set-Cookie",
)

# CLASE PRINCIPAL

class OSINTEngine:

    def __init__(self, sentinel: ApexSentinel) -> None:
        self._s      = sentinel
        self._con    = sentinel.console
        self._log    = sentinel.log
        self._sesion = self._crear_sesion()
        self._abuse_key: str = os.getenv("ABUSEIPDB_KEY", "")
        _EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    # API pública
    def analizar_ip(self, ip: str) -> dict[str, Any]:
        self._con.print(
            f"\n[bold cyan]OSINT  →  IP:[/bold cyan] "
            f"[bold white]{ip}[/bold white]"
        )
        self._con.print(Rule(style="dim cyan"))
        datos: dict[str, Any] = {"objetivo": ip, "tipo": "ip"}

        with self._con.status("[dim]Consultando geolocalización...[/dim]"):
            geo = self._geo_ip(ip)
        if geo:
            datos["geo"] = geo
            self._mostrar_geo(geo)

        with self._con.status("[dim]Consultando ASN / ISP...[/dim]"):
            asn = self._asn_ip(ip)
        if asn:
            datos["asn"] = asn
            self._mostrar_asn(asn)

        with self._con.status("[dim]Resolución DNS inversa...[/dim]"):
            rdns = self._rdns(ip)
        datos["rdns"] = rdns
        self._con.print(
            Panel(Text(rdns, style="white"),
                  title="[dim cyan]rDNS[/dim cyan]",
                  border_style="dim cyan",
                  expand=False))

        if self._abuse_key:
            with self._con.status("[dim]AbuseIPDB...[/dim]"):
                abuso = self._abuseipdb(ip)
            if abuso:
                datos["abuseipdb"] = abuso
                self._mostrar_abuso(abuso)

        self._registrar_y_exportar("osint_ip", ip, datos)
        return datos

    def analizar_dominio(self, dominio: str) -> dict[str, Any]:
        self._con.print(
            f"\n[bold cyan]OSINT  →  Dominio:[/bold cyan] "
            f"[bold white]{dominio}[/bold white]"
        )
        self._con.print(Rule(style="dim cyan"))
        datos: dict[str, Any] = {"objetivo": dominio, "tipo": "dominio"}

        with self._con.status("[dim]Resolviendo DNS...[/dim]"):
            dns = self._resolver_dns(dominio)
        datos["dns"] = dns
        self._mostrar_dns(dominio, dns)

        with self._con.status("[dim]Consultando WHOIS...[/dim]"):
            whois = self._whois(dominio)
        if whois:
            datos["whois"] = whois
            self._mostrar_whois(whois)

        with self._con.status("[dim]Analizando headers HTTP...[/dim]"):
            headers = self._headers_http(dominio)
        if headers:
            datos["headers"] = headers
            self._mostrar_headers(headers)

        self._registrar_y_exportar("osint_dominio", dominio, datos)
        return datos

    def menu(self) -> None:
        self._con.print()
        self._con.print(Panel(
            "[bold cyan]OSINT ENGINE[/bold cyan]\n"
            "[dim]Reconocimiento pasivo — solo APIs públicas[/dim]\n\n"
            "[green]1[/green]  Analizar IP\n"
            "[green]2[/green]  Analizar dominio\n"
            "[green]3[/green]  IP + dominio del mismo objetivo",
            border_style="cyan",
            expand=False,
        ))

        opcion = Prompt.ask("[bold cyan][?] Opción[/bold cyan]",
                            choices=["1", "2", "3"], default="1")

        if opcion == "1":
            ip = Prompt.ask("[bold cyan][?] IP a analizar[/bold cyan]").strip()
            if ip:
                self.analizar_ip(ip)

        elif opcion == "2":
            dominio = Prompt.ask(
                "[bold cyan][?] Dominio (ej: ejemplo.com)[/bold cyan]"
            ).strip()
            if dominio:
                self.analizar_dominio(dominio)

        elif opcion == "3":
            objetivo = Prompt.ask(
                "[bold cyan][?] Dominio o IP[/bold cyan]"
            ).strip()
            if not objetivo:
                return
            try:
                ip = socket.gethostbyname(objetivo)
                self.analizar_ip(ip)
            except OSError as exc:
                log.debug("Resolución DNS de %s falló: %s", objetivo, exc)
            self.analizar_dominio(objetivo)

    # IP Intelligence
    def _geo_ip(self, ip: str) -> dict[str, Any] | None:
        try:
            r = self._sesion.get(_URL_GEO.format(ip=ip), timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "success":
                return data
            log.warning("ip-api.com: status != success para %s", ip)
        except requests.Timeout:
            log.warning("ip-api.com: timeout para %s", ip)
        except requests.RequestException as exc:
            log.warning("ip-api.com: error — %s", exc)
        return None

    def _asn_ip(self, ip: str) -> dict[str, Any] | None:
        try:
            r = self._sesion.get(_URL_ASN.format(ip=ip), timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.Timeout:
            log.warning("ipinfo.io: timeout para %s", ip)
        except requests.RequestException as exc:
            log.warning("ipinfo.io: error — %s", exc)
        return None

    def _rdns(self, ip: str) -> str:
        try:
            return socket.gethostbyaddr(ip)[0]
        except OSError:
            return "Sin registro rDNS"

    def _abuseipdb(self, ip: str) -> dict[str, Any] | None:
        if not self._abuse_key:
            return None
        try:
            r = self._sesion.get(
                _URL_ABUSE,
                params={"ipAddress": ip, "maxAgeInDays": 90},
                headers={"Key": self._abuse_key, "Accept": "application/json"},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            return r.json().get("data")
        except requests.Timeout:
            log.warning("AbuseIPDB: timeout para %s", ip)
        except requests.RequestException as exc:
            log.warning("AbuseIPDB: error — %s", exc)
        return None

    # Domain Intelligence
    def _resolver_dns(self, dominio: str) -> dict[str, Any]:
        resultado: dict[str, Any] = {}
        try:
            _, _, ips = socket.gethostbyname_ex(dominio)
            resultado["A"] = ips
        except OSError as exc:
            log.debug("DNS A de %s: %s", dominio, exc)
            resultado["A"] = []

        # MX — intento con dnspython si disponible
        try:
            import dns.resolver  # noqa: PLC0415
            mx = [str(r.exchange).rstrip(".") for r in
                  dns.resolver.resolve(dominio, "MX")]
            resultado["MX"] = mx
        except Exception:
            pass

        return resultado

    def _whois(self, dominio: str) -> dict[str, Any] | None:
        # Intentar python-whois primero (más fiable)
        try:
            import whois  # noqa: PLC0415
            w = whois.whois(dominio)
            if w:
                return {k: str(v) for k, v in w.items()
                        if v and k not in ("status",)}
        except Exception:
            pass

        # Fallback: API pública
        try:
            r = self._sesion.get(
                _URL_WHOIS.format(dominio=dominio), timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.Timeout:
            log.warning("WHOIS API: timeout para %s", dominio)
        except requests.RequestException as exc:
            log.warning("WHOIS API: error — %s", exc)
        return None

    def _headers_http(self, dominio: str) -> dict[str, str] | None:
        for url in (f"https://{dominio}", f"http://{dominio}"):
            try:
                verify = not url.startswith("http://")
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    r = self._sesion.get(
                        url, timeout=_TIMEOUT, verify=verify,
                        allow_redirects=True)
                log.debug("Headers HTTP de %s: HTTP %d", url, r.status_code)
                return dict(r.headers)
            except requests.Timeout:
                log.debug("Headers HTTP: timeout para %s", url)
            except requests.RequestException as exc:
                log.debug("Headers HTTP: %s — %s", url, exc)
        return None

    # Display
    def _mostrar_geo(self, geo: dict[str, Any]) -> None:
        tb = self._tabla_kv()
        campos: list[tuple[str, str]] = [
            ("País",         geo.get("country", "—")),
            ("Región",       geo.get("regionName", "—")),
            ("Ciudad",       geo.get("city", "—")),
            ("Coordenadas",  f"{geo.get('lat', '?')}, {geo.get('lon', '?')}"),
            ("Zona horaria", geo.get("timezone", "—")),
            ("ISP",          geo.get("isp", "—")),
            ("Organización", geo.get("org", "—")),
            ("ASN",          geo.get("as", "—")),
            ("Proxy/VPN",    "[red]SÍ[/red]"   if geo.get("proxy")   else "[green]NO[/green]"),
            ("Hosting/DC",   "[yellow]SÍ[/yellow]" if geo.get("hosting") else "NO"),
            ("Red móvil",    "SÍ" if geo.get("mobile") else "NO"),
        ]
        for k, v in campos:
            tb.add_row(k, v)
        self._con.print(Panel(tb, title="[cyan]GEOLOCALIZACIÓN[/cyan]",
                              border_style="cyan"))

    def _mostrar_asn(self, asn: dict[str, Any]) -> None:
        tb = self._tabla_kv()
        for k, v in asn.items():
            if k not in ("ip", "readme") and v:
                tb.add_row(k.capitalize(), str(v)[:80])
        self._con.print(Panel(tb, title="[dim cyan]ASN / ORGANIZACIÓN[/dim cyan]",
                              border_style="dim cyan"))

    def _mostrar_abuso(self, abuso: dict[str, Any]) -> None:
        score = int(abuso.get("abuseConfidenceScore", 0))
        color = "red" if score >= 50 else ("yellow" if score >= 10 else "green")
        tb    = self._tabla_kv()
        tb.add_row("Score de abuso",   f"[{color}]{score}%[/{color}]")
        tb.add_row("Total reportes",   str(abuso.get("totalReports", 0)))
        tb.add_row("Último reporte",   str(abuso.get("lastReportedAt", "—")))
        tb.add_row("Categorías",
                   ", ".join(str(c) for c in abuso.get("reports", [])[:3]) or "—")
        self._con.print(Panel(tb, title="[red]ABUSEIPDB[/red]",
                              border_style="red"))

    def _mostrar_dns(self, dominio: str, dns: dict[str, Any]) -> None:
        tb = self._tabla_kv()
        for tipo, valores in dns.items():
            for v in (valores if isinstance(valores, list) else [valores]):
                tb.add_row(tipo, str(v))
        self._con.print(Panel(tb, title=f"[cyan]DNS — {dominio}[/cyan]",
                              border_style="cyan"))

    def _mostrar_whois(self, whois: dict[str, Any]) -> None:
        tb = self._tabla_kv()
        for k, v in list(whois.items())[:_MAX_WHOIS]:
            if v and str(v).strip():
                tb.add_row(str(k), str(v)[:80])
        self._con.print(Panel(tb, title="[dim cyan]WHOIS[/dim cyan]",
                              border_style="dim cyan"))

    def _mostrar_headers(self, headers: dict[str, str]) -> None:
        tb = self._tabla_kv(min_key_width=24)
        for h in _HEADERS_RELEVANTES:
            v = headers.get(h)
            if v:
                tb.add_row(h, str(v)[:90])
        if tb.row_count:
            self._con.print(Panel(tb, title="[dim cyan]HEADERS HTTP[/dim cyan]",
                                  border_style="dim cyan"))

    # Utilidades internas
    def _crear_sesion(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                f"ApexSentinel/{getattr(self._s, 'version', '2.3')} "
                "(security-research; passive-recon)"
            )
        })
        return s

    def _tabla_kv(self, min_key_width: int = 15) -> Table:
        tb = Table(box=box.SIMPLE, show_header=False,
                   show_edge=False, padding=(0, 2))
        tb.add_column(style="dim cyan", justify="right",
                      min_width=min_key_width)
        tb.add_column(style="white")
        return tb

    def _registrar_y_exportar(
        self,
        tipo:     str,
        objetivo: str,
        datos:    dict[str, Any],
    ) -> None:
        # Log en Sentinel
        self._log.info(
            f"OSINT completado — {objetivo} ({tipo})",
            "OSINTEngine",
        )

        # Guardar JSON en evidencias
        from datetime import datetime, UTC
        ts       = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        seguro   = objetivo.replace(".", "_").replace("/", "_")[:40]
        destino  = _EVIDENCE_DIR / f"{tipo}_{seguro}_{ts}.json"

        import json  # importación diferida — solo cuando se necesita
        destino.write_text(
            json.dumps(datos, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        log.info("OSINT exportado: %s", destino)

        # Registrar en proyecto activo
        gp = getattr(self._s, "gp", None)
        if gp and gp.proyecto_activo:
            gp.registrar_evidencia(
                tipo,
                f"OSINT: {objetivo}",
                {"ruta": str(destino), "campos": list(datos.keys())},
            )

        self._con.print(
            f"\n[dim]Evidencia guardada → "
            f"[cyan]{destino}[/cyan][/dim]\n"
        )