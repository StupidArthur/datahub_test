"""Registry for mocker processes launched by this repository's tests.

Every mocker launched via ``tests.support.mocker_process.start_mocker`` is
recorded under ``tmp/mocker-registry/<pid>.json``. The registry is the
ownership proof used by ``tools.cleanup_test_mockers`` to safely reap
orphaned mockers without ever matching unrelated processes.

Design rules:

* writes are atomic (temp file + ``os.replace``)
* ``stop_mocker`` removes the registry file only after the process has
  exited and its port is confirmed closed
* failed launches never leave a registry file behind
* ``tmp/`` is untracked and never committed
"""
from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = REPO_ROOT / "tmp" / "mocker-registry"
SCHEMA_VERSION = 1
LOCK_PATH = REGISTRY_DIR / ".lock"
_CREATE_TIME_TOLERANCE = 1.0


def generate_run_id() -> str:
    """Return a run id unique per pytest session (process + random suffix)."""
    return f"{os.getpid()}-{uuid.uuid4().hex[:12]}"


def get_process_create_time(pid: int) -> float:
    """Return the process create time (epoch seconds) via psutil."""
    import psutil

    return psutil.Process(pid).create_time()


def registry_path(pid: int) -> Path:
    return REGISTRY_DIR / f"{pid}.json"


def _atomic_write_json(path: Path, payload: dict) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def write_registry_entry(entry: dict) -> None:
    """Write a registry entry atomically. Fails loudly on invalid input."""
    pid = int(entry.get("pid"))
    if pid <= 0:
        raise ValueError(f"invalid registry pid: {pid!r}")
    if entry.get("repo_root") != str(REPO_ROOT):
        raise ValueError(
            f"registry entry repo_root mismatch: {entry.get('repo_root')!r} != {REPO_ROOT}"
        )
    _atomic_write_json(registry_path(pid), entry)


def remove_registry_entry(pid: int) -> None:
    path = registry_path(pid)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def read_registry_entries() -> tuple[list[dict], list[Path]]:
    """Return (valid_entries, corrupt_paths).

    Corrupted JSON files are reported but never silently dropped, so callers
    can surface them without attempting to act on them.
    """
    entries: list[dict] = []
    corrupt: list[Path] = []
    if not REGISTRY_DIR.exists():
        return entries, corrupt
    for p in sorted(REGISTRY_DIR.glob("*.json")):
        if p.name == ".lock":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                entries.append(data)
                continue
        except (json.JSONDecodeError, OSError):
            pass
        corrupt.append(p)
    return entries, corrupt


@contextmanager
def registry_lock():
    """Advisory lock serializing registry mutations across processes.

    On Windows uses msvcrt, on POSIX uses fcntl. Yields the open lock file;
    releasing it closes/unlocks the file.
    """
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_PATH, "a+")
    try:
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
    except ImportError:
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    try:
        yield lock_file
    finally:
        try:
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        except ImportError:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


def normalize_repo_path(value: str) -> str:
    """Normalize a path string for ownership comparison (Windows-safe)."""
    return str(Path(os.path.normpath(value)).resolve()).lower()


def is_within(root: Path, candidate: str) -> bool:
    root_norm = normalize_repo_path(str(root))
    cand_norm = normalize_repo_path(candidate)
    return cand_norm == root_norm or cand_norm.startswith(root_norm + os.sep)
