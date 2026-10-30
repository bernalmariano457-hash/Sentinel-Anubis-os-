from __future__ import annotations

import base64
import binascii
import io
import json
import os
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from sentinel import SentinelError

VAULT_SCHEMA_VERSION: Final = "1.0"
VAULT_META_FILENAME: Final = ".sentinel-vault.json"
VAULT_BLOB_FILENAME: Final = ".sentinel-vault.bin"
ARGON2_ITERATIONS: Final = 3
ARGON2_LANES: Final = 4
ARGON2_MEMORY_KIB: Final = 65536
SALT_LEN: Final = 16
NONCE_LEN: Final = 12
KEY_LEN: Final = 32
MIN_PASSPHRASE_LEN: Final = 16

_DEK_AAD: Final = b"sentinel-anubis:vault:dek:v1"
_BLOB_AAD: Final = b"sentinel-anubis:vault:blob:v1"


class VaultError(SentinelError):
    """Base error for vault operations."""


class VaultNotSetupError(VaultError):
    """The vault has not been initialised in this workspace."""


class VaultAlreadySetupError(VaultError):
    """The vault is already initialised in this workspace."""


class VaultAuthError(VaultError):
    """Wrong passphrase or tampered ciphertext."""


@dataclass(frozen=True)
class VaultMeta:

    schema_version: str
    salt_b64: str
    wrapped_dek_b64: str
    wrapped_dek_nonce_b64: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "salt_b64": self.salt_b64,
            "wrapped_dek_b64": self.wrapped_dek_b64,
            "wrapped_dek_nonce_b64": self.wrapped_dek_nonce_b64,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VaultMeta:
        if not isinstance(d, dict):
            raise VaultError("vault metadata must be a JSON object")
        version = d.get("schema_version")
        if version != VAULT_SCHEMA_VERSION:
            raise VaultError(f"unsupported vault schema_version: {version!r}")
        try:
            values = [d["salt_b64"], d["wrapped_dek_b64"],
                      d["wrapped_dek_nonce_b64"]]
        except KeyError as e:
            raise VaultError(f"vault metadata missing field: {e}") from e
        if not all(isinstance(v, str) for v in values):
            raise VaultError("vault metadata fields must be strings")
        return cls(version, values[0], values[1], values[2])


