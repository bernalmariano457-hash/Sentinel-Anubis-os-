from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from rich.panel import Panel
from rich.table import Table
from rich.console import Console

log = logging.getLogger("sentinel.geoprecise")

# ── Rutas ──────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_RESULTS_DIR = _HERE / "data" / "evidence" / "geo"

# ── Constantes ─────────────────────────────────────────────────────────
_TIMEOUT_SEG = int(os.getenv("GEO_TIMEOUT", 8))
_MIN_REDES = int(os.getenv("GEO_MIN_NETWORKS", 2))   # mínimo para triangular
_CACHE_SEG = int(os.getenv("GEO_CACHE_SECONDS", 30)
                 )  # evitar llamadas duplicadas

# ── Proveedores ────────────────────────────────────────────────────────
_PROVEEDORES = {
    "mozilla": "https://location.services.mozilla.com/v1/geolocate?key=test",
    "google":  "https://www.googleapis.com/geolocation/v1/geolocate?key={key}",
    "ipapi":   "http://ip-api.com/json/",
}


# ══════════════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class PuntoAcceso:
    macAddress:     str
    signalStrength: int          # RSSI en dBm (negativo, ej. -65)
    channel:        int = 0
    signalToNoiseRatio: int = 0

    def validar(self) -> bool:
        mac = self.macAddress.replace(":", "").replace("-", "")
        return (
            len(mac) == 12 and
            all(c in "0123456789abcdefABCDEF" for c in mac) and
            -120 <= self.signalStrength <= 0
        )

    def to_dict(self) -> dict:
        d = {"macAddress": self.macAddress,
             "signalStrength": self.signalStrength}
        if self.channel:
            d["channel"] = self.channel
        if self.signalToNoiseRatio:
            d["signalToNoiseRatio"] = self.signalToNoiseRatio
        return d


@dataclass
class ResultadoGeo:
    latitud:    float
    longitud:   float
    precision:  float            # metros
    proveedor:  str
    timestamp:  str
    redes_usadas: int

    @property
    def maps_url(self) -> str:
        return f"https://www.google.com/maps?q={self.latitud},{self.longitud}"

    @property
    def coords(self) -> tuple[float, float]:
        return (self.latitud, self.longitud)


# ══════════════════════════════════════════════════════════════════════
# MÓDULO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════

