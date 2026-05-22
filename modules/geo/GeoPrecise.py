from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from Main import ApexSentinel

log = logging.getLogger("sentinel.geoprecise")

# ── Rutas ─────────────────────────────────────────────────────────────
_RESULTS_DIR = Path("data/evidence/geo")

# ── Configuración por variables de entorno ────────────────────────────
_TIMEOUT_SEG  = int(os.getenv("GEO_TIMEOUT",        "8"))
_MIN_REDES    = int(os.getenv("GEO_MIN_NETWORKS",    "2"))
_CACHE_SEG    = int(os.getenv("GEO_CACHE_SECONDS",   "30"))

# ── Endpoints de proveedores ──────────────────────────────────────────
_URL_MOZILLA = "https://location.services.mozilla.com/v1/geolocate?key=test"
_URL_GOOGLE  = "https://www.googleapis.com/geolocation/v1/geolocate?key={key}"
_URL_IPAPI   = "http://ip-api.com/json/"


# ══════════════════════════════════════════════════════════════════════
# DATACLASSES
# ══════════════════════════════════════════════════════════════════════

@dataclass
class PuntoAcceso:
    macAddress:         str
    signalStrength:     int          # RSSI en dBm (negativo, ej. -65)
    channel:            int = 0
    signalToNoiseRatio: int = 0

    def validar(self) -> bool:
        mac = self.macAddress.replace(":", "").replace("-", "")
        return (
            len(mac) == 12
            and all(c in "0123456789abcdefABCDEF" for c in mac)
            and -120 <= self.signalStrength <= 0
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "macAddress":    self.macAddress,
            "signalStrength": self.signalStrength,
        }
        if self.channel:
            d["channel"] = self.channel
        if self.signalToNoiseRatio:
            d["signalToNoiseRatio"] = self.signalToNoiseRatio
        return d