def _derive_kek(passphrase: str, salt: bytes) -> bytes:
    kdf = Argon2id(
        salt=salt,
        length=KEY_LEN,
        iterations=ARGON2_ITERATIONS,
        lanes=ARGON2_LANES,
        memory_cost=ARGON2_MEMORY_KIB,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _check_passphrase(passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        raise ValueError(
            f"passphrase must be at least {MIN_PASSPHRASE_LEN} characters")


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _write_meta(workspace: Path, meta: VaultMeta) -> None:
    text = json.dumps(meta.to_dict(), indent=2, sort_keys=True) + "\n"
    try:
        _atomic_write(workspace / VAULT_META_FILENAME, text.encode("utf-8"))
    except OSError as e:
        raise VaultError(f"cannot write vault metadata: {e}") from e


def setup(workspace: Path | str, passphrase: str) -> VaultMeta:
    root = Path(workspace)
    if (root / VAULT_META_FILENAME).exists():
        raise VaultAlreadySetupError("vault is already set up")
    _check_passphrase(passphrase)
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    dek = os.urandom(KEY_LEN)
    kek = _derive_kek(passphrase, salt)
    wrapped = AESGCM(kek).encrypt(nonce, dek, _DEK_AAD)
    meta = VaultMeta(
        schema_version=VAULT_SCHEMA_VERSION,
        salt_b64=base64.b64encode(salt).decode("ascii"),
        wrapped_dek_b64=base64.b64encode(wrapped).decode("ascii"),
        wrapped_dek_nonce_b64=base64.b64encode(nonce).decode("ascii"),
    )
    root.mkdir(parents=True, exist_ok=True)
    _write_meta(root, meta)
    return meta


def load_meta(workspace: Path | str) -> VaultMeta:
    path = Path(workspace) / VAULT_META_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise VaultNotSetupError("vault is not set up") from e
    except (OSError, UnicodeDecodeError) as e:
        raise VaultError(f"cannot read vault metadata: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise VaultError(f"vault metadata is not valid JSON: {e}") from e
    return VaultMeta.from_dict(data)


def _unwrap_dek(meta: VaultMeta, passphrase: str) -> bytes:
    try:
        salt = base64.b64decode(meta.salt_b64, validate=True)
        wrapped = base64.b64decode(meta.wrapped_dek_b64, validate=True)
        nonce = base64.b64decode(meta.wrapped_dek_nonce_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise VaultError(f"vault metadata is corrupt: {e}") from e
    kek = _derive_kek(passphrase, salt)
    try:
        return AESGCM(kek).decrypt(nonce, wrapped, _DEK_AAD)
    except InvalidTag as e:
        raise VaultAuthError("invalid passphrase") from e


def verify_passphrase(workspace: Path | str, passphrase: str) -> None:
    """Raise VaultAuthError unless the passphrase unwraps the DEK."""
    _unwrap_dek(load_meta(workspace), passphrase)


def _check_member_name(name: str) -> None:
    posix = PurePosixPath(name)
    windows = PureWindowsPath(name)
    unsafe = (
        not name
        or posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
        or ".." in windows.parts
    )
    if unsafe:
        raise VaultError(f"unsafe path: {name!r}")


def validate_include(include: Sequence[str]) -> None:
    if not include:
        raise VaultError("include list is empty")
    for name in include:
        _check_member_name(name)


def _wrap_directory(source: Path, include: list[str]) -> bytes:
    buffer = io.BytesIO()
    added = 0
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in include:
            _check_member_name(name)
            target = source / name
            if target.exists() or target.is_symlink():
                tar.add(target, arcname=name)
                added += 1
    if not added:
        raise VaultError("none of the included paths exist")
    return buffer.getvalue()


def _extract_directory(data: bytes, dest: Path) -> None:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                _check_member_name(member.name)
            tar.extractall(dest, filter="data")
    except (tarfile.TarError, OSError, EOFError) as e:
        raise VaultError(f"cannot extract vault archive: {e}") from e


def seal(workspace: Path | str, passphrase: str, include: list[str]) -> Path:
    root = Path(workspace)
    meta = load_meta(root)
    dek = _unwrap_dek(meta, passphrase)
    archive = _wrap_directory(root, include)
    nonce = os.urandom(NONCE_LEN)
    ciphertext = AESGCM(dek).encrypt(nonce, archive, _BLOB_AAD)
    blob_path = root / VAULT_BLOB_FILENAME
    try:
        _atomic_write(blob_path, nonce + ciphertext)
    except OSError as e:
        raise VaultError(f"cannot write vault blob: {e}") from e
    return blob_path


def unseal(workspace: Path | str, passphrase: str) -> None:
    root = Path(workspace)
    meta = load_meta(root)
    blob_path = root / VAULT_BLOB_FILENAME
    if not blob_path.is_file():
        raise VaultError("vault blob not found")
    dek = _unwrap_dek(meta, passphrase)
    try:
        blob = blob_path.read_bytes()
    except OSError as e:
        raise VaultError(f"cannot read vault blob: {e}") from e
    if len(blob) < NONCE_LEN:
        raise VaultError("vault blob is truncated")
    nonce, ciphertext = blob[:NONCE_LEN], blob[NONCE_LEN:]
    try:
        archive = AESGCM(dek).decrypt(nonce, ciphertext, _BLOB_AAD)
    except InvalidTag as e:
        raise VaultAuthError("vault integrity check failed") from e
    _extract_directory(archive, root)


def change_passphrase(workspace: Path | str, old: str, new: str) -> None:
    _check_passphrase(new)
    root = Path(workspace)
    meta = load_meta(root)
    dek = _unwrap_dek(meta, old)
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    kek = _derive_kek(new, salt)
    wrapped = AESGCM(kek).encrypt(nonce, dek, _DEK_AAD)
    _write_meta(
        root,
        VaultMeta(
            schema_version=VAULT_SCHEMA_VERSION,
            salt_b64=base64.b64encode(salt).decode("ascii"),
            wrapped_dek_b64=base64.b64encode(wrapped).decode("ascii"),
            wrapped_dek_nonce_b64=base64.b64encode(nonce).decode("ascii"),
        ),
    )


def is_setup(workspace: Path | str) -> bool:
    return (Path(workspace) / VAULT_META_FILENAME).exists()


def has_blob(workspace: Path | str) -> bool:
    return (Path(workspace) / VAULT_BLOB_FILENAME).exists()
