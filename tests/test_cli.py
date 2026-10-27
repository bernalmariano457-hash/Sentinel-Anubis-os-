from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from sentinel.cli import main
from sentinel.custody.log import CustodyAction, CustodyLog
from sentinel.integrity.hashing import hash_file
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.signing import sign_artifact_manifest, write_signature
from sentinel.integrity.timestamp import TimeSource, Timestamp
from sentinel.packaging.sae import pack


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


@pytest.fixture
def artifact_dir(alice: KeyManager, tmp_path: Path) -> Path:
    d = tmp_path / "artifacts" / "art-1"
    d.mkdir(parents=True)
    data_path = d / "data.bin"
    data_path.write_bytes(b"fake iq data" * 100)
    file_hash = hash_file(data_path)
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
            "sha256": file_hash,
        },
    }
    sig = sign_artifact_manifest(alice, manifest)
    manifest["signature"] = sig.to_dict()
    (d / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    write_signature(d / "signature.sig", sig)
    return d


@pytest.fixture
def custody_log_path(
    alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
) -> Path:
    path = tmp_path / "custody.log"
    log = CustodyLog(path)
    log.append(alice, CustodyAction.CREATE,
               timestamp=ts_gps, artifact_id="art-1")
    log.append(alice, CustodyAction.VERIFY,
               timestamp=ts_gps, artifact_id="art-1")
    return path


@pytest.fixture
def sae_package(
    alice: KeyManager,
    artifact_dir: Path,
    custody_log_path: Path,
    tmp_path: Path,
    ts_gps: Timestamp,
) -> Path:
    out = tmp_path / "pkg.sae"
    pack(out, alice, "op-1", [artifact_dir],
         custody_log_path, timestamp=ts_gps)
    return out


@pytest.fixture
def operator_pub(alice: KeyManager, tmp_path: Path) -> Path:
    p = tmp_path / "operator.pub"
    alice.save_public(p)
    return p


class TestVerifyCommand:
    def test_valid_package_with_operator(
        self, sae_package: Path, operator_pub: Path
    ) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["verify", str(sae_package), "--operator", str(operator_pub)],
        )
        assert result.exit_code == 0
        assert "VALID" in result.output

    def test_valid_package_without_operator(self, sae_package: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["verify", str(sae_package)])
        assert result.exit_code == 0
        assert "VALID" in result.output

    def test_json_output(self, sae_package: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["verify", str(sae_package), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["valid"] is True
        assert data["signatures_verified"] is False

    def test_corrupt_package(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.sae"
        bad.write_bytes(b"not a zip")
        runner = CliRunner()
        result = runner.invoke(main, ["verify", str(bad)])
        assert result.exit_code == 2

    def test_no_custody_flag(self, sae_package: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main, ["verify", str(sae_package), "--no-custody"])
        assert result.exit_code == 0

    def test_missing_operator_file(self, sae_package: Path, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["verify", str(sae_package), "--operator",
             str(tmp_path / "nope.pub")],
        )
        assert result.exit_code != 0


class TestKeygenCommand:
    def test_creates_operator(self, memory_keyring: Any, tmp_path: Path) -> None:
        out = tmp_path / "op.pub"
        runner = CliRunner()
        result = runner.invoke(
            main, ["keygen", "--name", "Alice", "--output", str(out)]
        )
        assert result.exit_code == 0
        assert out.is_file()

    def test_shows_fingerprint(self, memory_keyring: Any) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["keygen", "--name", "Alice"])
        assert result.exit_code == 0
        assert "SHA256:" in result.output

    def test_custom_operator_id(self, memory_keyring: Any, tmp_path: Path) -> None:
        out = tmp_path / "op.pub"
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "keygen",
                "--name",
                "Alice",
                "--operator-id",
                "op-custom",
                "--output",
                str(out),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["operator_id"] == "op-custom"


class TestShowOperatorCommand:
    def test_reads_pub(self, operator_pub: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["show-operator", str(operator_pub)])
        assert result.exit_code == 0
        assert "op-alice" in result.output
