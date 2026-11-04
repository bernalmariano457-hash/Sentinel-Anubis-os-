from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from sentinel.cli import main
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.timestamp import Timestamp
from sentinel.packaging.sae import pack


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
