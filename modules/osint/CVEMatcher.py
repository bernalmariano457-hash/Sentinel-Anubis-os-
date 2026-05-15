from __future__ import annotations

import re
import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.rule import Rule
from rich import box

console = Console()
TIMEOUT = 8
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"


SEVERIDAD_COLOR = {
    "CRITICAL": "bold red",
    "HIGH":     "red",
    "MEDIUM":   "yellow",
    "LOW":      "cyan",
    "NONE":     "dim",
}

SEVERIDAD_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🔵",
    "NONE":     "⚪",
}


class CVEMatcher:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.console = sentinel.console
        self.gp = getattr(sentinel, "gp", None)
        self._sesion = requests.Session()
        self._sesion.headers.update({
            "User-Agent": "AnubisOS-CVEMatcher/2.1"
        })

    # ------------------------------------------------------------------
    # API PÚBLICA
    # ------------------------------------------------------------------

    def analizar_servicio(self, servicio: str, version: str = ""):
        query = f"{servicio} {version}".strip()
        self.console.print(
            f"\n[bold cyan]CVE Matcher → {query}[/bold cyan]"
        )
        self.console.print(Rule(style="dim cyan"))

        cves = self._buscar_nvd(query)
        if not cves:
            self.console.print(
                f"[dim]No se encontraron CVEs para '{query}'.[/dim]"
            )
            return []

        self._mostrar_cves(cves, query)

        # Registrar hallazgos críticos en el proyecto
        if self.gp:
            for cve in cves:
                sev = cve.get("severidad", "NONE")
                if sev in ("CRITICAL", "HIGH"):
                    self.gp.registrar_hallazgo(
                        "ALTO" if sev == "HIGH" else "CRITICO",
                        f"CVE: {cve['id']} en {query}",
                        cve.get("descripcion", "Sin descripción"),
                        f"Ver: https://nvd.nist.gov/vuln/detail/{cve['id']}"
                    )
            self.gp.registrar_evidencia(
                "cve_match",
                f"CVEs encontrados para {query}: {len(cves)}",
                {"query": query, "total": len(cves),
                 "criticos": sum(1 for c in cves if c.get("severidad") == "CRITICAL")}
            )

        return cves

    def analizar_resultado_scan(self, servicios: list[dict]):
        if not servicios:
            self.console.print(
                "[yellow][!] No hay servicios para analizar.[/yellow]")
            return

        self.console.print(Panel(
            f"[cyan]Analizando {len(servicios)} servicios contra base de datos CVE...[/cyan]",
            border_style="cyan"
        ))

        todos_cves = {}
        for srv in servicios:
            nombre = srv.get("nombre", srv.get("service", ""))
            version = srv.get("version", "")
            if nombre:
                cves = self._buscar_nvd(f"{nombre} {version}".strip())
                if cves:
                    todos_cves[f"{nombre} {version}".strip()] = cves

        self._mostrar_resumen_scan(todos_cves)
        return todos_cves

    def busqueda_libre(self):
        self.console.print()
        query = self.console.input(
            "[bold cyan][?] Buscar CVE (ej: 'apache 2.4', 'openssh'): [/bold cyan]"
        ).strip()
        if query:
            self.analizar_servicio(query)

    # ------------------------------------------------------------------
    # NVD API
    # ------------------------------------------------------------------

    def _buscar_nvd(self, query: str, max_results: int = 10) -> list[dict]:
        try:
            r = self._sesion.get(
                NVD_URL,
                params={
                    "keywordSearch":  query,
                    "resultsPerPage": max_results,
                    "startIndex":     0,
                },
                timeout=TIMEOUT
            )

            if r.status_code == 200:
                data = r.json()
                return self._parsear_nvd(data)

            elif r.status_code == 403:
                self.console.print(
                    "[yellow][!] NVD API rate limit. Espera 30s e intenta de nuevo.[/yellow]"
                )
            else:
                self.console.print(
                    f"[red][!] NVD API error: HTTP {r.status_code}[/red]"
                )

        except requests.Timeout:
            self.console.print("[red][!] NVD API timeout.[/red]")
        except Exception as e:
            self.console.print(f"[red][!] Error consultando NVD: {e}[/red]")

        return []

    def _parsear_nvd(self, data: dict) -> list[dict]:
        resultados = []
        vulnerabilidades = data.get("vulnerabilities", [])

        for item in vulnerabilidades:
            cve_data = item.get("cve", {})
            cve_id = cve_data.get("id", "—")

            # Descripción en inglés
            descripciones = cve_data.get("descriptions", [])
            descripcion = next(
                (d["value"] for d in descripciones if d.get("lang") == "en"),
                "Sin descripción disponible."
            )

            # CVSS Score y severidad
            score = None
            severidad = "NONE"
            vector = "—"

            metricas = cve_data.get("metrics", {})

            # Intentar CVSS v3.1 primero, luego v3.0, luego v2
            for version_cvss in ["cvssMetricV31", "cvssMetricV30", "cvssMetricV2"]:
                lista = metricas.get(version_cvss, [])
                if lista:
                    cvss_data = lista[0].get("cvssData", {})
                    score = cvss_data.get("baseScore")
                    severidad = cvss_data.get("baseSeverity",
                                              lista[0].get("baseSeverity", "NONE")).upper()
                    vector = cvss_data.get("vectorString", "—")
                    break

            # Referencias
            refs = [
                r["url"] for r in cve_data.get("references", [])[:3]
            ]

            # Fecha de publicación
            publicado = cve_data.get("published", "")[:10]

            resultados.append({
                "id":          cve_id,
                "descripcion": descripcion[:200] + "..." if len(descripcion) > 200 else descripcion,
                "score":       score,
                "severidad":   severidad,
                "vector":      vector,
                "publicado":   publicado,
                "referencias": refs,
            })

        return resultados

    # ------------------------------------------------------------------
    # VISUALIZACIÓN
    # ------------------------------------------------------------------

    def _mostrar_cves(self, cves: list[dict], query: str):
        criticos = sum(1 for c in cves if c["severidad"] == "CRITICAL")
        altos = sum(1 for c in cves if c["severidad"] == "HIGH")

        titulo = (
            f"CVEs para '{query}' — "
            f"[red]{criticos} críticos[/red]  "
            f"[orange1]{altos} altos[/orange1]  "
            f"[dim]total: {len(cves)}[/dim]"
        )

        tabla = Table(box=box.SIMPLE_HEAD, header_style="bold red",
                      show_edge=False, expand=True)
        tabla.add_column("CVE ID",     style="cyan",   width=18, no_wrap=True)
        tabla.add_column("Score",      width=7,        justify="center")
        tabla.add_column("Severidad",  width=10,       justify="center")
        tabla.add_column("Publicado",  style="dim",
                         width=12, justify="center")
        tabla.add_column("Descripción", style="white")

        for c in sorted(cves,
                        key=lambda x: (x["score"] or 0),
                        reverse=True):
            color = SEVERIDAD_COLOR.get(c["severidad"], "white")
            emoji = SEVERIDAD_EMOJI.get(c["severidad"], "⚪")
            score_fmt = (
                f"[{color}]{c['score']}[/{color}]"
                if c["score"] else "[dim]—[/dim]"
            )
            sev_fmt = f"[{color}]{emoji} {c['severidad']}[/{color}]"

            tabla.add_row(
                c["id"], score_fmt, sev_fmt,
                c["publicado"], c["descripcion"]
            )

        self.console.print(Panel(tabla, title=titulo, border_style="red"))

        # Mostrar referencias del más crítico
        if cves:
            top = max(cves, key=lambda x: x["score"] or 0)
            if top["referencias"]:
                self.console.print(
                    f"\n[dim]Referencias para {top['id']}:[/dim]"
                )
                for ref in top["referencias"]:
                    self.console.print(f"  [dim]→[/dim] [blue]{ref}[/blue]")

    def _mostrar_resumen_scan(self, todos_cves: dict):
        if not todos_cves:
            self.console.print(
                "[green][+] No se encontraron CVEs conocidos.[/green]")
            return

        tabla = Table(box=box.SIMPLE_HEAD, header_style="bold cyan",
                      show_edge=False, expand=True)
        tabla.add_column("Servicio",   style="cyan",  min_width=20)
        tabla.add_column("CVEs",       width=6,       justify="center")
        tabla.add_column("Críticos",   width=9,       justify="center")
        tabla.add_column("Altos",      width=7,       justify="center")
        tabla.add_column("Score max",  width=10,      justify="center")

        for srv, cves in todos_cves.items():
            criticos = sum(1 for c in cves if c["severidad"] == "CRITICAL")
            altos = sum(1 for c in cves if c["severidad"] == "HIGH")
            score_max = max((c["score"] or 0 for c in cves), default=0)

            tabla.add_row(
                srv,
                str(len(cves)),
                f"[red]{criticos}[/red]" if criticos else "[dim]0[/dim]",
                f"[orange1]{altos}[/orange1]" if altos else "[dim]0[/dim]",
                f"[red]{score_max}[/red]" if score_max >= 7 else
                f"[yellow]{score_max}[/yellow]" if score_max >= 4 else
                f"[dim]{score_max}[/dim]"
            )

        self.console.print(Panel(tabla, title="RESUMEN CVE POR SERVICIO",
                                 border_style="red"))
