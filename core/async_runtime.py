from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Coroutine


class AsyncRuntime:

    def __init__(self, nombre: str = "AsyncRuntime") -> None:
        self._nombre = nombre
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._tareas: dict[str, asyncio.Task[Any]] = {}

    @property
    def activo(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def tarea_activa(self, nombre: str) -> bool:
        tarea = self._tareas.get(nombre)
        return tarea is not None and not tarea.done()

    def iniciar(self) -> None:

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            listo = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(
                    listo,), name=self._nombre, daemon=True,
            )
            self._thread.start()
        listo.wait(timeout=10.0)

    def _run(self, listo: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        listo.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    def ejecutar_ahora(self, coro: Coroutine[Any, Any, Any], timeout: float = 15.0) -> Any:

        if self._loop is None:
            raise RuntimeError(
                f"{self._nombre}: el loop todavía no está listo.")
        futuro = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return futuro.result(timeout=timeout)

    def lanzar_tarea(
        self, nombre: str, coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    ) -> None:

        if self._loop is None:
            raise RuntimeError(
                f"{self._nombre}: el loop todavía no está listo.")
        if self.tarea_activa(nombre):
            raise RuntimeError(f"La tarea '{nombre}' ya está corriendo.")

        def _crear() -> None:
            tarea = self._loop.create_task(coro_factory())
            self._tareas[nombre] = tarea

        self._loop.call_soon_threadsafe(_crear)

    def cancelar_tarea(self, nombre: str, timeout: float = 10.0) -> None:
        tarea = self._tareas.pop(nombre, None)
        if tarea is None or self._loop is None:
            return

        async def _cancelar() -> None:
            tarea.cancel()
            try:
                await tarea
            except asyncio.CancelledError:
                pass

        self.ejecutar_ahora(_cancelar(), timeout=timeout)

    def detener(self, timeout: float = 10.0) -> None:
        with self._lock:
            hilo, loop = self._thread, self._loop
        if hilo is None or loop is None:
            return
        for nombre in list(self._tareas):
            self.cancelar_tarea(nombre, timeout=timeout)
        loop.call_soon_threadsafe(loop.stop)
        hilo.join(timeout=timeout)
        with self._lock:
            self._thread = None
            self._loop = None
