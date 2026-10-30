from __future__ import annotations

import fnmatch
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final

from sentinel import SentinelError
from sentinel.integrity.hashing import canonical_json, hash_file
from sentinel.integrity.keys import KeyManager, OperatorIdentity, SignatureBundle
from sentinel.integrity.signing import read_signature, write_signature
from sentinel.integrity.timestamp import Timestamp

BASELINE_SCHEMA_VERSION: Final = "1.0"
DOMAIN_BASELINE: Final = b"sentinel-anubis:baseline:v1:"
BASELINE_MEMBER: Final = "baseline.json"
BASELINE_SIG_MEMBER: Final = "baseline.sig"
DEFAULT_INCLUDE_PATTERNS: Final[tuple[str, ...]] = (
    "**/*.py",
    "**/*.toml",
    "**/*.json",
    "**/*.md",
)
DEFAULT_EXCLUDE_PATTERNS: Final[tuple[str, ...]] = (
    "__pycache__",
    "*.pyc",
    ".venv",
    ".git",
    ".pytest_cache",
    "*.egg-info",
    "workspace",
    "*.sae",
    "*.sig",
    "*.log",
    "baseline.json",
)


class BaselineError(SentinelError):
    """Base error for baseline operations."""


class BaselineLoadError(BaselineError):
    """Baseline could not be read from disk."""


class BaselineSignError(BaselineError):
    """Baseline could not be signed or its signature is invalid."""


class BaselineStructureError(BaselineError):
    """Baseline content does not have the expected structure."""


