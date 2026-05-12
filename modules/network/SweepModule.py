from __future__ import annotations

import csv
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn, Progress, SpinnerColumn,
    TaskProgressColumn, TextColumn, TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

# ── Scapy ────────────────────────────────────────────────────────────
try:
    from scapy.all import ARP, Ether, srp
    _SCAPY_OK = True
except ImportError:
    _SCAPY_OK = False

# ── Requests (resolución de fabricante online) ───────────────────────
try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# CONSTANTES
# ════════════════════════════════════════════════════════════════════

_ARP_TIMEOUT_DEFAULT = 3       # segundos de espera ARP
_VENDOR_API_TIMEOUT = 2       # timeout HTTP para macvendors
_VENDOR_API_URL = "https://api.macvendors.com/{}"
_EVIDENCE_DIR = Path("data/evidence/sweep")
_CSV_FIELDS = ["ip", "mac", "fabricante",
               "nivel_riesgo", "descripcion", "timestamp"]


# ════════════════════════════════════════════════════════════════════
# BASE DE DATOS OUI — HARDWARE DE VIGILANCIA / RIESGO
# ════════════════════════════════════════════════════════════════════
#
# Niveles de riesgo:
#   CRÍTICO  — hardware diseñado específicamente para vigilancia
#   ALTO     — frecuentemente usado en dispositivos espía DIY
#   MEDIO    — hardware legítimo con usos duales conocidos
#   INFO     — fabricantes que merecen atención por contexto

OUI_DATABASE: dict[str, dict] = {
    # ── Módulos IoT / Espía conocidos ───────────────────────────────
    "A4:C1:38": {
        "fabricante":  "Tuya Smart",
        "descripcion": "Módulos IoT — usado en cámaras ocultas comerciales",
        "riesgo":      "CRÍTICO",
    },
    "48:8A:D2": {
        "fabricante":  "Shenzhen Generic",
        "descripcion": "Hardware genérico chino — micrófonos y cámaras IP baratas",
        "riesgo":      "CRÍTICO",
    },
    "00:1D:6D": {
        "fabricante":  "OvisLink",
        "descripcion": "Cámaras de vigilancia de bajo perfil",
        "riesgo":      "CRÍTICO",
    },
    "8C:CE:4E": {
        "fabricante":  "Hikvision",
        "descripcion": "Sistemas CCTV/IP — cámaras de vigilancia profesionales",
        "riesgo":      "CRÍTICO",
    },
    "00:23:63": {
        "fabricante":  "Dahua Technology",
        "descripcion": "Cámaras IP y NVR — fabricante CCTV chino",
        "riesgo":      "CRÍTICO",
    },
    "70:85:C2": {
        "fabricante":  "Hanwha Vision (Samsung)",
        "descripcion": "Cámaras IP de seguridad — línea SmartCam",
        "riesgo":      "ALTO",
    },
    # ── Microcontroladores — uso dual ────────────────────────────────
    "24:0A:C4": {
        "fabricante":  "Espressif",
        "descripcion": "ESP32 — frecuente en hardware espía casero / IoT",
        "riesgo":      "ALTO",
    },
    "5C:CF:7F": {
        "fabricante":  "Espressif",
        "descripcion": "ESP8266 — módulos Wi-Fi usados en keyloggers y grabadores",
        "riesgo":      "ALTO",
    },
    "E8:DB:84": {
        "fabricante":  "Espressif",
        "descripcion": "ESP32-S — variante frecuente en hardware de intercepción",
        "riesgo":      "ALTO",
    },
    "A0:20:A6": {
        "fabricante":  "Raspberry Pi Foundation",
        "descripcion": "Raspberry Pi — dispositivo legítimo con usos de pentesting",
        "riesgo":      "MEDIO",
    },
    # ── Grabadores y transmisores ────────────────────────────────────
    "B0:4E:26": {
        "fabricante":  "Sony",
        "descripcion": "Posible cámara/grabador Sony — verificar contexto",
        "riesgo":      "MEDIO",
    },
    "00:1A:C1": {
        "fabricante":  "3Com",
        "descripcion": "Hardware legado — posible punto de transmisión encubierta",
        "riesgo":      "MEDIO",
    },
    # ── Routers con backdoors documentados ──────────────────────────
    "C8:3A:35": {
        "fabricante":  "Tenda",
        "descripcion": "Router Tenda — backdoors documentados en firmware",
        "riesgo":      "ALTO",
    },
    "14:CF:E2": {
        "fabricante":  "TP-Link",
        "descripcion": "TP-Link — verificar firmware / CVEs activos",
        "riesgo":      "INFO",
    },
}

