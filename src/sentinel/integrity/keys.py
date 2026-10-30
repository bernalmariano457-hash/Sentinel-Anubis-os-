from __future__ import annotations

import base64
import hashlib
import secrets
import warnings
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import keyring
import keyring.errors
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from sentinel import SentinelError

DEFAULT_SERVICE: Final[str] = "sentinel-anubis"

_PUBKEY_RAW_LEN: Final[int] = 32

_PRIVKEY_RAW_LEN: Final[int] = 32

_SIGNATURE_LEN: Final[int] = 64

_FP_PREFIX: Final[str] = "SHA256:"


class SentinelKeyError(SentinelError):
    """Base class for all key-management errors."""


class OperatorNotFoundError(SentinelKeyError):
    """The operator_id does not exist in the keyring."""


class KeyringUnavailableError(SentinelKeyError):
    """The OS keyring backend is not available or refused the operation."""


class InvalidSignatureError(SentinelKeyError):
    """The signature does not verify against the given data and public key."""


class InvalidSignatureBundleError(SentinelKeyError):
    """The signature bundle is malformed."""


class RotationError(SentinelKeyError):
    """Rotation cannot be completed (e.g. target operator_id already exists)."""
@dataclass(frozen=True)
class SignatureBundle:

    algorithm: str
    value: str
    pubkey_fingerprint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "algorithm": self.algorithm,
            "value": self.value,
            "pubkey_fingerprint": self.pubkey_fingerprint,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SignatureBundle:
        if not isinstance(d, dict):
            raise InvalidSignatureBundleError(
                f"signature bundle must be a dict, got {type(d).__name__}"
            )
        try:
            algorithm = d["algorithm"]
            value = d["value"]
            fingerprint = d["pubkey_fingerprint"]
        except KeyError as e:
            raise InvalidSignatureBundleError(f"missing key: {e}") from e
        if algorithm != "ed25519":
            raise InvalidSignatureBundleError(
                f"unsupported algorithm: {algorithm!r} (only 'ed25519')"
            )
        if not isinstance(value, str) or not isinstance(fingerprint, str):
            raise InvalidSignatureBundleError(
                "value and fingerprint must be strings")
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, base64.binascii.Error) as e:
            raise InvalidSignatureBundleError(
                f"value is not valid base64: {e}") from e
        if len(raw) != _SIGNATURE_LEN:
            raise InvalidSignatureBundleError(
                f"signature must be {_SIGNATURE_LEN} bytes, got {len(raw)}"
            )
        if not fingerprint.startswith(_FP_PREFIX) or len(fingerprint) != len(_FP_PREFIX) + 64:
            raise InvalidSignatureBundleError(
                f"invalid fingerprint format: {fingerprint!r}"
            )
        return cls(algorithm=algorithm, value=value, pubkey_fingerprint=fingerprint)


@dataclass(frozen=True)
class OperatorIdentity:

    operator_id: str
    display_name: str
    pubkey_b64: str
    pubkey_fingerprint: str
    created_at: str
    rotated_from: str | None = None
    revoked_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "schema_version": "1.0",
            "operator_id": self.operator_id,
            "display_name": self.display_name,
            "pubkey": self.pubkey_b64,
            "pubkey_fingerprint": self.pubkey_fingerprint,
            "created_at": self.created_at,
        }
        if self.rotated_from is not None:
            d["rotated_from"] = self.rotated_from
        if self.revoked_at is not None:
            d["revoked_at"] = self.revoked_at
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> OperatorIdentity:
        if d.get("schema_version") != "1.0":
            raise SentinelKeyError(
                f"unsupported schema_version: {d.get('schema_version')!r}"
            )
        try:
            return cls(
                operator_id=d["operator_id"],
                display_name=d["display_name"],
                pubkey_b64=d["pubkey"],
                pubkey_fingerprint=d["pubkey_fingerprint"],
                created_at=d["created_at"],
                rotated_from=d.get("rotated_from"),
                revoked_at=d.get("revoked_at"),
            )
        except KeyError as e:
            raise SentinelKeyError(f"missing required field: {e}") from e

    def to_public_key(self) -> Ed25519PublicKey:
        raw = base64.b64decode(self.pubkey_b64, validate=True)
        if len(raw) != _PUBKEY_RAW_LEN:
            raise SentinelKeyError(
                f"public key must be {_PUBKEY_RAW_LEN} bytes, got {len(raw)}"
            )
        return Ed25519PublicKey.from_public_bytes(raw)

    def verify(self, data: bytes, signature: SignatureBundle) -> None:

        if signature.pubkey_fingerprint != self.pubkey_fingerprint:
            raise InvalidSignatureError(
                f"signature fingerprint {signature.pubkey_fingerprint} "
                f"does not match operator {self.pubkey_fingerprint}"
            )
        raw_sig = base64.b64decode(signature.value, validate=True)
        try:
            self.to_public_key().verify(raw_sig, data)
        except InvalidSignature as e:
            raise InvalidSignatureError("signature verification failed") from e


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fingerprint(pubkey_raw: bytes) -> str:
    return _FP_PREFIX + hashlib.sha256(pubkey_raw).hexdigest()


def _new_operator_id() -> str:
    return "op-" + secrets.token_hex(4)


def _keyring_username(operator_id: str) -> str:
    return f"ed25519-private:{operator_id}"


