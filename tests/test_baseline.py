from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sentinel.integrity.baseline import (
    BASELINE_MEMBER,
    BASELINE_SIG_MEMBER,
    Baseline,
    BaselineEntry,
    BaselineError,
    BaselineLoadError,
    BaselineSignError,
    _safe_join,
)
from sentinel.integrity.hashing import hash_file
from sentinel.integrity.keys import KeyManager
from sentinel.integrity.timestamp import TimeSource, Timestamp

FILES = {
    "a.py": "print('a')\n",
    "pkg/b.py": "print('b')\n",
    "pkg/data.json": '{"k": 1}\n',
    "README.md": "# readme\n",
}


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


@pytest.fixture
def alice(memory_keyring: Any) -> KeyManager:
    return KeyManager.generate("Alice")


@pytest.fixture
def bob(memory_keyring: Any) -> KeyManager:
    return KeyManager.generate("Bob")


@pytest.fixture
def ts() -> Timestamp:
    return Timestamp("2026-01-15T12:00:00Z", TimeSource.SYSTEM, 50)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    base = tmp_path / "root"
    _write(base, FILES)
    return base


@pytest.fixture
def baseline(alice: KeyManager, ts: Timestamp, root: Path) -> Baseline:
    return Baseline.create(alice, root, ts)


