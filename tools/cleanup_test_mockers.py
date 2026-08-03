"""Safely reap mocker processes owned by this repository.

Only processes that are provably owned by this repository *and* orphaned
(their registered parent process is gone) are terminated. Any uncertainty
is reported as ``ambiguous`` and never acted on.

Usage:
    python -m tools.cleanup_test_mockers --check
    python -m tools.cleanup_test_mockers --check --json
    python -m tools.cleanup_test_mockers --apply
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MOCKER_ENTRYPOINT = REPO_ROOT / "ua_mocker" / "main.py"
TMP_ROOT = REPO_ROOT / "tmp"
SCHEMA_VERSION = 1
CREATE_TIME_TOLERANCE = 1.0
TERMINATE_POLL_SECONDS = 10.0
KILL_POLL_SECONDS = 5.0

from tests.support.mocker_registry import (  # noqa: E402
    normalize_repo_path,
    read_registry_entries,
    registry_lock,
    remove_registry_entry,
    is_within,
)


@dataclass
class ProcInfo:
    pid: int
    create_time: float
    ppid: int
    cmdline: list[str]
    status: str
    rss: int
    cwd: str | None = None


class PsutilBackend:
    """Real process backend backed by psutil."""

    def current_pid(self) -> int:
        return os.getpid()

    def get(self, pid: int) -> ProcInfo | None:
        import psutil

        try:
            p = psutil.Process(pid)
            info = p.as_dict(attrs=["pid", "create_time", "ppid", "cmdline", "status", "memory_info"])
            try:
                cwd = p.cwd()
            except (psutil.AccessDenied, psutil.ZombieProcess):
                cwd = None
            rss = (info.get("memory_info") or {}).rss if info.get("memory_info") else 0
            return ProcInfo(
                pid=int(info["pid"]),
                create_time=float(info["create_time"]),
                ppid=int(info["ppid"]),
                cmdline=list(info.get("cmdline") or []),
                status=str(info.get("status") or ""),
                rss=int(rss),
                cwd=cwd,
            )
        except psutil.NoSuchProcess:
            return None
        except (psutil.AccessDenied, psutil.ZombieProcess, ValueError):
            return None

    def terminate(self, pid: int) -> None:
        import psutil

        psutil.Process(pid).terminate()

    def kill(self, pid: int) -> None:
        import psutil

        psutil.Process(pid).kill()

    def wait_exit(self, pid: int, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get(pid) is None:
                return True
            time.sleep(0.2)
        return self.get(pid) is None


def port_closed(port: int, host: str = "127.0.0.1", timeout: float = 5.0) -> bool:
    """Return True when nothing accepts connections on the given port."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                time.sleep(0.2)
        except OSError:
            return True
    return False


def _cmdline_points_to_entrypoint(proc: ProcInfo, entrypoint: Path) -> bool:
    """Ownership proof: cwd is the repo's ua_mocker dir and main.py is invoked."""
    if proc.cwd is None:
        return False
    if normalize_repo_path(proc.cwd) != normalize_repo_path(str(entrypoint.parent)):
        return False
    return any(os.path.basename(token) == entrypoint.name for token in proc.cmdline)


def _cmdline_uses_config(proc: ProcInfo, config_path: str) -> bool:
    cfg_norm = normalize_repo_path(config_path)
    return any(normalize_repo_path(token) == cfg_norm for token in proc.cmdline)


