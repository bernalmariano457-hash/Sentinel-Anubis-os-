from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from sentinel.integrity.hashing import canonical_json, hash_file
from sentinel.integrity.keys import (
    KeyManager,
    OperatorIdentity,
    SentinelKeyError,
    SignatureBundle,
)

DOMAIN_BYTES: Final[bytes] = b"sentinel-anubis:bytes:v1:"
DOMAIN_FILE: Final[bytes] = b"sentinel-anubis:file:v1:"
DOMAIN_ENTITY: Final[bytes] = b"sentinel-anubis:entity:v1:"
DOMAIN_MANIFEST_ARTIFACT: Final[bytes] = b"sentinel-anubis:artifact-manifest:v1:"
DOMAIN_MANIFEST_PACKAGE: Final[bytes] = b"sentinel-anubis:package-manifest:v1:"
DOMAIN_CUSTODY_ENTRY: Final[bytes] = b"sentinel-anubis:custody-entry:v1:"


_MANIFEST_EXCLUDED: Final[frozenset[str]] = frozenset({"signature"})
_CUSTODY_EXCLUDED: Final[frozenset[str]] = frozenset(
    {"entry_hash", "signature"})


class SigningError(SentinelKeyError):
    """Base class for signing-related errors."""


class SignatureFileError(SigningError):
    """A `.sig` sidecar file is missing, malformed, or unreadable."""


class ManifestStructureError(SigningError):
    """A manifest is missing required fields or has the wrong type."""
def sign_bytes(
    km: KeyManager,
    data: bytes,
    domain: bytes = DOMAIN_BYTES,
) -> SignatureBundle:

    if not isinstance(domain, bytes) or not domain:
        raise TypeError("domain must be a non-empty bytes object")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes-like, got {type(data).__name__}")
    return km.sign(domain + bytes(data))


def verify_bytes(
    identity: OperatorIdentity,
    data: bytes,
    bundle: SignatureBundle,
    domain: bytes = DOMAIN_BYTES,
) -> None:

    if not isinstance(domain, bytes) or not domain:
        raise TypeError("domain must be a non-empty bytes object")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError(f"data must be bytes-like, got {type(data).__name__}")
    identity.verify(domain + bytes(data), bundle)


def sign_file(km: KeyManager, path: Path | str) -> SignatureBundle:

    digest = hash_file(path)
    return km.sign(DOMAIN_FILE + digest.encode("ascii"))


def verify_file(
    identity: OperatorIdentity,
    path: Path | str,
    bundle: SignatureBundle,
) -> None:

    digest = hash_file(path)
    identity.verify(DOMAIN_FILE + digest.encode("ascii"), bundle)


def sign_entity(
    km: KeyManager,
    entity: dict[str, Any],
    domain: bytes,
) -> SignatureBundle:

    if not isinstance(entity, dict):
        raise TypeError(f"entity must be a dict, got {type(entity).__name__}")
    return km.sign(domain + canonical_json(entity))


def verify_entity(
    identity: OperatorIdentity,
    entity: dict[str, Any],
    bundle: SignatureBundle,
    domain: bytes,
) -> None:

    if not isinstance(entity, dict):
        raise TypeError(f"entity must be a dict, got {type(entity).__name__}")
    identity.verify(domain + canonical_json(entity), bundle)


def _strip(entity: dict[str, Any], excluded: frozenset[str]) -> dict[str, Any]:
    return {k: v for k, v in entity.items() if k not in excluded}


def sign_artifact_manifest(
    km: KeyManager,
    manifest: dict[str, Any],
) -> SignatureBundle:

    _require_fields(manifest, ("schema_version", "artifact_id"))
    return km.sign(
        DOMAIN_MANIFEST_ARTIFACT +
        canonical_json(_strip(manifest, _MANIFEST_EXCLUDED))
    )


def verify_artifact_manifest(
    identity: OperatorIdentity,
    manifest: dict[str, Any],
    bundle: SignatureBundle,
) -> None:
    _require_fields(manifest, ("schema_version", "artifact_id"))
    identity.verify(
        DOMAIN_MANIFEST_ARTIFACT +
        canonical_json(_strip(manifest, _MANIFEST_EXCLUDED)),
        bundle,
    )


def sign_package_manifest(
    km: KeyManager,
    manifest: dict[str, Any],
) -> SignatureBundle:

    _require_fields(manifest, ("schema_version", "package_id"))
    return km.sign(
        DOMAIN_MANIFEST_PACKAGE +
        canonical_json(_strip(manifest, _MANIFEST_EXCLUDED))
    )


def verify_package_manifest(
    identity: OperatorIdentity,
    manifest: dict[str, Any],
    bundle: SignatureBundle,
) -> None:

    _require_fields(manifest, ("schema_version", "package_id"))
    identity.verify(
        DOMAIN_MANIFEST_PACKAGE +
        canonical_json(_strip(manifest, _MANIFEST_EXCLUDED)),
        bundle,
    )


def sign_custody_entry(
    km: KeyManager,
    entry: dict[str, Any],
) -> SignatureBundle:

    _require_fields(entry, ("schema_version", "entry_id", "seq"))
    return km.sign(
        DOMAIN_CUSTODY_ENTRY + canonical_json(_strip(entry, _CUSTODY_EXCLUDED))
    )


def verify_custody_entry(
    identity: OperatorIdentity,
    entry: dict[str, Any],
    bundle: SignatureBundle,
) -> None:

    _require_fields(entry, ("schema_version", "entry_id", "seq"))
    identity.verify(
        DOMAIN_CUSTODY_ENTRY +
        canonical_json(_strip(entry, _CUSTODY_EXCLUDED)),
        bundle,
    )


def write_signature(path: Path | str, bundle: SignatureBundle) -> None:

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def read_signature(path: Path | str) -> SignatureBundle:

    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise SignatureFileError(f"signature file not found: {p}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SignatureFileError(f"invalid JSON in {p}: {e}") from e
    try:
        return SignatureBundle.from_dict(data)
    except SentinelKeyError as e:
        raise SignatureFileError(
            f"invalid signature bundle in {p}: {e}") from e


def sign_file_with_sidecar(
    km: KeyManager,
    path: Path | str,
    sig_path: Path | str | None = None,
) -> Path:

    bundle = sign_file(km, path)
    target = Path(sig_path) if sig_path is not None else Path(
        str(path) + ".sig")
    write_signature(target, bundle)
    return target


def verify_file_with_sidecar(
    identity: OperatorIdentity,
    path: Path | str,
    sig_path: Path | str | None = None,
) -> None:

    bundle = read_signature(
        Path(sig_path) if sig_path is not None else Path(str(path) + ".sig")
    )
    verify_file(identity, path, bundle)


def _require_fields(entity: dict[str, Any], fields: tuple[str, ...]) -> None:
    if not isinstance(entity, dict):
        raise ManifestStructureError(
            f"entity must be a dict, got {type(entity).__name__}"
        )
    missing = [f for f in fields if f not in entity]
    if missing:
        raise ManifestStructureError(
            f"missing required field(s): {', '.join(missing)}"
        )