@dataclass(frozen=True)
class BaselineEntry:

    path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size_bytes": self.size_bytes}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BaselineEntry:
        try:
            path, digest, size = d["path"], d["sha256"], d["size_bytes"]
        except (KeyError, TypeError) as e:
            raise BaselineStructureError(
                f"malformed baseline entry: {e}") from e
        if (
            not isinstance(path, str)
            or not isinstance(digest, str)
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise BaselineStructureError("invalid baseline entry values")
        return cls(path=path, sha256=digest, size_bytes=size)


@dataclass(frozen=True)
class BaselineIssue:

    code: str
    path: str
    expected_sha256: str | None
    actual_sha256: str | None
    expected_size: int | None
    actual_size: int | None


@dataclass(frozen=True)
class BaselineReport:

    root: str
    checked: int
    valid: int
    issues: tuple[BaselineIssue, ...]

    @property
    def is_clean(self) -> bool:
        return not self.issues

    def raise_if_invalid(self) -> None:
        if not self.is_clean:
            raise BaselineError(self.summary())

    def summary(self) -> str:
        if self.is_clean:
            return f"clean: {self.valid}/{self.checked} files verified"
        lines = [
            f"{len(self.issues)} issue(s): {self.valid}/{self.checked} files valid"]
        lines.extend(f"  {issue.code}: {issue.path}" for issue in self.issues)
        return "\n".join(lines)


@dataclass(frozen=True)
class Baseline:

    schema_version: str
    created_at: str
    operator_id: str
    root: str
    files: tuple[BaselineEntry, ...]
    exclude_patterns: tuple[str, ...]
    include_patterns: tuple[str, ...]
    signature: SignatureBundle

    def to_dict(self) -> dict[str, Any]:
        data = _payload_from_baseline(self)
        data["signature"] = self.signature.to_dict()
        return data

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Baseline:
        if not isinstance(d, dict):
            raise BaselineStructureError("baseline must be a JSON object")
        version = d.get("schema_version")
        if version != BASELINE_SCHEMA_VERSION:
            raise BaselineStructureError(
                f"unsupported baseline schema_version: {version!r}")
        try:
            return cls(
                schema_version=version,
                created_at=_require_str(d, "created_at"),
                operator_id=_require_str(d, "operator_id"),
                root=_require_str(d, "root"),
                files=tuple(BaselineEntry.from_dict(item)
                            for item in d["files"]),
                exclude_patterns=_require_str_tuple(d, "exclude_patterns"),
                include_patterns=_require_str_tuple(d, "include_patterns"),
                signature=SignatureBundle.from_dict(d["signature"]),
            )
        except BaselineError:
            raise
        except (KeyError, TypeError, ValueError, SentinelError) as e:
            raise BaselineStructureError(f"malformed baseline: {e}") from e

    @classmethod
    def create(
        cls,
        operator: KeyManager,
        root: Path | str,
        timestamp: Timestamp,
        include_patterns: Sequence[str] | None = None,
        exclude_patterns: Sequence[str] | None = None,
    ) -> Baseline:
        """Hash every matching file under root and sign the resulting manifest."""
        base = Path(root)
        if not base.is_dir():
            raise BaselineError(f"root is not a directory: {base}")
        base = base.resolve()
        includes = tuple(
            include_patterns) if include_patterns is not None else DEFAULT_INCLUDE_PATTERNS
        excludes = tuple(
            exclude_patterns) if exclude_patterns is not None else DEFAULT_EXCLUDE_PATTERNS
        entries = _collect_entries(base, includes, excludes)
        if not entries:
            raise BaselineStructureError(
                "no files matched the include patterns")
        payload = _build_payload(
            operator, timestamp, base, entries, includes, excludes)
        try:
            signature = operator.sign(
                DOMAIN_BASELINE + canonical_json(payload))
        except SentinelError as e:
            raise BaselineSignError(f"cannot sign baseline: {e}") from e
        return cls(
            schema_version=BASELINE_SCHEMA_VERSION,
            created_at=timestamp.iso_utc,
            operator_id=operator.identity.operator_id,
            root=str(base),
            files=tuple(entries),
            exclude_patterns=excludes,
            include_patterns=includes,
            signature=signature,
        )

    def save(self, path: Path | str) -> None:
        json_path, sig_path = _output_paths(Path(path))
        text = json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"
        try:
            _atomic_write(json_path, text.encode("utf-8"))
        except OSError as e:
            raise BaselineError(f"cannot write baseline: {e}") from e
        write_signature(sig_path, self.signature)

    @classmethod
    def load(cls, path: Path | str) -> Baseline:
        json_path, sig_path = _output_paths(Path(path))
        try:
            raw = json_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise BaselineLoadError(
                f"cannot read baseline {json_path}: {e}") from e
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise BaselineLoadError(
                f"baseline {json_path} is not valid JSON: {e}") from e
        baseline = cls.from_dict(data)
        if sig_path.exists():
            try:
                detached = read_signature(sig_path)
            except SentinelError as e:
                raise BaselineLoadError(
                    f"cannot read signature {sig_path}: {e}") from e
            if detached.to_dict() != baseline.signature.to_dict():
                raise BaselineLoadError(
                    "detached signature does not match the baseline")
        return baseline

    def verify_signature(self, identity: OperatorIdentity) -> None:
        data = DOMAIN_BASELINE + canonical_json(_payload_from_baseline(self))
        try:
            identity.verify(data, self.signature)
        except SentinelError as e:
            raise BaselineSignError(
                f"baseline signature is invalid: {e}") from e

    def verify_files(self, root: Path | str | None = None, check_extras: bool = False) -> BaselineReport:
        base = Path(root) if root is not None else Path(self.root)
        if not base.is_dir():
            raise BaselineError(f"root is not a directory: {base}")
        base = base.resolve()
        issues: list[BaselineIssue] = []
        valid = 0
        for entry in self.files:
            issue = _check_entry(entry, _safe_join(base, entry.path))
            if issue is None:
                valid += 1
            else:
                issues.append(issue)
        if check_extras:
            known = {entry.path for entry in self.files}
            for extra in _collect_entries(base, self.include_patterns, self.exclude_patterns):
                if extra.path not in known:
                    issues.append(
                        BaselineIssue("extra", extra.path, None,
                                      extra.sha256, None, extra.size_bytes)
                    )
        return BaselineReport(root=str(base), checked=len(self.files), valid=valid, issues=tuple(issues))


def _build_payload(
    operator: KeyManager,
    timestamp: Timestamp,
    root: Path,
    entries: Sequence[BaselineEntry],
    includes: Sequence[str],
    excludes: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "created_at": timestamp.iso_utc,
        "operator_id": operator.identity.operator_id,
        "root": str(root),
        "files": [entry.to_dict() for entry in entries],
        "include_patterns": list(includes),
        "exclude_patterns": list(excludes),
    }


def _payload_from_baseline(baseline: Baseline) -> dict[str, Any]:
    return {
        "schema_version": baseline.schema_version,
        "created_at": baseline.created_at,
        "operator_id": baseline.operator_id,
        "root": baseline.root,
        "files": [entry.to_dict() for entry in baseline.files],
        "include_patterns": list(baseline.include_patterns),
        "exclude_patterns": list(baseline.exclude_patterns),
    }


def _collect_entries(root: Path, includes: Sequence[str], excludes: Sequence[str]) -> list[BaselineEntry]:
    found: dict[str, Path] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        base = Path(dirpath)
        rel_dir = base.relative_to(root)
        dirnames[:] = sorted(d for d in dirnames if not _is_excluded(
            (rel_dir / d).as_posix(), excludes))
        for name in filenames:
            rel = (rel_dir / name).as_posix()
            if _is_excluded(rel, excludes) or not _is_included(rel, includes):
                continue
            full = base / name
            if full.is_symlink():
                continue
            found[rel] = full
    entries: list[BaselineEntry] = []
    for rel in sorted(found):
        try:
            size = found[rel].stat().st_size
            digest = hash_file(found[rel])
        except OSError as e:
            raise BaselineError(f"cannot read {rel}: {e}") from e
        entries.append(BaselineEntry(path=rel, sha256=digest, size_bytes=size))
    return entries


def _matches(rel_path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(rel_path, pattern) or fnmatch.fnmatchcase(rel_path, pattern.replace("**/", ""))


def _is_included(rel_path: str, patterns: Sequence[str]) -> bool:
    return any(_matches(rel_path, pattern) for pattern in patterns)


def _is_excluded(rel_path: str, patterns: Sequence[str]) -> bool:
    parts = PurePosixPath(rel_path).parts
    for pattern in patterns:
        if fnmatch.fnmatchcase(rel_path, pattern):
            return True
        if any(fnmatch.fnmatchcase(part, pattern) for part in parts):
            return True
    return False


def _safe_join(root: Path, rel: str) -> Path:
    if not rel:
        raise BaselineError("empty path in baseline")
    posix = PurePosixPath(rel)
    windows = PureWindowsPath(rel)
    if posix.is_absolute() or windows.is_absolute() or windows.drive or windows.root:
        raise BaselineError(f"absolute path in baseline: {rel!r}")
    if ".." in posix.parts or ".." in windows.parts:
        raise BaselineError(f"path traversal in baseline: {rel!r}")
    resolved_root = root.resolve()
    candidate = resolved_root / posix
    if not candidate.parent.resolve().is_relative_to(resolved_root):
        raise BaselineError(f"path escapes root: {rel!r}")
    return candidate


def _check_entry(entry: BaselineEntry, target: Path) -> BaselineIssue | None:
    try:
        if target.is_symlink():
            return BaselineIssue("modified", entry.path, entry.sha256, None, entry.size_bytes, None)
        if not target.is_file():
            return BaselineIssue("missing", entry.path, entry.sha256, None, entry.size_bytes, None)
        size = target.stat().st_size
        if size != entry.size_bytes:
            return BaselineIssue("size_changed", entry.path, entry.sha256, None, entry.size_bytes, size)
        digest = hash_file(target)
    except OSError:
        return BaselineIssue("unreadable", entry.path, entry.sha256, None, entry.size_bytes, None)
    if digest != entry.sha256:
        return BaselineIssue("modified", entry.path, entry.sha256, digest, entry.size_bytes, size)
    return None


def _output_paths(target: Path) -> tuple[Path, Path]:
    if target.is_dir():
        return target / BASELINE_MEMBER, target / BASELINE_SIG_MEMBER
    return target, target.with_name(target.name + ".sig")


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _require_str(d: dict[str, Any], key: str) -> str:
    value = d[key]
    if not isinstance(value, str) or not value:
        raise BaselineStructureError(f"{key} must be a non-empty string")
    return value


def _require_str_tuple(d: dict[str, Any], key: str) -> tuple[str, ...]:
    value = d[key]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BaselineStructureError(f"{key} must be a list of strings")
    return tuple(value)