def classify_entry(
    entry: dict,
    proc: ProcInfo | None,
    *,
    repo_root: Path,
    tmp_root: Path,
    entrypoint: Path,
    self_pid: int,
    active_run_ids: set[str],
    parent_alive: bool,
) -> tuple[str, list[str]]:
    """Classify a registry entry.

    Returns ``(status, reasons)`` where status is one of:
    ``foreign``, ``stale``, ``ambiguous``, ``active-owned``, ``orphan``.
    Only ``orphan`` is safe to reap.
    """
    reasons: list[str] = []

    if int(entry.get("schema_version") or 0) != SCHEMA_VERSION:
        return "ambiguous", ["unsupported schema_version"]

    if normalize_repo_path(entry.get("repo_root") or "") != normalize_repo_path(str(repo_root)):
        return "foreign", ["repo_root does not match current repository"]

    if proc is None:
        return "stale", ["pid not running"]

    if int(entry.get("pid", -1)) != proc.pid:
        return "ambiguous", ["registered pid does not match process pid"]

    entry_ct = float(entry.get("process_create_time") or 0)
    if abs(entry_ct - proc.create_time) > CREATE_TIME_TOLERANCE:
        reasons.append("create_time mismatch (possible pid reuse)")
        return "ambiguous", reasons

    if proc.pid == self_pid:
        return "ambiguous", ["is the cleanup tool itself"]

    if not _cmdline_points_to_entrypoint(proc, entrypoint):
        return "ambiguous", ["cmdline does not point at repo mocker entrypoint"]

    config_path = entry.get("config_path") or ""
    if not is_within(tmp_root, config_path):
        return "ambiguous", ["config_path outside repo tmp scope"]

    if not _cmdline_uses_config(proc, config_path):
        return "ambiguous", ["cmdline does not use registered config_path"]

    if entry.get("run_id") in active_run_ids:
        return "active-owned", ["belongs to an active pytest run"]

    if parent_alive:
        return "active-owned", ["registered parent process is still alive"]

    return "orphan", []


def _entry_item(entry: dict, status: str, reasons: list[str], proc: ProcInfo | None) -> dict:
    return {
        "pid": entry.get("pid"),
        "status": status,
        "reasons": reasons,
        "rss": proc.rss if proc else 0,
        "age_seconds": int(time.time() - float(entry.get("process_create_time") or time.time())),
        "port": entry.get("port"),
        "run_id": entry.get("run_id"),
        "case_id": entry.get("case_id"),
        "config_path": entry.get("config_path"),
        "command_line": proc.cmdline if proc else None,
    }


def build_report(entries: list[dict], corrupt: list[Path], backend) -> dict:
    self_pid = backend.current_pid()
    active_run_ids = {
        e.get("run_id")
        for e in entries
        if e.get("run_id") and e.get("parent_pid") is not None
        and backend.get(int(e["parent_pid"])) is not None
    }

    buckets = {"foreign": [], "stale": [], "ambiguous": [], "active-owned": [], "orphan": []}
    for entry in entries:
        pid = entry.get("pid")
        proc = backend.get(int(pid)) if pid is not None else None
        parent_alive = bool(entry.get("parent_pid")) and backend.get(int(entry["parent_pid"])) is not None
        status, reasons = classify_entry(
            entry, proc,
            repo_root=REPO_ROOT, tmp_root=TMP_ROOT, entrypoint=MOCKER_ENTRYPOINT,
            self_pid=self_pid, active_run_ids=active_run_ids, parent_alive=parent_alive,
        )
        buckets[status].append(_entry_item(entry, status, reasons, proc))

    active_rss = sum(i["rss"] for i in buckets["active-owned"])
    orphan_rss = sum(i["rss"] for i in buckets["orphan"])
    ambiguous_rss = sum(i["rss"] for i in buckets["ambiguous"])
    stale_rss = sum(i["rss"] for i in buckets["stale"])

    return {
        "schema_version": SCHEMA_VERSION,
        "repo": str(REPO_ROOT),
        "active_run_ids": sorted(active_run_ids),
        "owned_active_mockers": len(buckets["active-owned"]),
        "owned_orphan_mockers": len(buckets["orphan"]),
        "ambiguous_entries": len(buckets["ambiguous"]),
        "stale_entries": len(buckets["stale"]),
        "foreign_entries": len(buckets["foreign"]),
        "corrupt_entries": [str(p) for p in corrupt],
        "active_rss_bytes": active_rss,
        "orphan_rss_bytes": orphan_rss,
        "ambiguous_rss_bytes": ambiguous_rss,
        "stale_rss_bytes": stale_rss,
        "total_owned_rss_bytes": active_rss + orphan_rss + ambiguous_rss + stale_rss,
        "orphans": buckets["orphan"],
        "ambiguous": buckets["ambiguous"],
        "stale": buckets["stale"],
        "foreign": buckets["foreign"],
        "active_owned": buckets["active-owned"],
    }


