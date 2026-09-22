from __future__ import annotations
from core.log_sistema import LogSistema
from core.ModuleRegistry import ModuleRegistry
from core.command_handler import CommandHandler
from core.vendor_resolver import VendorResolver
from core.sentinel_ui import animar_barra, mostrar_dashboard_exito

import asyncio
import functools
import json
import logging
import logging.handlers
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

from rich.console import Console
from rich.markup import escape as _esc
from rich.prompt import Prompt
from rich.panel import Panel
from rich.rule import Rule

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


try:
    from core.bootscreen import (
        COMANDOS_HELP,
        mostrar_ayuda,
        mostrar_banner,
        mostrar_bootloader,
    )
except ImportError:
    COMANDOS_HELP: dict[str, Any] = {}

    def mostrar_bootloader(c: Console, nombre: str, version: str,
                           iface: str, estados_modulos: Any = None) -> None:
        c.print(
            Panel(f"[bold steel_blue1]{nombre} v{version}[/bold steel_blue1]"))

    def mostrar_banner(c: Console, nombre: str, version: str,
                       iface: str, proyecto: str | None = None) -> None:
        c.print(
            Rule(f"[bold steel_blue1]{nombre} v{version}[/bold steel_blue1]"))

    def mostrar_ayuda(c: Console, version: str,
                      cmds: dict[str, Any] | None = None,
                      filtro: str | None = None) -> None:
        c.print(Panel("[dim]Sin ayuda.[/dim]", title="AYUDA"))

try:
    from core.auth import GestorAuth
except ImportError:
    class GestorAuth:
        def __init__(self, *a: Any, **kw: Any) -> None: pass
        def solicitar_acceso(self) -> bool: return True

try:
    from FlipperModule import FlipperModule
    _FLIPPER_OK = True
except ImportError:
    _FLIPPER_OK = False

try:
    import yaml

    from core.event_bus import Event, EventBus, EventType
    from modules.forensics.integrity.hash_chain import ChainIntegrityError, HashChainLogger
    from modules.forensics.network.sniffer import NetworkSniffer, RotationPolicy, SnifferError
    _FORENSICS_OK = True
    _FORENSICS_IMPORT_ERROR: str | None = None
except ImportError as _forensics_import_error:
    _FORENSICS_OK = False
    _FORENSICS_IMPORT_ERROR = str(_forensics_import_error)

ManejadorComando = Callable[[list[str]], None]


_WORK_DIRS: tuple[str, ...] = (
    "data/logs", "data/evidence", "data/evidence/rf",
    "data/evidence/rf/iq", "data/evidence/mobile",
    "core/data/logs", "core/data/security", "plugins",
)

_ENV_REQUIREMENTS: tuple[str, ...] = ()

_MIN_FREE_BYTES: int = 50 * 1024 * 1024


class BootstrapError(RuntimeError):
    pass


def _validate_bootstrap() -> None:
    missing_vars = [v for v in _ENV_REQUIREMENTS if not os.environ.get(v)]
    if missing_vars:
        raise BootstrapError(
            f"[FATAL] Variables de entorno requeridas ausentes: {missing_vars}"
        )

    for raw_path in _WORK_DIRS:
        target = Path(raw_path)
        target.mkdir(parents=True, exist_ok=True)

        resolved = target.resolve()
        try:
            mode = resolved.stat().st_mode
        except FileNotFoundError:
            raise BootstrapError(
                f"[FATAL] No se pudo crear o acceder al directorio: {resolved}"
            )

        owner_writable = bool(mode & stat.S_IWUSR)
        group_writable = bool(mode & stat.S_IWGRP)
        other_writable = bool(mode & stat.S_IWOTH)
        effective_uid = os.geteuid() if hasattr(os, "geteuid") else -1
        effective_gid = os.getegid() if hasattr(os, "getegid") else -1

        try:
            dir_stat = resolved.stat()
        except OSError:
            raise BootstrapError(
                f"[FATAL] Permisos ilegibles en: {resolved}"
            )

        is_owner = (effective_uid == dir_stat.st_uid)
        is_group = (effective_gid == dir_stat.st_gid)

        write_ok = (
            (is_owner and owner_writable)
            or (is_group and group_writable)
            or other_writable
            or effective_uid == 0
        )

        if not write_ok:
            raise BootstrapError(
                f"[FATAL] Sin permisos de escritura en: {resolved}"
            )

    try:
        statvfs = os.statvfs(".")
        free_bytes = statvfs.f_bavail * statvfs.f_frsize
        if free_bytes < _MIN_FREE_BYTES:
            raise BootstrapError(
                f"[FATAL] Espacio insuficiente en disco: "
                f"{free_bytes // 1024 // 1024} MB disponibles, "
                f"mínimo requerido: {_MIN_FREE_BYTES // 1024 // 1024} MB"
            )
    except AttributeError:
        pass


