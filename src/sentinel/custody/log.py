from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterator

import portalocker

from sentinel import SentinelCustodyError
from sentinel.integrity.hashing import sha256_canonical
from sentinel.integrity.keys import (
    InvalidSignatureError,
    KeyManager,
    OperatorIdentity,
    SignatureBundle,
)
from sentinel.integrity.signing import (
    ManifestStructureError,
    sign_custody_entry,
    verify_custody_entry,
)
from sentinel.integrity.timestamp import TimeSource, Timestamp


SCHEMA_VERSION: Final[str] = "1.0"

DEFAULT_LOCK_TIMEOUT_S: Final[float] = 10.0


class CustodyError(SentinelCustodyError):


class CustodyLogError(CustodyError):


class CustodyChainError(CustodyError):


class CustodyIOError(CustodyError):


class CustodyAction(str, Enum):

    CREATE = "create"
    VERIFY = "verify"
    PACK = "pack"
    UNPACK = "unpack"
    EXPORT = "export"
    SIGN = "sign"
    ROTATE_KEY = "rotate_key"


def build_entry(
    seq: int,
    prev_hash: str,
    operator_id: str,
    action: CustodyAction,
    timestamp: Timestamp,
    artifact_id: str | None = None,
    package_id: str | None = None,
    details: dict[str, Any] | None = None,
    entry_id: str | None = None,
) -> dict[str, Any]:

    if seq < 0:
        raise ValueError(f"seq must be >= 0, got {seq}")
    if not isinstance(prev_hash, str):
        raise ValueError(
            f"prev_hash must be str, got {type(prev_hash).__name__}")
    if seq == 0 and prev_hash != "":
        raise ValueError("prev_hash must be empty for seq=0")
    if seq > 0 and not prev_hash:
        raise ValueError("prev_hash must be non-empty for seq>0")
    if not operator_id:
        raise ValueError("operator_id must be non-empty")
    if not isinstance(action, CustodyAction):
        raise ValueError(
            f"action must be a CustodyAction, got {type(action).__name__}")

    return {
        "schema_version": SCHEMA_VERSION,
        "entry_id": entry_id or str(uuid.uuid4()),
        "seq": seq,
        "timestamp": timestamp.iso_utc,
        "time_source": timestamp.source.value,
        "operator_id": operator_id,
        "action": action.value,
        "artifact_id": artifact_id,
        "package_id": package_id,
        "details": details or None,
        "prev_hash": prev_hash,
    }


def finalize_entry(
    operator: KeyManager,
    payload: dict[str, Any],
) -> dict[str, Any]:

    if "entry_hash" in payload or "signature" in payload:
        raise ValueError(
            "payload must not contain entry_hash or signature; "
            "use build_entry() then finalize_entry()"
        )
    if payload.get("operator_id") != operator.identity.operator_id:
        raise ValueError(
            f"payload operator_id {payload.get('operator_id')!r} does not match "
            f"signing operator {operator.identity.operator_id!r}"
        )

    entry_hash = sha256_canonical(payload)
    signature = sign_custody_entry(operator, payload)
    full = dict(payload)
    full["entry_hash"] = entry_hash
    full["signature"] = signature.to_dict()
    return full


@dataclass(frozen=True)
class ChainIssue:
    seq: int | None

    line_no: int

    code: str

    message: str


_ISSUE_CODES = frozenset(
    {
        "invalid_json",
        "invalid_structure",
        "unsupported_version",
        "seq_mismatch",
        "prev_hash_mismatch",
        "entry_hash_mismatch",
        "signature_invalid",
        "operator_unknown",
        "fingerprint_mismatch",
        "empty_log_with_expected_entries",
    }
)