def _warn_if_insecure_backend() -> None:
    try:
        backend = keyring.get_keyring()
        backend_name = type(backend).__module__ + "." + type(backend).__name__
        if "keyrings.alt" in backend_name:
            warnings.warn(
                f"Keyring backend {backend_name} stores secrets in plaintext. "
                "Use a real OS keyring (Secret Service, Keychain, Credential Locker) "
                "in production.",
                RuntimeWarning,
                stacklevel=3,
            )
    except Exception:
        pass


@dataclass
class KeyManager:

    identity: OperatorIdentity
    service: str = DEFAULT_SERVICE
    _private_key: Ed25519PrivateKey = field(repr=False, compare=False)

    @classmethod
    def generate(
        cls,
        display_name: str,
        operator_id: str | None = None,
        service: str = DEFAULT_SERVICE,
        rotated_from: str | None = None,
    ) -> KeyManager:

        if not display_name or not display_name.strip():
            raise ValueError("display_name must be non-empty")

        op_id = operator_id or _new_operator_id()

        try:
            existing = keyring.get_password(service, _keyring_username(op_id))
        except keyring.errors.KeyringError as e:
            raise KeyringUnavailableError(f"keyring read failed: {e}") from e
        if existing is not None:
            raise RotationError(
                f"operator_id {op_id!r} already exists in keyring service {service!r}"
            )

        _warn_if_insecure_backend()

        private_key = Ed25519PrivateKey.generate()
        pub_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        priv_raw = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        if len(priv_raw) != _PRIVKEY_RAW_LEN or len(pub_raw) != _PUBKEY_RAW_LEN:
            raise SentinelKeyError(
                "unexpected key length from cryptography backend")

        try:
            keyring.set_password(
                service,
                _keyring_username(op_id),
                base64.b64encode(priv_raw).decode("ascii"),
            )
        except keyring.errors.KeyringError as e:
            raise KeyringUnavailableError(f"keyring write failed: {e}") from e

        identity = OperatorIdentity(
            operator_id=op_id,
            display_name=display_name.strip(),
            pubkey_b64=base64.b64encode(pub_raw).decode("ascii"),
            pubkey_fingerprint=_fingerprint(pub_raw),
            created_at=_now_utc_iso(),
            rotated_from=rotated_from,
        )
        return cls(identity=identity, service=service, _private_key=private_key)

    @classmethod
    def load(
        cls,
        operator_id: str,
        display_name: str,
        service: str = DEFAULT_SERVICE,
        created_at: str | None = None,
        rotated_from: str | None = None,
    ) -> KeyManager:
        try:
            stored = keyring.get_password(
                service, _keyring_username(operator_id))
        except keyring.errors.KeyringError as e:
            raise KeyringUnavailableError(f"keyring read failed: {e}") from e
        if stored is None:
            raise OperatorNotFoundError(
                f"operator {operator_id!r} not found in keyring service {service!r}"
            )

        try:
            priv_raw = base64.b64decode(stored, validate=True)
        except (ValueError, base64.binascii.Error) as e:
            raise SentinelKeyError(f"corrupt stored private key: {e}") from e
        if len(priv_raw) != _PRIVKEY_RAW_LEN:
            raise SentinelKeyError(
                f"stored private key must be {_PRIVKEY_RAW_LEN} bytes, got {len(priv_raw)}"
            )

        _warn_if_insecure_backend()

        private_key = Ed25519PrivateKey.from_private_bytes(priv_raw)
        pub_raw = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        identity = OperatorIdentity(
            operator_id=operator_id,
            display_name=display_name.strip(),
            pubkey_b64=base64.b64encode(pub_raw).decode("ascii"),
            pubkey_fingerprint=_fingerprint(pub_raw),
            created_at=created_at or _now_utc_iso(),
            rotated_from=rotated_from,
        )
        return cls(identity=identity, service=service, _private_key=private_key)

    def sign(self, data: bytes) -> SignatureBundle:

        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(
                f"sign() requires bytes-like, got {type(data).__name__}"
            )
        raw_sig = self._private_key.sign(bytes(data))
        return SignatureBundle(
            algorithm="ed25519",
            value=base64.b64encode(raw_sig).decode("ascii"),
            pubkey_fingerprint=self.identity.pubkey_fingerprint,
        )

    def verify(self, data: bytes, signature: SignatureBundle) -> None:

        self.identity.verify(data, signature)

    def rotate(
        self,
        new_display_name: str | None = None,
        new_operator_id: str | None = None,
    ) -> KeyManager:

        return KeyManager.generate(
            display_name=new_display_name or self.identity.display_name,
            operator_id=new_operator_id,
            service=self.service,
            rotated_from=self.identity.operator_id,
        )

    def revoke(self) -> None:

        try:
            keyring.delete_password(
                self.service, _keyring_username(self.identity.operator_id)
            )
        except keyring.errors.PasswordDeleteError as e:
            raise OperatorNotFoundError(
                f"operator {self.identity.operator_id!r} not in keyring"
            ) from e
        except keyring.errors.KeyringError as e:
            raise KeyringUnavailableError(f"keyring delete failed: {e}") from e

    def verify_consistency(self) -> None:
        pub_raw = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        if _fingerprint(pub_raw) != self.identity.pubkey_fingerprint:
            raise SentinelKeyError(
                f"stored private key does not match public key for "
                f"operator {self.identity.operator_id!r}"
            )
