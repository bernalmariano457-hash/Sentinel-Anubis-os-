"""
core/event_bus.py

Bus de eventos (EventBus) asíncrono y desacoplado, basado en el patrón
Publicador/Suscriptor, utilizado para la comunicación intermódulo del
Subsistema Forense de Anubis OS (Apex Sentinel).

Los módulos de captura de red, integridad criptográfica y orquestación se
comunican exclusivamente a través de este bus, sin conocerse directamente
entre sí.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, DefaultDict, List, Optional, Union

logger = logging.getLogger("apex_sentinel.event_bus")


class EventType(str, Enum):
    """Catálogo canónico de tipos de eventos reconocidos por el sistema."""
    EVIDENCE_CREATED = "EVIDENCE_CREATED"
    EVIDENCE_SEALED = "EVIDENCE_SEALED"
    CHAIN_VERIFIED = "CHAIN_VERIFIED"
    CHAIN_COMPROMISED = "CHAIN_COMPROMISED"
    CAPTURE_STARTED = "CAPTURE_STARTED"
    CAPTURE_STOPPED = "CAPTURE_STOPPED"
    CAPTURE_ERROR = "CAPTURE_ERROR"
    SYSTEM_SHUTDOWN = "SYSTEM_SHUTDOWN"


@dataclass(frozen=True)
class Event:
    """Estructura inmutable de un evento publicado en el bus."""
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)


EventHandler = Callable[[Event], Union[None, Awaitable[None]]]


class EventBus:
    """
    Bus de eventos asíncrono Pub/Sub para la comunicación desacoplada entre
    los subsistemas de Apex Sentinel.

    Los manejadores pueden ser funciones síncronas o corutinas; ambas se
    invocan de forma segura desde el bucle de despacho interno. Un fallo en
    un manejador individual se registra pero jamás interrumpe el despacho a
    los demás suscriptores ni el procesamiento de futuros eventos.
    """

    def __init__(self, *, max_queue_size: int = 1000, history_size: int = 200) -> None:
        self._subscribers: DefaultDict[str, List[EventHandler]] = defaultdict(list)
        self._wildcard_subscribers: List[EventHandler] = []
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._dispatcher_task: Optional[asyncio.Task[None]] = None
        self._running: bool = False
        self._history: List[Event] = []
        self._max_history: int = history_size

    @property
    def is_running(self) -> bool:
        return self._running

    def subscribe(self, event_type: Union[str, EventType], handler: EventHandler) -> None:
        """
        Suscribe un manejador a un tipo de evento específico.

        Usa el comodín '*' como `event_type` para recibir todos los eventos
        publicados en el bus, independientemente de su tipo.
        """
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)
        if key == "*":
            self._wildcard_subscribers.append(handler)
        else:
            self._subscribers[key].append(handler)
        logger.debug("Suscriptor registrado para '%s': %s", key, getattr(handler, "__name__", repr(handler)))

    def unsubscribe(self, event_type: Union[str, EventType], handler: EventHandler) -> bool:
        """Elimina un manejador previamente suscrito. Retorna True si existía, False en caso contrario."""
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)
        try:
            if key == "*":
                self._wildcard_subscribers.remove(handler)
            else:
                self._subscribers[key].remove(handler)
            return True
        except ValueError:
            return False

    async def publish(
        self,
        event_type: Union[str, EventType],
        payload: Optional[dict[str, Any]] = None,
        source: str = "unknown",
    ) -> Event:
        """
        Publica un evento en la cola interna para su procesamiento asíncrono.

        Seguro de invocar desde una corutina que se ejecuta en el mismo hilo
        que el bucle de eventos. Para publicar desde otro hilo del sistema
        operativo (por ejemplo, el hilo de captura de Scapy), utiliza
        `asyncio.run_coroutine_threadsafe(bus.publish(...), loop)`.
        """
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)
        event = Event(type=key, payload=payload or {}, source=source)
        await self._queue.put(event)
        return event

    def publish_nowait(
        self,
        event_type: Union[str, EventType],
        payload: Optional[dict[str, Any]] = None,
        source: str = "unknown",
    ) -> Event:
        """
        Variante no bloqueante de `publish()`.

        Solo es segura desde el mismo hilo del bucle de eventos; NO debe
        invocarse directamente desde otro hilo del sistema operativo.
        Lanza `asyncio.QueueFull` si la cola alcanzó `max_queue_size`.
        """
        key = event_type.value if isinstance(event_type, EventType) else str(event_type)
        event = Event(type=key, payload=payload or {}, source=source)
        self._queue.put_nowait(event)
        return event

    async def _dispatch(self, event: Event) -> None:
        """Invoca a todos los manejadores suscritos a un evento, aislando fallos individuales."""
        handlers: List[EventHandler] = list(self._subscribers.get(event.type, [])) + list(self._wildcard_subscribers)
        if not handlers:
            logger.debug("Evento '%s' (id=%s) publicado sin suscriptores.", event.type, event.event_id)
            return
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception(
                    "Error no controlado en el manejador '%s' para el evento '%s' (id=%s).",
                    getattr(handler, "__name__", repr(handler)), event.type, event.event_id,
                )

    def _record_history(self, event: Event) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history.pop(0)

    async def _run_dispatcher(self) -> None:
        """Bucle principal: consume la cola y distribuye eventos a los suscriptores."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                self._record_history(event)
                await self._dispatch(event)
            finally:
                self._queue.task_done()

    async def start(self) -> None:
        """Inicia el bucle de despacho de eventos en una tarea de fondo (idempotente)."""
        if self._running:
            logger.warning("EventBus ya se encuentra en ejecución; se ignora la solicitud de inicio.")
            return
        self._running = True
        self._dispatcher_task = asyncio.create_task(self._run_dispatcher(), name="apex-sentinel-event-bus")
        logger.info("EventBus iniciado.")

    async def stop(self, *, drain: bool = True, timeout: float = 10.0) -> None:
        """
        Detiene el bucle de despacho.

        Si `drain` es True, espera (hasta `timeout` segundos) a que todos los
        eventos ya encolados sean procesados antes de detener el bucle.
        """
        if drain:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("Tiempo de espera agotado drenando la cola de eventos antes del apagado.")

        self._running = False
        if self._dispatcher_task is not None:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
            self._dispatcher_task = None
        logger.info("EventBus detenido.")

    def get_history(self) -> List[Event]:
        """Retorna una copia superficial del historial reciente de eventos procesados."""
        return list(self._history)