class GeoPrecise:
    def __init__(self, sentinel):
        self.sentinel = sentinel
        self.console: Console = getattr(sentinel, "console", Console())
        self._google_key = os.getenv("GOOGLE_GEO_KEY", "")
        self._cache: Optional[tuple[float, ResultadoGeo]
                              ] = None   # (timestamp, resultado)
        _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── API pública ────────────────────────────────────────────────────

    def triangular(
        self,
        redes: list[PuntoAcceso | dict],
        forzar: bool = False,
    ) -> Optional[ResultadoGeo]:
        # Normalizar a PuntoAcceso
        puntos = self._normalizar(redes)

        # Validar cantidad mínima
        if len(puntos) < _MIN_REDES:
            self._warn(
                f"Se necesitan al menos {_MIN_REDES} redes para triangular "
                f"(recibidas: {len(puntos)})."
            )
            return None

        # Filtrar entradas inválidas
        validos = [p for p in puntos if p.validar()]
        descartados = len(puntos) - len(validos)
        if descartados:
            log.warning(
                f"{descartados} punto(s) de acceso descartados por MAC/RSSI inválidos.")

        if len(validos) < _MIN_REDES:
            self._warn("Insuficientes redes válidas tras filtrado.")
            return None

        # Caché
        if not forzar and self._cache:
            ts, resultado = self._cache
            if time.time() - ts < _CACHE_SEG:
                log.debug("Resultado de geolocalización servido desde caché.")
                return resultado

        # Intentar proveedores en orden
        resultado = (
            self._consultar_mozilla(validos) or
            self._consultar_google(validos) or
            self._consultar_ipapi()
        )

        if resultado:
            self._cache = (time.time(), resultado)
            self._registrar_log(resultado, len(validos))

        return resultado

    def mostrar_resultado(self, r: ResultadoGeo) -> None:
        tabla = Table(show_header=False, box=None, padding=(0, 2))
        tabla.add_column(style="dim cyan")
        tabla.add_column(style="bold white")

        tabla.add_row("Latitud",     f"{r.latitud:.7f}°")
        tabla.add_row("Longitud",    f"{r.longitud:.7f}°")
        tabla.add_row("Precisión",   f"± {r.precision:.0f} metros")
        tabla.add_row("Proveedor",   r.proveedor)
        tabla.add_row("Redes usadas", str(r.redes_usadas))
        tabla.add_row("Timestamp",   r.timestamp)
        tabla.add_row("Google Maps", f"[link={r.maps_url}]{r.maps_url}[/link]")

        self.console.print(Panel(
            tabla,
            title="[bold green]✔ GEOLOCALIZACIÓN COMPLETADA[/bold green]",
            border_style="green",
        ))

    def exportar(self, r: ResultadoGeo, ruta: Optional[str] = None) -> Path:

        ts_safe = r.timestamp.replace(":", "-").replace(" ", "_")
        nombre = f"geo_{ts_safe}_{r.proveedor}.json"
        destino = Path(ruta) if ruta else _RESULTS_DIR / nombre

        payload = {
            **asdict(r),
            "maps_url": r.maps_url,
        }
        destino.write_text(json.dumps(payload, indent=4), encoding="utf-8")
        log.info(f"Resultado geo exportado: {destino}")
        return destino

    # ── Proveedores ────────────────────────────────────────────────────

    def _consultar_mozilla(self, puntos: list[PuntoAcceso]) -> Optional[ResultadoGeo]:
        payload = {"wifiAccessPoints": [p.to_dict() for p in puntos]}
        log.debug(f"Consultando Mozilla MLS con {len(puntos)} redes...")
        try:
            resp = requests.post(
                _PROVEEDORES["mozilla"],
                json=payload,
                timeout=_TIMEOUT_SEG,
            )
            if resp.status_code == 200:
                data = resp.json()
                return ResultadoGeo(
                    latitud=data["location"]["lat"],
                    longitud=data["location"]["lng"],
                    precision=data.get("accuracy", 0),
                    proveedor="Mozilla MLS",
                    timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                    redes_usadas=len(puntos),
                )
            log.warning(f"Mozilla MLS respondió {resp.status_code}.")
        except requests.Timeout:
            log.warning("Mozilla MLS: timeout.")
        except requests.RequestException as e:
            log.warning(f"Mozilla MLS: error de red — {e}")
        return None

    def _consultar_google(self, puntos: list[PuntoAcceso]) -> Optional[ResultadoGeo]:
        if not self._google_key:
            return None
        url = _PROVEEDORES["google"].format(key=self._google_key)
        payload = {"wifiAccessPoints": [p.to_dict() for p in puntos]}
        log.debug(f"Consultando Google Geolocation con {len(puntos)} redes...")
        try:
            resp = requests.post(url, json=payload, timeout=_TIMEOUT_SEG)
            if resp.status_code == 200:
                data = resp.json()
                return ResultadoGeo(
                    latitud=data["location"]["lat"],
                    longitud=data["location"]["lng"],
                    precision=data.get("accuracy", 0),
                    proveedor="Google Geolocation",
                    timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                    redes_usadas=len(puntos),
                )
            log.warning(f"Google Geolocation respondió {resp.status_code}.")
        except requests.Timeout:
            log.warning("Google Geolocation: timeout.")
        except requests.RequestException as e:
            log.warning(f"Google Geolocation: error de red — {e}")
        return None

    def _consultar_ipapi(self) -> Optional[ResultadoGeo]:
        log.info("Usando fallback ip-api (geolocalización por IP)...")
        try:
            resp = requests.get(_PROVEEDORES["ipapi"], timeout=_TIMEOUT_SEG)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return ResultadoGeo(
                        latitud=data["lat"],
                        longitud=data["lon"],
                        precision=50_000,   # IP-based ~50km de margen
                        proveedor=f"ip-api (ISP: {data.get('isp', '?')})",
                        timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        redes_usadas=0,
                    )
        except requests.RequestException as e:
            log.error(f"ip-api fallback falló: {e}")
        return None

    # ── Utilidades internas ────────────────────────────────────────────

    def _normalizar(self, redes: list) -> list[PuntoAcceso]:
        resultado = []
        for r in redes:
            if isinstance(r, PuntoAcceso):
                resultado.append(r)
            elif isinstance(r, dict):
                try:
                    resultado.append(PuntoAcceso(
                        macAddress=r.get("macAddress", r.get("bssid", "")),
                        signalStrength=int(
                            r.get("signalStrength", r.get("rssi", -100))),
                        channel=int(r.get("channel", 0)),
                        signalToNoiseRatio=int(r.get("signalToNoiseRatio", 0)),
                    ))
                except (ValueError, TypeError) as e:
                    log.warning(
                        f"Punto de acceso ignorado por datos inválidos: {r} — {e}")
            else:
                log.warning(f"Tipo de entrada desconocido ignorado: {type(r)}")
        return resultado

    def _registrar_log(self, r: ResultadoGeo, n_redes: int) -> None:
        mensaje = (
            f"Triangulación exitosa via {r.proveedor} | "
            f"Coords: {r.latitud:.5f}, {r.longitud:.5f} | "
            f"Precisión: ±{r.precision:.0f}m | "
            f"Redes: {n_redes}"
        )
        try:
            self.sentinel.reportes.registrar_evento("GEO", mensaje)
        except AttributeError:
            log.info(f"[GEO] {mensaje}")

    def _warn(self, msg: str) -> None:
        self.console.print(f"[bold red][!] GeoPrecise: {msg}[/bold red]")
        log.warning(msg)
