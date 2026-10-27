from __future__ import annotations

import json
import os
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from sentinel import SentinelPackagingError
from sentinel.custody.log import (
    SCHEMA_VERSION as CUSTODY_SCHEMA_VERSION,
    CustodyAction,
    CustodyLog,
)
from sentinel.integrity.hashing import canonical_json, hash_file, hash_stream
from sentinel.integrity.keys import (
    InvalidSignatureError,
    KeyManager,
    OperatorIdentity,
    SignatureBundle,
)
from sentinel.integrity.signing import (
    ManifestStructureError,
    read_signature,
    sign_package_manifest,
    verify_artifact_manifest,
    verify_custody_entry,
    verify_package_manifest,
    write_signature,
)
from sentinel.integrity.timestamp import SystemClock, TimeSource, Timestamp

PACKAGE_SCHEMA_VERSION: Final[str] = "1.0"
ARTIFACT_SCHEMA_VERSION: Final[str] = "1.0"
MANIFEST_MEMBER: Final[str] = "manifest.json"
MANIFEST_SIG_MEMBER: Final[str] = "manifest.sig"
CUSTODY_MEMBER: Final[str] = "custody.log"
TIMELINE_MEMBER: Final[str] = "timeline.json"
REPORT_MEMBER: Final[str] = "report.pdf"
ARTIFACTS_PREFIX: Final[str] = "artifacts/"

DEFAULT_MAX_TOTAL_BYTES: Final[int] = 100 * 1024**3
DEFAULT_MAX_ZIP_RATIO: Final[int] = 100
_ZIP_COMPRESSION: Final[int] = zipfile.ZIP_DEFLATED
_ZIP_STORED: Final[int] = zipfile.ZIP_STORED


class SAEError(SentinelPackagingError):


class SAEPackError(SAEError):


class SAEVerifyError(SAEError):


class SAEUnpackError(SAEError):


@dataclass(frozen=True)
class SAEArtifactResult:

    artifact_id: str
    valid: bool
    file_count: int
    signature_verified: bool
    issues: tuple["SAEIssue", ...] = ()


@dataclass(frozen=True)
class SAEIssue:

    code: str
    message: str
    location: str | None = None


@dataclass(frozen=True)
class SAEVerificationReport:

    valid: bool
    package_id: str | None
    artifacts: tuple[SAEArtifactResult, ...]
    custody_chain_valid: bool
    signatures_verified: bool
    issues: tuple[SAEIssue, ...]

    @property
    def artifacts_valid(self) -> int:
        return sum(1 for a in self.artifacts if a.valid)

    @property
    def artifacts_total(self) -> int:
        return len(self.artifacts)

    def raise_if_invalid(self) -> None:
        if not self.valid:
            codes = ", ".join(sorted({i.code for i in self.issues}))
            raise SAEError(
                f".sae verification failed: {len(self.issues)} issue(s) [{codes}]"
            )

    def summary(self) -> str:
        status = "OK" if self.valid else f"FAILED ({len(self.issues)} issues)"
        sig = "signed" if self.signatures_verified else "unsigned (no operators)"
        custody = "ok" if self.custody_chain_valid else "BROKEN"
        return (
            f"artifacts {self.artifacts_valid}/{self.artifacts_total}, "
            f"custody: {custody}, signatures: {sig}, status: {status}"
        )


