from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import keyring
import keyring.backend
import keyring.core
import pytest
from sentinel.custody.log import CustodyAction, CustodyLog
from sentinel.integrity.hashing import hash_file
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.signing import sign_artifact_manifest, write_signature
from sentinel.integrity.timestamp import TimeSource, Timestamp


class InMemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self._store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self._store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self._store:
            raise keyring.errors.PasswordDeleteError(
                f"no entry for {service}/{username}"
            )
        del self._store[(service, username)]


@pytest.fixture
def memory_keyring(monkeypatch: pytest.MonkeyPatch) -> InMemoryKeyring:
    backend = InMemoryKeyring()
    monkeypatch.setattr(keyring.core, "_keyring_backend", backend)
    return backend


@pytest.fixture
def alice(memory_keyring: InMemoryKeyring) -> KeyManager:
    return KeyManager.generate("Alice", operator_id="op-alice")


@pytest.fixture
def bob(memory_keyring: InMemoryKeyring) -> KeyManager:
    return KeyManager.generate("Bob", operator_id="op-bob")


@pytest.fixture
def ts_gps() -> Timestamp:
    return Timestamp(
        iso_utc="2026-10-26T14:00:05Z", source=TimeSource.GPS, uncertainty_ms=50
    )


@pytest.fixture
def artifact_dir(alice: KeyManager, tmp_path: Path) -> Path:
    d = tmp_path / "artifacts" / "art-1"
    d.mkdir(parents=True)
    data_path = d / "data.bin"
    data_path.write_bytes(b"fake iq data" * 100)
    (d / "data.sigmf-meta").write_text("{}", encoding="utf-8")
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_id": "art-1",
        "type": "iq",
        "operator_id": "op-alice",
        "created_at": "2026-10-26T14:00:05Z",
        "time_source": "gps",
        "time_uncertainty_ms": 5,
        "file": {
            "name": "data.bin",
            "size_bytes": data_path.stat().st_size,
            "sha256": hash_file(data_path),
        },
    }
    sig = sign_artifact_manifest(alice, manifest)
    manifest["signature"] = sig.to_dict()
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_signature(d / "signature.sig", sig)
    return d


@pytest.fixture
def custody_log_path(alice: KeyManager, ts_gps: Timestamp, tmp_path: Path) -> Path:
    path = tmp_path / "custody.log"
    log = CustodyLog(path)
    log.append(alice, CustodyAction.CREATE, timestamp=ts_gps, artifact_id="art-1")
    log.append(alice, CustodyAction.VERIFY, timestamp=ts_gps, artifact_id="art-1")
    return path