@dataclass(frozen=True)
class ChainVerificationReport:

    total_lines: int
    valid_entries: int
    issues: tuple[ChainIssue, ...]
    head_hash: str | None
    signatures_verified: bool

    @property
    def valid(self) -> bool:
        return len(self.issues) == 0

    def raise_if_invalid(self) -> None:
        if not self.valid:
            codes = ", ".join(sorted({i.code for i in self.issues}))
            raise CustodyChainError(
                f"custody chain verification failed: {len(self.issues)} issue(s) "
                f"[{codes}]"
            )

    def summary(self) -> str:
        status = "OK" if self.valid else f"FAILED ({len(self.issues)} issues)"
        sig = "signed" if self.signatures_verified else "unsigned (no operators given)"
        return (
            f"{self.valid_entries}/{self.total_lines} entries valid, "
            f"signatures: {sig}, status: {status}"
        )


@dataclass
class CustodyLog:

    path: Path
    lock_timeout_s: float = DEFAULT_LOCK_TIMEOUT_S
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.lock_timeout_s <= 0:
            raise ValueError("lock_timeout_s must be positive")

    def exists(self) -> bool:
        return self.path.exists()

    def _open_for_append(self) -> Any:

        self.path.parent.mkdir(parents=True, exist_ok=True)
        return open(self.path, "a+", encoding="utf-8", newline="\n")

    def _open_for_read(self) -> Any:
        return open(self.path, "r", encoding="utf-8", newline="\n")

    def _locked(self, fh: Any, mode: int) -> None:
        try:
            portalocker.lock(fh, mode, timeout=self.lock_timeout_s)
        except portalocker.LockException as e:
            raise CustodyIOError(f"cannot lock {self.path}: {e}") from e

    def _unlock(self, fh: Any) -> None:
        try:
            portalocker.unlock(fh)
        except portalocker.LockException:
            pass

    def _read_all_locked(self, fh: Any) -> list[dict[str, Any]]:
        fh.seek(0)
        return [e for e in _parse_jsonl(fh.read())]

    def count(self) -> int:
        if not self.exists():
            return 0
        with self._open_for_read() as fh:
            self._locked(fh, portalocker.LOCK_SH)
            try:
                return sum(1 for line in fh if line.strip())
            finally:
                self._unlock(fh)

    def head_hash(self) -> str:
        if not self.exists():
            return ""
        with self._open_for_read() as fh:
            self._locked(fh, portalocker.LOCK_SH)
            try:
                entries = [e for e in _parse_jsonl(
                    fh.read()) if "_error" not in e]
            finally:
                self._unlock(fh)
        if not entries:
            return ""
        last = entries[-1]
        hash_val = last.get("entry_hash")
        if not isinstance(hash_val, str):
            raise CustodyLogError("last entry is missing entry_hash")
        return hash_val

    def read_all(self) -> list[dict[str, Any]]:

        if not self.exists():
            return []
        with self._open_for_read() as fh:
            self._locked(fh, portalocker.LOCK_SH)
            try:
                return [e for e in _parse_jsonl(fh.read())]
            finally:
                self._unlock(fh)

    def append(
        self,
        operator: KeyManager,
        action: CustodyAction,
        timestamp: Timestamp | None = None,
        artifact_id: str | None = None,
        package_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        if timestamp is None:
            from sentinel.integrity.timestamp import SystemClock

            timestamp = SystemClock().now()

        fh = self._open_for_append()
        try:
            self._locked(fh, portalocker.LOCK_EX)
            try:
                entries = self._read_all_locked(fh)
                if any("_error" in e for e in entries):
                    raise CustodyLogError(
                        f"refusing to append to corrupt log {self.path}; "
                        "run verify_chain() to diagnose"
                    )
                if entries:
                    prev_hash = entries[-1].get("entry_hash")
                    if not isinstance(prev_hash, str) or not prev_hash:
                        raise CustodyLogError(
                            f"last entry in {self.path} has no entry_hash"
                        )
                    seq = len(entries)
                else:
                    prev_hash = ""
                    seq = 0

                payload = build_entry(
                    seq=seq,
                    prev_hash=prev_hash,
                    operator_id=operator.identity.operator_id,
                    action=action,
                    timestamp=timestamp,
                    artifact_id=artifact_id,
                    package_id=package_id,
                    details=details,
                )
                full = finalize_entry(operator, payload)
                line = json.dumps(full, ensure_ascii=False,
                                  separators=(",", ":"))
                fh.write(line + "\n")
                fh.flush()
                os.fsync(fh.fileno())
                return full
            finally:
                self._unlock(fh)
        except OSError as e:
            raise CustodyIOError(f"cannot append to {self.path}: {e}") from e
        finally:
            fh.close()

    def verify_chain(
        self,
        operators: dict[str, OperatorIdentity] | None = None,
    ) -> ChainVerificationReport:

        if not self.exists():
            return ChainVerificationReport(
                total_lines=0,
                valid_entries=0,
                issues=(),
                head_hash=None,
                signatures_verified=operators is not None,
            )

        issues: list[ChainIssue] = []
        valid_entries = 0
        expected_seq = 0
        expected_prev_hash = ""
        head_hash: str | None = None
        total_lines = 0

        with self._open_for_read() as fh:
            self._locked(fh, portalocker.LOCK_SH)
            try:
                for line_no, raw in enumerate(fh, start=1):
                    if not raw.strip():
                        continue
                    total_lines += 1
                    entry = _try_parse(raw)
                    if entry is None:
                        issues.append(
                            ChainIssue(
                                seq=None,
                                line_no=line_no,
                                code="invalid_json",
                                message="line is not valid JSON",
                            )
                        )

                        expected_seq += 1
                        continue

                    structural = _validate_structure(entry)
                    if structural:
                        for code, msg in structural:
                            issues.append(
                                ChainIssue(
                                    seq=entry.get("seq") if isinstance(
                                        entry.get("seq"), int) else None,
                                    line_no=line_no,
                                    code=code,
                                    message=msg,
                                )
                            )
                        expected_seq += 1
                        continue

                    if entry["seq"] != expected_seq:
                        issues.append(
                            ChainIssue(
                                seq=entry["seq"],
                                line_no=line_no,
                                code="seq_mismatch",
                                message=(
                                    f"expected seq={expected_seq}, got {entry['seq']}"
                                ),
                            )
                        )
                        expected_seq = entry["seq"] + 1
                    else:
                        expected_seq += 1

                    if entry["prev_hash"] != expected_prev_hash:
                        issues.append(
                            ChainIssue(
                                seq=entry["seq"],
                                line_no=line_no,
                                code="prev_hash_mismatch",
                                message=(
                                    f"prev_hash does not match previous entry "
                                    f"(expected {expected_prev_hash[:16]}..., "
                                    f"got {entry['prev_hash'][:16]}...)"
                                ),
                            )
                        )

                    payload = _strip_for_hash(entry)
                    try:
                        recomputed = sha256_canonical(payload)
                    except (TypeError, ValueError) as e:
                        issues.append(
                            ChainIssue(
                                seq=entry["seq"],
                                line_no=line_no,
                                code="entry_hash_mismatch",
                                message=f"cannot recompute entry_hash: {e}",
                            )
                        )
                        expected_prev_hash = entry["entry_hash"]
                        head_hash = entry["entry_hash"]
                        continue
                    if recomputed != entry["entry_hash"]:
                        issues.append(
                            ChainIssue(
                                seq=entry["seq"],
                                line_no=line_no,
                                code="entry_hash_mismatch",
                                message=(
                                    f"recomputed {recomputed[:16]}... != "
                                    f"stored {entry['entry_hash'][:16]}..."
                                ),
                            )
                        )

                    if operators is not None:
                        sig_check = _verify_signature(
                            entry, payload, operators)
                        if sig_check is not None:
                            code, msg = sig_check
                            issues.append(
                                ChainIssue(
                                    seq=entry["seq"],
                                    line_no=line_no,
                                    code=code,
                                    message=msg,
                                )
                            )

                    expected_prev_hash = entry["entry_hash"]
                    head_hash = entry["entry_hash"]
                    valid_entries += 1
            finally:
                self._unlock(fh)

        return ChainVerificationReport(
            total_lines=total_lines,
            valid_entries=valid_entries,
            issues=tuple(issues),
            head_hash=head_hash,
            signatures_verified=operators is not None,
        )

    def iter_entries(self) -> Iterator[dict[str, Any]]:

        if not self.exists():
            return
        try:
            with self._open_for_read() as fh:
                self._locked(fh, portalocker.LOCK_SH)
                try:
                    for line_no, raw in enumerate(fh, start=1):
                        if not raw.strip():
                            continue
                        entry = _try_parse(raw)
                        if entry is None:
                            yield {"_error": "invalid JSON", "_line_no": line_no}
                        else:
                            yield entry
                finally:
                    self._unlock(fh)
        except OSError as e:
            raise CustodyIOError(f"cannot read {self.path}: {e}") from e


def _try_parse(line: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _parse_jsonl(text: str) -> Iterator[dict[str, Any]]:
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        entry = _try_parse(raw)
        if entry is None:
            yield {"_error": "invalid JSON", "_line_no": line_no}
        else:
            yield entry


def _strip_for_hash(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k not in ("entry_hash", "signature")}


def _validate_structure(entry: dict[str, Any]) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []
    required = (
        "schema_version",
        "entry_id",
        "seq",
        "timestamp",
        "time_source",
        "operator_id",
        "action",
        "prev_hash",
        "entry_hash",
        "signature",
    )
    for f in required:
        if f not in entry:
            problems.append(("invalid_structure", f"missing field: {f}"))
    if problems:
        return problems

    if entry["schema_version"] != SCHEMA_VERSION:
        problems.append(
            (
                "unsupported_version",
                f"schema_version {entry['schema_version']!r} != {SCHEMA_VERSION!r}",
            )
        )
    if not isinstance(entry["seq"], int) or entry["seq"] < 0:
        problems.append(
            ("invalid_structure", "seq must be a non-negative int"))
    if not isinstance(entry["prev_hash"], str):
        problems.append(("invalid_structure", "prev_hash must be a string"))
    if not isinstance(entry["entry_hash"], str):
        problems.append(("invalid_structure", "entry_hash must be a string"))
    if not isinstance(entry["operator_id"], str) or not entry["operator_id"]:
        problems.append(
            ("invalid_structure", "operator_id must be a non-empty string"))
    if entry["time_source"] not in {s.value for s in TimeSource}:
        problems.append(
            ("invalid_structure",
             f"invalid time_source: {entry['time_source']!r}")
        )
    if entry["action"] not in {a.value for a in CustodyAction}:
        problems.append(
            ("invalid_structure", f"invalid action: {entry['action']!r}"))
    if not isinstance(entry["signature"], dict):
        problems.append(("invalid_structure", "signature must be an object"))
    return problems


def _verify_signature(
    entry: dict[str, Any],
    payload: dict[str, Any],
    operators: dict[str, OperatorIdentity],
) -> tuple[str, str] | None:
    op_id = entry.get("operator_id")
    identity = operators.get(op_id) if op_id else None
    if identity is None:
        return (
            "operator_unknown",
            f"operator_id {op_id!r} not in provided operators map",
        )
    try:
        bundle = SignatureBundle.from_dict(entry["signature"])
    except Exception as e:
        return ("signature_invalid", f"malformed signature bundle: {e}")
    if bundle.pubkey_fingerprint != identity.pubkey_fingerprint:
        return (
            "fingerprint_mismatch",
            f"signature fingerprint does not match operator "
            f"{identity.pubkey_fingerprint[:16]}...",
        )
    try:
        verify_custody_entry(identity, payload, bundle)
    except InvalidSignatureError as e:
        return ("signature_invalid", f"signature does not verify: {e}")
    except ManifestStructureError as e:
        return ("signature_invalid", f"payload malformed: {e}")
    return None


__all__ = [
    "SCHEMA_VERSION",
    "ChainIssue",
    "ChainVerificationReport",
    "CustodyAction",
    "CustodyChainError",
    "CustodyError",
    "CustodyIOError",
    "CustodyLog",
    "CustodyLogError",
    "build_entry",
    "finalize_entry",
]
