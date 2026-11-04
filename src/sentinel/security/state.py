from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from sentinel import SentinelError
from sentinel.integrity.hashing import sha256_canonical
from sentinel.integrity.keys import KeyManager, OperatorIdentity, SignatureBundle
from sentinel.integrity.signing import sign_entity, verify_entity

STATE_SCHEMA_VERSION: Final = "1.0"
DOMAIN_STATE: Final = b"sentinel-anubis:lock-state:v1:"
STATE_FILENAME: Final = ".sentinel-state.json"


class LockState(StrEnum):

    NORMAL = "normal"
    LOCKED = "locked"
    UNLOCKED = "unlocked"


class StateError(SentinelError):
    """State file is missing, malformed or cannot be written."""


@dataclass(frozen=True)
class StateRecord:

    schema_version: str
    state: LockState
    changed_at: str
    operator_id: str
    reason: str
    details: dict[str, Any]
    signature: SignatureBundle

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "state": self.state.value,
            "changed_at": self.changed_at,
            "operator_id": self.operator_id,
            "reason": self.reason,
            "details": self.details,
        }

    def to_dict(self) -> dict[str, Any]:
        data = self._payload()
        data["signature"] = self.signature.to_dict()
        return data

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StateRecord:
        if not isinstance(d, dict):
            raise StateError("state record must be a JSON object")
        version = d.get("schema_version")
        if version != STATE_SCHEMA_VERSION:
            raise StateError(f"unsupported state schema_version: {version!r}")
        try:
            details = d["details"]
            if not isinstance(details, dict):
                raise StateError("details must be an object")
            changed_at, operator_id, reason = d["changed_at"], d["operator_id"], d["reason"]
            if not all(isinstance(v, str) for v in (changed_at, operator_id, reason)):
                raise StateError(
                    "changed_at, operator_id and reason must be strings")
            return cls(
                schema_version=version,
                state=LockState(d["state"]),
                changed_at=changed_at,
                operator_id=operator_id,
                reason=reason,
                details=details,
                signature=SignatureBundle.from_dict(d["signature"]),
            )
        except StateError:
            raise
        except (KeyError, TypeError, ValueError, SentinelError) as e:
            raise StateError(f"malformed state record: {e}") from e


def write_state(
    workspace: Path | str,
    operator: KeyManager,
    state: LockState,
    changed_at: str,
    reason: str,
    details: dict[str, Any] | None = None,
) -> StateRecord:
    root = Path(workspace)
    if not root.is_dir():
        raise StateError(f"workspace is not a directory: {root}")
    payload: dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "state": state.value,
        "changed_at": changed_at,
        "operator_id": operator.identity.operator_id,
        "reason": reason,
        "details": dict(details) if details else {},
    }
    try:
        signature = sign_entity(operator, payload, DOMAIN_STATE)
    except TypeError as e:
        raise StateError(f"details are not serializable: {e}") from e
    record = StateRecord(
        schema_version=STATE_SCHEMA_VERSION,
        state=state,
        changed_at=changed_at,
        operator_id=payload["operator_id"],
        reason=reason,
        details=payload["details"],
        signature=signature,
    )
    target = root / STATE_FILENAME
    tmp = target.with_name(target.name + ".tmp")
    text = json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n"
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError as e:
        raise StateError(f"cannot write state file: {e}") from e
    return record


def read_state(workspace: Path | str) -> StateRecord:
    path = Path(workspace) / STATE_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise StateError(f"state file not found: {path}") from e
    except (OSError, UnicodeDecodeError) as e:
        raise StateError(f"cannot read state file: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise StateError(f"state file is not valid JSON: {e}") from e
    return StateRecord.from_dict(data)


def verify_state(record: StateRecord, identity: OperatorIdentity) -> None:
    verify_entity(identity, record._payload(),
                  record.signature, domain=DOMAIN_STATE)


def state_hash(record: StateRecord) -> str:
    return sha256_canonical(record._payload())
