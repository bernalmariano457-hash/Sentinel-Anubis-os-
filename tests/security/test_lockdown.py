from __future__ import annotations

import json
from pathlib import Path

import pytest
from sentinel.custody.log import CustodyAction, CustodyLog
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.timestamp import Timestamp
from sentinel.security import (
    Lockdown,
    LockdownActiveError,
    LockdownError,
    LockdownNotActiveError,
    LockState,
    VaultAuthError,
    VaultError,
    read_state,
    verify_state,
)
from sentinel.security.state import STATE_FILENAME
from sentinel.security.vault import VAULT_BLOB_FILENAME

WRONG = "another-long-passphrase"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for name in ("evidence", "config")
        for path in sorted((root / name).rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def lockdown(workspace: Path, alice: KeyManager) -> Lockdown:
    return Lockdown(workspace, alice)


@pytest.fixture
def ready(lockdown: Lockdown, passphrase: str) -> Lockdown:
    lockdown.setup(passphrase)
    return lockdown


class TestSetup:
    def test_setup(self, lockdown: Lockdown, workspace: Path, passphrase: str) -> None:
        lockdown.setup(passphrase)
        assert (workspace / ".sentinel-vault.json").exists()
        assert not lockdown.is_locked()

    def test_workspace_is_normalized_to_path(self, workspace: Path, alice: KeyManager) -> None:
        assert isinstance(Lockdown(str(workspace), alice).workspace, Path)  # type: ignore[arg-type]


class TestLock:
    def test_lock_encrypts_and_removes_files(self, ready: Lockdown, workspace: Path, passphrase: str) -> None:
        record = ready.lock(passphrase)
        assert not (workspace / "evidence").exists()
        assert not (workspace / "config").exists()
        assert (workspace / VAULT_BLOB_FILENAME).exists()
        assert record.state is LockState.LOCKED
        assert record.details["blob"] == VAULT_BLOB_FILENAME
        assert record.details["included"] == ["evidence", "custody.log", "config"]

    def test_lock_persists_state(
        self, ready: Lockdown, workspace: Path, alice: KeyManager, ts: Timestamp, passphrase: str
    ) -> None:
        ready.lock(passphrase, reason="incident", details={"case": "C-1"})
        persisted = read_state(workspace)
        assert persisted.state is LockState.LOCKED
        assert persisted.reason == "incident"
        assert persisted.details == {"case": "C-1"}
        assert persisted.changed_at == ts.iso_utc
        verify_state(persisted, alice.identity)
        assert ready.is_locked()
        assert ready.current_state().state is LockState.LOCKED

    def test_lock_requires_setup(self, lockdown: Lockdown, workspace: Path, passphrase: str) -> None:
        with pytest.raises(LockdownError):
            lockdown.lock(passphrase)
        assert (workspace / "evidence").exists()

    def test_double_lock_rejected(self, ready: Lockdown, passphrase: str) -> None:
        ready.lock(passphrase)
        with pytest.raises(LockdownActiveError):
            ready.lock(passphrase)

    def test_existing_blob_is_never_overwritten(self, ready: Lockdown, workspace: Path, passphrase: str) -> None:
        ready.lock(passphrase)
        (workspace / STATE_FILENAME).unlink()
        with pytest.raises(LockdownActiveError):
            ready.lock(passphrase)

    def test_wrong_passphrase_leaves_workspace_untouched(self, ready: Lockdown, workspace: Path) -> None:
        before = _snapshot(workspace)
        with pytest.raises(VaultAuthError):
            ready.lock(WRONG)
        assert _snapshot(workspace) == before
        assert not (workspace / STATE_FILENAME).exists()
        assert not (workspace / VAULT_BLOB_FILENAME).exists()

    def test_unsafe_include_is_rejected_before_any_change(
        self, ready: Lockdown, workspace: Path, passphrase: str
    ) -> None:
        with pytest.raises(VaultError):
            ready.lock(passphrase, include=("../outside",))
        assert not (workspace / STATE_FILENAME).exists()

    def test_failed_seal_restores_previous_state(self, ready: Lockdown, workspace: Path, passphrase: str) -> None:
        with pytest.raises(VaultError):
            ready.lock(passphrase, include=("does-not-exist",))
        assert not ready.is_locked()
        assert (workspace / "evidence").exists()

    def test_lock_records_custody_entry(
        self, ready: Lockdown, workspace: Path, alice: KeyManager, ts: Timestamp, passphrase: str
    ) -> None:
        log = CustodyLog(workspace / "custody.log")
        log.append(alice, CustodyAction.EXPORT, timestamp=ts, details={"note": "seed"})
        ready.lock(passphrase)
        assert not (workspace / "custody.log").exists()
        ready.unlock(passphrase)
        entries = log.read_all()
        assert len(entries) == 3
        assert log.verify_chain().valid


class TestUnlock:
    def test_unlock_restores_files(self, ready: Lockdown, workspace: Path, passphrase: str) -> None:
        before = _snapshot(workspace)
        ready.lock(passphrase)
        record = ready.unlock(passphrase)
        assert _snapshot(workspace) == before
        assert record.state is LockState.UNLOCKED
        assert not ready.is_locked()
        assert not (workspace / VAULT_BLOB_FILENAME).exists()

    def test_unlock_wrong_passphrase_fails(self, ready: Lockdown, workspace: Path, passphrase: str) -> None:
        ready.lock(passphrase)
        with pytest.raises(VaultAuthError):
            ready.unlock(WRONG)
        assert ready.is_locked()
        assert (workspace / VAULT_BLOB_FILENAME).exists()
        assert not (workspace / "evidence").exists()

    def test_unlock_requires_locked_state(self, ready: Lockdown, passphrase: str) -> None:
        with pytest.raises(LockdownNotActiveError):
            ready.unlock(passphrase)

    def test_unlock_after_unlock_is_rejected(self, ready: Lockdown, passphrase: str) -> None:
        ready.lock(passphrase)
        ready.unlock(passphrase)
        with pytest.raises(LockdownNotActiveError):
            ready.unlock(passphrase)

    def test_unlock_requires_setup(self, lockdown: Lockdown, passphrase: str) -> None:
        with pytest.raises(LockdownError):
            lockdown.unlock(passphrase)

    def test_unlock_rejects_tampered_state(self, ready: Lockdown, workspace: Path, passphrase: str) -> None:
        ready.lock(passphrase)
        path = workspace / STATE_FILENAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["reason"] = "forged"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(LockdownError):
            ready.unlock(passphrase)
        assert (workspace / VAULT_BLOB_FILENAME).exists()

    def test_unlock_rejects_state_signed_by_other_operator(
        self, ready: Lockdown, workspace: Path, bob: KeyManager, passphrase: str
    ) -> None:
        ready.lock(passphrase)
        with pytest.raises(LockdownError):
            Lockdown(workspace, bob).unlock(passphrase)


class TestFailsafeLock:
    def test_marks_locked_without_encrypting(
        self, ready: Lockdown, workspace: Path
    ) -> None:
        before = _snapshot(workspace)
        record = ready.lock(reason="auto-response")
        assert record.state is LockState.LOCKED
        assert ready.is_locked()
        assert _snapshot(workspace) == before
        assert (workspace / "evidence").exists()
        assert (workspace / "config").exists()
        assert not (workspace / VAULT_BLOB_FILENAME).exists()

    def test_requires_setup(self, lockdown: Lockdown) -> None:
        with pytest.raises(LockdownError):
            lockdown.lock()

    def test_double_lock_rejected(self, ready: Lockdown) -> None:
        ready.lock()
        with pytest.raises(LockdownActiveError):
            ready.lock()

    def test_persists_state_without_blob_details(
        self, ready: Lockdown, workspace: Path, alice: KeyManager
    ) -> None:
        ready.lock(reason="auto-response", details={"case": "C-1"})
        persisted = read_state(workspace)
        assert persisted.state is LockState.LOCKED
        assert persisted.reason == "auto-response"
        assert persisted.details == {"case": "C-1"}
        verify_state(persisted, alice.identity)

    def test_records_custody_entry_as_unencrypted(
        self, ready: Lockdown, workspace: Path, alice: KeyManager, ts: Timestamp
    ) -> None:
        log = CustodyLog(workspace / "custody.log")
        log.append(alice, CustodyAction.CREATE, timestamp=ts)
        ready.lock()
        entries = log.read_all()
        assert entries[-1]["details"]["encrypted"] is False
        assert log.verify_chain().valid

    def test_unlock_restores_normal_state_without_passphrase_check(
        self, ready: Lockdown, workspace: Path
    ) -> None:
        before = _snapshot(workspace)
        ready.lock()
        record = ready.unlock(WRONG)
        assert record.state is LockState.UNLOCKED
        assert not ready.is_locked()
        assert _snapshot(workspace) == before

    def test_then_real_lock_still_encrypts(
        self, ready: Lockdown, workspace: Path, passphrase: str
    ) -> None:
        ready.lock()
        ready.unlock(passphrase)
        ready.lock(passphrase)
        assert not (workspace / "evidence").exists()
        assert (workspace / VAULT_BLOB_FILENAME).exists()


class TestCycle:
    def test_lock_unlock_lock(self, ready: Lockdown, workspace: Path, passphrase: str) -> None:
        before = _snapshot(workspace)
        ready.lock(passphrase)
        ready.unlock(passphrase)
        assert _snapshot(workspace) == before
        ready.lock(passphrase)
        assert ready.is_locked()
        assert not (workspace / "evidence").exists()
        ready.unlock(passphrase)
        assert _snapshot(workspace) == before
