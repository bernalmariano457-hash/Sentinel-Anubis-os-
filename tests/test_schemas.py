from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sentinel.custody.log import CustodyAction, CustodyLog
from sentinel.integrity.hashing import hash_file
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.signing import sign_artifact_manifest, write_signature
from sentinel.integrity.timestamp import TimeSource, Timestamp
from sentinel.packaging.sae import pack
from sentinel.schemas import (
    SchemaNotFoundError,
    SchemaValidationError,
    is_valid,
    load_schema,
    registered_schemas,
    schema_path,
    validate,
)


@pytest.fixture
def alice(memory_keyring: Any) -> KeyManager:
    return KeyManager.generate("Alice", operator_id="op-alice")


@pytest.fixture
def ts_gps() -> Timestamp:
    return Timestamp(
        iso_utc="2026-10-26T15:00:00Z",
        source=TimeSource.GPS,
        uncertainty_ms=5,
    )


class TestLoader:
    def test_all_registered_schemas_load(self) -> None:
        for name in registered_schemas():
            assert isinstance(load_schema(name), dict)

    def test_unknown_schema_rejected(self) -> None:
        with pytest.raises(SchemaNotFoundError):
            load_schema("does-not-exist")

    def test_schema_files_exist(self) -> None:
        for name in registered_schemas():
            assert schema_path(name).is_file()


class TestValidation:
    def test_bad_instance_raises(self) -> None:
        with pytest.raises(SchemaValidationError):
            validate({"schema_version": "1.0"}, "operator")

    def test_is_valid_returns_false(self) -> None:
        assert is_valid({"schema_version": "1.0"}, "operator") is False

    def test_valid_instance_passes(self, alice: KeyManager) -> None:
        validate(alice.identity.to_dict(), "operator")


class TestOperatorSchema:
    def test_real_output_validates(self, alice: KeyManager) -> None:
        validate(alice.identity.to_dict(), "operator")

    def test_rotated_identity_validates(self, alice: KeyManager) -> None:
        bob = alice.rotate()
        validate(bob.identity.to_dict(), "operator")

    def test_revoked_identity_validates(self, alice: KeyManager) -> None:
        from dataclasses import replace

        revoked = replace(alice.identity, revoked_at="2026-10-26T16:00:00Z")
        validate(revoked.to_dict(), "operator")


class TestCustodyEntrySchema:
    def test_real_output_validates(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        entry = log.append(
            alice,
            CustodyAction.CREATE,
            timestamp=ts_gps,
            artifact_id="6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
            details={"file_sha256": "a" * 64},
        )
        validate(entry, "custody-entry")

    def test_pack_action_validates(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        entry = log.append(
            alice,
            CustodyAction.PACK,
            timestamp=ts_gps,
            package_id="pkg-1",
        )
        validate(entry, "custody-entry")


class TestArtifactManifestSchema:
    def test_real_output_validates(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        d = tmp_path / "art-1"
        d.mkdir()
        data_path = d / "data.bin"
        data_path.write_bytes(b"iq" * 500)
        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "artifact_id": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
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
        validate(manifest, "artifact-manifest")


class TestPackageManifestSchema:
    def test_real_output_validates(
        self, alice: KeyManager, tmp_path: Path, ts_gps: Timestamp
    ) -> None:
        d = tmp_path / "art-1"
        d.mkdir()
        (d / "data.bin").write_bytes(b"iq" * 500)
        manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "artifact_id": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
            "type": "iq",
            "operator_id": "op-alice",
            "created_at": "2026-10-26T14:00:05Z",
            "time_source": "gps",
            "time_uncertainty_ms": 5,
            "file": {
                "name": "data.bin",
                "size_bytes": (d / "data.bin").stat().st_size,
                "sha256": hash_file(d / "data.bin"),
            },
        }
        sig = sign_artifact_manifest(alice, manifest)
        manifest["signature"] = sig.to_dict()
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        write_signature(d / "signature.sig", sig)

        custody_path = tmp_path / "custody.log"
        log = CustodyLog(custody_path)
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)

        out = tmp_path / "pkg.sae"
        pkg_manifest = pack(
            out, alice, "op-1", [d], custody_path, timestamp=ts_gps
        )
        validate(pkg_manifest, "package-manifest")


class TestOperationSchema:
    def test_minimal_valid(self) -> None:
        op = {
            "schema_version": "1.0",
            "operation_id": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
            "name": "Auditoría RF",
            "operator_id": "op-alice",
            "started_at": "2026-10-26T14:00:00Z",
            "time_source": "gps",
            "time_uncertainty_ms": 5,
            "jurisdiction": "MX",
            "legal_basis": "Contrato #2026-042",
            "device": {"model": "uConsole", "serial": "UC-1", "os_version": "0.1.0"},
        }
        validate(op, "operation")

    def test_full_valid(self) -> None:
        op = {
            "schema_version": "1.0",
            "operation_id": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
            "name": "Auditoría RF",
            "description": "Barrido 100-1000 MHz",
            "operator_id": "op-alice",
            "started_at": "2026-10-26T14:00:00Z",
            "ended_at": None,
            "time_source": "gps",
            "time_uncertainty_ms": 5,
            "location": {"lat": 19.4326, "lon": -99.1332, "alt_m": 2240},
            "jurisdiction": "MX",
            "legal_basis": "Contrato #2026-042",
            "device": {"model": "uConsole", "serial": "UC-1", "os_version": "0.1.0"},
            "tags": ["rf", "audit"],
        }
        validate(op, "operation")


class TestTimelineEventSchema:
    def test_minimal_valid(self) -> None:
        ev = {
            "schema_version": "1.0",
            "event_id": "11111111-2222-3333-4444-555555555555",
            "timestamp": "2026-10-26T14:00:30Z",
            "time_uncertainty_ms": 50,
            "source": "rf",
            "type": "signal_detected",
            "artifact_ref": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
            "artifact_hash": "a" * 64,
            "description": "Señal ADS-B detectada",
        }
        validate(ev, "timeline-event")