# Colores por nivel de riesgo
_RIESGO_STYLE: dict[str, str] = {
    "CRÍTICO": "bold red",
    "ALTO":    "red",
    "MEDIO":   "yellow",
    "INFO":    "cyan",
    "LIMPIO":  "green",
}


# ════════════════════════════════════════════════════════════════════
# TIPOS DE DATOS
# ════════════════════════════════════════════════════════════════════

@dataclass
class Dispositivo:
    ip:           str
    mac:          str
    fabricante:   str = "Desconocido"
    descripcion:  str = "—"
    nivel_riesgo: str = "LIMPIO"
    timestamp:    str = field(
        default_factory=lambda: datetime.now().isoformat())

    @property
    def es_amenaza(self) -> bool:
        return self.nivel_riesgo in ("CRÍTICO", "ALTO")

    @property
    def oui(self) -> str:
        """Primeros 3 octetos de la MAC (OUI)."""
        return self.mac[:8].upper()

    @property
    def riesgo_style(self) -> str:
        return _RIESGO_STYLE.get(self.nivel_riesgo, "white")


@dataclass
class ResultadoSweep:
    rango:       str
    total:       int
    amenazas:    int
    dispositivos: list[Dispositivo]
    duracion_s:  float
    timestamp:   str = field(
        default_factory=lambda: datetime.now().isoformat())

    @property
    def perimetro_limpio(self) -> bool:
        return self.amenazas == 0


# ════════════════════════════════════════════════════════════════════
# MÓDULO SWEEP
# ════════════════════════════════════════════════════════════════════

