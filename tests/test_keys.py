from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from sentinel.integrity.keys import (
    DEFAULT_SERVICE,
    InvalidSignatureBundleError,
    InvalidSignatureError,
    KeyManager,
    KeyringUnavailableError,
    OperatorIdentity,
    OperatorNotFoundError,
    RotationError,
    SentinelKeyError,
    SignatureBundle,
)


class TestSignatureBundle:
    def test_roundtrip(self) -> None:
        bundle = SignatureBundle(
            algorithm="ed25519",
            value=base64.b64encode(b"\x00" * 64).decode("ascii"),
            pubkey_fingerprint="SHA256:" + "a" * 64,
        )
        assert SignatureBundle.from_dict(bundle.to_dict()) == bundle

    def test_rejects_non_dict(self) -> None:
        with pytest.raises(InvalidSignatureBundleError, match="must be a dict"):
            SignatureBundle.from_dict("not a dict")  # type: ignore[arg-type]

    def test_rejects_missing_field(self) -> None:
        with pytest.raises(InvalidSignatureBundleError, match="missing key"):
            SignatureBundle.from_dict({"algorithm": "ed25519"})

    def test_rejects_wrong_algorithm(self) -> None:
        with pytest.raises(InvalidSignatureBundleError, match="unsupported algorithm"):
            SignatureBundle.from_dict(
                {
                    "algorithm": "rsa",
                    "value": "x",
                    "pubkey_fingerprint": "SHA256:" + "a" * 64,
                }
            )

    def test_rejects_bad_base64(self) -> None:
        with pytest.raises(InvalidSignatureBundleError, match="not valid base64"):
            SignatureBundle.from_dict(
                {
                    "algorithm": "ed25519",
                    "value": "!!!not-base64!!!",
                    "pubkey_fingerprint": "SHA256:" + "a" * 64,
                }
            )

    def test_rejects_wrong_signature_length(self) -> None:
        with pytest.raises(InvalidSignatureBundleError, match="must be 64 bytes"):
            SignatureBundle.from_dict(
                {
                    "algorithm": "ed25519",
                    "value": base64.b64encode(b"\x00" * 32).decode("ascii"),
                    "pubkey_fingerprint": "SHA256:" + "a" * 64,
                }
            )

    def test_rejects_bad_fingerprint_format(self) -> None:
        with pytest.raises(InvalidSignatureBundleError, match="invalid fingerprint"):
            SignatureBundle.from_dict(
                {
                    "algorithm": "ed25519",
                    "value": base64.b64encode(b"\x00" * 64).decode("ascii"),
                    "pubkey_fingerprint": "sha256:aaaa",
                }
            )


