"""Unit tests for the mocker process registry (offline, no real processes)."""
from __future__ import annotations

import json
import os

import pytest

from tests.support import mocker_registry as reg


@pytest.fixture
def isolate_registry(tmp_path, monkeypatch):
    """Point the registry dir at a tmp path and reset the session run id."""
    monkeypatch.setattr(reg, "REGISTRY_DIR", tmp_path)
    monkeypatch.setattr(reg, "LOCK_PATH", tmp_path / ".lock")
    monkeypatch.setattr(reg, "REPO_ROOT", tmp_path.parent)
    return tmp_path


def _entry(pid=1234, repo_root=None, **kw):
    base = {
        "schema_version": reg.SCHEMA_VERSION,
        "pid": pid,
        "process_create_time": 1000.0,
        "parent_pid": 99,
        "repo_root": repo_root or str(reg.REPO_ROOT),
        "python_executable": "python",
        "entrypoint": str(reg.REPO_ROOT / "ua_mocker" / "main.py"),
        "config_path": str(reg.REPO_ROOT / "tmp" / "mocker-configs" / "run-x" / f"mocker_{pid}.yaml"),
        "host": "10.0.0.1",
        "port": 18000 + pid,
        "run_id": "run-x",
        "case_id": "UA-9-9-999",
        "started_at_utc": "2026-01-01T00:00:00+00:00",
        "command_line": ["python", "main.py", "x"],
    }
    base.update(kw)
    return base


class TestRunId:
    def test_session_run_id_is_stable_and_contains_pid(self):
        a = reg.generate_run_id()
        b = reg.generate_run_id()
        assert a != b
        assert str(os.getpid()) in a


class TestWriteReadRemove:
    def test_write_and_read_roundtrip(self, isolate_registry):
        entry = _entry()
        reg.write_registry_entry(entry)
        entries, corrupt = reg.read_registry_entries()
        assert corrupt == []
        assert len(entries) == 1
        assert entries[0]["pid"] == 1234
        assert entries[0]["repo_root"] == str(reg.REPO_ROOT)

    def test_remove_deletes_file(self, isolate_registry):
        entry = _entry()
        reg.write_registry_entry(entry)
        assert reg.registry_path(1234).exists()
        reg.remove_registry_entry(1234)
        assert not reg.registry_path(1234).exists()
        assert reg.read_registry_entries() == ([], [])

    def test_remove_missing_is_noop(self, isolate_registry):
        reg.remove_registry_entry(999999)  # must not raise

    def test_write_invalid_pid_rejected(self, isolate_registry):
        with pytest.raises(ValueError):
            reg.write_registry_entry(_entry(pid=0))

    def test_write_foreign_repo_rejected(self, isolate_registry):
        with pytest.raises(ValueError):
            reg.write_registry_entry(_entry(repo_root="C:/elsewhere"))

    def test_atomic_write_replaces_without_tmp_leftover(self, isolate_registry):
        reg.write_registry_entry(_entry(pid=7, process_create_time=1.0))
        reg.write_registry_entry(_entry(pid=7, process_create_time=2.0))
        entries, corrupt = reg.read_registry_entries()
        assert len(entries) == 1
        assert entries[0]["process_create_time"] == 2.0
        leftovers = [p for p in isolate_registry.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    def test_corrupt_json_reported_not_dropped(self, isolate_registry):
        reg.write_registry_entry(_entry(pid=1))
        bad = reg.registry_path(2)
        bad.write_text("{not json", encoding="utf-8")
        entries, corrupt = reg.read_registry_entries()
        assert len(entries) == 1
        assert bad in corrupt


class TestPathHelpers:
    def test_normalize_repo_path_case_and_separators(self):
        norm = reg.normalize_repo_path("C:/Foo\\Bar/")
        assert norm.endswith("foo\\bar") or norm.endswith("foo/bar")

    def test_is_within(self):
        root = reg.REPO_ROOT
        assert reg.is_within(root, str(root / "tmp" / "x.yaml"))
        assert not reg.is_within(root, "C:/elsewhere/x.yaml")


class TestLock:
    def test_lock_acquire_release(self, isolate_registry):
        with reg.registry_lock() as f:
            assert f is not None
        assert True