class TestCreate:
    def test_creates_signed_baseline(self, baseline: Baseline, alice: KeyManager, ts: Timestamp, root: Path) -> None:
        assert baseline.operator_id == alice.identity.operator_id
        assert baseline.created_at == ts.iso_utc
        assert baseline.root == str(root.resolve())
        entry = next(e for e in baseline.files if e.path == "a.py")
        assert entry.sha256 == hash_file(root / "a.py")
        assert entry.size_bytes == len(FILES["a.py"])
        baseline.verify_signature(alice.identity)

    def test_entries_are_sorted(self, baseline: Baseline) -> None:
        paths = [e.path for e in baseline.files]
        assert paths == sorted(FILES)

    def test_rejects_empty_match(self, alice: KeyManager, ts: Timestamp, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        _write(empty, {"blob.bin": "x"})
        with pytest.raises(BaselineError):
            Baseline.create(alice, empty, ts)

    def test_rejects_missing_root(self, alice: KeyManager, ts: Timestamp, tmp_path: Path) -> None:
        with pytest.raises(BaselineError):
            Baseline.create(alice, tmp_path / "nope", ts)

    def test_excludes_pycache(self, alice: KeyManager, ts: Timestamp, root: Path) -> None:
        _write(root, {"pkg/__pycache__/cached.py": "x = 1\n"})
        created = Baseline.create(alice, root, ts)
        assert all("__pycache__" not in e.path for e in created.files)

    def test_custom_patterns(self, alice: KeyManager, ts: Timestamp, root: Path) -> None:
        _write(root, {"notes.txt": "n", "skip.txt": "s"})
        created = Baseline.create(
            alice, root, ts, include_patterns=("**/*.txt",), exclude_patterns=("skip.txt",)
        )
        assert [e.path for e in created.files] == ["notes.txt"]
        assert created.include_patterns == ("**/*.txt",)
        assert created.exclude_patterns == ("skip.txt",)


class TestSaveLoad:
    def test_roundtrip(self, baseline: Baseline, tmp_path: Path) -> None:
        target = tmp_path / "out" / "base.json"
        target.parent.mkdir()
        baseline.save(target)
        assert (target.parent / "base.json.sig").exists()
        loaded = Baseline.load(target)
        assert loaded.to_dict() == baseline.to_dict()

    def test_save_in_directory(self, baseline: Baseline, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        baseline.save(out)
        assert (out / BASELINE_MEMBER).exists()
        assert (out / BASELINE_SIG_MEMBER).exists()
        assert Baseline.load(out).to_dict() == baseline.to_dict()

    def test_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(BaselineLoadError):
            Baseline.load(tmp_path / "missing.json")

    def test_bad_json_raises(self, tmp_path: Path) -> None:
        target = tmp_path / "bad.json"
        target.write_text("{not json", encoding="utf-8")
        with pytest.raises(BaselineLoadError):
            Baseline.load(target)

    def test_bad_schema_version_raises(self, baseline: Baseline, tmp_path: Path) -> None:
        target = tmp_path / "base.json"
        baseline.save(target)
        data = json.loads(target.read_text(encoding="utf-8"))
        data["schema_version"] = "9.9"
        target.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(BaselineError):
            Baseline.load(target)

    def test_mismatched_detached_signature_raises(self, baseline: Baseline, tmp_path: Path) -> None:
        out = tmp_path / "out"
        out.mkdir()
        baseline.save(out)
        sig = out / BASELINE_SIG_MEMBER
        sig.write_text(sig.read_text(encoding="utf-8").replace("a", "b", 1), encoding="utf-8")
        with pytest.raises(BaselineError):
            Baseline.load(out)


class TestVerifySignature:
    def test_ok_with_correct_operator(self, baseline: Baseline, alice: KeyManager) -> None:
        baseline.verify_signature(alice.identity)

    def test_fails_with_wrong_operator(self, baseline: Baseline, bob: KeyManager) -> None:
        with pytest.raises(BaselineSignError):
            baseline.verify_signature(bob.identity)

    def test_fails_after_tamper(self, baseline: Baseline, alice: KeyManager) -> None:
        tampered = replace(baseline, files=baseline.files[:-1])
        with pytest.raises(BaselineSignError):
            tampered.verify_signature(alice.identity)


class TestVerifyFiles:
    def test_clean(self, baseline: Baseline, root: Path) -> None:
        report = baseline.verify_files(root)
        assert report.is_clean
        assert report.checked == len(FILES)
        assert report.valid == len(FILES)
        assert "clean" in report.summary()

    def test_defaults_to_baseline_root(self, baseline: Baseline) -> None:
        assert baseline.verify_files().is_clean

    def test_detects_missing(self, baseline: Baseline, root: Path) -> None:
        (root / "a.py").unlink()
        report = baseline.verify_files(root)
        assert [(i.code, i.path) for i in report.issues] == [("missing", "a.py")]
        assert report.valid == len(FILES) - 1

    def test_detects_modified(self, baseline: Baseline, root: Path) -> None:
        (root / "a.py").write_text("print('X')\n", encoding="utf-8")
        report = baseline.verify_files(root)
        assert [(i.code, i.path) for i in report.issues] == [("modified", "a.py")]
        issue = report.issues[0]
        assert issue.expected_sha256 != issue.actual_sha256

    def test_detects_size_changed(self, baseline: Baseline, root: Path) -> None:
        (root / "a.py").write_text("print('a')\n# extra\n", encoding="utf-8")
        report = baseline.verify_files(root)
        assert [(i.code, i.path) for i in report.issues] == [("size_changed", "a.py")]
        issue = report.issues[0]
        assert issue.expected_size == len(FILES["a.py"])
        assert issue.actual_size == len("print('a')\n# extra\n")

    def test_ignores_extras_by_default(self, baseline: Baseline, root: Path) -> None:
        _write(root, {"new.py": "x = 1\n"})
        assert baseline.verify_files(root).is_clean

    def test_detects_extras_when_requested(self, baseline: Baseline, root: Path) -> None:
        _write(root, {"new.py": "x = 1\n"})
        report = baseline.verify_files(root, check_extras=True)
        assert [(i.code, i.path) for i in report.issues] == [("extra", "new.py")]
        assert report.issues[0].actual_sha256 == hash_file(root / "new.py")

    def test_raise_if_invalid(self, baseline: Baseline, root: Path) -> None:
        baseline.verify_files(root).raise_if_invalid()
        (root / "a.py").unlink()
        report = baseline.verify_files(root)
        with pytest.raises(BaselineError):
            report.raise_if_invalid()
        assert "missing" in report.summary()


class TestPathSafety:
    @pytest.mark.parametrize("rel", ["../escape.py", "a/../../escape.py", "/etc/passwd", ""])
    def test_safe_join_rejects(self, root: Path, rel: str) -> None:
        with pytest.raises(BaselineError):
            _safe_join(root, rel)

    def test_safe_join_accepts_relative(self, root: Path) -> None:
        assert _safe_join(root, "pkg/b.py") == root.resolve() / "pkg" / "b.py"

    def test_verify_files_rejects_traversal_entry(self, baseline: Baseline, root: Path) -> None:
        evil = replace(baseline, files=(BaselineEntry("../outside.py", "0" * 64, 1),))
        with pytest.raises(BaselineError):
            evil.verify_files(root)
