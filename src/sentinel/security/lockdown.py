"""Lock/unlock orchestration over the vault, the state machine and the custody log."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from sentinel import SentinelError
from sentinel.custody.log import CustodyAction, CustodyLog
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.timestamp import TimeResolver, Timestamp
from sentinel.security import vault
from sentinel.security.state import (
    LockState,
    StateError,
    StateRecord,
    read_state,
    verify_state,
    write_state,
)

DEFAULT_LOCK_INCLUDE: Final[tuple[str, ...]] = ("evidence", "custody.log", "config")


class LockdownError(SentinelError):
    """Base error for lockdown operations."""


class LockdownNotActiveError(LockdownError):
    """Operation requires the workspace to be locked."""


class LockdownActiveError(LockdownError):
    """Operation is not allowed while the workspace is locked or sealed."""


@dataclass
class Lockdown:
    """Encrypts and removes evidence on lock, restores it on unlock."""

    workspace: Path
    operator: KeyManager

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace)

    def _now(self) -> Timestamp:
        return TimeResolver().now()

    def _custody(self) -> CustodyLog:
        return CustodyLog(self.workspace / "custody.log")

    def setup(self, passphrase: str) -> None:
        vault.setup(self.workspace, passphrase)

    def current_state(self) -> StateRecord:
        return read_state(self.workspace)

    def is_locked(self) -> bool:
        try:
            return read_state(self.workspace).state is LockState.LOCKED
        except StateError:
            return False

    def lock(
        self,
        passphrase: str | None = None,
        include: tuple[str, ...] = DEFAULT_LOCK_INCLUDE,
        reason: str = "manual",
        details: dict[str, Any] | None = None,
    ) -> StateRecord:
        """Seal the included paths, delete the plaintext and mark the workspace locked.
        If passphrase is None, the workspace is marked LOCKED but files are not encrypted.
        """
        if not vault.is_setup(self.workspace):
            raise LockdownError("vault is not set up")
        if self.is_locked():
            raise LockdownActiveError("workspace is already locked")
        if vault.has_blob(self.workspace):
            raise LockdownActiveError("a sealed vault blob already exists")
        
        names = list(include)
        vault.validate_include(names)
        if passphrase is not None:
            vault.verify_passphrase(self.workspace, passphrase)
            
        previous = self._previous_state()
        write_state(self.workspace, self.operator, LockState.LOCKED, self._now().iso_utc, reason, details)
        
        try:
            custody = self._custody()
            if custody.exists():
                custody.append(
                    self.operator,
                    CustodyAction.EXPORT,
                    timestamp=self._now(),
                    details={"action": "lockdown", "reason": reason, "encrypted": passphrase is not None},
                )
            if passphrase is not None:
                vault.seal(self.workspace, passphrase, names)
        except Exception:
            write_state(self.workspace, self.operator, previous, self._now().iso_utc, "lock aborted")
            raise

        if passphrase is not None:
            self._remove(names)
            record = read_state(self.workspace)
            merged = {**record.details, "blob": vault.VAULT_BLOB_FILENAME, "included": names}
            return replace(record, details=merged)
        
        return read_state(self.workspace)

    def unlock(self, passphrase: str) -> StateRecord:
        """Verify the lock state, restore the sealed paths and mark the workspace unlocked."""
        if not vault.is_setup(self.workspace):
            raise LockdownError("vault is not set up")
        try:
            current = read_state(self.workspace)
        except StateError as e:
            raise LockdownNotActiveError(f"workspace is not locked: {e}") from e
        if current.state is not LockState.LOCKED:
            raise LockdownNotActiveError(f"workspace is not locked (state: {current.state.value})")
        try:
            verify_state(current, self.operator.identity)
        except SentinelError as e:
            raise LockdownError(f"lock state signature is invalid: {e}") from e
            
        if vault.has_blob(self.workspace):
            vault.unseal(self.workspace, passphrase)
            self._discard_blob()
            
        write_state(self.workspace, self.operator, LockState.UNLOCKED, self._now().iso_utc, "unlock")
        
        custody = self._custody()
        if custody.exists():
            report = custody.verify_chain()
            if not report.valid:
                raise LockdownError(f"custody chain is invalid after unlock: {len(report.issues)} issue(s)")
            custody.append(
                self.operator,
                CustodyAction.UNPACK,
                timestamp=self._now(),
                details={"action": "unlock"},
            )
        return read_state(self.workspace)

    def _previous_state(self) -> LockState:
        try:
            return read_state(self.workspace).state
        except StateError:
            return LockState.NORMAL

    def _remove(self, names: list[str]) -> None:
        for name in names:
            target = self.workspace / name
            try:
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                elif target.exists() or target.is_symlink():
                    target.unlink()
            except OSError as e:
                raise LockdownError(f"cannot remove {name}: {e}") from e

    def _discard_blob(self) -> None:
        try:
            (self.workspace / vault.VAULT_BLOB_FILENAME).unlink()
        except OSError as e:
            raise LockdownError(f"cannot remove sealed vault blob: {e}") from e