class SweepModule:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.console: Console = getattr(sentinel, "console", Console())
        self._log_s = getattr(sentinel, "log", None)
        self._vendor_cache: dict[str, str] = {}

    # ── API pública ──────────────────────────────────────────────────

    def escanear_perimetro(
        self,
        ip_rango:  str = "192.168.1.0/24",
        timeout:   int = _ARP_TIMEOUT_DEFAULT,
        exportar:  bool = False,
        resolver:  bool = False,
    ) -> Optional[ResultadoSweep]:
        if not _SCAPY_OK:
            self.console.print(
                "[red][!] Scapy no disponible.[/red]\n"
                "[dim]    pip install scapy[/dim]"
            )
            return None

        self._cabecera(ip_rango)
        t_inicio = time.time()

        # ── Envío ARP ────────────────────────────────────────────────
        hosts_raw = self._arp_scan(ip_rango, timeout)
        if hosts_raw is None:
            return None

        # ── Clasificación ────────────────────────────────────────────
        dispositivos = self._clasificar(hosts_raw, resolver)

        duracion = time.time() - t_inicio
        amenazas = sum(1 for d in dispositivos if d.es_amenaza)

        resultado = ResultadoSweep(
            rango=ip_rango,
            total=len(dispositivos),
            amenazas=amenazas,
            dispositivos=dispositivos,
            duracion_s=duracion,
        )

        # ── Render ───────────────────────────────────────────────────
        self._renderizar(resultado)

        # ── Exportar evidencia ───────────────────────────────────────
        if exportar:
            csv_path = self._exportar_csv(resultado)
            if csv_path:
                self.console.print(
                    f"[dim][+] Evidencia exportada → {csv_path}[/dim]"
                )

        # ── Registrar en Sentinel ────────────────────────────────────
        self._registrar(resultado)

        log.info(
            f"Sweep {ip_rango}: {resultado.total} hosts, "
            f"{amenazas} amenazas, {duracion:.1f}s"
        )
        return resultado

    # ── ARP ──────────────────────────────────────────────────────────

    def _arp_scan(
        self, ip_rango: str, timeout: int
    ) -> Optional[list[dict]]:
        paquete = Ether(dst="ff:ff:ff:ff:ff:ff") / ARP(pdst=ip_rango)

        with Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[cyan]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as prog:
            prog.add_task(f"Enviando ARP broadcast → {ip_rango}...")
            try:
                answered, _ = srp(paquete, timeout=timeout, verbose=0)
            except PermissionError:
                self.console.print(
                    "[red][!] Permisos insuficientes para enviar ARP raw.\n"
                    "    Ejecuta como root (Linux) o administrador (Windows).[/red]"
                )
                return None
            except OSError as e:
                self.console.print(f"[red][!] Error de red: {e}[/red]")
                log.error(f"ARP scan OSError: {e}")
                return None

        return [
            {"ip": r.psrc, "mac": r.hwsrc.upper()}
            for _, r in answered
        ]

    # ── Clasificación OUI ─────────────────────────────────────────────

    def _clasificar(
        self, hosts: list[dict], resolver: bool
    ) -> list[Dispositivo]:
        dispositivos: list[Dispositivo] = []

        for h in hosts:
            mac = h["mac"].upper()
            oui = mac[:8]
            info = OUI_DATABASE.get(oui)

            if info:
                dev = Dispositivo(
                    ip=h["ip"],
                    mac=mac,
                    fabricante=info["fabricante"],
                    descripcion=info["descripcion"],
                    nivel_riesgo=info["riesgo"],
                )
            else:
                fabricante = "Desconocido"
                if resolver:
                    fabricante = self._resolver_fabricante(mac)
                dev = Dispositivo(
                    ip=h["ip"],
                    mac=mac,
                    fabricante=fabricante,
                    nivel_riesgo="LIMPIO",
                )

            dispositivos.append(dev)
            log.debug(
                f"{mac} ({h['ip']}) → {dev.nivel_riesgo} [{dev.fabricante}]")

        return dispositivos

    # ── Resolución online de fabricante ──────────────────────────────

    def _resolver_fabricante(self, mac: str) -> str:
        oui = mac[:8]
        if oui in self._vendor_cache:
            return self._vendor_cache[oui]

        if not _REQUESTS_OK:
            return "Desconocido"

        try:
            r = _requests.get(
                _VENDOR_API_URL.format(mac),
                timeout=_VENDOR_API_TIMEOUT,
            )
            if r.status_code == 200:
                nombre = r.text.strip()
                self._vendor_cache[oui] = nombre
                return nombre
        except Exception:
            pass

        self._vendor_cache[oui] = "Desconocido"
        return "Desconocido"

    # ── Exportación CSV ───────────────────────────────────────────────

    def _exportar_csv(self, resultado: ResultadoSweep) -> Optional[Path]:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = _EVIDENCE_DIR / f"sweep_{ts}.csv"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
                writer.writeheader()
                for d in resultado.dispositivos:
                    writer.writerow({
                        "ip":           d.ip,
                        "mac":          d.mac,
                        "fabricante":   d.fabricante,
                        "nivel_riesgo": d.nivel_riesgo,
                        "descripcion":  d.descripcion,
                        "timestamp":    d.timestamp,
                    })
            return out
        except OSError as e:
            log.error(f"Error exportando CSV: {e}")
            return None

    # ── Registro en Sentinel ──────────────────────────────────────────

    def _registrar(self, resultado: ResultadoSweep) -> None:
        reportes = getattr(self.sentinel, "reportes", None)
        if not reportes:
            return

        for d in resultado.dispositivos:
            if d.es_amenaza:
                try:
                    reportes.registrar_evento(
                        "TSCM-ALERT",
                        f"{d.nivel_riesgo}: {d.mac} ({d.fabricante}) "
                        f"en {d.ip} — {d.descripcion}",
                    )
                except Exception as e:
                    log.warning(f"Error registrando evento: {e}")

        if resultado.perimetro_limpio:
            try:
                reportes.registrar_evento(
                    "TSCM-OK",
                    f"Perímetro limpio: {resultado.total} hosts en {resultado.rango}",
                )
            except Exception as e:
                log.warning(f"Error registrando evento OK: {e}")

    # ── Rich UI ───────────────────────────────────────────────────────

    def _cabecera(self, ip_rango: str) -> None:
        self.console.print(Panel(
            f"[cyan]Rango:[/cyan]    {ip_rango}\n"
            f"[cyan]Protocolo:[/cyan] ARP Broadcast\n"
            f"[cyan]Modo:[/cyan]     TSCM — Búsqueda de hardware de vigilancia",
            title="[bold cyan]BARRIDO DE PERÍMETRO[/bold cyan]",
            border_style="cyan",
            box=box.HEAVY_HEAD,
        ))

    def _renderizar(self, r: ResultadoSweep) -> None:
        # ── Tabla de dispositivos ────────────────────────────────────
        tb = Table(
            box=box.HEAVY_HEAD,
            header_style="bold cyan",
            show_edge=True,
            expand=True,
        )
        tb.add_column("IP",          style="cyan",  min_width=15, no_wrap=True)
        tb.add_column("MAC",         style="white", min_width=17, no_wrap=True)
        tb.add_column("Fabricante",  style="white", min_width=20)
        tb.add_column("Riesgo",      justify="center", min_width=9)
        tb.add_column("Descripción", style="dim",   min_width=30)

        for d in sorted(
            r.dispositivos,
            key=lambda x: ["CRÍTICO", "ALTO", "MEDIO",
                           "INFO", "LIMPIO"].index(x.nivel_riesgo)
        ):
            riesgo_txt = Text(d.nivel_riesgo, style=d.riesgo_style)
            tb.add_row(
                d.ip,
                d.mac,
                d.fabricante,
                riesgo_txt,
                d.descripcion,
            )

        self.console.print(Panel(
            tb,
            title=f"[bold cyan]DISPOSITIVOS DETECTADOS [{r.total}][/bold cyan]",
            border_style="cyan",
            box=box.HEAVY_HEAD,
        ))

        # ── Resumen ──────────────────────────────────────────────────
        g = Table.grid(padding=(0, 3))
        g.add_column(style="dim cyan", justify="right", min_width=20)
        g.add_column(style="white")

        g.add_row("Rango escaneado",  r.rango)
        g.add_row("Hosts activos",    str(r.total))
        g.add_row("Duración",         f"{r.duracion_s:.1f}s")

        if r.perimetro_limpio:
            g.add_row(
                "Estado",
                "[bold green]✓ PERÍMETRO LIMPIO — Sin hardware de vigilancia[/bold green]",
            )
        else:
            g.add_row(
                "Amenazas",
                f"[bold red]⚠ {r.amenazas} dispositivo(s) de riesgo detectado(s)[/bold red]",
            )

        border = "green" if r.perimetro_limpio else "red"
        titulo = (
            "[bold green]RESULTADO — LIMPIO[/bold green]"
            if r.perimetro_limpio
            else "[bold red]RESULTADO — AMENAZAS DETECTADAS[/bold red]"
        )

        self.console.print(Panel(
            g,
            title=titulo,
            border_style=border,
            box=box.HEAVY_HEAD,
        ))
