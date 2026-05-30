from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.rule import Rule
from rich import box

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

NVD_BASE_URL    = "https://services.nvd.nist.gov/rest/json/cves/2.0"
REQUEST_TIMEOUT = 10
MAX_RESULTS     = 10
RATE_LIMIT_WAIT = 30        # segundos de espera al recibir HTTP 403
USER_AGENT      = "AnubisOS-CVEMatcher/3.0"

CVSS_PRIORITY = ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2")

SEVERITY_STYLE: dict[str, str] = {
    "CRITICAL": "bold red",
    "HIGH":     "red",
    "MEDIUM":   "yellow",
    "LOW":      "cyan",
    "NONE":     "dim",
}

SEVERITY_BADGE: dict[str, str] = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🔵",
    "NONE":     "⚪",
}

SEVERITY_RANK: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH":     3,
    "MEDIUM":   2,
    "LOW":      1,
    "NONE":     0,
}

# ---------------------------------------------------------------------------
# Modelo de datos
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CVERecord:
    id:          str
    description: str
    score:       float | None
    severity:    str
    vector:      str
    published:   str
    references:  tuple[str, ...] = field(default_factory=tuple)

    @property
    def sort_key(self) -> tuple[int, float]:
        return (SEVERITY_RANK.get(self.severity, 0), self.score or 0.0)

    @property
    def is_critical(self) -> bool:
        return self.severity == "CRITICAL"

    @property
    def is_high(self) -> bool:
        return self.severity == "HIGH"

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _build_session() -> requests.Session:
    retry = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist={500, 502, 503, 504},
        allowed_methods={"GET"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers["User-Agent"] = USER_AGENT
    return session

# ---------------------------------------------------------------------------
# Parser NVD
# ---------------------------------------------------------------------------

def _parse_metrics(metrics: dict) -> tuple[float | None, str, str]:
    for key in CVSS_PRIORITY:
        entries = metrics.get(key, [])
        if not entries:
            continue
        entry     = entries[0]
        cvss_data = entry.get("cvssData", {})
        score     = cvss_data.get("baseScore")
        severity  = (
            cvss_data.get("baseSeverity") or entry.get("baseSeverity", "NONE")
        ).upper()
        vector    = cvss_data.get("vectorString", "—")
        return score, severity, vector
    return None, "NONE", "—"

def _truncate(text: str, limit: int = 200) -> str:
    return text[:limit] + "..." if len(text) > limit else text

def _parse_nvd_response(data: dict) -> list[CVERecord]:
    records: list[CVERecord] = []

    for item in data.get("vulnerabilities", []):
        cve_data = item.get("cve", {})

        cve_id = cve_data.get("id", "—")

        descriptions = cve_data.get("descriptions", [])
        description  = next(
            (d["value"] for d in descriptions if d.get("lang") == "en"),
            "No description available.",
        )

        score, severity, vector = _parse_metrics(cve_data.get("metrics", {}))

        references = tuple(
            r["url"] for r in cve_data.get("references", [])[:3]
        )
        published = cve_data.get("published", "")[:10]

        records.append(CVERecord(
            id          = cve_id,
            description = _truncate(description),
            score       = score,
            severity    = severity,
            vector      = vector,
            published   = published,
            references  = references,
        ))

    return records

# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class CVEMatcher:

    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.console: Console = sentinel.console
        self.gp               = getattr(sentinel, "gp", None)
        self._session         = _build_session()

    # -----------------------------------------------------------------------
    # API pública
    # -----------------------------------------------------------------------

    def analyze_service(self, service: str, version: str = "") -> list[CVERecord]:
        query = f"{service} {version}".strip()

        self.console.print(f"\n[bold cyan]CVE Matcher → {query}[/bold cyan]")
        self.console.print(Rule(style="dim cyan"))

        records = self._fetch_nvd(query)

        if not records:
            self.console.print(f"[dim]No CVEs found for '{query}'.[/dim]")
            return []

        self._render_cve_table(records, query)
        self._register_findings(records, query)
        return records

    def analyze_scan_results(self, services: list[dict]) -> dict[str, list[CVERecord]]:
        if not services:
            self.console.print("[yellow][!] No services to analyze.[/yellow]")
            return {}

        self.console.print(Panel(
            f"[cyan]Analyzing {len(services)} services against CVE database...[/cyan]",
            border_style="cyan",
        ))

        results: dict[str, list[CVERecord]] = {}

        for srv in services:
            name    = srv.get("nombre") or srv.get("service", "")
            version = srv.get("version", "")
            if not name:
                continue
            key     = f"{name} {version}".strip()
            records = self._fetch_nvd(key)
            if records:
                results[key] = records

        self._render_scan_summary(results)
        return results

    def interactive_search(self) -> None:
        self.console.print()
        query = self.console.input(
            "[bold cyan][?] Search CVE (e.g. 'apache 2.4', 'openssh'): [/bold cyan]"
        ).strip()
        if query:
            self.analyze_service(query)

    # -----------------------------------------------------------------------
    # Llamada a la API NVD
    # -----------------------------------------------------------------------

    def _fetch_nvd(self, query: str) -> list[CVERecord]:
        params = {
            "keywordSearch":  query,
            "resultsPerPage": MAX_RESULTS,
            "startIndex":     0,
        }
        try:
            response = self._session.get(
                NVD_BASE_URL,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                return _parse_nvd_response(response.json())

            if response.status_code == 403:
                self.console.print(
                    f"[yellow][!] NVD rate limit hit. Waiting {RATE_LIMIT_WAIT}s...[/yellow]"
                )
                time.sleep(RATE_LIMIT_WAIT)
                return self._fetch_nvd(query)

            self.console.print(
                f"[red][!] NVD API returned HTTP {response.status_code}.[/red]"
            )

        except requests.Timeout:
            self.console.print(
                f"[red][!] NVD request timed out after {REQUEST_TIMEOUT}s.[/red]"
            )
        except requests.ConnectionError as exc:
            self.console.print(f"[red][!] Connection error: {exc}[/red]")
            log.debug("NVD connection error", exc_info=exc)
        except Exception as exc:
            self.console.print(f"[red][!] Unexpected error querying NVD: {exc}[/red]")
            log.exception("Unexpected NVD error")

        return []

    # -----------------------------------------------------------------------
    # Registro en el proyecto (GestorProyecto)
    # -----------------------------------------------------------------------

    def _register_findings(self, records: list[CVERecord], query: str) -> None:
        if not self.gp:
            return

        for rec in records:
            if rec.is_critical or rec.is_high:
                level = "CRITICO" if rec.is_critical else "ALTO"
                self.gp.registrar_hallazgo(
                    level,
                    f"CVE: {rec.id} en {query}",
                    rec.description,
                    f"https://nvd.nist.gov/vuln/detail/{rec.id}",
                )

        self.gp.registrar_evidencia(
            "cve_match",
            f"CVEs found for {query}: {len(records)}",
            {
                "query":    query,
                "total":    len(records),
                "critical": sum(1 for r in records if r.is_critical),
            },
        )

    # -----------------------------------------------------------------------
    # Renderizado
    # -----------------------------------------------------------------------

    def _render_cve_table(self, records: list[CVERecord], query: str) -> None:
        critical_count = sum(1 for r in records if r.is_critical)
        high_count     = sum(1 for r in records if r.is_high)

        title = (
            f"CVEs for '{query}' — "
            f"[red]{critical_count} critical[/red]  "
            f"[orange1]{high_count} high[/orange1]  "
            f"[dim]total: {len(records)}[/dim]"
        )

        table = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold red",
            show_edge=False,
            expand=True,
        )
        table.add_column("CVE ID",      style="cyan",  width=18, no_wrap=True)
        table.add_column("Score",        width=7,       justify="center")
        table.add_column("Severity",     width=12,      justify="center")
        table.add_column("Published",    style="dim",   width=12, justify="center")
        table.add_column("Description",  style="white")

        for rec in sorted(records, key=lambda r: r.sort_key, reverse=True):
            style   = SEVERITY_STYLE.get(rec.severity, "white")
            badge   = SEVERITY_BADGE.get(rec.severity, "⚪")
            score_f = (
                f"[{style}]{rec.score}[/{style}]"
                if rec.score is not None
                else "[dim]—[/dim]"
            )
            sev_f = f"[{style}]{badge} {rec.severity}[/{style}]"

            table.add_row(rec.id, score_f, sev_f, rec.published, rec.description)

        self.console.print(Panel(table, title=title, border_style="red"))
        self._render_top_references(records)

    def _render_top_references(self, records: list[CVERecord]) -> None:
        if not records:
            return
        top = max(records, key=lambda r: r.score or 0.0)
        if not top.references:
            return
        self.console.print(f"\n[dim]References for {top.id}:[/dim]")
        for url in top.references:
            self.console.print(f"  [dim]→[/dim] [blue]{url}[/blue]")

    def _render_scan_summary(self, results: dict[str, list[CVERecord]]) -> None:
        if not results:
            self.console.print("[green][+] No known CVEs found.[/green]")
            return

        table = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            show_edge=False,
            expand=True,
        )
        table.add_column("Service",    style="cyan",  min_width=20)
        table.add_column("CVEs",       width=6,       justify="center")
        table.add_column("Critical",   width=9,       justify="center")
        table.add_column("High",       width=7,       justify="center")
        table.add_column("Max Score",  width=10,      justify="center")

        for service, records in results.items():
            critical_count = sum(1 for r in records if r.is_critical)
            high_count     = sum(1 for r in records if r.is_high)
            max_score      = max((r.score or 0.0 for r in records), default=0.0)

            table.add_row(
                service,
                str(len(records)),
                f"[red]{critical_count}[/red]"    if critical_count else "[dim]0[/dim]",
                f"[orange1]{high_count}[/orange1]" if high_count     else "[dim]0[/dim]",
                _score_cell(max_score),
            )

        self.console.print(Panel(
            table,
            title="CVE SUMMARY BY SERVICE",
            border_style="red",
        ))

# ---------------------------------------------------------------------------
# Utilidades de formato
# ---------------------------------------------------------------------------

def _score_cell(score: float) -> str:
    if score >= 7.0:
        return f"[red]{score}[/red]"
    if score >= 4.0:
        return f"[yellow]{score}[/yellow]"
    return f"[dim]{score}[/dim]"