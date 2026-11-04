from __future__ import annotations

import logging
import threading
from pathlib import Path

from sentinel.integrity.baseline import Baseline
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.monitor import IntegrityMonitor
from sentinel.security import Lockdown, LockState, StateError, read_state
from sentinel.security.auto_response import AutoResponder

logger = logging.getLogger(__name__)


def get_lockdown(workspace: Path, operator_id: str) -> Lockdown:
    km = KeyManager.load(operator_id, operator_id)
    return Lockdown(workspace, km)


def is_system_locked(workspace: Path) -> bool:
    try:
        record = read_state(workspace)
        return record.state is LockState.LOCKED
    except StateError:
        # Si no hay archivo de estado, el sistema está limpio (NORMAL).
        return False


def start_integrity_monitor(workspace: Path, operator_id: str, baseline_path: Path) -> None:

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
            logger.error(
                "Fallo el monitor de integridad en segundo plano: %s", e)

    thread = threading.Thread(target=_monitor_loop,
                              daemon=True, name="IntegrityMonitor")
    thread.start()
    logger.info("Monitor de integridad iniciado en segundo plano.")
