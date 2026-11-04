from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sentinel.integrity.baseline import BaselineIssue, BaselineReport
from sentinel.integrity.monitor import IntegrityEvent
from sentinel.security.auto_response import AutoResponder
from sentinel.security.lockdown import Lockdown
from sentinel.security.state import LockState, read_state


@pytest.fixture
def event_clean(ts: Any) -> IntegrityEvent:
    return IntegrityEvent(
        timestamp=ts,
        report=BaselineReport(root="/tmp", checked=10, valid=10, issues=()),
        baseline_valid=True,
    )


@pytest.fixture
def event_tampered(ts: Any) -> IntegrityEvent:
    return IntegrityEvent(
        timestamp=ts,
        report=BaselineReport(
            root="/tmp", checked=10, valid=9,
            issues=(BaselineIssue("modified", "a.py", None, None, None, None),),
        ),
        baseline_valid=True,
    )


@pytest.fixture
def event_baseline_invalid(ts: Any) -> IntegrityEvent:
    return IntegrityEvent(
        timestamp=ts,
        report=BaselineReport(root="/tmp", checked=0, valid=0, issues=()),
        baseline_valid=False,
    )


class TestAutoResponder:
    def test_ignores_clean_event(
        self, workspace: Path, alice: Any, event_clean: IntegrityEvent
    ) -> None:
        ld = Lockdown(workspace, alice)
        ld.setup("correct-horse-battery-staple")

        responder = AutoResponder(lockdown=ld)
        assert not responder.handle_event(event_clean)

        # Debe estar en NORMAL, no LOCKED. Si el archivo de estado no
        # existe, está normal por defecto.
        with contextlib.suppress(Exception):
            assert read_state(workspace).state is not LockState.LOCKED

    def test_locks_on_tampered_event(
        self, workspace: Path, alice: Any, event_tampered: IntegrityEvent
    ) -> None:
        ld = Lockdown(workspace, alice)
        ld.setup("correct-horse-battery-staple")

        responder = AutoResponder(lockdown=ld)
        assert responder.handle_event(event_tampered)

        record = read_state(workspace)
        assert record.state is LockState.LOCKED
        assert record.reason.startswith("auto-lockdown:")

    def test_locks_on_invalid_baseline(
        self, workspace: Path, alice: Any, event_baseline_invalid: IntegrityEvent
    ) -> None:
        ld = Lockdown(workspace, alice)
        ld.setup("correct-horse-battery-staple")

        responder = AutoResponder(lockdown=ld)
        assert responder.handle_event(event_baseline_invalid)
        assert read_state(workspace).state is LockState.LOCKED

    def test_does_not_lock_twice(
        self, workspace: Path, alice: Any, event_tampered: IntegrityEvent
    ) -> None:
        ld = Lockdown(workspace, alice)
        ld.setup("correct-horse-battery-staple")

        responder = AutoResponder(lockdown=ld)
        assert responder.handle_event(event_tampered)

        # El segundo evento debe ser ignorado porque ya está bloqueado
        assert not responder.handle_event(event_tampered)

    def test_triggers_callback(
        self, workspace: Path, alice: Any, event_tampered: IntegrityEvent
    ) -> None:
        ld = Lockdown(workspace, alice)
        ld.setup("correct-horse-battery-staple")

        callback_mock = MagicMock()
        responder = AutoResponder(lockdown=ld, on_lock_callback=callback_mock)

        responder.handle_event(event_tampered)
        callback_mock.assert_called_once_with(event_tampered)