@dataclass
class ResultadoGeo:
    latitud:      float
    longitud:     float
    precision:    float          # metros
    proveedor:    str
    timestamp:    str
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

    def __init__(self, sentinel: ApexSentinel) -> None:
        self._s           = sentinel
        self.console:     Console = getattr(sentinel, "console", Console())
        self._google_key: str     = os.getenv("GOOGLE_GEO_KEY", "")
        self._cache:      tuple[float, ResultadoGeo] | None = None
        _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── API pública ───────────────────────────────────────────────────

    def triangular(
        self,
        redes:   list[PuntoAcceso | dict[str, Any]],
        forzar:  bool = False,
    ) -> ResultadoGeo | None:
        puntos = self._normalizar(redes)

        if len(puntos) < _MIN_REDES:
            self._aviso(
                f"Se necesitan ≥ {_MIN_REDES} redes para triangular "
                f"(recibidas: {len(puntos)})."
            )
            return None

        validos     = [p for p in puntos if p.validar()]
        descartados = len(puntos) - len(validos)
        if descartados:
            log.warning("%d punto(s) de acceso descartados (MAC/RSSI inválidos).",
                        descartados)

        if len(validos) < _MIN_REDES:
            self._aviso("Insuficientes redes válidas tras filtrado.")
            return None

        if not forzar and self._cache is not None:
            ts, resultado = self._cache
            if time.time() - ts < _CACHE_SEG:
                log.debug("Resultado geo servido desde caché.")
                return resultado

        resultado = (
            self._consultar_mozilla(validos)
            or self._consultar_google(validos)
            or self._consultar_ipapi()
        )

        if resultado:
            self._cache = (time.time(), resultado)
            self._registrar(resultado, len(validos))

        return resultado

    def mostrar_resultado(self, r: ResultadoGeo) -> None:
        tabla = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        tabla.add_column(style="dim cyan",   min_width=16)
        tabla.add_column(style="bold white")

        tabla.add_row("Latitud",      f"{r.latitud:.7f}°")
        tabla.add_row("Longitud",     f"{r.longitud:.7f}°")
        tabla.add_row("Precisión",    f"± {r.precision:.0f} metros")
        tabla.add_row("Proveedor",    r.proveedor)
        tabla.add_row("Redes usadas", str(r.redes_usadas))
        tabla.add_row("Timestamp",    r.timestamp)
        tabla.add_row("Google Maps",
                      f"[link={r.maps_url}]{r.maps_url}[/link]")

        self.console.print(Panel(
            tabla,
            title="[bold green]GEOLOCALIZACIÓN COMPLETADA[/bold green]",
            border_style="green",
            box=box.ROUNDED,
        ))

    def exportar(
        self,
        r:    ResultadoGeo,
        ruta: str | None = None,
    ) -> Path:
        ts_safe = r.timestamp.replace(":", "-").replace(" ", "_")
        nombre  = f"geo_{ts_safe}_{r.proveedor.replace(' ', '_')}.json"
        destino = Path(ruta) if ruta else _RESULTS_DIR / nombre

        payload: dict[str, Any] = {**asdict(r), "maps_url": r.maps_url}
        destino.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                           encoding="utf-8")
        log.info("Resultado geo exportado: %s", destino)

        if self._s.gp and self._s.gp.proyecto_activo:
            self._s.gp.registrar_evidencia(
                "geolocalizacion",
                f"Triangulación vía {r.proveedor} — ±{r.precision:.0f}m",
                {"ruta": str(destino), "coords": list(r.coords)},
            )

        return destino

    # ── Proveedores ───────────────────────────────────────────────────

    def _consultar_mozilla(
        self, puntos: list[PuntoAcceso]
    ) -> ResultadoGeo | None:
        payload = {"wifiAccessPoints": [p.to_dict() for p in puntos]}
        log.debug("Mozilla MLS — %d redes", len(puntos))
        try:
            resp = requests.post(
                _URL_MOZILLA, json=payload, timeout=_TIMEOUT_SEG)
            if resp.status_code == 200:
                data = resp.json()
                return ResultadoGeo(
                    latitud=data["location"]["lat"],
                    longitud=data["location"]["lng"],
                    precision=float(data.get("accuracy", 0)),
                    proveedor="Mozilla MLS",
                    timestamp=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    redes_usadas=len(puntos),
                )
            log.warning("Mozilla MLS: HTTP %d", resp.status_code)
        except requests.Timeout:
            log.warning("Mozilla MLS: timeout tras %ds.", _TIMEOUT_SEG)
        except requests.RequestException as exc:
            log.warning("Mozilla MLS: error de red — %s", exc)
        return None

    def _consultar_google(
        self, puntos: list[PuntoAcceso]
    ) -> ResultadoGeo | None:
        if not self._google_key:
            return None
        payload = {"wifiAccessPoints": [p.to_dict() for p in puntos]}
        log.debug("Google Geolocation — %d redes", len(puntos))
        try:
            url  = _URL_GOOGLE.format(key=self._google_key)
            resp = requests.post(url, json=payload, timeout=_TIMEOUT_SEG)
            if resp.status_code == 200:
                data = resp.json()
                return ResultadoGeo(
                    latitud=data["location"]["lat"],
                    longitud=data["location"]["lng"],
                    precision=float(data.get("accuracy", 0)),
                    proveedor="Google Geolocation",
                    timestamp=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    redes_usadas=len(puntos),
                )
            log.warning("Google Geolocation: HTTP %d", resp.status_code)
        except requests.Timeout:
            log.warning("Google Geolocation: timeout.")
        except requests.RequestException as exc:
            log.warning("Google Geolocation: error — %s", exc)
        return None

    def _consultar_ipapi(self) -> ResultadoGeo | None:
        log.info("Fallback ip-api — geolocalización por IP (±50 km).")
        try:
            resp = requests.get(_URL_IPAPI, timeout=_TIMEOUT_SEG)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    return ResultadoGeo(
                        latitud=float(data["lat"]),
                        longitud=float(data["lon"]),
                        precision=50_000.0,
                        proveedor=f"ip-api (ISP: {data.get('isp', '?')})",
                        timestamp=datetime.now(UTC).strftime(
                            "%Y-%m-%d %H:%M:%S UTC"),
                        redes_usadas=0,
                    )
        except requests.RequestException as exc:
            log.error("ip-api fallback falló: %s", exc)
        return None

    # ── Utilidades internas ───────────────────────────────────────────

    def _normalizar(
        self, redes: list[Any]
    ) -> list[PuntoAcceso]:
        resultado: list[PuntoAcceso] = []
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
                except (ValueError, TypeError) as exc:
                    log.warning("Punto ignorado por datos inválidos: %s — %s",
                                r, exc)
            else:
                log.warning("Tipo de entrada desconocido ignorado: %s", type(r))
        return resultado

    def _registrar(self, r: ResultadoGeo, n_redes: int) -> None:
        mensaje = (
            f"Triangulación vía {r.proveedor} | "
            f"{r.latitud:.5f}, {r.longitud:.5f} | "
            f"±{r.precision:.0f}m | {n_redes} redes"
        )
        self._s.log.info(mensaje, "GeoPrecise")

    def _aviso(self, msg: str) -> None:
        self.console.print(f"[bold yellow][!] GeoPrecise: {msg}[/bold yellow]")
        log.warning(msg)
