from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sentinel.security import vault
from sentinel.security.vault import (
    VAULT_BLOB_FILENAME,
    VAULT_META_FILENAME,
    VaultAlreadySetupError,
    VaultAuthError,
    VaultError,
    VaultNotSetupError,
)

INCLUDE = ["evidence", "config"]


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for name in INCLUDE
        for path in sorted((root / name).rglob("*"))
        if path.is_file()
    }


class TestSetup:
    def test_setup_ok(self, workspace: Path, passphrase: str) -> None:
        meta = vault.setup(workspace, passphrase)
        assert vault.is_setup(workspace)
        assert not vault.has_blob(workspace)
        assert (workspace / VAULT_META_FILENAME).exists()
        assert vault.load_meta(workspace) == meta

    def test_rejects_short_passphrase(self, workspace: Path) -> None:
        with pytest.raises(ValueError):
            vault.setup(workspace, "too-short")
        assert not vault.is_setup(workspace)

    def test_rejects_double_setup(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        with pytest.raises(VaultAlreadySetupError):
            vault.setup(workspace, passphrase)

    def test_load_meta_requires_setup(self, workspace: Path) -> None:
        with pytest.raises(VaultNotSetupError):
            vault.load_meta(workspace)

    def test_meta_does_not_contain_passphrase(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        assert passphrase not in (workspace / VAULT_META_FILENAME).read_text(encoding="utf-8")


class TestSealUnseal:
    def test_roundtrip(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        before = _snapshot(workspace)
        blob = vault.seal(workspace, passphrase, INCLUDE)
        assert blob == workspace / VAULT_BLOB_FILENAME
        assert vault.has_blob(workspace)
        shutil.rmtree(workspace / "evidence")
        shutil.rmtree(workspace / "config")
        vault.unseal(workspace, passphrase)
        assert _snapshot(workspace) == before

    def test_blob_is_not_plaintext(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        blob = vault.seal(workspace, passphrase, INCLUDE)
        assert b"evidence-bytes" not in blob.read_bytes()
        assert b"operation" not in blob.read_bytes()

    def test_seal_skips_missing_paths(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        vault.seal(workspace, passphrase, ["evidence", "custody.log"])
        shutil.rmtree(workspace / "evidence")
        vault.unseal(workspace, passphrase)
        assert (workspace / "evidence" / "artifact.bin").exists()

    def test_seal_requires_existing_paths(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        with pytest.raises(VaultError):
            vault.seal(workspace, passphrase, ["nothing-here"])

    @pytest.mark.parametrize("name", ["../escape", "/etc/passwd", ""])
    def test_seal_rejects_unsafe_paths(self, workspace: Path, passphrase: str, name: str) -> None:
        vault.setup(workspace, passphrase)
        with pytest.raises(VaultError):
            vault.seal(workspace, passphrase, [name])

    def test_seal_requires_setup(self, workspace: Path, passphrase: str) -> None:
        with pytest.raises(VaultNotSetupError):
            vault.seal(workspace, passphrase, INCLUDE)

    def test_wrong_passphrase_fails_on_seal(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        with pytest.raises(VaultAuthError):
            vault.seal(workspace, "another-long-passphrase", INCLUDE)
        assert not vault.has_blob(workspace)

    def test_wrong_passphrase_fails_on_unseal(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        vault.seal(workspace, passphrase, INCLUDE)
        with pytest.raises(VaultAuthError):
            vault.unseal(workspace, "another-long-passphrase")

    def test_tampered_blob_fails(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        blob = vault.seal(workspace, passphrase, INCLUDE)
        data = bytearray(blob.read_bytes())
        data[-1] ^= 0xFF
        blob.write_bytes(bytes(data))
        with pytest.raises(VaultAuthError):
            vault.unseal(workspace, passphrase)

    def test_truncated_blob_fails(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        blob = vault.seal(workspace, passphrase, INCLUDE)
        blob.write_bytes(blob.read_bytes()[:5])
        with pytest.raises(VaultError):
            vault.unseal(workspace, passphrase)

    def test_missing_blob_fails(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        with pytest.raises(VaultError):
            vault.unseal(workspace, passphrase)


class TestChangePassphrase:
    def test_change_passphrase_works(self, workspace: Path, passphrase: str) -> None:
        new = "a-different-long-passphrase"
        vault.setup(workspace, passphrase)
        before = _snapshot(workspace)
        vault.seal(workspace, passphrase, INCLUDE)
        vault.change_passphrase(workspace, passphrase, new)
        shutil.rmtree(workspace / "evidence")
        shutil.rmtree(workspace / "config")
        with pytest.raises(VaultAuthError):
            vault.unseal(workspace, passphrase)
        vault.unseal(workspace, new)
        assert _snapshot(workspace) == before

    def test_rejects_short_new_passphrase(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        with pytest.raises(ValueError):
            vault.change_passphrase(workspace, passphrase, "short")
        vault.verify_passphrase(workspace, passphrase)

    def test_rejects_wrong_old_passphrase(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        with pytest.raises(VaultAuthError):
            vault.change_passphrase(workspace, "wrong-passphrase-here", "a-different-long-passphrase")
        vault.verify_passphrase(workspace, passphrase)

    def test_leaves_no_temporary_file(self, workspace: Path, passphrase: str) -> None:
        vault.setup(workspace, passphrase)
        vault.change_passphrase(workspace, passphrase, "a-different-long-passphrase")
        assert not list(workspace.glob("*.tmp"))
