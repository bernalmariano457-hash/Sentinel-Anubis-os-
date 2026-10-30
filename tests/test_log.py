from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from sentinel.custody.log import (
    SCHEMA_VERSION,
    CustodyAction,
    CustodyChainError,
    CustodyLog,
    CustodyLogError,
    build_entry,
    finalize_entry,
)
from sentinel.integrity.hashing import sha256_canonical
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.timestamp import Timestamp


class TestBuildEntry:
    def test_basic(self, ts_gps: Timestamp) -> None:
        e = build_entry(
            seq=0,
            prev_hash="",
            operator_id="op-alice",
            action=CustodyAction.CREATE,
            timestamp=ts_gps,
            artifact_id="a-1",
            details={"file_sha256": "x" * 64},
        )
        assert e["schema_version"] == SCHEMA_VERSION
        assert e["seq"] == 0
        assert e["prev_hash"] == ""
        assert e["time_source"] == "gps"
        assert e["action"] == "create"
        assert e["artifact_id"] == "a-1"
        assert "entry_hash" not in e
        assert "signature" not in e

    def test_rejects_negative_seq(self, ts_gps: Timestamp) -> None:
        with pytest.raises(ValueError, match="seq"):
            build_entry(0, "", "op", CustodyAction.CREATE,
                        ts_gps)
        with pytest.raises(ValueError):
            build_entry(-1, "", "op", CustodyAction.CREATE, ts_gps)

    def test_rejects_nonempty_prev_hash_at_seq_zero(self, ts_gps: Timestamp) -> None:
        with pytest.raises(ValueError, match="prev_hash must be empty"):
            build_entry(0, "deadbeef", "op", CustodyAction.CREATE, ts_gps)

    def test_rejects_empty_prev_hash_at_seq_nonzero(self, ts_gps: Timestamp) -> None:
        with pytest.raises(ValueError, match="prev_hash must be non-empty"):
            build_entry(1, "", "op", CustodyAction.CREATE, ts_gps)

    def test_rejects_empty_operator(self, ts_gps: Timestamp) -> None:
        with pytest.raises(ValueError, match="operator_id"):
            build_entry(0, "", "", CustodyAction.CREATE, ts_gps)

    def test_rejects_non_enum_action(self, ts_gps: Timestamp) -> None:
        with pytest.raises(ValueError, match="CustodyAction"):
            # type: ignore[arg-type]
            build_entry(0, "", "op", "create", ts_gps)

    def test_custom_entry_id(self, ts_gps: Timestamp) -> None:
        e = build_entry(
            0, "", "op", CustodyAction.CREATE, ts_gps, entry_id="custom-id"
        )
        assert e["entry_id"] == "custom-id"


class TestFinalizeEntry:
    def test_adds_hash_and_signature(
        self, alice: KeyManager, ts_gps: Timestamp
    ) -> None:
        payload = build_entry(0, "", "op-alice", CustodyAction.CREATE, ts_gps)
        full = finalize_entry(alice, payload)
        assert "entry_hash" in full
        assert "signature" in full
        assert full["signature"]["algorithm"] == "ed25519"
        # entry_hash must match recomputation.
        payload_again = {k: v for k, v in full.items(
        ) if k not in ("entry_hash", "signature")}
        assert sha256_canonical(payload_again) == full["entry_hash"]

    def test_rejects_payload_with_hash_or_signature(
        self, alice: KeyManager, ts_gps: Timestamp
    ) -> None:
        payload = build_entry(0, "", "op-alice", CustodyAction.CREATE, ts_gps)
        payload["entry_hash"] = "deadbeef"
        with pytest.raises(ValueError, match="must not contain"):
            finalize_entry(alice, payload)

    def test_rejects_mismatched_operator(
        self, alice: KeyManager, bob: KeyManager, ts_gps: Timestamp
    ) -> None:
        payload = build_entry(0, "", "op-alice", CustodyAction.CREATE, ts_gps)
        with pytest.raises(ValueError, match="does not match"):
            finalize_entry(bob, payload)


