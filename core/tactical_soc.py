from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from core.evidence_bridge import register_evidence

logger = logging.getLogger("apex_sentinel_soc")


class IngestaSuricata:
    def __init__(self, ruta_eve_json: str | Path, poll_interval: float = 1.0) -> None:
        self._ruta = Path(ruta_eve_json)
        self._poll_interval = poll_interval
        self._offset = 0

    async def eventos(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            try:
                tam_actual = self._ruta.stat().st_size
                if tam_actual < self._offset:
                    self._offset = 0
                if tam_actual > self._offset:
                    with self._ruta.open("r", encoding="utf-8") as fh:
                        fh.seek(self._offset)
                        for linea in fh:
                            linea = linea.strip()
                            if linea:
                                try:
                                    yield json.loads(linea)
                                except json.JSONDecodeError:
                                    pass
                        self._offset = fh.tell()
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning("Error leyendo %s: %s", self._ruta, exc)
            await asyncio.sleep(self._poll_interval)


class FeedSimulado:
    def __init__(self, eventos_simulados: list[dict[str, Any]], intervalo: float = 3.0) -> None:
        self._eventos = eventos_simulados
        self._intervalo = intervalo

    async def eventos(self) -> AsyncIterator[dict[str, Any]]:
        for evento in self._eventos:
            await asyncio.sleep(self._intervalo)
            yield evento


@dataclass
class ReglaRespuesta:
    severidad_minima: int = 1
    cooldown_seg: float = 30.0
    ips_protegidas: frozenset[str] = field(default_factory=frozenset)
    dry_run: bool = True


class TacticalSOC:
    def __init__(
        self,
        ingesta: IngestaSuricata | FeedSimulado,
        playbook: "ResponsePlaybook",
        regla: ReglaRespuesta,
        on_alerta: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._ingesta = ingesta
        self._playbook = playbook
        self._regla = regla
        self._on_alerta = on_alerta
        self._ultimo_bloqueo: dict[str, float] = {}

    async def ejecutar(self) -> None:
        async for evento in self._ingesta.eventos():
            if evento.get("event_type") != "alert":
                continue
            await self._procesar_alerta(evento)

    async def _procesar_alerta(self, evento: dict[str, Any]) -> None:
        alerta = evento.get("alert", {})
        severidad = alerta.get("severity", 3)
        ip_origen = evento.get("src_ip")

        if self._on_alerta is not None:
            self._on_alerta(evento)

        if severidad > self._regla.severidad_minima:
            return
        if not ip_origen or not self._ip_valida(ip_origen):
            return
        if ip_origen in self._regla.ips_protegidas:
            return

        ahora = time.monotonic()
        if ahora - self._ultimo_bloqueo.get(ip_origen, 0.0) < self._regla.cooldown_seg:
            return
        self._ultimo_bloqueo[ip_origen] = ahora

        await self._playbook.responder(evento, ip_origen, dry_run=self._regla.dry_run)

    @staticmethod
    def _ip_valida(valor: str) -> bool:
        try:
            ipaddress.ip_address(valor)
            return True
        except ValueError:
            return False


class ResponsePlaybook:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        workspace: Path,
        operator_id: str,
    ) -> None:
        self._loop = loop
        self._workspace = workspace
        self._operator_id = operator_id

    async def responder(self, evento: dict[str, Any], ip_origen: str, dry_run: bool) -> None:
        firma = evento.get("alert", {}).get("signature", "?")
        logger.critical("ALERTA CRÍTICA de %s — %s", ip_origen, firma)

        if dry_run:
            logger.info(
                "[dry-run] Se habría bloqueado %s en iptables.", ip_origen)
        else:
            try:
                subprocess.run(["sudo", "iptables", "-A", "INPUT", "-s",
                               ip_origen, "-j", "DROP"], check=True, capture_output=True)
                logger.info("IP %s bloqueada vía iptables.", ip_origen)
            except Exception as e:
                logger.error("No se pudo bloquear %s: %s", ip_origen, e)

        snapshot = await self._loop.run_in_executor(None, self._tomar_snapshot)
        paquete = {
            "evento_suricata": evento,
            "snapshot_sistema": snapshot,
            "ip_bloqueada": None if dry_run else ip_origen,
        }

        def _guardar_y_firmar():
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
                json.dump(paquete, f, indent=2)
                temp_path = Path(f.name)

            register_evidence(
                workspace=self._workspace,
                operator_id=self._operator_id,
                artifact_path=temp_path,
                artifact_type="soc_alerta",
                details={"ip": ip_origen, "firma": firma}
            )

        try:
            await self._loop.run_in_executor(None, _guardar_y_firmar)
        except Exception:
            logger.exception(
                "Fallo al sellar la evidencia de la alerta de %s", ip_origen)

    @staticmethod
    def _tomar_snapshot() -> dict[str, Any]:
        snapshot: dict[str, Any] = {"timestamp": time.time()}
        comandos = {"procesos": ["tasklist"]
                    if subprocess.os.name == "nt" else ["ps", "aux"]}
        for clave, comando in comandos.items():
            try:
                resultado = subprocess.run(
                    comando, capture_output=True, text=True, timeout=5, check=False)
                snapshot[clave] = resultado.stdout
            except Exception as exc:
                snapshot[clave] = f"<no disponible: {exc}>"
        return snapshot
