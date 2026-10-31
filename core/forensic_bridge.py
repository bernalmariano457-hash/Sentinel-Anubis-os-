"""Puente entre el sistema legacy y el módulo forense de seguridad."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from sentinel.security import Lockdown, LockState, read_state, StateError
from sentinel.integrity.monitor import IntegrityMonitor
from sentinel.integrity.baseline import Baseline
from sentinel.integrity.keys import KeyManager
from sentinel.security.auto_response import AutoResponder

logger = logging.getLogger(__name__)


def get_lockdown(workspace: Path, operator_id: str) -> Lockdown:
    """Carga el operador y devuelve una instancia de Lockdown."""
    km = KeyManager.load(operator_id, operator_id)
    return Lockdown(workspace, km)


def is_system_locked(workspace: Path) -> bool:
    """Revisa el archivo de estado. Devuelve True si está bloqueado."""
    try:
        record = read_state(workspace)
        return record.state is LockState.LOCKED
    except StateError:
        # Si no hay archivo de estado, el sistema está limpio (NORMAL).
        return False


def start_integrity_monitor(workspace: Path, operator_id: str, baseline_path: Path) -> None:
    """
    Inicia el monitor de integridad en un hilo de fondo.
    Si detecta un hackeo, dispara el AutoResponder.
    """
    def _monitor_loop() -> None:
        try:
            km = KeyManager.load(operator_id, operator_id)
            baseline = Baseline.load(baseline_path)
            lockdown = Lockdown(workspace, km)
            
            monitor = IntegrityMonitor(baseline, km.identity)
            responder = AutoResponder(lockdown=lockdown)
            
            # Corre en bucle, cada 60 segundos
            monitor.run_forever(
                interval_s=60.0,
                on_event=responder.handle_event,
                check_extras=False
            )
        except Exception as e:
            logger.error("Fallo el monitor de integridad en segundo plano: %s", e)

    # Iniciar en un hilo daemon para que muera cuando se cierre Main.py
    thread = threading.Thread(target=_monitor_loop, daemon=True, name="IntegrityMonitor")
    thread.start()
    logger.info("Monitor de integridad iniciado en segundo plano.")