class TimeoutRequeridoError(ValueError):
    pass


class SubprocesoRechazadoError(RuntimeError):
    pass


class _ShutdownCoordinator:

    CALLBACK_TIMEOUT_SECONDS: float = 5.0

    def __init__(self, callback_timeout: float | None = None) -> None:
        self._shutdown_event: threading.Event = threading.Event()
        self._registered_workers: list[tuple[int,
                                             str, Callable[[], None]]] = []
        self._lock: threading.Lock = threading.Lock()
        self._triggered: bool = False
        self._callback_timeout: float = callback_timeout or self.CALLBACK_TIMEOUT_SECONDS

    def register_worker_shutdown(
        self,
        callback: Callable[[], None],
        nombre: str | None = None,
        prioridad: int = 0,
    ) -> None:
        etiqueta = nombre or getattr(callback, "__name__", "callback")
        with self._lock:
            self._registered_workers.append((prioridad, etiqueta, callback))

    def trigger(self) -> list[tuple[str, BaseException]]:
        with self._lock:
            if self._triggered:
                return []
            self._triggered = True
            self._shutdown_event.set()
            workers = sorted(self._registered_workers,
                             key=lambda entrada: -entrada[0])

        fallos: list[tuple[str, BaseException]] = []
        for _prioridad, nombre, callback in workers:
            try:
                self._ejecutar_con_limite(nombre, callback)
            except BaseException as error_apagado:
                fallos.append((nombre, error_apagado))
        return fallos

    def _ejecutar_con_limite(self, nombre: str, callback: Callable[[], None]) -> None:
        puede_usar_alarma = (
            hasattr(signal, "SIGALRM")
            and hasattr(signal, "setitimer")
            and threading.current_thread() is threading.main_thread()
        )
        if not puede_usar_alarma:
            callback()
            return

        def _al_expirar(signum: int, frame: Any) -> None:
            raise TimeoutError(f"timeout de apagado excedido para {nombre}")

        manejador_previo = signal.signal(signal.SIGALRM, _al_expirar)
        signal.setitimer(signal.ITIMER_REAL, max(self._callback_timeout, 0.1))
        try:
            callback()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(
                signal.SIGALRM,
                manejador_previo if manejador_previo is not None else signal.SIG_DFL,
            )

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown_event.is_set()


FORENSICS_APP_NAME = "apex_sentinel_forensics"
_forensics_logger = logging.getLogger(FORENSICS_APP_NAME)

_FORENSICS_REQUIRED_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "network": ("interface",),
    "capture": ("max_file_size_bytes", "max_file_duration_seconds"),
    "storage": ("base_path", "pcap_dir", "logs_dir", "audit_chain_file"),
    "integrity": (),
}


class ForensicsConfigError(Exception):
    pass


def load_forensics_config(config_path: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(config_path)
    if not path.is_file():
        raise ForensicsConfigError(
            f"Archivo de configuración no encontrado: '{path}'.")

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ForensicsConfigError(
            f"Error de sintaxis YAML en '{path}': {exc}") from exc
    except OSError as exc:
        raise ForensicsConfigError(
            f"No fue posible leer '{path}': {exc}") from exc

    if not isinstance(data, dict):
        raise ForensicsConfigError(
            f"'{path}' debe contener un mapeo YAML en su raíz.")

    problems: list[str] = []
    for section, required_keys in _FORENSICS_REQUIRED_CONFIG_KEYS.items():
        section_data = data.get(section)
        if not isinstance(section_data, dict):
            problems.append(f"Falta la sección obligatoria '{section}'.")
            continue
        for key in required_keys:
            if key not in section_data:
                problems.append(
                    f"Falta la clave obligatoria '{section}.{key}'.")

    if problems:
        raise ForensicsConfigError(
            f"Configuración inválida en '{path}':\n  - " + "\n  - ".join(problems))

    return data


def configure_forensics_logging(log_level: str, log_dir: Path) -> None:
    level = getattr(logging, str(log_level).upper(), logging.INFO)

    file_handler: logging.Handler | None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_dir / f"{FORENSICS_APP_NAME}.log"),
            maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
    except OSError as exc:
        file_handler = None
        sys.stderr.write(
            f"ADVERTENCIA: no fue posible preparar el log forense en '{log_dir}': {exc}\n"
        )

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    _forensics_logger.setLevel(level)
    _forensics_logger.propagate = False
    _forensics_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    _forensics_logger.addHandler(console_handler)

    if file_handler is not None:
        file_handler.setFormatter(formatter)
        _forensics_logger.addHandler(file_handler)