def _build_package_manifest(
    operator: KeyManager,
    operation_id: str,
    timestamp: Timestamp,
    artifact_entries: list[dict[str, Any]],
    custody_log_bytes: bytes,
    custody_entries_count: int,
    custody_head_hash: str,
    timeline_bytes: bytes | None,
    report_bytes: bytes | None,
) -> dict[str, Any]:
    from sentinel.integrity.hashing import sha256_canonical

    manifest: dict[str, Any] = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": str(uuid.uuid4()),
        "operation_id": operation_id,
        "created_at": timestamp.iso_utc,
        "time_source": timestamp.source.value,
        "time_uncertainty_ms": timestamp.uncertainty_ms,
        "operator_id": operator.identity.operator_id,
        "artifacts": artifact_entries,
        "custody_log_sha256": sha256_canonical({"bytes": custody_log_bytes.decode("utf-8")})
        if False
        else _sha256_bytes(custody_log_bytes),
        "custody_entries_count": custody_entries_count,
        "custody_head_hash": custody_head_hash,
        "timeline_sha256": _sha256_bytes(timeline_bytes) if timeline_bytes else None,
        "report_sha256": _sha256_bytes(report_bytes) if report_bytes else None,
    }
    _ = sha256_canonical
    return manifest


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _read_artifact_manifest(directory: Path) -> dict[str, Any]:
    p = directory / "manifest.json"
    if not p.is_file():
        raise SAEPackError(f"artifact manifest missing: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SAEPackError(f"invalid artifact manifest {p}: {e}") from e
    if not isinstance(data, dict):
        raise SAEPackError(f"artifact manifest {p} is not a dict")
    if data.get("schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise SAEPackError(
            f"artifact {p} has unsupported schema_version "
            f"{data.get('schema_version')!r}"
        )
    for required in ("artifact_id", "type", "file"):
        if required not in data:
            raise SAEPackError(f"artifact manifest {p} missing {required!r}")
    return data


def _artifact_file_names(manifest: dict[str, Any]) -> list[str]:
    names: list[str] = ["manifest.json", "signature.sig"]
    file_field = manifest.get("file")
    if isinstance(file_field, dict) and isinstance(file_field.get("name"), str):
        names.append(file_field["name"])
    aux = manifest.get("auxiliary_files")
    if isinstance(aux, list):
        for n in aux:
            if isinstance(n, str):
                names.append(n)
    if (Path("data.sigmf-meta").name == "data.sigmf-meta"):
        if (manifest.get("file") or {}).get("name") == "data.bin":
            if "data.sigmf-meta" not in names:
                names.append("data.sigmf-meta")
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def pack(
    output_path: Path | str,
    operator: KeyManager,
    operation_id: str,
    artifact_dirs: list[Path | str] | tuple[Path | str, ...],
    custody_log_path: Path | str,
    timestamp: Timestamp | None = None,
    timeline_path: Path | str | None = None,
    report_path: Path | str | None = None,
    compress: bool = False,
) -> dict[str, Any]:

    if not artifact_dirs:
        raise SAEPackError("at least one artifact is required")
    if not operation_id:
        raise SAEPackError("operation_id must be non-empty")

    if timestamp is None:
        timestamp = SystemClock().now()

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    artifact_dirs_resolved: list[tuple[Path, dict[str, Any], list[str]]] = []
    artifact_entries: list[dict[str, Any]] = []
    for raw in artifact_dirs:
        d = Path(raw)
        if not d.is_dir():
            raise SAEPackError(f"artifact directory not found: {d}")
        manifest = _read_artifact_manifest(d)
        files = _artifact_file_names(manifest)
        for name in files:
            if not (d / name).is_file():
                raise SAEPackError(
                    f"artifact {manifest['artifact_id']}: missing {name}")
        artifact_dirs_resolved.append((d, manifest, files))

    for d, manifest, files in artifact_dirs_resolved:
        file_entries: list[dict[str, Any]] = []
        for name in files:
            if name in ("manifest.json", "signature.sig"):
                continue
            p = d / name
            file_entries.append(
                {
                    "name": name,
                    "sha256": hash_file(p),
                    "size_bytes": p.stat().st_size,
                }
            )
        manifest_sha = hash_file(d / "manifest.json")
        artifact_entries.append(
            {
                "artifact_id": manifest["artifact_id"],
                "type": manifest["type"],
                "directory": f"{ARTIFACTS_PREFIX}{manifest['artifact_id']}/",
                "files": file_entries,
                "manifest_sha256": manifest_sha,
            }
        )

    custody_path = Path(custody_log_path)
    if not custody_path.is_file():
        raise SAEPackError(f"custody log not found: {custody_path}")
    custody_log = CustodyLog(custody_path)
    chain_report = custody_log.verify_chain()
    if not chain_report.valid:
        raise SAEPackError(
            f"refusing to package corrupt custody log: "
            f"{len(chain_report.issues)} issue(s)"
        )
    custody_bytes = custody_path.read_bytes()
    custody_count = chain_report.valid_entries
    custody_head = chain_report.head_hash or ""

    timeline_bytes: bytes | None = None
    if timeline_path is not None:
        tp = Path(timeline_path)
        if not tp.is_file():
            raise SAEPackError(f"timeline not found: {tp}")
        timeline_bytes = tp.read_bytes()
    report_bytes: bytes | None = None
    if report_path is not None:
        rp = Path(report_path)
        if not rp.is_file():
            raise SAEPackError(f"report not found: {rp}")
        report_bytes = rp.read_bytes()

    manifest = _build_package_manifest(
        operator=operator,
        operation_id=operation_id,
        timestamp=timestamp,
        artifact_entries=artifact_entries,
        custody_log_bytes=custody_bytes,
        custody_entries_count=custody_count,
        custody_head_hash=custody_head,
        timeline_bytes=timeline_bytes,
        report_bytes=report_bytes,
    )
    signature = sign_package_manifest(operator, manifest)
    manifest["signature"] = signature.to_dict()

    manifest_bytes = canonical_json(manifest)
    signature_bytes = canonical_json(signature.to_dict())

    compression = _ZIP_COMPRESSION if compress else _ZIP_STORED
    try:
        with zipfile.ZipFile(output, "w", compression=compression, allowZip64=True) as zf:
            zf.writestr(MANIFEST_MEMBER, manifest_bytes)
            zf.writestr(MANIFEST_SIG_MEMBER, signature_bytes)
            zf.writestr(CUSTODY_MEMBER, custody_bytes)
            if timeline_bytes is not None:
                zf.writestr(TIMELINE_MEMBER, timeline_bytes)
            if report_bytes is not None:
                zf.writestr(REPORT_MEMBER, report_bytes)
            for d, art_manifest, files in artifact_dirs_resolved:
                aid = art_manifest["artifact_id"]
                for name in files:
                    zf.write(
                        d / name, arcname=f"{ARTIFACTS_PREFIX}{aid}/{name}")
    except OSError as e:
        raise SAEPackError(f"cannot write {output}: {e}") from e

    return manifest


def verify(
    package_path: Path | str,
    operators: dict[str, OperatorIdentity] | None = None,
    verify_custody_chain: bool = True,
) -> SAEVerificationReport:

    path = Path(package_path)
    if not path.is_file():
        raise SAEVerifyError(f"package not found: {path}")

    issues: list[SAEIssue] = []
    artifact_results: list[SAEArtifactResult] = []
    custody_chain_valid = True
    package_id: str | None = None

    try:
        zf = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as e:
        raise SAEVerifyError(f"not a valid ZIP: {e}") from e

    with zf:
        names = set(zf.namelist())
        for required in (MANIFEST_MEMBER, MANIFEST_SIG_MEMBER, CUSTODY_MEMBER):
            if required not in names:
                issues.append(
                    SAEIssue(
                        code="missing_member",
                        message=f"required member {required!r} is missing",
                    )
                )
        if issues:
            return SAEVerificationReport(
                valid=False,
                package_id=None,
                artifacts=(),
                custody_chain_valid=False,
                signatures_verified=operators is not None,
                issues=tuple(issues),
            )

        try:
            manifest = json.loads(zf.read(MANIFEST_MEMBER).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            issues.append(
                SAEIssue(code="manifest_invalid",
                         message=f"cannot parse manifest: {e}")
            )
            return _finalize(issues, artifact_results, False, None, operators)

        if not isinstance(manifest, dict):
            issues.append(
                SAEIssue(code="manifest_invalid",
                         message="manifest is not a JSON object")
            )
            return _finalize(issues, artifact_results, False, None, operators)

        package_id = manifest.get("package_id")
        if manifest.get("schema_version") != PACKAGE_SCHEMA_VERSION:
            issues.append(
                SAEIssue(
                    code="schema_version",
                    message=f"unsupported schema_version "
                    f"{manifest.get('schema_version')!r}",
                )
            )
            return _finalize(issues, artifact_results, False, package_id, operators)

        try:
            embedded_sig = SignatureBundle.from_dict(
                manifest.get("signature", {}))
        except Exception as e:
            issues.append(
                SAEIssue(code="signature_missing",
                         message=f"manifest signature: {e}")
            )
            embedded_sig = None

        if embedded_sig is not None:
            try:
                sidecar_sig = SignatureBundle.from_dict(
                    json.loads(zf.read(MANIFEST_SIG_MEMBER).decode("utf-8"))
                )
            except Exception as e:
                issues.append(
                    SAEIssue(code="signature_sidecar",
                             message=f"manifest.sig: {e}")
                )
                sidecar_sig = None

            if sidecar_sig is not None:
                if sidecar_sig != embedded_sig:
                    issues.append(
                        SAEIssue(
                            code="signature_mismatch",
                            message="embedded signature != manifest.sig",
                        )
                    )

            if operators is not None:
                op_id = manifest.get("operator_id")
                identity = operators.get(op_id) if op_id else None
                if identity is None:
                    issues.append(
                        SAEIssue(
                            code="operator_unknown",
                            message=f"operator_id {op_id!r} not in operators map",
                        )
                    )
                else:
                    try:
                        verify_package_manifest(
                            identity, manifest, embedded_sig)
                    except (InvalidSignatureError, ManifestStructureError) as e:
                        issues.append(
                            SAEIssue(
                                code="signature_invalid",
                                message=f"package signature: {e}",
                            )
                        )

        artifact_entries = manifest.get("artifacts", [])
        if not isinstance(artifact_entries, list):
            issues.append(
                SAEIssue(code="manifest_invalid",
                         message="artifacts is not a list")
            )
            artifact_entries = []
        for entry in artifact_entries:
            if not isinstance(entry, dict):
                issues.append(
                    SAEIssue(code="manifest_invalid",
                             message="artifact entry not an object")
                )
                continue
            artifact_results.append(
                _verify_artifact_entry(zf, entry, operators, issues)
            )

        try:
            custody_bytes = zf.read(CUSTODY_MEMBER)
        except KeyError as e:
            issues.append(
                SAEIssue(code="missing_member", message=f"custody.log: {e}")
            )
            custody_bytes = b""

        expected_custody_hash = manifest.get("custody_log_sha256")
        if isinstance(expected_custody_hash, str):
            actual = _sha256_bytes(custody_bytes)
            if actual != expected_custody_hash:
                issues.append(
                    SAEIssue(
                        code="custody_hash_mismatch",
                        message=(
                            f"custody.log hash {actual[:16]}... != "
                            f"{expected_custody_hash[:16]}..."
                        ),
                    )
                )
        expected_count = manifest.get("custody_entries_count")
        if isinstance(expected_count, int):
            actual_lines = sum(
                1 for line in custody_bytes.decode("utf-8", errors="replace").splitlines()
                if line.strip()
            )
            if actual_lines != expected_count:
                issues.append(
                    SAEIssue(
                        code="custody_count_mismatch",
                        message=(
                            f"custody.log has {actual_lines} lines, "
                            f"manifest says {expected_count}"
                        ),
                    )
                )

        if verify_custody_chain and custody_bytes:
            custody_chain_valid = _verify_custody(
                zf, custody_bytes, manifest, operators, issues
            )

        if TIMELINE_MEMBER in names:
            _verify_optional_member(
                zf, TIMELINE_MEMBER, manifest.get("timeline_sha256"), issues
            )
        elif manifest.get("timeline_sha256"):
            issues.append(
                SAEIssue(
                    code="missing_member",
                    message="manifest declares timeline but member is missing",
                )
            )

        if REPORT_MEMBER in names:
            _verify_optional_member(
                zf, REPORT_MEMBER, manifest.get("report_sha256"), issues
            )
        elif manifest.get("report_sha256"):
            issues.append(
                SAEIssue(
                    code="missing_member",
                    message="manifest declares report but member is missing",
                )
            )

    return _finalize(issues, artifact_results, custody_chain_valid, package_id, operators)


def _finalize(
    issues: list[SAEIssue],
    artifact_results: list[SAEArtifactResult],
    custody_chain_valid: bool,
    package_id: str | None,
    operators: dict[str, OperatorIdentity] | None,
) -> SAEVerificationReport:
    artifact_ok = all(
        a.valid for a in artifact_results) if artifact_results else True
    valid = (
        not issues
        and artifact_ok
        and (custody_chain_valid or True)
    )
    return SAEVerificationReport(
        valid=valid,
        package_id=package_id,
        artifacts=tuple(artifact_results),
        custody_chain_valid=custody_chain_valid,
        signatures_verified=operators is not None,
        issues=tuple(issues),
    )


def _verify_artifact_entry(
    zf: zipfile.ZipFile,
    entry: dict[str, Any],
    operators: dict[str, OperatorIdentity] | None,
    parent_issues: list[SAEIssue],
) -> SAEArtifactResult:
    local_issues: list[SAEIssue] = []
    artifact_id = entry.get("artifact_id", "<unknown>")
    directory = entry.get("directory")
    if not isinstance(directory, str) or not directory.endswith("/"):
        parent_issues.append(
            SAEIssue(
                code="manifest_invalid",
                message=f"artifact {artifact_id}: bad directory field",
                location=artifact_id,
            )
        )
        return SAEArtifactResult(
            artifact_id=str(artifact_id),
            valid=False,
            file_count=0,
            signature_verified=False,
            issues=(SAEIssue(code="manifest_invalid",
                    message="bad directory field"),),
        )

    files = entry.get("files", [])
    if not isinstance(files, list):
        local_issues.append(
            SAEIssue(code="manifest_invalid", message="files is not a list")
        )
        files = []

    file_count = 0
    for f in files:
        if not isinstance(f, dict):
            local_issues.append(
                SAEIssue(code="manifest_invalid",
                         message="file entry not an object")
            )
            continue
        name = f.get("name")
        expected = f.get("sha256")
        if not isinstance(name, str) or not isinstance(expected, str):
            local_issues.append(
                SAEIssue(
                    code="manifest_invalid",
                    message=f"file entry for {name!r} missing name/sha256",
                )
            )
            continue
        member = f"{directory}{name}"
        try:
            with zf.open(member) as fh:
                actual = hash_stream(fh)
        except KeyError:
            local_issues.append(
                SAEIssue(
                    code="missing_member",
                    message=f"file {name} declared but not in ZIP",
                    location=member,
                )
            )
            continue
        file_count += 1
        if actual != expected:
            local_issues.append(
                SAEIssue(
                    code="artifact_hash_mismatch",
                    message=(
                        f"{name}: {actual[:16]}... != {expected[:16]}..."
                    ),
                    location=member,
                )
            )

    manifest_member = f"{directory}manifest.json"
    expected_manifest_hash = entry.get("manifest_sha256")
    try:
        art_manifest_bytes = zf.read(manifest_member)
    except KeyError:
        local_issues.append(
            SAEIssue(
                code="missing_member",
                message="artifact manifest missing from ZIP",
                location=manifest_member,
            )
        )
        art_manifest_bytes = b""

    art_manifest: dict[str, Any] | None = None
    if art_manifest_bytes:
        actual_mh = _sha256_bytes(art_manifest_bytes)
        if isinstance(expected_manifest_hash, str) and actual_mh != expected_manifest_hash:
            local_issues.append(
                SAEIssue(
                    code="manifest_hash_mismatch",
                    message=(
                        f"artifact manifest hash {actual_mh[:16]}... != "
                        f"{expected_manifest_hash[:16]}..."
                    ),
                    location=manifest_member,
                )
            )
        try:
            art_manifest = json.loads(art_manifest_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            local_issues.append(
                SAEIssue(
                    code="manifest_invalid",
                    message=f"cannot parse artifact manifest: {e}",
                    location=manifest_member,
                )
            )

    signature_verified = False
    if operators is not None and isinstance(art_manifest, dict):
        sig_member = f"{directory}signature.sig"
        try:
            art_sig = SignatureBundle.from_dict(
                json.loads(zf.read(sig_member).decode("utf-8"))
            )
        except KeyError:
            local_issues.append(
                SAEIssue(
                    code="missing_member",
                    message="artifact signature missing from ZIP",
                    location=sig_member,
                )
            )
            art_sig = None
        except Exception as e:
            local_issues.append(
                SAEIssue(
                    code="signature_missing",
                    message=f"artifact signature: {e}",
                    location=sig_member,
                )
            )
            art_sig = None

        if art_sig is not None:
            op_id = art_manifest.get("operator_id")
            identity = operators.get(op_id) if isinstance(op_id, str) else None
            if identity is None:
                local_issues.append(
                    SAEIssue(
                        code="operator_unknown",
                        message=f"artifact operator_id {op_id!r} not in operators",
                        location=sig_member,
                    )
                )
            else:
                try:
                    verify_artifact_manifest(identity, art_manifest, art_sig)
                    signature_verified = True
                except (InvalidSignatureError, ManifestStructureError) as e:
                    local_issues.append(
                        SAEIssue(
                            code="signature_invalid",
                            message=f"artifact signature: {e}",
                            location=sig_member,
                        )
                    )

    parent_issues.extend(local_issues)
    return SAEArtifactResult(
        artifact_id=str(artifact_id),
        valid=not local_issues,
        file_count=file_count,
        signature_verified=signature_verified,
        issues=tuple(local_issues),
    )


def _verify_custody(
    zf: zipfile.ZipFile,
    custody_bytes: bytes,
    manifest: dict[str, Any],
    operators: dict[str, OperatorIdentity] | None,
    parent_issues: list[SAEIssue],
) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
        tmp.write(custody_bytes)
        tmp_path = Path(tmp.name)
    try:
        log = CustodyLog(tmp_path)
        if operators is not None:
            report = log.verify_chain(operators=operators)
        else:
            report = log.verify_chain()
    finally:
        tmp_path.unlink(missing_ok=True)

    if not report.valid:
        for i in report.issues:
            parent_issues.append(
                SAEIssue(
                    code=f"custody_{i.code}",
                    message=f"custody entry seq={i.seq}: {i.message}",
                    location=f"custody.log:line {i.line_no}",
                )
            )
    expected_head = manifest.get("custody_head_hash")
    if isinstance(expected_head, str) and expected_head:
        actual_head = report.head_hash or ""
        if actual_head != expected_head:
            parent_issues.append(
                SAEIssue(
                    code="custody_head_mismatch",
                    message=f"head hash {actual_head[:16]}... != {expected_head[:16]}...",
                )
            )
    return report.valid


def _verify_optional_member(
    zf: zipfile.ZipFile,
    member: str,
    expected: Any,
    issues: list[SAEIssue],
) -> None:
    if not isinstance(expected, str):
        issues.append(
            SAEIssue(
                code="manifest_invalid",
                message=f"manifest missing hash for {member}",
                location=member,
            )
        )
        return
    try:
        with zf.open(member) as fh:
            actual = hash_stream(fh)
    except KeyError:
        issues.append(
            SAEIssue(code="missing_member",
                     message=f"{member} not in ZIP", location=member)
        )
        return
    if actual != expected:
        issues.append(
            SAEIssue(
                code="optional_hash_mismatch",
                message=f"{member}: {actual[:16]}... != {expected[:16]}...",
                location=member,
            )
        )


def unpack(
    package_path: Path | str,
    output_dir: Path | str,
    overwrite: bool = False,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    max_ratio: int = DEFAULT_MAX_ZIP_RATIO,
) -> Path:

    src = Path(package_path)
    if not src.is_file():
        raise SAEUnpackError(f"package not found: {src}")

    dest = Path(output_dir).resolve()
    if dest.exists() and any(dest.iterdir()) and not overwrite:
        raise SAEUnpackError(f"destination is not empty: {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    try:
        zf = zipfile.ZipFile(src, "r")
    except zipfile.BadZipFile as e:
        raise SAEUnpackError(f"not a valid ZIP: {e}") from e

    total = 0
    with zf:
        for info in zf.infolist():
            member = info.filename
            target = _safe_extract_target(dest, member)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += info.file_size
            if total > max_total_bytes:
                raise SAEUnpackError(
                    f"uncompressed total exceeds {max_total_bytes} bytes "
                    f"(zip bomb protection)"
                )
            if info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > max_ratio:
                    raise SAEUnpackError(
                        f"{member}: compression ratio {ratio:.1f} > {max_ratio} "
                        f"(zip bomb protection)"
                    )
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(info) as src_fh, open(target, "wb") as dst_fh:
                    _copy_stream(src_fh, dst_fh)
            except OSError as e:
                raise SAEUnpackError(f"cannot extract {member}: {e}") from e

    return dest


def _safe_extract_target(base: Path, member: str) -> Path:
    if not member or member.endswith("/"):
        candidate = (base / member.rstrip("/")).resolve()
    else:
        candidate = (base / member).resolve()
    if member.startswith("/") or member.startswith("\\"):
        raise SAEUnpackError(f"absolute path in ZIP: {member!r}")
    if any(part == ".." for part in Path(member).parts):
        raise SAEUnpackError(f"'..' in ZIP member: {member!r}")
    try:
        candidate.relative_to(base)
    except ValueError as e:
        raise SAEUnpackError(
            f"ZIP member escapes destination: {member!r}") from e
    return candidate


def _copy_stream(src: Any, dst: Any, chunk_size: int = 1024 * 1024) -> None:
    while True:
        chunk = src.read(chunk_size)
        if not chunk:
            return
        dst.write(chunk)


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "CUSTODY_MEMBER",
    "DEFAULT_MAX_TOTAL_BYTES",
    "DEFAULT_MAX_ZIP_RATIO",
    "MANIFEST_MEMBER",
    "MANIFEST_SIG_MEMBER",
    "PACKAGE_SCHEMA_VERSION",
    "REPORT_MEMBER",
    "SAEArtifactResult",
    "SAEError",
    "SAEIssue",
    "SAEPackError",
    "SAEUnpackError",
    "SAEVerificationReport",
    "SAEVerifyError",
    "TIMELINE_MEMBER",
    "pack",
    "unpack",
    "verify",
]
