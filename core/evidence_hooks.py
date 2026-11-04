from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from core.evidence_bridge import register_evidence

logger = logging.getLogger(__name__)


def _safe_register(
    sentinel: Any,
    artifact_path: Path | str,
    artifact_type: str,
    details: dict[str, Any] | None = None,
) -> bool:

    try:
        path = Path(artifact_path)
        if not path.exists():
            logger.debug("Hook: archivo no existe, skip %s", path)
            return False

        workspace = getattr(sentinel, "workspace", Path.cwd())
        operator_id = getattr(sentinel, "operator_id", "op-mariano")

        register_evidence(
            workspace=workspace,
            operator_id=operator_id,
            artifact_path=path,
            artifact_type=artifact_type,
            details=details or {},
        )

        console = getattr(sentinel, "console", None)
        if console:
            console.print(
                f"[dim][+] Firmado en custodia: {path.name} "
                f"({artifact_type})[/dim]"
            )
        return True

    except Exception as e:
        logger.error("Hook: fallo firmando %s: %s", artifact_path, e)
        console = getattr(sentinel, "console", None)
        if console:
            console.print(
                f"[yellow][!] Firmado forense falló para "
                f"{Path(artifact_path).name}: {e}[/yellow]"
            )
        return False


def firmar_archivos_radar(
    sentinel: Any,
    json_path: Path | str,
    csv_path: Path | str,
    num_dispositivos: int,
    num_geoips: int = 0,
) -> tuple[bool, bool]:

    ok_json = _safe_register(
        sentinel,
        json_path,
        artifact_type="radar_wifi_json",
        details={
            "device_count": num_dispositivos,
            "geoip_count": num_geoips,
            "format": "json",
        },
    )
    ok_csv = _safe_register(
        sentinel,
        csv_path,
        artifact_type="radar_wifi_csv",
        details={
            "device_count": num_dispositivos,
            "format": "csv",
        },
    )
    return ok_json, ok_csv


def firmar_reporte_osint(
    sentinel: Any,
    json_path: Path | str,
    objetivo: str,
    tipo: str,
    campos: list[str] | None = None,
) -> bool:

    return _safe_register(
        sentinel,
        json_path,
        artifact_type=f"osint_{tipo}",
        details={
            "target": objetivo,
            "type": tipo,
            "fields": campos or [],
        },
    )


def firmar_resultados_cve(
    sentinel: Any,
    temp_json_path: Path | str,
    query: str,
    total_cves: int,
    critical_count: int = 0,
    high_count: int = 0,
) -> bool:

    return _safe_register(
        sentinel,
        temp_json_path,
        artifact_type="cve_scan_result",
        details={
            "query": query,
            "total_cves": total_cves,
            "critical": critical_count,
            "high": high_count,
        },
    )


def firmar_portscan(
    sentinel: Any,
    temp_json_path: Path | str,
    target_ip: str,
    open_ports: int,
) -> bool:

    return _safe_register(
        sentinel,
        temp_json_path,
        artifact_type="port_scan_result",
        details={
            "target_ip": target_ip,
            "open_ports": open_ports,
        },
    )


def firmar_archivos_geo(
    sentinel: Any,
    kml_path: Path | str,
    geojson_path: Path | str,
    num_points: int,
    has_gps: bool,
) -> tuple[bool, bool]:

    ok_kml = _safe_register(
        sentinel,
        kml_path,
        artifact_type="geo_kml",
        details={
            "points": num_points,
            "has_gps": has_gps,
        },
    )
    ok_geojson = _safe_register(
        sentinel,
        geojson_path,
        artifact_type="geo_geojson",
        details={
            "points": num_points,
            "has_gps": has_gps,
        },
    )
    return ok_kml, ok_geojson


__all__ = [
    "firmar_archivos_geo",
    "firmar_archivos_radar",
    "firmar_portscan",
    "firmar_reporte_osint",
    "firmar_resultados_cve",
]