class TestGenerate:
    def test_creates_distinct_operators(self, memory_keyring) -> None:
        a = KeyManager.generate("Alice")
        b = KeyManager.generate("Bob")
        assert a.identity.operator_id != b.identity.operator_id
        assert a.identity.pubkey_fingerprint != b.identity.pubkey_fingerprint

    def test_custom_operator_id(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice", operator_id="op-custom")
        assert km.identity.operator_id == "op-custom"

    def test_rejects_empty_display_name(self, memory_keyring) -> None:
        with pytest.raises(ValueError, match="display_name"):
            KeyManager.generate("   ")

    def test_rejects_duplicate_operator_id(self, memory_keyring) -> None:
        KeyManager.generate("Alice", operator_id="op-dup")
        with pytest.raises(RotationError, match="already exists"):
            KeyManager.generate("Bob", operator_id="op-dup")

    def test_fingerprint_format(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        fp = km.identity.pubkey_fingerprint
        assert fp.startswith("SHA256:")
        assert len(fp) == len("SHA256:") + 64
        int(fp[len("SHA256:"):], 16)  # must be hex

    def test_pubkey_is_32_bytes(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        raw = base64.b64decode(km.identity.pubkey_b64)
        assert len(raw) == 32

    def test_identity_is_consistent(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        km.verify_consistency()  # must not raise

    def test_default_operator_id_prefix(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        assert km.identity.operator_id.startswith("op-")

    def test_created_at_is_iso8601_utc(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        ts = km.identity.created_at
        assert ts.endswith("Z")
        assert "T" in ts

    def test_rotated_from_recorded(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice", rotated_from="op-old")
        assert km.identity.rotated_from == "op-old"


class TestSignVerify:
    def test_roundtrip(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        data = b"artifact payload"
        sig = km.sign(data)
        km.verify(data, sig)

    def test_signature_bundle_shape(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        sig = km.sign(b"x")
        d = sig.to_dict()
        assert d["algorithm"] == "ed25519"
        assert d["pubkey_fingerprint"] == km.identity.pubkey_fingerprint
        assert len(base64.b64decode(d["value"])) == 64

    def test_verify_fails_on_wrong_data(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        sig = km.sign(b"payload A")
        with pytest.raises(InvalidSignatureError):
            km.verify(b"payload B", sig)

    def test_verify_fails_on_wrong_key(self, memory_keyring) -> None:
        a = KeyManager.generate("Alice")
        b = KeyManager.generate("Bob")
        sig = a.sign(b"payload")
        with pytest.raises(InvalidSignatureError):
            b.verify(b"payload", sig)

    def test_verify_rejects_foreign_fingerprint(self, memory_keyring) -> None:
        a = KeyManager.generate("Alice")
        b = KeyManager.generate("Bob")
        sig = a.sign(b"payload")
        forged = SignatureBundle(
            algorithm="ed25519",
            value=sig.value,
            pubkey_fingerprint=b.identity.pubkey_fingerprint,
        )
        with pytest.raises(InvalidSignatureError, match="fingerprint"):
            b.verify(b"payload", forged)

    def test_sign_rejects_non_bytes(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        with pytest.raises(TypeError, match="bytes-like"):
            km.sign("string")

    def test_signature_changes_with_data(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        s1 = km.sign(b"a")
        s2 = km.sign(b"b")
        assert s1.value != s2.value

    def test_sign_is_deterministic_for_same_data(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        assert km.sign(b"x").value == km.sign(b"x").value


class TestLoad:
    def test_load_roundtrip(self, memory_keyring) -> None:
        original = KeyManager.generate("Alice", operator_id="op-load")
        loaded = KeyManager.load("op-load", "Alice")
        assert loaded.identity.pubkey_fingerprint == original.identity.pubkey_fingerprint
        sig = original.sign(b"hello")
        loaded.verify(b"hello", sig)

    def test_load_missing_raises(self, memory_keyring) -> None:
        with pytest.raises(OperatorNotFoundError):
            KeyManager.load("op-nope", "Nobody")

    def test_load_preserves_created_at(self, memory_keyring) -> None:
        KeyManager.generate("Alice", operator_id="op-t")
        loaded = KeyManager.load(
            "op-t", "Alice", created_at="2026-01-01T00:00:00Z")
        assert loaded.identity.created_at == "2026-01-01T00:00:00Z"

    def test_does_not_touch_filesystem(self, memory_keyring, tmp_path: Path) -> None:
        before = set(tmp_path.rglob("*"))
        KeyManager.generate("Alice")
        after = set(tmp_path.rglob("*"))
        assert before == after


class TestPublicExport:
    def test_save_and_load(self, memory_keyring, tmp_path: Path) -> None:
        km = KeyManager.generate("Alice")
        path = tmp_path / "config" / "operator.pub"
        km.save_public(path)
        assert path.exists()
        loaded = KeyManager.load_public(path)
        assert loaded == km.identity

    def test_saved_json_is_valid(self, memory_keyring, tmp_path: Path) -> None:
        km = KeyManager.generate("Alice")
        path = tmp_path / "operator.pub"
        km.save_public(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == "1.0"
        assert data["operator_id"] == km.identity.operator_id
        assert data["pubkey"] == km.identity.pubkey_b64
        assert data["pubkey_fingerprint"] == km.identity.pubkey_fingerprint

    def test_third_party_verify(self, memory_keyring, tmp_path: Path) -> None:
        km = KeyManager.generate("Alice")
        path = tmp_path / "operator.pub"
        km.save_public(path)

        pub = KeyManager.load_public(path)
        sig = km.sign(b"evidence")
        pub.verify(b"evidence", sig)

    def test_load_public_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            KeyManager.load_public(tmp_path / "nope.pub")

    def test_load_public_bad_schema_version(self, tmp_path: Path) -> None:
        path = tmp_path / "operator.pub"
        path.write_text(json.dumps(
            {"schema_version": "9.9"}), encoding="utf-8")
        with pytest.raises(SentinelKeyError, match="schema_version"):
            KeyManager.load_public(path)

    def test_load_public_missing_field(self, tmp_path: Path) -> None:
        path = tmp_path / "operator.pub"
        path.write_text(json.dumps(
            {"schema_version": "1.0"}), encoding="utf-8")
        with pytest.raises(SentinelKeyError, match="missing required field"):
            KeyManager.load_public(path)


class TestRotation:
    def test_rotate_creates_new_operator(self, memory_keyring) -> None:
        old = KeyManager.generate("Alice")
        new = old.rotate()
        assert new.identity.operator_id != old.identity.operator_id
        assert new.identity.rotated_from == old.identity.operator_id
        assert new.identity.display_name == old.identity.display_name
        assert new.identity.pubkey_fingerprint != old.identity.pubkey_fingerprint

    def test_old_key_still_verifies_old_signatures(self, memory_keyring) -> None:
        old = KeyManager.generate("Alice")
        sig = old.sign(b"legacy evidence")
        old.rotate()
        old.verify(b"legacy evidence", sig)

    def test_new_key_cannot_verify_old_signature(self, memory_keyring) -> None:
        old = KeyManager.generate("Alice")
        sig = old.sign(b"legacy")
        new = old.rotate()
        with pytest.raises(InvalidSignatureError):
            new.verify(b"legacy", sig)

    def test_rotate_custom_operator_id(self, memory_keyring) -> None:
        old = KeyManager.generate("Alice")
        new = old.rotate(new_operator_id="op-alice-2027")
        assert new.identity.operator_id == "op-alice-2027"

    def test_rotate_rejects_duplicate_id(self, memory_keyring) -> None:
        a = KeyManager.generate("Alice", operator_id="op-dup")
        with pytest.raises(RotationError):
            a.rotate(new_operator_id="op-dup")


class TestRevoke:
    def test_revoke_removes_from_keyring(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice", operator_id="op-rev")
        km.revoke()
        with pytest.raises(OperatorNotFoundError):
            KeyManager.load("op-rev", "Alice")

    def test_revoke_twice_raises(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice", operator_id="op-rev2")
        km.revoke()
        with pytest.raises(OperatorNotFoundError):
            km.revoke()


class TestEncryptedBackup:
    def test_roundtrip(self, memory_keyring) -> None:
        original = KeyManager.generate("Alice", operator_id="op-backup")
        pem = original.export_private_encrypted("strong-passphrase-1234")
        assert pem.startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----")

        original.revoke()
        with pytest.raises(OperatorNotFoundError):
            KeyManager.load("op-backup", "Alice")

        restored = KeyManager.import_private_encrypted(
            pem,
            "strong-passphrase-1234",
            operator_id="op-backup",
            display_name="Alice",
            created_at=original.identity.created_at,
        )
        assert restored.identity.pubkey_fingerprint == original.identity.pubkey_fingerprint
        assert restored.identity.created_at == original.identity.created_at

        sig = restored.sign(b"payload")
        original.identity.verify(b"payload", sig)

    def test_wrong_password_fails(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice", operator_id="op-bad-pw")
        pem = km.export_private_encrypted("correct")
        km.revoke()
        with pytest.raises(SentinelKeyError, match="cannot decrypt"):
            KeyManager.import_private_encrypted(
                pem, "wrong", operator_id="op-bad-pw", display_name="Alice"
            )

    def test_empty_password_rejected(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice")
        with pytest.raises(ValueError, match="password"):
            km.export_private_encrypted("")

    def test_import_into_existing_id_rejected(self, memory_keyring) -> None:
        km = KeyManager.generate("Alice", operator_id="op-exists")
        pem = km.export_private_encrypted("pw")
        with pytest.raises(RotationError, match="already exists"):
            KeyManager.import_private_encrypted(
                pem, "pw", operator_id="op-exists", display_name="Alice"
            )


class TestKeyringErrors:

    def test_read_failure_surfaces_as_unavailable(self, monkeypatch) -> None:
        import keyring

        def boom(*a, **kw):
            raise keyring.errors.KeyringError("backend dead")

        monkeypatch.setattr(keyring, "get_password", boom)
        with pytest.raises(KeyringUnavailableError):
            KeyManager.generate("Alice")

    def test_write_failure_surfaces_as_unavailable(self, monkeypatch) -> None:
        import keyring

        monkeypatch.setattr(keyring, "get_password", lambda *a, **kw: None)

        def boom(*a, **kw):
            raise keyring.errors.KeyringError("write blocked")

        monkeypatch.setattr(keyring, "set_password", boom)
        with pytest.raises(KeyringUnavailableError):
            KeyManager.generate("Alice")


class TestOperatorIdentity:
    def test_to_dict_includes_optional_fields_when_set(self) -> None:
        ident = OperatorIdentity(
            operator_id="op-1",
            display_name="Alice",
            pubkey_b64="AAAA",
            pubkey_fingerprint="SHA256:" + "a" * 64,
            created_at="2026-01-01T00:00:00Z",
            rotated_from="op-0",
            revoked_at="2026-06-01T00:00:00Z",
        )
        d = ident.to_dict()
        assert d["rotated_from"] == "op-0"
        assert d["revoked_at"] == "2026-06-01T00:00:00Z"

    def test_to_dict_omits_optional_fields_when_none(self) -> None:
        ident = OperatorIdentity(
            operator_id="op-1",
            display_name="Alice",
            pubkey_b64="AAAA",
            pubkey_fingerprint="SHA256:" + "a" * 64,
            created_at="2026-01-01T00:00:00Z",
        )
        d = ident.to_dict()
        assert "rotated_from" not in d
        assert "revoked_at" not in d

    def test_verify_rejects_wrong_key_length(self) -> None:
        ident = OperatorIdentity(
            operator_id="op-1",
            display_name="Alice",
            pubkey_b64=base64.b64encode(b"short").decode("ascii"),
            pubkey_fingerprint="SHA256:" + "a" * 64,
            created_at="2026-01-01T00:00:00Z",
        )
        with pytest.raises(SentinelKeyError, match="32 bytes"):
            ident.to_public_key()
