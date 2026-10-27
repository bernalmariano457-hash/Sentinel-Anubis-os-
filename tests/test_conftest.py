from __future__ import annotations

import pytest

from sentinel.integrity.keys import KeyManager
from sentinel.integrity.timestamp import TimeSource, Timestamp


@pytest.fixture
def alice(memory_keyring) -> KeyManager:
    return KeyManager.generate("Alice", operator_id="op-alice")


@pytest.fixture
def bob(memory_keyring) -> KeyManager:
    return KeyManager.generate("Bob", operator_id="op-bob")


@pytest.fixture
def ts_gps() -> Timestamp:
    return Timestamp(
        iso_utc="2026-10-26T14:00:05Z",
        source=TimeSource.GPS,
        uncertainty_ms=5,
        provider_detail="gpsd:/dev/ttyUSB0",
    )


@pytest.fixture
def ts_system() -> Timestamp:
    return Timestamp(
        iso_utc="2026-10-26T14:00:05Z",
        source=TimeSource.SYSTEM,
        uncertainty_ms=1000,
    )
