from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import queue
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Estilos visuales (compatible con bootscreen.py)
try:
    from core.bootscreen import ESTILOS_LOG
except ImportError:
    ESTILOS_LOG: dict[str, tuple[str, str]] = {
        "INFO":    ("cyan",    "ℹ"),
        "WARNING": ("yellow",  "⚠"),
        "ERROR":   ("red",     "✖"),
        "SUCCESS": ("green",   "✔"),
        "AUDIT":   ("magenta", "🔍"),
        "DEBUG":   ("dim",     "·"),
        "CRITICAL": ("bold red", "💀"),
    }

# Constantes
_MAX_ENTRADAS_MEMORIA: int = 1_000   # entradas en RAM
_MAX_BYTES_LOG:        int = 5 * 1024 * 1024  # 5 MB por archivo
_BACKUP_COUNT:         int = 5        # hasta 5 rotaciones (25 MB total)
_FLUSH_INTERVAL:       float = 2.0   # segundos entre flushes a disco
_QUEUE_MAXSIZE:        int = 4_096   # entradas pendientes en cola


def _ts_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

# Adaptador stdlib → LogSistema


class _StdlibHandler(logging.Handler):
    _NIVEL_MAP = {
        logging.DEBUG:    "DEBUG",
        logging.INFO:     "INFO",
        logging.WARNING:  "WARNING",
        logging.ERROR:    "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def __init__(self, log_sistema: "LogSistema"):
        super().__init__()
        self._ls = log_sistema

    def emit(self, record: logging.LogRecord) -> None:
        nivel = self._NIVEL_MAP.get(record.levelno, "INFO")
        modulo = record.name or "stdlib"
        self._ls._encolar(nivel, self.format(record), modulo, extra={})

# CLASE PRINCIPAL


class LogSistema:
    def __init__(
        self,
        console: Console,
        base_dir: Path | None = None,
        session_id: str | None = None,
    ) -> None:
        # Rutas absolutas
        self._base = (base_dir or Path(
            __file__).resolve().parent / "data").resolve()
        self._log_dir = self._base / "logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)

        self._log_file = self._log_dir / "sentinel.log"
        self._audit_file = self._log_dir / "audit.log"
        self._json_file = self._log_dir / "historial.json"
        self._jsonl_file = self._log_dir / "events.jsonl"

        # Estado interno
        self.console = console
        self.session_id = session_id or str(uuid.uuid4())
        self._lock = threading.Lock()
        self._entradas: list[dict] = []
        self._cola: queue.Queue[dict | None] = queue.Queue(
            maxsize=_QUEUE_MAXSIZE)
        self._dirty = False   # hay entradas sin persistir en JSON

        # Configurar handlers de stdlib logging
        self._logger = self._setup_logger("sentinel",   self._log_file)
        self._audit_logger = self._setup_logger(
            "sentinel.audit", self._audit_file)
        # Conectar stdlib raíz → LogSistema (captura librerías externas)
        self._stdlib_handler = _StdlibHandler(self)
        # solo WARNING+ de libs externas
        self._stdlib_handler.setLevel(logging.WARNING)
        logging.getLogger().addHandler(self._stdlib_handler)

        # Cargar historial previo
        self._entradas = self._cargar_historial()

        # Worker de I/O asíncrono
        self._stop_event = threading.Event()
        self._worker = threading.Thread(
            target=self._io_worker,
            name="LogSistema-IOWorker",
            daemon=True,
        )
        self._worker.start()
        atexit.register(self.cerrar)

    # Setup stdlib logger con rotación

    @staticmethod
    def _setup_logger(name: str, filepath: Path) -> logging.Logger:
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False  # no escalar al root logger
        if not logger.handlers:
            handler = logging.handlers.RotatingFileHandler(
                filename=filepath,
                maxBytes=_MAX_BYTES_LOG,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            fmt = logging.Formatter(
                fmt="%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
            handler.setFormatter(fmt)
            logger.addHandler(handler)
        return logger

    # Worker de I/O (hilo separado)

    def _io_worker(self) -> None:
        pending: list[dict] = []
        while not self._stop_event.is_set():
            try:
                # Espera con timeout para hacer flush periódico
                entry = self._cola.get(timeout=_FLUSH_INTERVAL)
                if entry is None:        # señal de cierre
                    break
                pending.append(entry)
                # Drain: vaciar todo lo que haya en cola ahora
                while True:
                    try:
                        e = self._cola.get_nowait()
                        if e is None:
                            break
                        pending.append(e)
                    except queue.Empty:
                        break
            except queue.Empty:
                pass  # timeout normal → hacer flush de lo pendiente

            if pending:
                self._flush_to_disk(pending)
                pending.clear()

        # Flush final antes de salir
        remaining: list[dict] = []
        while True:
            try:
                e = self._cola.get_nowait()
                if e is not None:
                    remaining.append(e)
            except queue.Empty:
                break
        if remaining:
            self._flush_to_disk(remaining)

    def _flush_to_disk(self, entries: list[dict]) -> None:
        # JSONL (append-only, apto para SIEM)
        try:
            with self._jsonl_file.open("a", encoding="utf-8") as f:
                for e in entries:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
        except OSError:
            pass

        # historial.json (snapshot de las últimas N entradas)
        with self._lock:
            snapshot = self._entradas[-_MAX_ENTRADAS_MEMORIA:]
        try:
            with self._json_file.open("w", encoding="utf-8") as f:
                json.dump(snapshot, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    # Carga inicial

    def _cargar_historial(self) -> list[dict]:
        try:
            with self._json_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
        return []

    # Núcleo: encolar entrada

    def _encolar(
        self,
        nivel: str,
        mensaje: str,
        modulo: str,
        extra: dict[str, Any],
    ) -> None:
        entrada: dict[str, Any] = {
            "event_id":   str(uuid.uuid4()),
            "session_id": self.session_id,
            "timestamp":  _ts_iso(),
            "nivel":      nivel,
            "modulo":     modulo,
            "mensaje":    str(mensaje),
        }
        if extra:
            entrada["extra"] = extra

        # Añadir a RAM (thread-safe)
        with self._lock:
            self._entradas.append(entrada)
            if len(self._entradas) > _MAX_ENTRADAS_MEMORIA:
                self._entradas = self._entradas[-_MAX_ENTRADAS_MEMORIA:]

        # Escribir a archivo de texto (stdlib logging con rotación)
        log_msg = f"[{modulo}] {mensaje}"
        if extra:
            log_msg += "  " + "  ".join(f"{k}={v}" for k, v in extra.items())

        stdlib_level = getattr(logging, nivel, logging.INFO)
        if nivel == "AUDIT":
            self._audit_logger.info(log_msg)
        elif nivel == "SUCCESS":
            self._logger.info(log_msg)
        elif nivel == "CRITICAL":
            self._logger.critical(log_msg)
        else:
            self._logger.log(stdlib_level, log_msg)

        # Encolar para flush asíncrono a JSONL/JSON
        try:
            self._cola.put_nowait(entrada)
        except queue.Full:
            # Cola llena: descartamos antes de bloquear el hilo principal.
            # Se loguea en stderr para no perder el evento silenciosamente.
            import sys
            print(
                f"[LogSistema] WARN: cola llena, evento descartado: {mensaje[:80]}", file=sys.stderr)

        # Mostrar en consola
        self._render_consola(entrada)

    # Render consola

    def _render_consola(self, entrada: dict) -> None:
        color, icono = ESTILOS_LOG.get(entrada["nivel"], ("white", "·"))
        line = Text()
        # Timestamp (solo HH:MM:SS en consola; el ISO completo va al archivo)
        ts_corto = entrada["timestamp"][11:19]  # "HH:MM:SS" del ISO-8601
        line.append(ts_corto, style="dim")
        line.append(" ")
        line.append(f"{icono} {entrada['nivel']:<8}", style=color)
        line.append(" ")
        line.append(f"{entrada['modulo']:<18}", style="cyan")
        line.append(" ")
        line.append(entrada["mensaje"])
        if "extra" in entrada:
            kv = "  ".join(f"[dim]{k}=[/dim][yellow]{v}[/yellow]"
                           for k, v in entrada["extra"].items())
            line.append("  ")
            line.append_text(Text.from_markup(kv))
        self.console.print(line)

    # API pública

    def debug(self, msg: str, modulo: str = "Sistema",
              **extra: Any) -> None:
        self._encolar("DEBUG", msg, modulo, extra)

    def info(self, msg: str, modulo: str = "Sistema",
             **extra: Any) -> None:
        self._encolar("INFO", msg, modulo, extra)

    def warning(self, msg: str, modulo: str = "Sistema",
                **extra: Any) -> None:
        self._encolar("WARNING", msg, modulo, extra)

    def error(self, msg: str, modulo: str = "Sistema",
              **extra: Any) -> None:
        self._encolar("ERROR", msg, modulo, extra)

    def critical(self, msg: str, modulo: str = "Sistema",
                 **extra: Any) -> None:
        self._encolar("CRITICAL", msg, modulo, extra)

    def success(self, msg: str, modulo: str = "Sistema",
                **extra: Any) -> None:
        self._encolar("SUCCESS", msg, modulo, extra)

    def audit(self, msg: str, modulo: str = "Auditoría",
              **extra: Any) -> None:
        self._encolar("AUDIT", msg, modulo, extra)

    # Consulta / visualización

    def mostrar_historial(
        self,
        ultimas: int = 50,
        nivel: str | None = None,
        modulo: str | None = None,
    ) -> None:

        with self._lock:
            entradas = list(self._entradas)

        # Filtros
        if nivel:
            entradas = [e for e in entradas if e.get("nivel") == nivel.upper()]
        if modulo:
            entradas = [e for e in entradas
                        if modulo.lower() in e.get("modulo", "").lower()]
        entradas = entradas[-ultimas:]

        if not entradas:
            self.console.print(Panel(
                "[dim]Sin registros que coincidan con los filtros.[/dim]",
                title="HISTORIAL", border_style="dim green",
            ))
            return

        # Resumen por nivel
        with self._lock:
            todas = list(self._entradas)
        conteos: dict[str, int] = {}
        for e in todas:
            conteos[e["nivel"]] = conteos.get(e["nivel"], 0) + 1

        resumen = Table.grid(padding=(0, 3))
        celdas = []
        for n, (c, ico) in ESTILOS_LOG.items():
            t = Text()
            t.append(f"{ico} {n}: {conteos.get(n, 0)}", style=c)
            celdas.append(t)
        resumen.add_row(*celdas)
        self.console.print(Panel(
            resumen,
            title=f"[bold]RESUMEN SESIÓN [dim]{self.session_id[:8]}…[/dim][/bold]",
            border_style="dim green",
            box=box.SIMPLE,
        ))

        # Tabla de eventos
        tabla = Table(
            box=box.SIMPLE_HEAD,
            header_style="bold cyan",
            show_edge=False,
            expand=True,
        )
        tabla.add_column("Timestamp",  style="dim",
                         min_width=24, no_wrap=True)
        tabla.add_column("Nivel",
                         min_width=10, no_wrap=True)
        tabla.add_column("Módulo",     style="cyan",  min_width=16)
        tabla.add_column("Mensaje",    style="white")
        tabla.add_column("Extra",      style="dim",   min_width=12)

        for e in entradas:
            color, icono = ESTILOS_LOG.get(e["nivel"], ("white", "·"))
            nivel_txt = Text()
            nivel_txt.append(f"{icono} {e['nivel']}", style=color)
            extra_str = ""
            if "extra" in e and e["extra"]:
                extra_str = "  ".join(
                    f"{k}={v}" for k, v in e["extra"].items())
            tabla.add_row(
                e["timestamp"],
                nivel_txt,
                str(e.get("modulo", "")),
                str(e.get("mensaje", "")),
                extra_str,
            )

        titulo = f"[bold]HISTORIAL — {len(entradas)} entradas[/bold]"
        if nivel or modulo:
            filtros = []
            if nivel:
                filtros.append(f"nivel={nivel}")
            if modulo:
                filtros.append(f"módulo={modulo}")
            titulo += f" [dim]({', '.join(filtros)})[/dim]"

        self.console.print(Panel(
            tabla,
            title=titulo,
            border_style="green",
            box=box.HEAVY_EDGE,
        ))

    def exportar_jsonl(self, destino: Path | None = None) -> Path:
        if destino is None:
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            destino = self._log_dir / \
                f"export_{self.session_id[:8]}_{ts}.jsonl"

        with self._lock:
            entradas = list(self._entradas)

        with destino.open("w", encoding="utf-8") as f:
            for e in entradas:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        self.success(f"JSONL exportado → {destino}", "LogSistema")
        return destino

    def verificar_y_limpiar(self, max_entradas: int = _MAX_ENTRADAS_MEMORIA) -> None:
        with self._lock:
            if len(self._entradas) > max_entradas:
                self._entradas = self._entradas[-max_entradas:]

    def cerrar(self) -> None:

        if self._stop_event.is_set():
            return  # ya cerrado
        self._stop_event.set()
        try:
            self._cola.put_nowait(None)   # señal de cierre al worker
        except queue.Full:
            pass
        self._worker.join(timeout=5.0)
        # Remover handler stdlib para no interferir con otros loggers
        logging.getLogger().removeHandler(self._stdlib_handler)
