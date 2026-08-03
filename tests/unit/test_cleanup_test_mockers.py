"""Unit tests for tools.cleanup_test_mockers (offline, fake process backend).

No real system processes are ever killed here.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tools import cleanup_test_mockers as ctm
from tools.cleanup_test_mockers import ProcInfo, classify_entry
from tests.support import mocker_registry as reg

REPO = ctm.REPO_ROOT


class FakeBackend:
    """In-memory process table; never touches the real OS."""

    def __init__(self, procs: dict[int, ProcInfo] | None = None, self_pid: int = 100000):
        self.procs = dict(procs or {})
        self.self_pid = self_pid
        self.terminated: list[int] = []
        self.killed: list[int] = []
        self._terminate_exits = True
        self._kill_exits = True
        self.port_open = False

    def current_pid(self) -> int:
        return self.self_pid

    def get(self, pid: int) -> ProcInfo | None:
        return self.procs.get(pid)

    def terminate(self, pid: int) -> None:
        self.terminated.append(pid)
        if self._terminate_exits:
            self.procs.pop(pid, None)

    def kill(self, pid: int) -> None:
        self.killed.append(pid)
        if self._kill_exits:
            self.procs.pop(pid, None)

    def wait_exit(self, pid: int, timeout: float) -> bool:
        return pid not in self.procs


def make_proc(
    pid: int,
    *,
    create_time: float = 1000.0,
    ppid: int = 99,
    cmdline: list[str] | None = None,
    status: str = "running",
    rss: int = 1024,
    cwd: str | None = None,
) -> ProcInfo:
    if cmdline is None:
        cfg = str(REPO / "tmp" / "mocker-configs" / "run-x" / f"mocker_{pid}.yaml")
        cmdline = [str(REPO / ".venv" / "python.exe"), "main.py", cfg]
    if cwd is None:
        cwd = str(REPO / "ua_mocker")
    return ProcInfo(pid=pid, create_time=create_time, ppid=ppid, cmdline=cmdline, status=status, rss=rss, cwd=cwd)


def make_entry(pid: int, *, run_id: str = "run-x", parent_pid: int = 99, **kw) -> dict:
    entry = {
        "schema_version": ctm.SCHEMA_VERSION,
        "pid": pid,
        "process_create_time": 1000.0,
        "parent_pid": parent_pid,
        "repo_root": str(REPO),
        "python_executable": str(REPO / ".venv" / "python.exe"),
        "entrypoint": str(REPO / "ua_mocker" / "main.py"),
        "config_path": str(REPO / "tmp" / "mocker-configs" / "run-x" / f"mocker_{pid}.yaml"),
        "host": "10.0.0.1",
        "port": 18000 + pid,
        "run_id": run_id,
        "case_id": "UA-9-9-999",
        "started_at_utc": "2026-01-01T00:00:00+00:00",
        "command_line": ["python", "main.py", "x"],
    }
    entry.update(kw)
    return entry


def classify(entry, backend, *, parent_alive=None, active_run_ids=None):
    pid = entry["pid"]
    proc = backend.get(pid)
    if parent_alive is None:
        parent_alive = bool(entry.get("parent_pid")) and backend.get(int(entry["parent_pid"])) is not None
    return classify_entry(
        entry, proc,
        repo_root=REPO, tmp_root=ctm.TMP_ROOT, entrypoint=ctm.MOCKER_ENTRYPOINT,
        self_pid=backend.current_pid(),
        active_run_ids=set(active_run_ids or []),
        parent_alive=parent_alive,
    )


def test_orphan_cleanable(monkeypatch):
    backend = FakeBackend({123: make_proc(123, cmdline=[str(REPO / ".venv" / "python.exe"), "main.py", str(REPO / "tmp" / "mocker-configs" / "run-x" / "mocker_123.yaml")])})
    entry = make_entry(123)
    status, reasons = classify(entry, backend, parent_alive=False)
    assert status == "orphan", reasons


def test_active_parent_not_cleaned(monkeypatch):
    backend = FakeBackend({
        123: make_proc(123),
        99: make_proc(99, cmdline=["python", "-m", "pytest"]),
    })
    entry = make_entry(123, parent_pid=99)
    status, reasons = classify(entry, backend, parent_alive=True)
    assert status == "active-owned", reasons


def test_foreign_repo_not_cleaned(monkeypatch):
    backend = FakeBackend({123: make_proc(123)})
    entry = make_entry(123, repo_root="C:/somewhere/else")
    status, _ = classify(entry, backend)
    assert status == "foreign"


def test_unregistered_pid_not_cleaned():
    # process table empty -> backend.get returns None -> stale
    backend = FakeBackend({})
    entry = make_entry(999)
    status, reasons = classify(entry, backend, parent_alive=False)
    assert status == "stale", reasons


def test_pid_reuse_create_time_mismatch_ambiguous(monkeypatch):
    backend = FakeBackend({123: make_proc(123, create_time=9999.0)})
    entry = make_entry(123, process_create_time=1000.0)
    status, reasons = classify(entry, backend, parent_alive=False)
    assert status == "ambiguous", reasons


def test_cmdline_mismatch_ambiguous():
    backend = FakeBackend({123: make_proc(123, cmdline=["python", "unrelated.py"])})
    entry = make_entry(123)
    status, reasons = classify(entry, backend, parent_alive=False)
    assert status == "ambiguous", reasons


def test_config_path_outside_tmp_ambiguous():
    backend = FakeBackend({123: make_proc(123)})
    entry = make_entry(123, config_path="C:/other/mocker.yaml")
    status, reasons = classify(entry, backend, parent_alive=False)
    assert status == "ambiguous", reasons


def test_active_run_id_not_cleaned():
    backend = FakeBackend({123: make_proc(123)})
    entry = make_entry(123, run_id="run-current")
    status, reasons = classify(entry, backend, parent_alive=False, active_run_ids=["run-current"])
    assert status == "active-owned", reasons


def test_bad_schema_version_ambiguous():
    backend = FakeBackend({123: make_proc(123)})
    entry = make_entry(123, schema_version=999)
    status, reasons = classify(entry, backend, parent_alive=False)
    assert status == "ambiguous", reasons


class TestReap:
    def test_terminate_success_exit_and_port(self, monkeypatch):
        backend = FakeBackend({123: make_proc(123)})
        backend.port_open = False
        entry = make_entry(123)
        result = ctm.reap_orphan(entry, backend)
        assert result["status"] == "reaped"
        assert result["method"] == "terminate"
        assert result["exit_confirmed"] is True
        assert result["port_closed"] is True
        assert 123 in backend.terminated
        assert 123 not in backend.procs

    def test_terminate_timeout_then_kill(self, monkeypatch):
        backend = FakeBackend({123: make_proc(123)})
        backend._terminate_exits = False  # terminate() keeps it alive
        backend.port_open = False
        entry = make_entry(123)
        result = ctm.reap_orphan(entry, backend)
        assert result["method"] == "kill"
        assert result["exit_confirmed"] is True
        assert 123 in backend.terminated
        assert 123 in backend.killed

    def test_port_not_closed_fails(self, monkeypatch):
        backend = FakeBackend({123: make_proc(123)})
        entry = make_entry(123)
        monkeypatch.setattr(ctm, "port_closed", lambda port, host="127.0.0.1", timeout=5.0: False)
        result = ctm.reap_orphan(entry, backend)
        assert result["status"] == "error"
        assert result["port_closed"] is False

    def test_gone_process_removes_registry(self, monkeypatch, tmp_path):
        monkeypatch.setattr(reg, "REGISTRY_DIR", tmp_path)
        backend = FakeBackend({})
        entry = make_entry(555)
        reg.write_registry_entry(entry)
        result = ctm.reap_orphan(entry, backend)
        assert result["status"] == "gone"
        assert not reg.registry_path(555).exists()

    def test_reclassify_skips_active_owned(self, monkeypatch):
        backend = FakeBackend({123: make_proc(123), 99: make_proc(99)})
        entry = make_entry(123, parent_pid=99)
        result = ctm.reap_orphan(entry, backend)
        assert result["status"] == "skipped"
        assert backend.terminated == []


class TestBuildReport:
    def test_orphan_counted_and_json_serializable(self, monkeypatch, tmp_path):
        monkeypatch.setattr(reg, "REGISTRY_DIR", tmp_path)
        backend = FakeBackend({123: make_proc(123)})
        entry = make_entry(123, parent_pid=99)
        reg.write_registry_entry(entry)
        entries, corrupt = reg.read_registry_entries()
        report = ctm.build_report(entries, corrupt, backend)
        assert report["owned_orphan_mockers"] == 1
        assert report["owned_active_mockers"] == 0
        json.dumps(report)  # must be serializable

    def test_corrupt_registry_reported(self, monkeypatch, tmp_path):
        monkeypatch.setattr(reg, "REGISTRY_DIR", tmp_path)
        (tmp_path / "999999.json").write_text("{broken", encoding="utf-8")
        entries, corrupt = reg.read_registry_entries()
        assert entries == []
        assert len(corrupt) == 1
        report = ctm.build_report(entries, corrupt, FakeBackend({}))
        assert len(report["corrupt_entries"]) == 1
