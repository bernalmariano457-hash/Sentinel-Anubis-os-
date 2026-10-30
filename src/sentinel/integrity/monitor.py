from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sentinel.integrity.baseline import Baseline, BaselineReport, BaselineSignError
from sentinel.integrity.keys import OperatorIdentity
from sentinel.integrity.timestamp import SystemClock, Timestamp

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntegrityEvent:

    timestamp: Timestamp
    report: BaselineReport
    baseline_valid: bool

    @property
    def is_violation(self) -> bool:
        return not self.baseline_valid or not self.report.is_clean

    def summary(self) -> str:
        if not self.baseline_valid:
            return f"{self.timestamp.iso_utc} baseline signature invalid"
        return f"{self.timestamp.iso_utc} {self.report.summary()}"


class IntegrityMonitor:
    """Runs baseline checks on demand or in a caller-driven loop."""

    def __init__(
        self,
        baseline: Baseline,
        operator: OperatorIdentity,
        clock: Callable[[], Timestamp] | None = None,
    ) -> None:
        self._baseline = baseline
        self._operator = operator
        self._clock: Callable[[
        ], Timestamp] = clock if clock is not None else SystemClock().now

    @property
    def baseline(self) -> Baseline:
        return self._baseline

    def check_once(self, root: Path | str | None = None, check_extras: bool = False) -> IntegrityEvent:
        timestamp = self._clock()
        try:
            self._baseline.verify_signature(self._operator)
        except BaselineSignError as e:
            logger.warning("baseline signature verification failed: %s", e)
            empty = BaselineReport(
                root=self._baseline.root, checked=0, valid=0, issues=())
            return IntegrityEvent(timestamp=timestamp, report=empty, baseline_valid=False)
        report = self._baseline.verify_files(
            root=root, check_extras=check_extras)
        return IntegrityEvent(timestamp=timestamp, report=report, baseline_valid=True)

    def run_forever(
        self,
        interval_s: float,
        on_event: Callable[[IntegrityEvent], None],
        stop: Callable[[], bool] | None = None,
        root: Path | str | None = None,
        check_extras: bool = False,
    ) -> None:
        """Check every interval_s seconds until stop() returns True."""
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        while stop is None or not stop():
            on_event(self.check_once(root=root, check_extras=check_extras))
            time.sleep(interval_s)
