from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from sentinel.custody.log import CustodyLog
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.timestamp import Timestamp
from sentinel.packaging.sae import (
    CUSTODY_MEMBER,
    MANIFEST_MEMBER,
    MANIFEST_SIG_MEMBER,
    TIMELINE_MEMBER,
    SAEPackError,
    SAEUnpackError,
    SAEVerifyError,
    pack,
    unpack,
    verify,
)


class TestPack:
    def test_creates_file(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        manifest = pack(
            out,
            alice,
            operation_id="op-1",
            artifact_dirs=[artifact_dir],
            custody_log_path=custody_log_path,
            timestamp=ts_gps,
        )
        assert out.is_file()
        assert manifest["package_id"]
        assert manifest["operator_id"] == "op-alice"
        assert "signature" in manifest
        assert manifest["time_source"] == "gps"

    def test_manifest_inside_zip_matches_returned(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        returned = pack(
            out, alice, "op-1", [artifact_dir], custody_log_path, timestamp=ts_gps
        )
        with zipfile.ZipFile(out) as zf:
            stored = json.loads(zf.read(MANIFEST_MEMBER).decode("utf-8"))
        assert stored == returned

    def test_rejects_empty_artifact_list(
        self,
        alice: KeyManager,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        with pytest.raises(SAEPackError, match="at least one artifact"):
            pack(
                tmp_path / "x.sae",
                alice,
                "op-1",
                [],
                custody_log_path,
                timestamp=ts_gps,
            )

    def test_rejects_empty_operation(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        with pytest.raises(SAEPackError, match="operation_id"):
            pack(
                tmp_path / "x.sae",
                alice,
                "",
                [artifact_dir],
                custody_log_path,
                timestamp=ts_gps,
            )

    def test_rejects_missing_artifact_dir(
        self,
        alice: KeyManager,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        with pytest.raises(SAEPackError, match="not found"):
            pack(
                tmp_path / "x.sae",
                alice,
                "op-1",
                [tmp_path / "nope"],
                custody_log_path,
                timestamp=ts_gps,
            )

    def test_rejects_missing_custody(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        with pytest.raises(SAEPackError, match="custody"):
            pack(
                tmp_path / "x.sae",
                alice,
                "op-1",
                [artifact_dir],
                tmp_path / "nope.log",
                timestamp=ts_gps,
            )

    def test_rejects_corrupt_custody(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        bad = tmp_path / "custody.log"
        bad.write_text("not a json line\n", encoding="utf-8")
        with pytest.raises(SAEPackError, match="corrupt custody"):
            pack(
                tmp_path / "x.sae", alice, "op-1", [artifact_dir], bad, timestamp=ts_gps
            )

    def test_includes_optional_timeline_and_report(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        tl = tmp_path / "timeline.json"
        tl.write_text('{"events":[]}', encoding="utf-8")
        rp = tmp_path / "report.pdf"
        rp.write_bytes(b"%PDF-1.4 fake")
        out = tmp_path / "pkg.sae"
        manifest = pack(
            out,
            alice,
            "op-1",
            [artifact_dir],
            custody_log_path,
            timestamp=ts_gps,
            timeline_path=tl,
            report_path=rp,
        )
        assert manifest["timeline_sha256"] is not None
        assert manifest["report_sha256"] is not None
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert TIMELINE_MEMBER in names
        assert "report.pdf" in names


class TestVerify:
    def test_valid_package(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        report = verify(out, operators={"op-alice": alice.identity})
        report.raise_if_invalid()
        assert report.signatures_verified is True
        assert report.artifacts_valid == 1
        assert report.custody_chain_valid is True

    def test_valid_without_operators(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        report = verify(out)
        assert report.valid
        assert report.signatures_verified is False

    def test_missing_file_raises(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(SAEVerifyError, match="not found"):
            verify(tmp_path / "nope.sae")

    def test_not_a_zip_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.sae"
        p.write_bytes(b"not a zip")
        with pytest.raises(SAEVerifyError, match="not a valid ZIP"):
            verify(p)

    def test_detects_artifact_data_tamper(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        _tamper_member(out, "artifacts/art-1/data.bin", b"TAMPERED")
        report = verify(out)
        assert not report.valid
        codes = {i.code for i in report.issues}
        assert "artifact_hash_mismatch" in codes

    def test_detects_artifact_manifest_tamper(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        with zipfile.ZipFile(out) as zf:
            m = json.loads(zf.read("artifacts/art-1/manifest.json"))
        m["file"]["sha256"] = "0" * 64
        _tamper_member(
            out,
            "artifacts/art-1/manifest.json",
            json.dumps(m).encode("utf-8"),
        )
        report = verify(out)
        codes = {i.code for i in report.issues}
        assert "manifest_hash_mismatch" in codes

    def test_detects_package_manifest_tamper(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        with zipfile.ZipFile(out) as zf:
            m = json.loads(zf.read(MANIFEST_MEMBER))
        m["operator_id"] = "op-evil"
        _tamper_member(out, MANIFEST_MEMBER, json.dumps(m).encode("utf-8"))
        report = verify(out, operators={"op-alice": alice.identity})
        codes = {i.code for i in report.issues}
        assert "signature_invalid" in codes

    def test_detects_custody_tamper(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        _tamper_member(out, CUSTODY_MEMBER, b'{"tampered":true}\n')
        report = verify(out)
        codes = {i.code for i in report.issues}
        assert "custody_hash_mismatch" in codes

    def test_detects_wrong_operator(
        self,
        memory_keyring,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        bob = KeyManager.generate("Bob", operator_id="op-bob")
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        report = verify(out, operators={"op-alice": bob.identity})
        codes = {i.code for i in report.issues}
        assert "signature_invalid" in codes

    def test_detects_unknown_operator(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        report = verify(out, operators={})
        codes = {i.code for i in report.issues}
        assert "operator_unknown" in codes

    def test_detects_signature_sidecar_mismatch(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        _tamper_member(out, MANIFEST_SIG_MEMBER,
                       b'{"algorithm":"ed25519","value":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==","pubkey_fingerprint":"SHA256:' + b"a" * 64 + b'"}')
        report = verify(out)
        codes = {i.code for i in report.issues}
        assert "signature_mismatch" in codes

    def test_detects_missing_member(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        _drop_member(out, MANIFEST_SIG_MEMBER)
        report = verify(out)
        codes = {i.code for i in report.issues}
        assert "missing_member" in codes

    def test_detects_timeline_tamper(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        tl = tmp_path / "timeline.json"
        tl.write_text('{"events":[]}', encoding="utf-8")
        out = tmp_path / "pkg.sae"
        pack(
            out, alice, "op-1", [artifact_dir], custody_log_path,
            timestamp=ts_gps, timeline_path=tl,
        )
        _tamper_member(out, TIMELINE_MEMBER, b'{"events":[1]}')
        report = verify(out)
        codes = {i.code for i in report.issues}
        assert "optional_hash_mismatch" in codes

    def test_skip_custody_chain_verification(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        report = verify(out, verify_custody_chain=False)
        assert report.valid


class TestUnpack:
    def test_extracts_package(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        dest = tmp_path / "extracted"
        unpack(out, dest)
        assert (dest / MANIFEST_MEMBER).is_file()
        assert (dest / CUSTODY_MEMBER).is_file()
        assert (dest / "artifacts" / "art-1" / "data.bin").is_file()

    def test_refuses_nonempty_destination(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "existing.txt").write_text("x")
        with pytest.raises(SAEUnpackError, match="not empty"):
            unpack(out, dest)

    def test_overwrite_allows_nonempty_destination(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        pack(out, alice, "op-1", [artifact_dir],
             custody_log_path, timestamp=ts_gps)
        dest = tmp_path / "dest"
        dest.mkdir()
        (dest / "existing.txt").write_text("x")
        unpack(out, dest, overwrite=True)
        assert (dest / MANIFEST_MEMBER).is_file()

    def test_rejects_zip_slip(
        self, tmp_path: Path
    ) -> None:
        bad = tmp_path / "evil.sae"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../outside.txt", b"pwned")
        with pytest.raises(SAEUnpackError, match=r"\.\."):
            unpack(bad, tmp_path / "out")

    def test_rejects_absolute_path(self, tmp_path: Path) -> None:
        bad = tmp_path / "evil.sae"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("/etc/passwd", b"x")
        with pytest.raises(SAEUnpackError, match="absolute"):
            unpack(bad, tmp_path / "out")

    def test_rejects_zip_bomb_by_total_size(self, tmp_path: Path) -> None:
        bad = tmp_path / "bomb.sae"
        with zipfile.ZipFile(bad, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.bin", b"\x00" * (100 * 1024 * 1024))
        with pytest.raises(SAEUnpackError, match="zip bomb"):
            unpack(bad, tmp_path / "out", max_total_bytes=1024 * 1024)

    def test_rejects_zip_bomb_by_ratio(self, tmp_path: Path) -> None:
        bad = tmp_path / "bomb.sae"
        with zipfile.ZipFile(bad, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("zeros.bin", b"\x00" * (10 * 1024 * 1024))
        with pytest.raises(SAEUnpackError, match="ratio"):
            unpack(
                bad, tmp_path / "out",
                max_total_bytes=100 * 1024 * 1024,
                max_ratio=50,
            )


class TestEndToEnd:
    def test_full_roundtrip(
        self,
        alice: KeyManager,
        artifact_dir: Path,
        custody_log_path: Path,
        tmp_path: Path,
        ts_gps: Timestamp,
    ) -> None:
        out = tmp_path / "pkg.sae"
        manifest = pack(
            out, alice, "op-1", [artifact_dir], custody_log_path, timestamp=ts_gps
        )

        report = verify(out, operators={"op-alice": alice.identity})
        report.raise_if_invalid()
        assert report.package_id == manifest["package_id"]

        dest = tmp_path / "extracted"
        unpack(out, dest)
        extracted_log = CustodyLog(dest / CUSTODY_MEMBER)
        extracted_report = extracted_log.verify_chain(
            operators={"op-alice": alice.identity}
        )
        extracted_report.raise_if_invalid()


def _tamper_member(sae_path: Path, member: str, new_bytes: bytes) -> None:
    members: dict[str, bytes] = {}
    with zipfile.ZipFile(sae_path) as zf:
        for name in zf.namelist():
            members[name] = zf.read(name)
    members[member] = new_bytes
    with zipfile.ZipFile(sae_path, "w", zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _drop_member(sae_path: Path, member: str) -> None:
    members: dict[str, bytes] = {}
    with zipfile.ZipFile(sae_path) as zf:
        for name in zf.namelist():
            if name != member:
                members[name] = zf.read(name)
    with zipfile.ZipFile(sae_path, "w", zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
