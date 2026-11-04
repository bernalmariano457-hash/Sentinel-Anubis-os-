"""Self-defense layer: lock state, evidence vault and lockdown orchestration."""

from __future__ import annotations

from sentinel.security.auto_response import AutoResponder
from sentinel.security.lockdown import (
    DEFAULT_LOCK_INCLUDE,
    Lockdown,
    LockdownActiveError,
    LockdownError,
    LockdownNotActiveError,
)
from sentinel.security.state import (
    LockState,
    StateError,
    StateRecord,
    read_state,
    verify_state,
    write_state,
)
from sentinel.security.vault import (
    VaultAlreadySetupError,
    VaultAuthError,
    VaultError,
    VaultMeta,
    VaultNotSetupError,
    change_passphrase,
    has_blob,
    is_setup,
    load_meta,
    seal,
    setup,
    unseal,
)

__all__ = [
    "DEFAULT_LOCK_INCLUDE",
    "AutoResponder",
    "LockState",
    "Lockdown",
    "LockdownActiveError",
    "LockdownError",
    "LockdownNotActiveError",
    "StateError",
    "StateRecord",
    "VaultAlreadySetupError",
    "VaultAuthError",
    "VaultError",
    "VaultMeta",
    "VaultNotSetupError",
    "change_passphrase",
    "has_blob",
    "is_setup",
    "load_meta",
    "read_state",
    "seal",
    "setup",
    "unseal",
    "verify_state",
    "write_state",
]