class TestAppend:
    def test_creates_file(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        assert not log.exists()
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        assert log.exists()

    def test_first_entry_seq_zero_empty_prev_hash(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        entry = log.append(
            alice, CustodyAction.CREATE, timestamp=ts_gps, artifact_id="a-1"
        )
        assert entry["seq"] == 0
        assert entry["prev_hash"] == ""

    def test_entries_are_chained(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        e1 = log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        e2 = log.append(alice, CustodyAction.VERIFY, timestamp=ts_gps)
        e3 = log.append(alice, CustodyAction.EXPORT, timestamp=ts_gps)
        assert e1["seq"] == 0
        assert e2["seq"] == 1
        assert e3["seq"] == 2
        assert e2["prev_hash"] == e1["entry_hash"]
        assert e3["prev_hash"] == e2["entry_hash"]

    def test_count_increments(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        assert log.count() == 0
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        assert log.count() == 1
        log.append(alice, CustodyAction.VERIFY, timestamp=ts_gps)
        assert log.count() == 2

    def test_head_hash(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        assert log.head_hash() == ""
        e = log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        assert log.head_hash() == e["entry_hash"]

    def test_different_operators_in_chain(
        self,
        alice: KeyManager,
        bob: KeyManager,
        ts_gps: Timestamp,
        tmp_path: Path,
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        log.append(bob, CustodyAction.VERIFY, timestamp=ts_gps)
        entries = log.read_all()
        assert entries[0]["operator_id"] == "op-alice"
        assert entries[1]["operator_id"] == "op-bob"

    def test_refuses_to_append_to_corrupt_log(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        path.write_text("not a json line\n", encoding="utf-8")
        log = CustodyLog(path)
        with pytest.raises(CustodyLogError, match="refusing to append"):
            log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)

    def test_fallback_timestamp_when_none(
        self, alice: KeyManager, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        entry = log.append(alice, CustodyAction.CREATE)
        assert entry["time_source"] == "system"
        assert entry["timestamp"].endswith("Z")


class TestConcurrency:
    def test_concurrent_appends_do_not_fork(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        n_threads = 4
        per_thread = 5
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(per_thread):
                    log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"worker errors: {errors}"
        assert log.count() == n_threads * per_thread
        report = log.verify_chain(operators={"op-alice": alice.identity})
        report.raise_if_invalid()
        assert report.valid_entries == n_threads * per_thread


class TestRead:
    def test_read_all_empty(
        self, tmp_path: Path
    ) -> None:
        assert CustodyLog(tmp_path / "nope.log").read_all() == []

    def test_read_all_returns_entries(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        e1 = log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        e2 = log.append(alice, CustodyAction.VERIFY, timestamp=ts_gps)
        entries = log.read_all()
        assert len(entries) == 2
        assert entries[0]["entry_id"] == e1["entry_id"]
        assert entries[1]["entry_id"] == e2["entry_id"]

    def test_read_all_surfaces_corrupt_lines(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("this is not json\n")
        entries = log.read_all()
        assert len(entries) == 2
        assert "_error" in entries[1]

    def test_iter_entries(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        log.append(alice, CustodyAction.VERIFY, timestamp=ts_gps)
        entries = list(log.iter_entries())
        assert len(entries) == 2

    def test_iter_entries_missing_file(
        self, tmp_path: Path
    ) -> None:
        # Returns empty iterator, does not raise.
        assert list(CustodyLog(tmp_path / "nope.log").iter_entries()) == []


class TestVerifyChain:
    def test_empty_log(self, tmp_path: Path) -> None:
        report = CustodyLog(tmp_path / "nope.log").verify_chain()
        assert report.valid
        assert report.total_lines == 0
        assert report.head_hash is None

    def test_valid_chain_without_operators(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        for _ in range(5):
            log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        report = log.verify_chain()
        assert report.valid
        assert report.valid_entries == 5
        assert report.signatures_verified is False

    def test_valid_chain_with_operators(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        for _ in range(3):
            log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        report = log.verify_chain(operators={"op-alice": alice.identity})
        assert report.valid
        assert report.signatures_verified is True

    def test_detects_modified_entry_hash(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        log.append(alice, CustodyAction.VERIFY, timestamp=ts_gps)
        entries = log.read_all()
        entries[0]["entry_hash"] = "0" * 64
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )
        report = log.verify_chain()
        assert not report.valid
        codes = {i.code for i in report.issues}
        assert "entry_hash_mismatch" in codes
        assert "prev_hash_mismatch" in codes  # chain broken for entry 1

    def test_detects_modified_content(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        log.append(
            alice, CustodyAction.CREATE, timestamp=ts_gps, artifact_id="a-1"
        )
        entries = log.read_all()
        entries[0]["artifact_id"] = "a-TAMPERED"
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )
        report = log.verify_chain(operators={"op-alice": alice.identity})
        codes = {i.code for i in report.issues}
        assert "entry_hash_mismatch" in codes
        assert "signature_invalid" in codes

    def test_detects_deleted_entry(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        for _ in range(4):
            log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        entries = log.read_all()
        del entries[1]
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )
        report = log.verify_chain()
        codes = {i.code for i in report.issues}
        # seq gap (0, 2, 3) and prev_hash mismatch at the new "seq=2"
        assert "seq_mismatch" in codes
        assert "prev_hash_mismatch" in codes

    def test_detects_reordered_entries(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        for _ in range(3):
            log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        entries = log.read_all()
        entries[0], entries[1] = entries[1], entries[0]
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )
        report = log.verify_chain()
        assert not report.valid
        codes = {i.code for i in report.issues}
        assert "seq_mismatch" in codes

    def test_detects_invalid_signature(
        self,
        alice: KeyManager,
        bob: KeyManager,
        ts_gps: Timestamp,
        tmp_path: Path,
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        entries = log.read_all()
        # Swap the signature with Bob's signature over some other payload.
        bogus = bob.sign(b"unrelated")
        entries[0]["signature"] = bogus.to_dict()
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )
        report = log.verify_chain(
            operators={"op-alice": alice.identity, "op-bob": bob.identity})
        codes = {i.code for i in report.issues}
        assert "fingerprint_mismatch" in codes

    def test_detects_unknown_operator(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        report = log.verify_chain(operators={})  # empty map
        codes = {i.code for i in report.issues}
        assert "operator_unknown" in codes

    def test_signature_check_skipped_when_operators_none(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        entries = log.read_all()
        entries[0]["signature"] = {
            "algorithm": "ed25519", "value": "AAAA", "pubkey_fingerprint": "SHA256:" + "a" * 64}
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )
        report = log.verify_chain()
        assert report.signatures_verified is False
        assert not report.valid

    def test_detects_invalid_json_line(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("not json\n")
        report = log.verify_chain()
        codes = {i.code for i in report.issues}
        assert "invalid_json" in codes

    def test_detects_missing_required_field(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        entries = log.read_all()
        del entries[0]["entry_id"]
        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )
        report = log.verify_chain()
        codes = {i.code for i in report.issues}
        assert "invalid_structure" in codes

    def test_detects_unsupported_schema_version(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        entries = log.read_all()
        entries[0]["schema_version"] = "9.9"

        path.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
        )
        report = log.verify_chain()
        codes = {i.code for i in report.issues}
        assert "unsupported_version" in codes

    def test_raise_if_invalid(self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("garbage\n")
        with pytest.raises(CustodyChainError):
            log.verify_chain().raise_if_invalid()

    def test_summary(self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)
        report = log.verify_chain(operators={"op-alice": alice.identity})
        assert "1/1" in report.summary()
        assert "OK" in report.summary()


class TestEndToEnd:
    def test_survives_process_restart(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        path = tmp_path / "custody.log"
        log = CustodyLog(path)
        for _ in range(3):
            log.append(alice, CustodyAction.CREATE, timestamp=ts_gps)

        # New instance = new process (no shared state).
        log2 = CustodyLog(path)
        assert log2.count() == 3
        report = log2.verify_chain(operators={"op-alice": alice.identity})
        report.raise_if_invalid()

    def test_full_lifecycle(
        self, alice: KeyManager, ts_gps: Timestamp, tmp_path: Path
    ) -> None:
        log = CustodyLog(tmp_path / "custody.log")
        e_create = log.append(
            alice,
            CustodyAction.CREATE,
            timestamp=ts_gps,
            artifact_id="artifact-1",
            details={"file_sha256": "a" * 64, "size_bytes": 1024},
        )
        e_verify = log.append(
            alice,
            CustodyAction.VERIFY,
            timestamp=ts_gps,
            artifact_id="artifact-1",
            details={"verified": True},
        )
        e_pack = log.append(
            alice,
            CustodyAction.PACK,
            timestamp=ts_gps,
            package_id="package-1",
            details={"artifact_count": 1},
        )
        report = log.verify_chain(operators={"op-alice": alice.identity})
        report.raise_if_invalid()

        assert report.head_hash == e_pack["entry_hash"]
        assert e_verify["prev_hash"] == e_create["entry_hash"]
        assert e_pack["prev_hash"] == e_verify["entry_hash"]
