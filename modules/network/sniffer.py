from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from scapy.all import AsyncSniffer, Packet, PcapWriter
    _SCAPY_AVAILABLE = True
except ImportError:
    _SCAPY_AVAILABLE = False
    AsyncSniffer = Any
    Packet = Any
    PcapWriter = Any

from core.event_bus import EventBus, EventType

logger = logging.getLogger("apex_sentinel.sniffer")

STARTUP_TIMEOUT_SECONDS = 10.0
EVIDENCE_NOTIFY_TIMEOUT_SECONDS = 5.0


class SnifferError(Exception):


class SnifferDependencyError(SnifferError):


class SnifferPermissionError(SnifferError):


@dataclass(frozen=True)
class RotationPolicy:
    max_size_bytes: int
    max_duration_seconds: float

    def __post_init__(self) -> None:
        if self.max_size_bytes <= 0:
            raise ValueError("max_size_bytes debe ser mayor que cero.")
        if self.max_duration_seconds <= 0:
            raise ValueError("max_duration_seconds debe ser mayor que cero.")


@dataclass
class _ActiveCapture:
    path: Path
    writer: "PcapWriter"
    opened_at_monotonic: float
    opened_at_iso: str
    packet_count: int = 0
    bytes_written: int = 0


class NetworkSniffer:

    def __init__(
        self,
        *,
        interface: str,
        output_dir: str | os.PathLike[str],
        rotation_policy: RotationPolicy,
        event_bus: EventBus,
        event_loop: asyncio.AbstractEventLoop,
        file_prefix: str = "apex_sentinel",
        bpf_filter: str = "",
        snapshot_length: int = 65535,
        promiscuous: bool = True,
        sync_writes: bool = True,
    ) -> None:
        if not _SCAPY_AVAILABLE:
            raise SnifferDependencyError(
                "Scapy no está instalado. Instálalo con 'pip install scapy' para "
                "habilitar la captura de tráfico de red."
            )
        if not interface:
            raise ValueError(
                "La interfaz de red ('interface') no puede estar vacía.")

        self._interface = interface
        self._output_dir = Path(output_dir)
        self._rotation_policy = rotation_policy
        self._event_bus = event_bus
        self._event_loop = event_loop
        self._file_prefix = file_prefix
        self._bpf_filter = bpf_filter
        self._snapshot_length = snapshot_length
        self._promiscuous = promiscuous
        self._sync_writes = sync_writes

        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SnifferError(
                f"No fue posible crear el directorio de salida '{self._output_dir}': {exc}") from exc

        self._state_lock = threading.RLock()
        self._active_capture: Optional[_ActiveCapture] = None
        self._sniffer: Optional["AsyncSniffer"] = None
        self._rotation_watchdog: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False
        self._sequence_number = 0

    @property
    def is_running(self) -> bool:
        return self._running

    def _generate_pcap_path(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._sequence_number += 1
        filename = f"{self._file_prefix}_{timestamp}_{self._sequence_number:06d}.pcap"
        return self._output_dir / filename

    def _open_new_capture(self) -> _ActiveCapture:
        path = self._generate_pcap_path()
        try:
            writer = PcapWriter(
                str(path), append=False, sync=self._sync_writes, snaplen=self._snapshot_length)
        except OSError as exc:
            raise SnifferError(
                f"No fue posible crear el archivo PCAP '{path}': {exc}") from exc
        now = datetime.now(timezone.utc)
        logger.info("Nuevo archivo de evidencia PCAP abierto: %s", path)
        return _ActiveCapture(path=path, writer=writer, opened_at_monotonic=time.monotonic(), opened_at_iso=now.isoformat())

    def _finalize_closed_capture(self, capture: _ActiveCapture) -> None:
        if capture.packet_count == 0:
            logger.debug(
                "Archivo PCAP '%s' descartado por no contener paquetes.", capture.path)
            try:
                capture.path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "No fue posible eliminar el archivo PCAP vacío '%s'.", capture.path)
            return
        logger.info(
            "Archivo de evidencia cerrado: %s (%d paquetes, %d bytes).",
            capture.path, capture.packet_count, capture.bytes_written,
        )
        self._notify_evidence_created(capture)

    def _notify_evidence_created(self, capture: _ActiveCapture) -> None:
        payload = {
            "file_path": str(capture.path),
            "packet_count": capture.packet_count,
            "bytes_written": capture.bytes_written,
            "opened_at": capture.opened_at_iso,
            "closed_at": datetime.now(timezone.utc).isoformat(),
            "interface": self._interface,
        }
        try:
            future = asyncio.run_coroutine_threadsafe(
                self._event_bus.publish(
                    EventType.EVIDENCE_CREATED, payload=payload, source="NetworkSniffer"),
                self._event_loop,
            )
            future.result(timeout=EVIDENCE_NOTIFY_TIMEOUT_SECONDS)
        except Exception:
            logger.exception(
                "No fue posible publicar el evento EVIDENCE_CREATED para '%s'.", capture.path)

    def _should_rotate(self, capture: _ActiveCapture) -> bool:
        elapsed = time.monotonic() - capture.opened_at_monotonic
        if elapsed >= self._rotation_policy.max_duration_seconds:
            return True
        if capture.bytes_written >= self._rotation_policy.max_size_bytes:
            return True
        return False

    def _rotate_if_needed(self) -> None:
        closed_capture: Optional[_ActiveCapture] = None
        with self._state_lock:
            capture = self._active_capture
            if capture is not None and self._should_rotate(capture):
                try:
                    capture.writer.close()
                except Exception:
                    logger.exception(
                        "Error cerrando el escritor PCAP para '%s'.", capture.path)
                closed_capture = capture
                self._active_capture = self._open_new_capture()
        if closed_capture is not None:
            self._finalize_closed_capture(closed_capture)

    def _shutdown_active_capture(self) -> None:
        with self._state_lock:
            capture = self._active_capture
            self._active_capture = None
            if capture is not None:
                try:
                    capture.writer.close()
                except Exception:
                    logger.exception(
                        "Error cerrando el escritor PCAP para '%s'.", capture.path)
        if capture is not None:
            self._finalize_closed_capture(capture)

    def _handle_packet(self, packet: "Packet") -> None:
        try:
            raw_length = len(bytes(packet))
            with self._state_lock:
                if self._active_capture is None:
                    self._active_capture = self._open_new_capture()
                self._active_capture.writer.write(packet)
                self._active_capture.packet_count += 1
                self._active_capture.bytes_written += raw_length
            self._rotate_if_needed()
        except Exception:
            logger.exception("Error procesando un paquete capturado.")

    def _rotation_watchdog_loop(self) -> None:

        while not self._stop_event.wait(timeout=1.0):
            self._rotate_if_needed()

    def start(self) -> None:

        if self._running:
            logger.warning("NetworkSniffer ya se encuentra en ejecución.")
            return

        with self._state_lock:
            self._active_capture = self._open_new_capture()

        started_event = threading.Event()
        self._sniffer = AsyncSniffer(
            iface=self._interface,
            filter=self._bpf_filter or None,
            prn=self._handle_packet,
            store=False,
            promisc=self._promiscuous,
            started_callback=started_event.set,
        )

        try:
            self._sniffer.start()
        except Exception as exc:
            self._shutdown_active_capture()
            raise SnifferError(
                f"No fue posible iniciar el hilo de captura en '{self._interface}': {exc}") from exc

        started_in_time = started_event.wait(timeout=STARTUP_TIMEOUT_SECONDS)
        startup_exception = getattr(self._sniffer, "exception", None)

        if not started_in_time or startup_exception is not None:
            self._shutdown_active_capture()
            if isinstance(startup_exception, PermissionError):
                raise SnifferPermissionError(
                    f"Permisos insuficientes para capturar en '{self._interface}'. "
                    "Ejecuta el proceso con privilegios elevados (root) o concede la "
                    "capability CAP_NET_RAW/CAP_NET_ADMIN al intérprete de Python, ej.: "
                    "'sudo setcap cap_net_raw,cap_net_admin+eip $(readlink -f $(which python3))'."
                ) from startup_exception
            if startup_exception is not None:
                raise SnifferError(
                    f"Fallo al iniciar la captura en '{self._interface}': {startup_exception}") from startup_exception
            raise SnifferError(
                f"Tiempo de espera agotado ({STARTUP_TIMEOUT_SECONDS}s) iniciando la captura en "
                f"'{self._interface}'. Verifica que la interfaz exista y esté activa ('ip link show')."
            )

        self._stop_event.clear()
        self._rotation_watchdog = threading.Thread(
            target=self._rotation_watchdog_loop,
            name="apex-sentinel-rotation-watchdog",
            daemon=True,
        )
        self._rotation_watchdog.start()

        self._running = True
        logger.info(
            "Captura de red iniciada en interfaz '%s' (filtro='%s', promiscuo=%s).",
            self._interface, self._bpf_filter or "<ninguno>", self._promiscuous,
        )

    def stop(self) -> None:
        if not self._running:
            logger.debug(
                "NetworkSniffer.stop() invocado pero el sniffer no estaba en ejecución.")
            return

        logger.info("Deteniendo captura de red...")
        self._running = False
        self._stop_event.set()

        if self._rotation_watchdog is not None:
            self._rotation_watchdog.join(timeout=5.0)
            self._rotation_watchdog = None

        if self._sniffer is not None:
            try:
                if self._sniffer.running:
                    self._sniffer.stop()
            except Exception:
                logger.exception("Error deteniendo AsyncSniffer.")
            self._sniffer = None

        self._shutdown_active_capture()
        logger.info("Captura de red detenida. Evidencia final sellada.")