def reap_orphan(entry: dict, backend) -> dict:
    """Reap a single orphan with fresh re-verification before any signal."""
    pid = int(entry["pid"])
    port = entry.get("port")

    proc = backend.get(pid)
    if proc is None:
        remove_registry_entry(pid)
        return {
            "pid": pid, "status": "gone", "port": port, "run_id": entry.get("run_id"),
            "method": "none", "exit_confirmed": True, "port_closed": True,
            "reason": "process already gone; registry entry removed",
        }

    parent_alive = bool(entry.get("parent_pid")) and backend.get(int(entry["parent_pid"])) is not None
    status, reasons = classify_entry(
        entry, proc,
        repo_root=REPO_ROOT, tmp_root=TMP_ROOT, entrypoint=MOCKER_ENTRYPOINT,
        self_pid=backend.current_pid(),
        active_run_ids=set(),
        parent_alive=parent_alive,
    )
    if status != "orphan":
        return {
            "pid": pid, "status": "skipped", "port": port, "run_id": entry.get("run_id"),
            "method": "none", "exit_confirmed": False, "port_closed": None,
            "reason": f"reclassification: {status}: {'; '.join(reasons)}",
        }

    method = "terminate"
    backend.terminate(pid)
    exited = backend.wait_exit(pid, TERMINATE_POLL_SECONDS)
    if not exited:
        method = "kill"
        backend.kill(pid)
        exited = backend.wait_exit(pid, KILL_POLL_SECONDS)

    port_ok = port_closed(port) if port else True

    if exited:
        remove_registry_entry(pid)

    return {
        "pid": pid, "status": "reaped" if (exited and port_ok) else "error",
        "port": port, "run_id": entry.get("run_id"),
        "method": method, "exit_confirmed": exited, "port_closed": port_ok,
        "reason": "" if (exited and port_ok) else "exit or port-close not confirmed",
    }


def _print_summary(report: dict) -> None:
    print(f"repo: {report['repo']}")
    print(f"owned active mockers : {report['owned_active_mockers']}")
    print(f"owned orphan mockers : {report['owned_orphan_mockers']}")
    print(f"ambiguous entries    : {report['ambiguous_entries']}")
    print(f"stale entries        : {report['stale_entries']}")
    print(f"foreign entries      : {report['foreign_entries']}")
    print(f"corrupt entries      : {len(report['corrupt_entries'])}")
    print(f"total owned RSS      : {report['total_owned_rss_bytes']} bytes")
    for item in report["orphans"]:
        print(f"  orphan pid={item['pid']} port={item['port']} run_id={item['run_id']} rss={item['rss']}")
    for item in report["ambiguous"]:
        print(f"  ambiguous pid={item['pid']} reasons={'; '.join(item['reasons'])}")
    if report["corrupt_entries"]:
        for p in report["corrupt_entries"]:
            print(f"  corrupt registry file: {p}")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reap repo-owned orphan mockers safely.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="report only, never terminate")
    group.add_argument("--apply", action="store_true", help="reap confirmed orphans")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    entries, corrupt = read_registry_entries()
    backend = PsutilBackend()

    if args.apply:
        report = build_report(entries, corrupt, backend)
        if report["ambiguous_entries"] or report["corrupt_entries"]:
            _print_summary(report)
            print("\n--apply aborted: ambiguous or corrupt entries present", file=sys.stderr)
            return 1
        with registry_lock():
            entries, corrupt = read_registry_entries()
            report = build_report(entries, corrupt, backend)
            if report["ambiguous_entries"] or report["corrupt_entries"]:
                _print_summary(report)
                print("\n--apply aborted: ambiguous or corrupt entries present", file=sys.stderr)
                return 1
            results = [reap_orphan(e, backend) for e in entries if e.get("pid") is not None]
            for r in results:
                print(f"  pid={r['pid']} status={r['status']} method={r['method']} "
                      f"exit={r['exit_confirmed']} port_closed={r['port_closed']} "
                      f"port={r['port']} run_id={r['run_id']} reason={r['reason']}")
        if args.json:
            print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
        failures = [r for r in results if r["status"] == "error"]
        return 1 if failures else 0

    report = build_report(entries, corrupt, backend)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_summary(report)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
