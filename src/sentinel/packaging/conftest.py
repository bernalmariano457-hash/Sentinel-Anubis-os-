from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinel.custody.log import CustodyAction, CustodyLog
from sentinel.integrity.hashing import hash_file
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.signing import sign_artifact_manifest, write_signature
from sentinel.integrity.timestamp import TimeSource, Timestamp


@pytest.fixture
def alice(memory_keyring) -> KeyManager:
    return KeyManager.generate("Alice", operator_id="op-alice")


@pytest.fixture
def ts_gps() -> Timestamp:
    return Timestamp(
        iso_utc="2026-10-26T15:00:00Z",
        source=TimeSource.GPS,
        uncertainty_ms=5,
    )


@pytest.fixture
def artifact_dir(alice: KeyManager, tmp_path: Path) -> Path:
    d = tmp_path / "artifacts" / "art-1"
    d.mkdir(parents=True)

    data_path = d / "data.bin"
    data_path.write_bytes(b"fake iq data" * 100)
    file_hash = hash_file(data_path)

    manifest = {
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
            "sha256": file_hash,
        },
    }
    sig = sign_artifact_manifest(alice, manifest)
    manifest["signature"] = sig.to_dict()
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_signature(d / "signature.sig", sig)

    return d


@pytest.fixture
def custody_log_path(
    alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
) -> Path:
    path = tmp_path / "custody.log"
    log = CustodyLog(path)
    log.append(
        alice,
        CustodyAction.CREATE,
        timestamp=ts_gps,
        artifact_id="art-1",
        details={"file_sha256": "a" * 64},
    )
    log.append(
        alice,
        CustodyAction.VERIFY,
        timestamp=ts_gps,
        artifact_id="art-1",
    )
    return path
