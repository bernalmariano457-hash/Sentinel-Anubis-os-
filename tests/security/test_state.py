from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sentinel.integrity.keys import InvalidSignatureError, KeyManager
from sentinel.integrity.timestamp import Timestamp
from sentinel.security.state import (
    STATE_FILENAME,
    LockState,
    StateError,
    read_state,
    state_hash,
    verify_state,
    write_state,
)


class TestWriteRead:
    def test_roundtrip(self, workspace: Path, alice: KeyManager, ts: Timestamp) -> None:
        record = write_state(workspace, alice, LockState.LOCKED, ts.iso_utc, "incident", {"case": "C-1"})
        loaded = read_state(workspace)
        assert loaded.to_dict() == record.to_dict()
        assert loaded.state is LockState.LOCKED
        assert loaded.changed_at == ts.iso_utc
        assert loaded.operator_id == alice.identity.operator_id
        assert loaded.reason == "incident"
        assert loaded.details == {"case": "C-1"}
        assert (workspace / STATE_FILENAME).exists()

    def test_default_details_are_empty(self, workspace: Path, alice: KeyManager, ts: Timestamp) -> None:
        record = write_state(workspace, alice, LockState.NORMAL, ts.iso_utc, "init")
        assert record.details == {}

    def test_overwrites_previous_state(self, workspace: Path, alice: KeyManager, ts: Timestamp) -> None:
        write_state(workspace, alice, LockState.LOCKED, ts.iso_utc, "first")
        write_state(workspace, alice, LockState.UNLOCKED, ts.iso_utc, "second")
        assert read_state(workspace).state is LockState.UNLOCKED

    def test_rejects_missing_workspace(self, tmp_path: Path, alice: KeyManager, ts: Timestamp) -> None:
        with pytest.raises(StateError):
            write_state(tmp_path / "absent", alice, LockState.LOCKED, ts.iso_utc, "x")

    def test_missing_file_raises(self, workspace: Path) -> None:
        with pytest.raises(StateError):
            read_state(workspace)

    def test_bad_json_raises(self, workspace: Path) -> None:
        (workspace / STATE_FILENAME).write_text("{not json", encoding="utf-8")
        with pytest.raises(StateError):
            read_state(workspace)

    def test_bad_schema_version_raises(self, workspace: Path, alice: KeyManager, ts: Timestamp) -> None:
        write_state(workspace, alice, LockState.LOCKED, ts.iso_utc, "x")
        path = workspace / STATE_FILENAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_version"] = "9.9"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(StateError):
            read_state(workspace)

    def test_unknown_state_value_raises(self, workspace: Path, alice: KeyManager, ts: Timestamp) -> None:
        write_state(workspace, alice, LockState.LOCKED, ts.iso_utc, "x")
        path = workspace / STATE_FILENAME
        data = json.loads(path.read_text(encoding="utf-8"))
        data["state"] = "exploded"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(StateError):
            read_state(workspace)


class TestVerify:
    def test_verify_ok(self, workspace: Path, alice: KeyManager, ts: Timestamp) -> None:
        write_state(workspace, alice, LockState.LOCKED, ts.iso_utc, "x")
        verify_state(read_state(workspace), alice.identity)

    def test_verify_wrong_operator(self, workspace: Path, alice: KeyManager, bob: KeyManager, ts: Timestamp) -> None:
        write_state(workspace, alice, LockState.LOCKED, ts.iso_utc, "x")
        with pytest.raises(InvalidSignatureError):
            verify_state(read_state(workspace), bob.identity)

    def test_verify_detects_tamper(self, workspace: Path, alice: KeyManager, ts: Timestamp) -> None:
        record = write_state(workspace, alice, LockState.LOCKED, ts.iso_utc, "x")
        tampered = replace(record, state=LockState.UNLOCKED)
        with pytest.raises(InvalidSignatureError):
            verify_state(tampered, alice.identity)

    def test_state_hash_tracks_content(self, workspace: Path, alice: KeyManager, ts: Timestamp) -> None:
        first = write_state(workspace, alice, LockState.LOCKED, ts.iso_utc, "x")
        second = write_state(workspace, alice, LockState.UNLOCKED, ts.iso_utc, "x")
        assert state_hash(first) == state_hash(first)
        assert state_hash(first) != state_hash(second)
