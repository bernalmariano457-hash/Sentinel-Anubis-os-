from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sentinel.integrity.keys import KeyManager
from sentinel.integrity.timestamp import TimeSource, Timestamp
from sentinel.security import Lockdown, vault

PASSPHRASE = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault, "ARGON2_ITERATIONS", 1)
    monkeypatch.setattr(vault, "ARGON2_MEMORY_KIB", 1024)


@pytest.fixture
def passphrase() -> str:
    return PASSPHRASE


@pytest.fixture
def alice(memory_keyring: Any) -> KeyManager:
    return KeyManager.generate("Alice")


@pytest.fixture
def bob(memory_keyring: Any) -> KeyManager:
    return KeyManager.generate("Bob")


@pytest.fixture
def ts() -> Timestamp:
    return Timestamp("2026-01-15T12:00:00Z", TimeSource.SYSTEM, 50)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch: pytest.MonkeyPatch, ts: Timestamp) -> None:
    monkeypatch.setattr(Lockdown, "_now", lambda self: ts)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    base = tmp_path / "workspace"
    (base / "evidence").mkdir(parents=True)
    (base / "config").mkdir()
    (base / "evidence" / "artifact.bin").write_bytes(b"\x00\x01evidence-bytes\xff" * 32)
    (base / "config" / "operation.json").write_text('{"operation": "test"}\n', encoding="utf-8")
    return base
