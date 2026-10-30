from __future__ import annotations

import json
from pathlib import Path

import pytest
from sentinel.integrity.keys import (
    InvalidSignatureError,
    KeyManager,
    SignatureBundle,
)
from sentinel.integrity.signing import (
    DOMAIN_CUSTODY_ENTRY,
    DOMAIN_FILE,
    DOMAIN_MANIFEST_ARTIFACT,
    ManifestStructureError,
    SignatureFileError,
    read_signature,
    sign_artifact_manifest,
    sign_bytes,
    sign_custody_entry,
    sign_entity,
    sign_file,
    sign_file_with_sidecar,
    sign_package_manifest,
    verify_artifact_manifest,
    verify_bytes,
    verify_custody_entry,
    verify_entity,
    verify_file,
    verify_file_with_sidecar,
    verify_package_manifest,
    write_signature,
)


@pytest.fixture
def alice(memory_keyring) -> KeyManager:
    return KeyManager.generate("Alice", operator_id="op-alice")


@pytest.fixture
def bob(memory_keyring) -> KeyManager:
    return KeyManager.generate("Bob", operator_id="op-bob")


@pytest.fixture
def artifact_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "artifact_id": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
        "type": "iq",
        "operation_id": "op-0001",
        "operator_id": "op-alice",
        "created_at": "2026-10-26T14:00:05Z",
        "file": {"name": "data.bin", "size_bytes": 1024, "sha256": "a" * 64},
    }


@pytest.fixture
def package_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "package_id": "11111111-2222-3333-4444-555555555555",
        "operation_id": "op-0001",
        "created_at": "2026-10-26T15:00:00Z",
        "operator_id": "op-alice",
        "artifacts": [],
        "custody_log_sha256": "b" * 64,
        "custody_entries_count": 0,
    }


@pytest.fixture
def custody_entry() -> dict:
    return {
        "schema_version": "1.0",
        "entry_id": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
        "seq": 0,
        "timestamp": "2026-10-26T14:00:05Z",
        "time_source": "gps",
        "operator_id": "op-alice",
        "action": "create",
        "artifact_id": "6f8a2c1e-4b3d-4e9a-9c7f-1a2b3c4d5e6f",
        "prev_hash": "",
        "entry_hash": "c" * 64,
    }


class TestSignBytes:
    def test_roundtrip(self, alice: KeyManager) -> None:
        bundle = sign_bytes(alice, b"payload")
        verify_bytes(alice.identity, b"payload", bundle)

    def test_detects_modification(self, alice: KeyManager) -> None:
        bundle = sign_bytes(alice, b"payload A")
        with pytest.raises(InvalidSignatureError):
            verify_bytes(alice.identity, b"payload B", bundle)

    def test_rejects_wrong_operator(self, alice: KeyManager, bob: KeyManager) -> None:
        bundle = sign_bytes(alice, b"payload")
        with pytest.raises(InvalidSignatureError):
            verify_bytes(bob.identity, b"payload", bundle)

    def test_default_domain_is_bytes(self, alice: KeyManager) -> None:
        bundle = sign_bytes(alice, b"payload")
        with pytest.raises(InvalidSignatureError):
            verify_bytes(alice.identity, b"payload",
                         bundle, domain=DOMAIN_FILE)

    def test_rejects_empty_domain(self, alice: KeyManager) -> None:
        with pytest.raises(TypeError, match="non-empty bytes"):
            sign_bytes(alice, b"payload", domain=b"")

    def test_rejects_non_bytes_domain(self, alice: KeyManager) -> None:
        with pytest.raises(TypeError, match="non-empty bytes"):
            sign_bytes(alice, b"payload", domain="not-bytes")

    def test_rejects_non_bytes_data(self, alice: KeyManager) -> None:
        with pytest.raises(TypeError, match="bytes-like"):
            sign_bytes(alice, "string")

    def test_accepts_bytearray_and_memoryview(self, alice: KeyManager) -> None:
        b1 = sign_bytes(alice, bytearray(b"x"))
        verify_bytes(alice.identity, memoryview(b"x"), b1)


