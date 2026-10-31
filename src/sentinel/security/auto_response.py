"""Automated response to integrity violations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from sentinel.integrity.monitor import IntegrityEvent
from sentinel.security.lockdown import Lockdown, LockdownError
from sentinel.security.state import LockState, read_state, StateError

logger = logging.getLogger(__name__)


class AutoResponseError(Exception):
    """Base error for auto-response failures."""


@dataclass
class AutoResponder:
    """Listens to IntegrityEvents and triggers Lockdown when a violation occurs."""
    
    lockdown: Lockdown
    on_lock_callback: Callable[[IntegrityEvent], None] | None = None

    def handle_event(self, event: IntegrityEvent) -> bool:
        """
        Evaluates an event and locks the system if necessary.
        Returns True if the system was locked, False otherwise.
        """
        if not event.is_violation:
            return False

        try:
            current_state = read_state(self.lockdown.workspace)
            if current_state.state is LockState.LOCKED:
                return False
        except StateError:
            pass

        reason = f"auto-lockdown: {event.summary()}"
        details = {
            "trigger": "integrity_violation",
            "baseline_valid": event.baseline_valid,
            "issues_count": len(event.report.issues),
            "event_time": event.timestamp.iso_utc,
        }

        try:
            # Block without passphrase: failsafe mode
            self.lockdown.lock(passphrase=None, reason=reason, details=details)
            logger.warning("SYSTEM AUTO-LOCKED: %s", reason)
            
            if self.on_lock_callback:
                self.on_lock_callback(event)
                
            return True
        except LockdownError as e:
            logger.error("Failed to auto-lock system: %s", e)
            return False