class ApexSentinelOrchestrator:

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._loop = asyncio.get_running_loop()
        self._event_bus = EventBus()
        self._sniffer: NetworkSniffer | None = None
        self._hash_chain: HashChainLogger | None = None
        self._pid_file: Path | None = None

    def _resolve_paths(self) -> dict[str, Path]:
        storage_cfg = self._config["storage"]
        base_path = Path(storage_cfg["base_path"])
        return {
            "base": base_path,
            "pcap_dir": base_path / storage_cfg["pcap_dir"],
            "logs_dir": base_path / storage_cfg["logs_dir"],
            "audit_chain_file": base_path / storage_cfg["audit_chain_file"],
        }

    def _write_pid_file(self) -> None:
        system_cfg = self._config.get("system", {})
        self._pid_file = Path(system_cfg.get(
            "pid_file", "/var/run/apex_sentinel_forensics.pid"))
        try:
            self._pid_file.parent.mkdir(parents=True, exist_ok=True)
            self._pid_file.write_text(str(os.getpid()), encoding="utf-8")
            _forensics_logger.debug(
                "Archivo PID escrito en '%s' (PID=%d).", self._pid_file, os.getpid())
        except OSError as exc:
            _forensics_logger.warning(
                "No fue posible escribir el archivo PID '%s': %s", self._pid_file, exc)

    def _remove_pid_file(self) -> None:
        if self._pid_file is None:
            return
        try:
            self._pid_file.unlink(missing_ok=True)
        except OSError as exc:
            _forensics_logger.warning(
                "No fue posible eliminar el archivo PID '%s': %s", self._pid_file, exc)

    async def _on_evidence_created(self, event: "Event") -> None:
        file_path = event.payload.get("file_path")
        if not file_path:
            _forensics_logger.error(
                "Evento EVIDENCE_CREATED sin 'file_path': %s", event.payload)
            return
        if self._hash_chain is None:
            _forensics_logger.error(
                "EVIDENCE_CREATED antes de inicializar HashChainLogger: %s", file_path)
            return

        seal_fn = functools.partial(
            self._hash_chain.seal_evidence,
            file_path,
            metadata={
                "packet_count": event.payload.get("packet_count"),
                "bytes_written": event.payload.get("bytes_written"),
                "interface": event.payload.get("interface"),
                "capture_opened_at": event.payload.get("opened_at"),
                "capture_closed_at": event.payload.get("closed_at"),
            },
        )
        try:
            block = await self._loop.run_in_executor(None, seal_fn)
        except FileNotFoundError:
            _forensics_logger.error(
                "El archivo de evidencia '%s' no existe; no pudo sellarse.", file_path)
            await self._event_bus.publish(EventType.CAPTURE_ERROR, payload={"file_path": file_path, "reason": "file_not_found"}, source="ApexSentinelOrchestrator")
            return
        except ChainIntegrityError as exc:
            _forensics_logger.exception(
                "Error de integridad al sellar '%s'.", file_path)
            await self._event_bus.publish(EventType.CAPTURE_ERROR, payload={"file_path": file_path, "reason": str(exc)}, source="ApexSentinelOrchestrator")
            return
        except Exception as exc:
            _forensics_logger.exception(
                "Error inesperado al sellar '%s'.", file_path)
            await self._event_bus.publish(EventType.CAPTURE_ERROR, payload={"file_path": file_path, "reason": str(exc)}, source="ApexSentinelOrchestrator")
            return

        _forensics_logger.info(
            "Evidencia sellada: bloque #%d para '%s'.", block.index, file_path)
        await self._event_bus.publish(
            EventType.EVIDENCE_SEALED,
            payload={"file_path": file_path, "block_index": block.index,
                     "block_hash": block.block_hash},
            source="ApexSentinelOrchestrator",
        )

    async def _log_all_events(self, event: "Event") -> None:
        _forensics_logger.debug("Evento: type=%s source=%s id=%s payload=%s",
                                event.type, event.source, event.event_id, event.payload)

    async def startup(self) -> None:
        paths = self._resolve_paths()
        for directory in (paths["pcap_dir"], paths["logs_dir"]):
            directory.mkdir(parents=True, exist_ok=True)

        await self._event_bus.start()

        integrity_cfg = self._config.get("integrity", {})
        self._hash_chain = HashChainLogger(
            chain_file_path=paths["audit_chain_file"], hash_algorithm=integrity_cfg.get(
                "hash_algorithm", "sha256"),
        )

        if integrity_cfg.get("auto_verify_on_start", True):
            _forensics_logger.info(
                "Verificando integridad de la cadena de custodia en '%s'...", paths["audit_chain_file"])
            result = await self._loop.run_in_executor(None, self._hash_chain.verify_chain)
            if result.is_valid:
                _forensics_logger.info(
                    "Cadena de custodia íntegra: %d bloque(s) verificado(s).", result.verified_blocks)
                await self._event_bus.publish(EventType.CHAIN_VERIFIED, payload=result.to_dict(), source=FORENSICS_APP_NAME)
            else:
                _forensics_logger.critical(
                    "¡ALERTA DE INTEGRIDAD! %d bloque(s) comprometido(s). Primer bloque afectado: #%s.",
                    len(result.failures), result.first_failure_index,
                )
                await self._event_bus.publish(EventType.CHAIN_COMPROMISED, payload=result.to_dict(), source=FORENSICS_APP_NAME)

        self._event_bus.subscribe(
            EventType.EVIDENCE_CREATED, self._on_evidence_created)
        self._event_bus.subscribe("*", self._log_all_events)

        network_cfg = self._config["network"]
        capture_cfg = self._config["capture"]
        rotation_policy = RotationPolicy(
            max_size_bytes=int(capture_cfg["max_file_size_bytes"]),
            max_duration_seconds=float(
                capture_cfg["max_file_duration_seconds"]),
        )
        self._sniffer = NetworkSniffer(
            interface=network_cfg["interface"],
            output_dir=paths["pcap_dir"],
            rotation_policy=rotation_policy,
            event_bus=self._event_bus,
            event_loop=self._loop,
            file_prefix=capture_cfg.get("file_prefix", FORENSICS_APP_NAME),
            bpf_filter=network_cfg.get("bpf_filter", ""),
            snapshot_length=int(network_cfg.get("snapshot_length", 65535)),
            promiscuous=bool(network_cfg.get("promiscuous_mode", True)),
            sync_writes=bool(capture_cfg.get("sync_writes", True)),
        )
        await self._loop.run_in_executor(None, self._sniffer.start)
        await self._event_bus.publish(EventType.CAPTURE_STARTED, payload={"interface": network_cfg["interface"]}, source=FORENSICS_APP_NAME)

        self._write_pid_file()
        _forensics_logger.info(
            "Subsistema forense operativo. Capturando tráfico en '%s'.", network_cfg["interface"])

    async def shutdown(self) -> None:
        _forensics_logger.info(
            "Iniciando apagado controlado del subsistema forense...")
        if self._sniffer is not None:
            await self._loop.run_in_executor(None, self._sniffer.stop)
            await self._event_bus.publish(EventType.CAPTURE_STOPPED, source=FORENSICS_APP_NAME)
        await asyncio.sleep(0.5)
        await self._event_bus.publish(EventType.SYSTEM_SHUTDOWN, source=FORENSICS_APP_NAME)
        await self._event_bus.stop(drain=True)
        self._remove_pid_file()
        _forensics_logger.info(
            "Subsistema forense detenido de forma segura. Evidencia sellada correctamente.")