class TestDomainSeparation:
    def test_file_signature_does_not_verify_as_bytes(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        p = tmp_path / "x.bin"
        p.write_bytes(b"hello")
        file_sig = sign_file(alice, p)
        with pytest.raises(InvalidSignatureError):
            verify_bytes(alice.identity, b"hello", file_sig)

    def test_bytes_signature_does_not_verify_as_file(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        p = tmp_path / "x.bin"
        p.write_bytes(b"hello")
        bytes_sig = sign_bytes(alice, b"hello")
        with pytest.raises(InvalidSignatureError):
            verify_file(alice.identity, p, bytes_sig)

    def test_artifact_manifest_does_not_verify_as_package_manifest(
        self,
        alice: KeyManager,
        artifact_manifest: dict,
        package_manifest: dict,
    ) -> None:
        sig = sign_artifact_manifest(alice, artifact_manifest)
        with pytest.raises(ManifestStructureError):
            # Different required fields; the structure check fires first.
            verify_package_manifest(alice.identity, artifact_manifest, sig)
        _ = package_manifest

    def test_custody_domain_isolated(
        self, alice: KeyManager, custody_entry: dict
    ) -> None:
        sig = sign_custody_entry(alice, custody_entry)
        with pytest.raises(InvalidSignatureError):
            verify_bytes(
                alice.identity,
                b"anything",
                sig,
                domain=DOMAIN_CUSTODY_ENTRY,
            )


class TestSignFile:
    def test_roundtrip(self, alice: KeyManager, tmp_path: Path) -> None:
        p = tmp_path / "artifact.bin"
        p.write_bytes(b"some iq data" * 1000)
        bundle = sign_file(alice, p)
        verify_file(alice.identity, p, bundle)

    def test_detects_modification(self, alice: KeyManager, tmp_path: Path) -> None:
        p = tmp_path / "artifact.bin"
        p.write_bytes(b"original")
        bundle = sign_file(alice, p)
        p.write_bytes(b"tampered")
        with pytest.raises(InvalidSignatureError):
            verify_file(alice.identity, p, bundle)

    def test_detects_truncation(self, alice: KeyManager, tmp_path: Path) -> None:
        p = tmp_path / "artifact.bin"
        p.write_bytes(b"x" * 1000)
        bundle = sign_file(alice, p)
        p.write_bytes(b"x" * 999)
        with pytest.raises(InvalidSignatureError):
            verify_file(alice.identity, p, bundle)

    def test_missing_file_raises(self, alice: KeyManager, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            sign_file(alice, tmp_path / "nope.bin")

    def test_signature_is_over_hash_not_content(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        p = tmp_path / "x.bin"
        p.write_bytes(b"abc")
        bundle = sign_file(alice, p)
        from sentinel.integrity.hashing import hash_file

        digest = hash_file(p).encode("ascii")
        expected = sign_bytes(alice, digest, domain=DOMAIN_FILE)
        assert bundle.value == expected.value


class TestSignEntity:
    def test_roundtrip(self, alice: KeyManager) -> None:
        entity = {"schema_version": "1.0", "x": 1}
        sig = sign_entity(alice, entity, domain=DOMAIN_MANIFEST_ARTIFACT)
        verify_entity(alice.identity, entity, sig,
                      domain=DOMAIN_MANIFEST_ARTIFACT)

    def test_detects_field_change(self, alice: KeyManager) -> None:
        entity = {"schema_version": "1.0", "x": 1}
        sig = sign_entity(alice, entity, domain=DOMAIN_MANIFEST_ARTIFACT)
        entity["x"] = 2
        with pytest.raises(InvalidSignatureError):
            verify_entity(alice.identity, entity, sig,
                          domain=DOMAIN_MANIFEST_ARTIFACT)

    def test_detects_field_added(self, alice: KeyManager) -> None:
        entity = {"schema_version": "1.0", "x": 1}
        sig = sign_entity(alice, entity, domain=DOMAIN_MANIFEST_ARTIFACT)
        entity["new_field"] = "injected"
        with pytest.raises(InvalidSignatureError):
            verify_entity(alice.identity, entity, sig,
                          domain=DOMAIN_MANIFEST_ARTIFACT)

    def test_detects_field_removed(self, alice: KeyManager) -> None:
        entity = {"schema_version": "1.0", "x": 1, "y": 2}
        sig = sign_entity(alice, entity, domain=DOMAIN_MANIFEST_ARTIFACT)
        del entity["y"]
        with pytest.raises(InvalidSignatureError):
            verify_entity(alice.identity, entity, sig,
                          domain=DOMAIN_MANIFEST_ARTIFACT)

    def test_key_order_independent(self, alice: KeyManager) -> None:
        e1 = {"a": 1, "b": 2}
        e2 = {"b": 2, "a": 1}
        sig = sign_entity(alice, e1, domain=DOMAIN_MANIFEST_ARTIFACT)
        verify_entity(alice.identity, e2, sig, domain=DOMAIN_MANIFEST_ARTIFACT)

    def test_rejects_non_dict(self, alice: KeyManager) -> None:
        with pytest.raises(TypeError, match="must be a dict"):
            # type: ignore[arg-type]
            sign_entity(alice, [1, 2, 3], domain=DOMAIN_MANIFEST_ARTIFACT)


class TestArtifactManifest:
    def test_roundtrip(self, alice: KeyManager, artifact_manifest: dict) -> None:
        sig = sign_artifact_manifest(alice, artifact_manifest)
        verify_artifact_manifest(alice.identity, artifact_manifest, sig)

    def test_ignores_embedded_signature(
        self, alice: KeyManager, artifact_manifest: dict
    ) -> None:
        sig = sign_artifact_manifest(alice, artifact_manifest)
        artifact_manifest["signature"] = sig.to_dict()
        verify_artifact_manifest(alice.identity, artifact_manifest, sig)

    def test_embedded_signature_can_be_verified_directly(
        self, alice: KeyManager, artifact_manifest: dict
    ) -> None:
        sig = sign_artifact_manifest(alice, artifact_manifest)
        artifact_manifest["signature"] = sig.to_dict()
        embedded = SignatureBundle.from_dict(artifact_manifest["signature"])
        verify_artifact_manifest(alice.identity, artifact_manifest, embedded)

    def test_detects_file_hash_change(
        self, alice: KeyManager, artifact_manifest: dict
    ) -> None:
        sig = sign_artifact_manifest(alice, artifact_manifest)
        artifact_manifest["file"]["sha256"] = "b" * 64
        with pytest.raises(InvalidSignatureError):
            verify_artifact_manifest(alice.identity, artifact_manifest, sig)

    def test_detects_nested_field_change(
        self, alice: KeyManager, artifact_manifest: dict
    ) -> None:
        sig = sign_artifact_manifest(alice, artifact_manifest)
        artifact_manifest["file"]["size_bytes"] = 999999
        with pytest.raises(InvalidSignatureError):
            verify_artifact_manifest(alice.identity, artifact_manifest, sig)

    def test_missing_required_field(self, alice: KeyManager) -> None:
        with pytest.raises(ManifestStructureError, match="schema_version"):
            sign_artifact_manifest(alice, {"artifact_id": "x"})

    def test_missing_artifact_id(self, alice: KeyManager) -> None:
        with pytest.raises(ManifestStructureError, match="artifact_id"):
            sign_artifact_manifest(alice, {"schema_version": "1.0"})

    def test_rejects_wrong_operator(
        self, alice: KeyManager, bob: KeyManager, artifact_manifest: dict
    ) -> None:
        sig = sign_artifact_manifest(alice, artifact_manifest)
        with pytest.raises(InvalidSignatureError):
            verify_artifact_manifest(bob.identity, artifact_manifest, sig)


class TestPackageManifest:
    def test_roundtrip(self, alice: KeyManager, package_manifest: dict) -> None:
        sig = sign_package_manifest(alice, package_manifest)
        verify_package_manifest(alice.identity, package_manifest, sig)

    def test_detects_artifact_list_change(
        self, alice: KeyManager, package_manifest: dict
    ) -> None:
        sig = sign_package_manifest(alice, package_manifest)
        package_manifest["artifacts"].append(
            {"artifact_id": "x", "file_sha256": "a" * 64}
        )
        with pytest.raises(InvalidSignatureError):
            verify_package_manifest(alice.identity, package_manifest, sig)

    def test_missing_required_field(self, alice: KeyManager) -> None:
        with pytest.raises(ManifestStructureError):
            sign_package_manifest(alice, {"schema_version": "1.0"})

    def test_artifact_and_package_domains_isolated(
        self,
        alice: KeyManager,
        artifact_manifest: dict,
        package_manifest: dict,
    ) -> None:
        art_sig = sign_artifact_manifest(alice, artifact_manifest)
        pkg_sig = sign_package_manifest(alice, package_manifest)
        verify_artifact_manifest(alice.identity, artifact_manifest, art_sig)
        verify_package_manifest(alice.identity, package_manifest, pkg_sig)
        with pytest.raises(InvalidSignatureError):
            verify_package_manifest(alice.identity, package_manifest, art_sig)
        with pytest.raises(InvalidSignatureError):
            verify_artifact_manifest(
                alice.identity, artifact_manifest, pkg_sig)


class TestCustodyEntry:
    def test_roundtrip(self, alice: KeyManager, custody_entry: dict) -> None:
        sig = sign_custody_entry(alice, custody_entry)
        verify_custody_entry(alice.identity, custody_entry, sig)

    def test_ignores_entry_hash_and_signature(
        self, alice: KeyManager, custody_entry: dict
    ) -> None:
        sig = sign_custody_entry(alice, custody_entry)
        custody_entry["entry_hash"] = "d" * 64
        verify_custody_entry(alice.identity, custody_entry, sig)

    def test_ignores_embedded_signature(
        self, alice: KeyManager, custody_entry: dict
    ) -> None:
        sig = sign_custody_entry(alice, custody_entry)
        custody_entry["signature"] = sig.to_dict()
        verify_custody_entry(alice.identity, custody_entry, sig)

    def test_detects_action_change(
        self, alice: KeyManager, custody_entry: dict
    ) -> None:
        sig = sign_custody_entry(alice, custody_entry)
        custody_entry["action"] = "tampered"
        with pytest.raises(InvalidSignatureError):
            verify_custody_entry(alice.identity, custody_entry, sig)

    def test_detects_prev_hash_change(
        self, alice: KeyManager, custody_entry: dict
    ) -> None:
        sig = sign_custody_entry(alice, custody_entry)
        custody_entry["prev_hash"] = "e" * 64
        with pytest.raises(InvalidSignatureError):
            verify_custody_entry(alice.identity, custody_entry, sig)

    def test_missing_required_field(self, alice: KeyManager) -> None:
        with pytest.raises(ManifestStructureError):
            sign_custody_entry(alice, {"schema_version": "1.0"})


class TestSidecar:
    def test_write_read_roundtrip(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        bundle = sign_bytes(alice, b"x")
        path = tmp_path / "out.sig"
        write_signature(path, bundle)
        assert read_signature(path) == bundle

    def test_written_file_is_json(self, alice: KeyManager, tmp_path: Path) -> None:
        bundle = sign_bytes(alice, b"x")
        path = tmp_path / "out.sig"
        write_signature(path, bundle)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["algorithm"] == "ed25519"
        assert data["pubkey_fingerprint"] == alice.identity.pubkey_fingerprint

    def test_write_creates_parents(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        path = tmp_path / "a" / "b" / "c.sig"
        write_signature(path, sign_bytes(alice, b"x"))
        assert path.exists()

    def test_read_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SignatureFileError, match="not found"):
            read_signature(tmp_path / "nope.sig")

    def test_read_bad_json_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.sig"
        p.write_text("not json", encoding="utf-8")
        with pytest.raises(SignatureFileError, match="invalid JSON"):
            read_signature(p)

    def test_read_bad_bundle_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.sig"
        p.write_text(json.dumps({"algorithm": "rsa"}), encoding="utf-8")
        with pytest.raises(SignatureFileError, match="invalid signature bundle"):
            read_signature(p)

    def test_sign_file_with_sidecar(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        p = tmp_path / "artifact.bin"
        p.write_bytes(b"content")
        sig_path = sign_file_with_sidecar(alice, p)
        assert sig_path == Path(str(p) + ".sig")
        assert sig_path.exists()
        verify_file_with_sidecar(alice.identity, p)

    def test_sign_file_with_explicit_sidecar_path(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        p = tmp_path / "artifact.bin"
        p.write_bytes(b"content")
        explicit = tmp_path / "custom.sig"
        sig_path = sign_file_with_sidecar(alice, p, sig_path=explicit)
        assert sig_path == explicit
        verify_file_with_sidecar(alice.identity, p, sig_path=explicit)

    def test_verify_file_with_sidecar_detects_tamper(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        p = tmp_path / "artifact.bin"
        p.write_bytes(b"original")
        sign_file_with_sidecar(alice, p)
        p.write_bytes(b"tampered")
        with pytest.raises(InvalidSignatureError):
            verify_file_with_sidecar(alice.identity, p)

    def test_verify_file_with_sidecar_missing_sig(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        p = tmp_path / "artifact.bin"
        p.write_bytes(b"content")
        with pytest.raises(SignatureFileError):
            verify_file_with_sidecar(alice.identity, p)


class TestEndToEnd:
    def test_manifest_survives_roundtrip(
        self, alice: KeyManager, tmp_path: Path, artifact_manifest: dict
    ) -> None:
        sig = sign_artifact_manifest(alice, artifact_manifest)
        artifact_manifest["signature"] = sig.to_dict()

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps(artifact_manifest, indent=2), encoding="utf-8"
        )
        pub_path = tmp_path / "operator.pub"
        alice.save_public(pub_path)

        loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        verifier = KeyManager.load_public(pub_path)
        embedded = SignatureBundle.from_dict(loaded_manifest["signature"])
        verify_artifact_manifest(verifier, loaded_manifest, embedded)

        loaded_manifest["file"]["sha256"] = "0" * 64
        with pytest.raises(InvalidSignatureError):
            verify_artifact_manifest(verifier, loaded_manifest, embedded)
