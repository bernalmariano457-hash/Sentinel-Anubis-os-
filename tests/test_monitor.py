from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sentinel.integrity.baseline import Baseline
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.monitor import IntegrityEvent, IntegrityMonitor
from sentinel.integrity.timestamp import TimeSource, Timestamp

FILES = {"a.py": "print('a')\n", "pkg/b.py": "print('b')\n", "README.md": "# readme\n"}


@pytest.fixture
def alice(memory_keyring: Any) -> KeyManager:
    return KeyManager.generate("Alice")


@pytest.fixture
def bob(memory_keyring: Any) -> KeyManager:
    return KeyManager.generate("Bob")


@pytest.fixture
def ts() -> Timestamp:
    return Timestamp("2026-01-15T12:00:00Z", TimeSource.SYSTEM, 50)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "root"
    for rel, content in FILES.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return base


@pytest.fixture
def baseline(alice: KeyManager, ts: Timestamp, root: Path) -> Baseline:
    return Baseline.create(alice, root, ts)


class TestCheckOnce:
    def test_clean(self, baseline: Baseline, alice: KeyManager, ts: Timestamp) -> None:
        monitor = IntegrityMonitor(baseline, alice.identity, clock=lambda: ts)
        event = monitor.check_once()
        assert event.baseline_valid
        assert not event.is_violation
        assert event.timestamp == ts
        assert event.report.checked == len(FILES)
        assert monitor.baseline is baseline

    def test_detects_modification(self, baseline: Baseline, alice: KeyManager, ts: Timestamp, root: Path) -> None:
        (root / "a.py").write_text("print('X')\n", encoding="utf-8")
        event = IntegrityMonitor(baseline, alice.identity, clock=lambda: ts).check_once(root)
        assert event.baseline_valid
        assert event.is_violation
        assert [i.code for i in event.report.issues] == ["modified"]
        assert "modified" in event.summary()

    def test_detects_extras_when_requested(
        self, baseline: Baseline, alice: KeyManager, ts: Timestamp, root: Path
    ) -> None:
        (root / "new.py").write_text("x = 1\n", encoding="utf-8")
        monitor = IntegrityMonitor(baseline, alice.identity, clock=lambda: ts)
        assert not monitor.check_once(root).is_violation
        assert monitor.check_once(root, check_extras=True).is_violation

    def test_detects_invalid_baseline_signature(self, baseline: Baseline, bob: KeyManager, ts: Timestamp) -> None:
        event = IntegrityMonitor(baseline, bob.identity, clock=lambda: ts).check_once()
        assert not event.baseline_valid
        assert event.is_violation
        assert event.report.checked == 0
        assert event.report.issues == ()
        assert "signature invalid" in event.summary()

    def test_default_clock_produces_timestamp(self, baseline: Baseline, alice: KeyManager) -> None:
        event = IntegrityMonitor(baseline, alice.identity).check_once()
        assert isinstance(event.timestamp, Timestamp)


class TestRunForever:
    def test_stops_when_stop_returns_true(self, baseline: Baseline, alice: KeyManager, ts: Timestamp) -> None:
        monitor = IntegrityMonitor(baseline, alice.identity, clock=lambda: ts)
        events: list[IntegrityEvent] = []
        monitor.run_forever(0.001, events.append, stop=lambda: len(events) >= 3)
        assert len(events) == 3
        assert not any(e.is_violation for e in events)

    def test_does_not_run_if_already_stopped(self, baseline: Baseline, alice: KeyManager, ts: Timestamp) -> None:
        monitor = IntegrityMonitor(baseline, alice.identity, clock=lambda: ts)
        events: list[IntegrityEvent] = []
        monitor.run_forever(0.001, events.append, stop=lambda: True)
        assert events == []

    @pytest.mark.parametrize("interval", [0, -1, -0.5])
    def test_rejects_non_positive_interval(
        self, baseline: Baseline, alice: KeyManager, ts: Timestamp, interval: float
    ) -> None:
        monitor = IntegrityMonitor(baseline, alice.identity, clock=lambda: ts)
        with pytest.raises(ValueError):
            monitor.run_forever(interval, lambda event: None, stop=lambda: True)