class ForensicsManager:

    def __init__(self, sentinel: "ApexSentinel", config_path: str | os.PathLike[str] | None = None) -> None:
        self._sentinel = sentinel
        self._config_path_default = Path(config_path) if config_path else (
            _HERE / "config" / "forensics.yaml")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._orchestrator: ApexSentinelOrchestrator | None = None
        self._lock = threading.Lock()
        self._error: str | None = None
        self._config_path_actual: Path | None = None

    @property
    def activo(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def iniciar(self, config_path: str | os.PathLike[str] | None = None) -> bool:
        c = self._sentinel.console
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                c.print(
                    "[orange3][!] El subsistema forense ya está en ejecución.[/orange3]")
                return False

            ruta = Path(
                config_path) if config_path else self._config_path_default
            self._config_path_actual = ruta
            self._error = None
            listo = threading.Event()

            self._thread = threading.Thread(
                target=self._run_loop, args=(ruta, listo),
                name="ForensicsOrchestrator", daemon=True,
            )
            self._thread.start()

        listo.wait(timeout=15.0)

        if self._error:
            c.print(
                f"[red][!] No se pudo iniciar el subsistema forense: {self._error}[/red]")
            self._sentinel.log.error(self._error, "ForensicsManager")
            with self._lock:
                self._thread = None
            return False

        c.print(
            "[sea_green3][+] Subsistema forense activo[/sea_green3] "
            f"(config: [dim]{ruta}[/dim]). Captura y cadena de custodia en marcha."
        )
        self._sentinel.log.info(
            "Subsistema forense iniciado.", "ForensicsManager")
        return True

    def _run_loop(self, config_path: Path, listo: threading.Event) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            config = load_forensics_config(config_path)
            system_cfg = config.get("system", {})
            storage_cfg = config["storage"]
            configure_forensics_logging(
                log_level=system_cfg.get("log_level", "INFO"),
                log_dir=Path(storage_cfg["base_path"]) /
                storage_cfg["logs_dir"],
            )
            self._orchestrator = loop.run_until_complete(
                self._crear_orquestador(config))
        except Exception as error_arranque:
            self._error = str(error_arranque)
            listo.set()
            loop.close()
            return

        listo.set()
        try:
            loop.run_forever()
        finally:
            loop.close()

    async def _crear_orquestador(self, config: dict[str, Any]) -> "ApexSentinelOrchestrator":
        orquestador = ApexSentinelOrchestrator(config)
        await orquestador.startup()
        return orquestador

    def detener(self, timeout: float = 15.0) -> bool:
        c = self._sentinel.console
        with self._lock:
            hilo = self._thread
            loop = self._loop
            orquestador = self._orchestrator

        if hilo is None or not hilo.is_alive() or loop is None or orquestador is None:
            c.print(
                "[orange3][!] El subsistema forense no está en ejecución.[/orange3]")
            return False

        futuro = asyncio.run_coroutine_threadsafe(orquestador.shutdown(), loop)
        try:
            futuro.result(timeout=timeout)
        except Exception as error_apagado:
            self._sentinel.log.error(
                f"Fallo al apagar el subsistema forense: {error_apagado}", "ForensicsManager")
            c.print(
                f"[red][!] Error al detener el subsistema forense: {error_apagado}[/red]")

        loop.call_soon_threadsafe(loop.stop)
        hilo.join(timeout=timeout)

        with self._lock:
            self._thread = None
            self._loop = None
            self._orchestrator = None

        c.print(
            "[grey58][+] Subsistema forense detenido. Evidencia sellada.[/grey58]")
        self._sentinel.log.info(
            "Subsistema forense detenido.", "ForensicsManager")
        return True

    def estado(self) -> None:
        c = self._sentinel.console
        if not self.activo or self._orchestrator is None:
            c.print(
                "[dim][forense] Inactivo. Usa [bold white]forense start[/bold white] para iniciarlo.[/dim]")
            return
        sniffer = self._orchestrator._sniffer
        interfaz = getattr(sniffer, "interface", "?") if sniffer else "?"
        c.print(
            f"[sea_green3][forense] Activo[/sea_green3] — interfaz: [bold]{interfaz}[/bold] — "
            f"config: [dim]{self._config_path_actual}[/dim]"
        )


class ApexSentinel:

    VERSION = "2.3"
    NOMBRE = "ApexSentinel"

    def __init__(self) -> None:
        self._initialized: bool = False
        self.console = Console(highlight=False)
        self.log = LogSistema(self.console)

        self._coordinator: _ShutdownCoordinator = _ShutdownCoordinator()
        self._registrar_apagado_nucleo()
        self._registrar_senales()

        self.config = self._cargar_config()
        self.nombre: str = self.config.get(
            "sistema", {}).get("nombre", self.NOMBRE)
        self.version: str = self.config.get(
            "sistema", {}).get("version", self.VERSION)
        self.auth = GestorAuth(self.config, self.console, self.log)

        VendorResolver._USER_AGENT = f"ApexSentinel/{self.version}"

        self._registry = ModuleRegistry(self)
        self._registry.cargar_todos()

        if _FLIPPER_OK:
            self.flipper = FlipperModule(self)
        else:
            self.flipper = None

        if _FORENSICS_OK:
            self.forense = ForensicsManager(self)
        else:
            self.forense = None

        self._cmd = CommandHandler(self)
        self._command_map: dict[str,
                                ManejadorComando] = self._build_command_map()

        if self.config.get("sistema", {}).get("primer_arranque", False):
            self.config["sistema"]["primer_arranque"] = False
            self._guardar_config()

        mostrar_bootloader(
            self.console,
            nombre=self.nombre,
            version=self.version,
            iface=self._iface(),
            estados_modulos=self._registry.estados(),
        )

        self._initialized = True

    def __enter__(self) -> "ApexSentinel":
        if not self._initialized:
            raise RuntimeError("ApexSentinel no completó su inicialización")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        self._apagar()
        return False

    def _registrar_senales(self) -> None:
        def _signal_handler(signum: int, frame: Any) -> None:
            nombre_senal = signal.Signals(signum).name
            self.console.print(
                f"\n[orange3][!] Señal {nombre_senal} recibida. "
                f"Iniciando apagado coordinado.[/orange3]"
            )
            self._apagar()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        sigterm = getattr(signal, "SIGTERM", None)
        if sigterm is not None:
            signal.signal(sigterm, _signal_handler)

    def _apagar(self) -> None:
        senales_a_bloquear = {
            s for s in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None))
            if s is not None
        }
        puede_enmascarar = (
            hasattr(signal, "pthread_sigmask")
            and threading.current_thread() is threading.main_thread()
        )
        mascara_previa = None
        if puede_enmascarar:
            mascara_previa = signal.pthread_sigmask(
                signal.SIG_BLOCK, senales_a_bloquear)

        try:
            fallos = self._coordinator.trigger()
            for nombre, error in fallos:
                self._registrar_fallo_apagado(nombre, error)
        finally:
            if puede_enmascarar and mascara_previa is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, mascara_previa)

    def _registrar_fallo_apagado(self, nombre: str, error: BaseException) -> None:
        try:
            self.log.error(
                f"Fallo en apagado de '{nombre}': {error}", "ShutdownCoordinator")
        except Exception:
            pass

    def registrar_apagado(
        self,
        callback: Callable[[], None],
        nombre: str | None = None,
        prioridad: int = 0,
    ) -> None:
        self._coordinator.register_worker_shutdown(callback, nombre, prioridad)

    def _registrar_apagado_nucleo(self) -> None:
        self.registrar_apagado(self._detener_tareas_activas,
                               "ColaTareas", prioridad=100)
        self.registrar_apagado(self._detener_forense,
                               "SubsistemaForense", prioridad=90)
        self.registrar_apagado(self._cerrar_modulos_hardware,
                               "ModulosHardware", prioridad=80)
        self.registrar_apagado(self._cerrar_proyecto_activo,
                               "GestorProyectos", prioridad=60)
        self.registrar_apagado(
            self._registrar_cierre_sesion, "LogSistema", prioridad=0)

    def _detener_forense(self) -> None:
        forense = getattr(self, "forense", None)
        if forense is not None and forense.activo:
            forense.detener()

    def _detener_tareas_activas(self) -> None:
        cola = getattr(self, "cola", None)
        if cola is None:
            return
        limpiador = getattr(cola, "limpiar_completadas", None)
        if callable(limpiador):
            limpiador()

    def _cerrar_modulos_hardware(self) -> None:
        closeable_attrs: tuple[tuple[str, str], ...] = (
            ("radar",   "stop_sniffing"),
            ("rf",      "cerrar"),
            ("wifitri", "cerrar"),
            ("adsb",    "cerrar"),
            ("flipper", "_desconectar"),
        )
        for attr_name, method_name in closeable_attrs:
            module_instance = getattr(self, attr_name, None)
            if module_instance is None:
                continue
            closer = getattr(module_instance, method_name, None)
            if callable(closer):
                closer()

    def _cerrar_proyecto_activo(self) -> None:
        gp = getattr(self, "gp", None)
        if gp is not None and getattr(gp, "proyecto_activo", False):
            gp.cerrar_proyecto()

    def _registrar_cierre_sesion(self) -> None:
        try:
            self.log.info("Sesión terminada.", "ApexSentinel")
        finally:
            cerrador = getattr(self.log, "cerrar", None)
            if callable(cerrador):
                cerrador()

    def ejecutar_subproceso(
        self,
        comando: list[str],
        timeout: float,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        capturar_salida: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if self._coordinator.is_shutdown:
            raise SubprocesoRechazadoError(
                f"Apagado en curso, subproceso rechazado: {comando!r}"
            )
        if timeout is None or timeout <= 0:
            raise TimeoutRequeridoError(
                f"timeout obligatorio y positivo para: {comando!r}"
            )
        try:
            return subprocess.run(
                comando,
                timeout=timeout,
                cwd=cwd,
                env=env,
                capture_output=capturar_salida,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.log.error(
                f"Timeout ({timeout}s) ejecutando: {comando!r}", "Subproceso")
            raise
        except FileNotFoundError:
            self.log.error(
                f"Binario no encontrado: {comando[0]!r}", "Subproceso")
            raise
        except OSError as error_sistema:
            self.log.error(
                f"Error de sistema ejecutando {comando!r}: {error_sistema}", "Subproceso"
            )
            raise

    def _cargar_config(self) -> dict[str, Any]:
        try:
            with open("config.json", encoding="utf-8") as config_file:
                return json.load(config_file)
        except FileNotFoundError:
            return {
                "sistema": {
                    "nombre": "Sentinel",
                    "version": self.VERSION,
                    "primer_arranque": True,
                }
            }
        except json.JSONDecodeError:
            raise SystemExit("[FATAL] config.json está dañado.")

    def _guardar_config(self) -> None:
        try:
            with open("config.json", "w", encoding="utf-8") as config_file:
                json.dump(self.config, config_file,
                          ensure_ascii=False, indent=2)
        except OSError as write_error:
            self.log.warning(
                f"No se pudo guardar config.json: {write_error}", "Config")

    def _iface(self) -> str:
        return getattr(getattr(self, "bt", None), "iface", "wlan0mon")

    def _modulo_ok(self, nombre_attr: str) -> bool:
        if getattr(self, nombre_attr, None) is None:
            self.console.print(
                f"[orange3][!] Módulo '[bold]{nombre_attr}[/bold]' "
                f"no disponible en este entorno.[/orange3]"
            )
            return False
        return True

    def _limpiar(self) -> None:
        comando = ["cmd", "/c", "cls"] if os.name == "nt" else ["clear"]
        try:
            self.ejecutar_subproceso(
                comando, timeout=3.0, capturar_salida=False)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError, SubprocesoRechazadoError):
            pass

    def obtener_fabricante(self, mac: str) -> str:
        return VendorResolver.resolve(mac)

    def animar_barra(self, tarea: str, pasos: int = 20) -> None:
        animar_barra(self.console, tarea, pasos)

    def mostrar_dashboard_exito(self, ip: str, servicio: str, credencial: str) -> None:
        mostrar_dashboard_exito(
            self.console, self.log, ip, servicio, credencial,
            gp=getattr(self, "gp", None),
        )

    def _build_command_map(self) -> dict[str, ManejadorComando]:
        c = self._cmd

        def _banner(args: list[str]) -> None:
            proyecto_nombre = (
                self.gp.proyecto_actual.nombre
                if getattr(self, "gp", None) and getattr(self.gp, "proyecto_actual", None)
                else None
            )
            mostrar_banner(
                self.console, self.nombre, self.version, self._iface(),
                proyecto=proyecto_nombre,
            )

        def _btmapa(args: list[str]) -> None:
            if not self._modulo_ok("bt"):
                return
            try:
                from modules.network.bt_mapa import BLEMapaRadar
            except ImportError:
                self.console.print(
                    "[orange3][!] bt_mapa.py no encontrado en modules/network/[/orange3]"
                )
                return
            duracion = 120
            try:
                raw_input = self.console.input(
                    "\n[bold steel_blue1]  [?] Duración en segundos (Enter = 120)[/bold steel_blue1]: "
                ).strip()
                if raw_input.isdigit():
                    duracion = int(raw_input)
            except (KeyboardInterrupt, EOFError):
                pass
            BLEMapaRadar(self.bt).iniciar(duracion_seg=duracion)

        def _locate(args: list[str]) -> None:
            (c.locate_p if "-p" in args else c.locate)()

        def _forense(args: list[str]) -> None:
            if not self._modulo_ok("forense"):
                return
            sub = args[0] if args else "status"
            if sub in ("start", "iniciar", "on"):
                ruta_config = args[1] if len(args) > 1 else None
                self.forense.iniciar(ruta_config)
            elif sub in ("stop", "detener", "off"):
                self.forense.detener()
            elif sub in ("status", "estado"):
                self.forense.estado()
            else:
                self.console.print(
                    "[orange3][?] Uso: forense <start|stop|status> [ruta_config][/orange3]"
                )

        return {
            "help": lambda args: mostrar_ayuda(
                self.console, self.version, COMANDOS_HELP,
                " ".join(args) if args else None),
            "?": lambda args: mostrar_ayuda(
                self.console, self.version, COMANDOS_HELP,
                " ".join(args) if args else None),
            "status": lambda args: c.status(),
            "hora": lambda args: self.console.print(
                f"[steel_blue1]Hora:[/steel_blue1] {time.strftime('%H:%M:%S')}"),
            "clear":       _banner,
            "cls":         _banner,
            "logs": lambda args: self.log.mostrar_historial(),
            "files": lambda args: c.files(),
            "scan": lambda args: c.scan(),
            "netscan": lambda args: c.scan(),
            "advscan": lambda args: c.advscan(),
            "portscan": lambda args: c.portscan(),
            "sweep": lambda args: c.sweep(),
            "sniff": lambda args: c.sniff(),
            "radar": lambda args: c.radar(),
            "audit": lambda args: c.audit(),
            "vulnscan": lambda args: c.vulnscan(),
            "sqlcheck": lambda args: c.sqlcheck(),
            "wifi": lambda args: c.wifi(),
            "eviltwin": lambda args: c.eviltwin(),
            "btjumper": lambda args: (
                self.bt.iniciar_jumper() if self._modulo_ok("bt") else None),
            "btmapa":      _btmapa,
            "rfscan": lambda args: c.rfscan(),
            "rfmenu": lambda args: c.rfmenu(),
            "rfbarrido": lambda args: c.rfbarrido(),
            "rfbandas": lambda args: c.rfbandas(),
            "rfdb": lambda args: c.rfdb(),
            "rfstats": lambda args: c.rfstats(),
            "rfstatus": lambda args: c.rfestado(),
            "radio": lambda args: c.radio(),
            "rfgrabar": lambda args: c.rfgrabar(),
            "rfplay": lambda args: c.rfplay(),
            "adsb": lambda args: c.adsb(),
            "noaa": lambda args: c.noaa(),
            "wifitri": lambda args: (
                self.wifitri.menu() if self._modulo_ok("wifitri") else None),
            "spectrum": lambda args: c.spectrum(),
            "sa": lambda args: c.spectrum(),
            "mobile": lambda args: c.mobile(),
            "mobile-deep": lambda args: c.mobile_deep(),
            "view": lambda args: c.view(),
            "geofoto": lambda args: c.geofoto(),
            "osint": lambda args: c.osint(),
            "cve": lambda args: c.cve(),
            "phishing": lambda args: c.phishing(),
            "ducky": lambda args: c.ducky(),
            "stealth": lambda args: c.stealth(),
            "panic": lambda args: c.panic(),
            "proyecto": lambda args: c.proyecto(args),
            "reporte": lambda args: c.reporte(args),
            "job": lambda args: c.jobs(args),
            "jobs": lambda args: c.jobs(args),
            "plugin": lambda args: c.plugins(args),
            "plugins": lambda args: c.plugins(args),
            "locate":      _locate,
            "recover": lambda args: c.recover(args),
            "flipper": lambda args: (
                self.flipper.menu() if self._modulo_ok("flipper") else None),
            "flipper-status": lambda args: (
                self.flipper.status() if self._modulo_ok("flipper") else None),
            "flipper-nfc": lambda args: (
                self.flipper.nfc_scan() if self._modulo_ok("flipper") else None),
            "flipper-rfid": lambda args: (
                self.flipper.rfid_scan() if self._modulo_ok("flipper") else None),
            "flipper-capture": lambda args: (
                self.flipper.subghz_capture() if self._modulo_ok("flipper") else None),
            "flipper-list": lambda args: (
                self.flipper.subghz_list() if self._modulo_ok("flipper") else None),
            "forense":     _forense,
        }

    def _despachar(self, entrada: str) -> bool:
        partes = entrada.strip().lower().split()
        if not partes:
            return True

        cmd, args = partes[0], partes[1:]

        handler = self._command_map.get(cmd)
        if handler is not None:
            try:
                handler(args)
            except Exception as dispatch_error:
                self.console.print(
                    f"[red][!] Error en '{cmd}': {dispatch_error}[/red]")
                self.log.error(str(dispatch_error), f"cmd:{cmd}")
            return True

        plugin_registry = getattr(self, "plugins", None)
        if plugin_registry is not None and plugin_registry.tiene_comando(cmd):
            plugin_registry.ejecutar_comando(cmd, args)
            return True

        return False

    def ejecutar(self) -> None:
        if not self.auth.solicitar_acceso():
            self.console.print(
                "[red][!] Acceso denegado. Sistema bloqueado.[/red]")
            self.log.warning(
                "Sistema bloqueado por intentos fallidos.", "GestorAuth")
            return

        dependency_checker = getattr(self, "checker", None)
        stealth_module = getattr(self, "stealth", None)

        with self.console.capture():
            if dependency_checker is not None:
                dependency_checker.verificar_dependencias()

            self.log.verificar_y_limpiar()

            if stealth_module is not None:
                stealth_module.verificar_identidad()

        self.log.info("Sistema iniciado correctamente.", "ApexSentinel")

        rf_module = getattr(self, "rf", None)
        if rf_module is not None:
            rf_hardware_tag = (
                f"[sea_green3]{rf_module.hw_nombre}[/sea_green3]"
                if rf_module.hw_disponible
                else f"[orange3]{rf_module.hw_nombre}[/orange3]"
            )
            self.console.print(
                f"\n[dim][RF] Hardware: {rf_hardware_tag}[/dim]")

        gp_module = getattr(self, "gp", None)
        if gp_module is not None and not gp_module.proyecto_activo:
            self.console.print(
                "\n[dim][tip] Usa [bold white]proyecto nuevo[/bold white] "
                "para crear un workspace de operación.[/dim]\n"
            )

        while not self._coordinator.is_shutdown:
            try:
                proyecto_label = (
                    f"[{_esc(str(self.gp.proyecto_activo.nombre))}]"
                    if getattr(self, "gp", None) and self.gp.proyecto_activo
                    else ""
                )
                prompt_str = (
                    f"[bold steel_blue1]AnubisOS[/bold steel_blue1]"
                    f"[dim white]@[/dim white]"
                    f"[bold white]Sentinel[/bold white]"
                    f"[dim]{proyecto_label}[/dim]"
                    f"[bold white]~#[/bold white]"
                )
                entrada = Prompt.ask(prompt_str, default="").strip()

                if not entrada:
                    continue

                if entrada.lower() == "exit":
                    self.console.print(
                        "[grey58][!] Desconectando Sentinel...[/grey58]")
                    self.log.info(
                        "Sesión cerrada por el operador.", "ApexSentinel")
                    time.sleep(0.5)
                    break

                if not self._despachar(entrada):
                    self.console.print(
                        f"[orange3][?] Comando '[bold]{entrada}[/bold]' no "
                        f"reconocido. Escribe [bold white]help[/bold white] "
                        f"para ver opciones.[/orange3]"
                    )

            except EOFError:
                break
            except Exception as loop_error:
                self.console.print(
                    f"[red][!] Error inesperado: {loop_error}[/red]")
                self.log.error(str(loop_error), "Bucle principal")


def main() -> None:
    try:
        _validate_bootstrap()
    except BootstrapError as bootstrap_failure:
        sys.stderr.write(str(bootstrap_failure) + "\n")
        sys.exit(1)

    with ApexSentinel() as sentinel:
        sentinel.ejecutar()


if __name__ == "__main__":
    main()
