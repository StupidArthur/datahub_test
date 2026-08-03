from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from tests.support.mocker_registry import (
    SCHEMA_VERSION,
    REPO_ROOT,
    generate_run_id,
    get_process_create_time,
    remove_registry_entry,
    write_registry_entry,
)

_MOCKER_DIR = Path(__file__).resolve().parents[2] / "ua_mocker"
_MOCKER_CONFIG_DIR = REPO_ROOT / "tmp" / "mocker-configs"

_SESSION_RUN_ID: str | None = None


def session_run_id() -> str:
    """Return a run id unique per pytest session (cached per process)."""
    global _SESSION_RUN_ID
    if _SESSION_RUN_ID is None:
        _SESSION_RUN_ID = generate_run_id()
    return _SESSION_RUN_ID


@dataclass
class MockerHandle:
    process: subprocess.Popen
    port: int
    endpoint: str
    config_path: Path
    run_id: str | None = None
    case_id: str | None = None


def find_free_port() -> int:
    """Find a free port with retry to reduce race-condition probability."""
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", 0))
            port = s.getsockname()[1]
        time.sleep(0.15)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.bind(("0.0.0.0", port))
            return port
        except OSError:
            continue
    raise RuntimeError("Could not find a stable free port after retries")


def _normalize_nodes(nodes: list[dict]) -> list[dict]:
    defaults = {"count": 1, "change": True}
    return [defaults | nd for nd in nodes]


def write_mocker_config(
    tmp_dir: Path,
    port: int,
    nodes: list[dict] | None = None,
    namespace_index: int = 2,
    cycle: int = 500,
    auth: dict | None = None,
) -> Path:
    """Write a mocker YAML config under the repo tmp scope.

    ``tmp_dir`` is kept for call-site compatibility but the config file is
    written under ``tmp/mocker-configs/`` so the registry's ``config_path``
    is always within the repository tmp scope (required by
    ``tools.cleanup_test_mockers`` ownership verification).
    """
    cfg: dict = {
        "server": "0.0.0.0",
        "port": port,
        "cycle": cycle,
        "namespace_index": namespace_index,
        "nodes": _normalize_nodes(nodes) if nodes else [
            {"name": "smoke_static_", "type": "Double", "count": 1, "change": False, "writable": True, "default": 12.5},
            {"name": "smoke_change_", "type": "Int32", "count": 1, "change": True, "writable": False},
        ],
    }
    if auth:
        cfg["auth"] = auth
    config_dir = _MOCKER_CONFIG_DIR / session_run_id()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"mocker_{port}.yaml"
    config_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    return config_path


def start_mocker(
    config_path: Path,
    port: int,
    host: str | None = None,
    *,
    run_id: str | None = None,
    case_id: str | None = None,
) -> MockerHandle:
    if not host:
        raise ValueError(
            "start_mocker requires an explicit host: cross-machine access uses "
            "the dev-machine IP; 127.0.0.1 would map to the local loopback and "
            "is not a valid DataHub datasource endpoint."
        )
    if run_id is None:
        run_id = session_run_id()
    proc = subprocess.Popen(
        [sys.executable, "main.py", str(config_path)],
        cwd=str(_MOCKER_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    endpoint = f"opc.tcp://{host}:{port}/ua_mocker/"
    try:
        # Local port ready check uses loopback; the YAML's `server: 0.0.0.0`
        # binds the OPC UA server to all interfaces, so the same port is
        # also reachable on `host` for DataHub.
        wait_port_ready(port, timeout=30.0)
    except Exception:
        stdout = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        proc.kill()
        remove_registry_entry(proc.pid)
        raise RuntimeError(
            f"mocker on port {port} did not start.\nstdout: {stdout}\nstderr: {stderr}"
        )
    # Registry entry is written only after the mocker is confirmed running.
    create_time = get_process_create_time(proc.pid)
    write_registry_entry({
        "schema_version": SCHEMA_VERSION,
        "pid": proc.pid,
        "process_create_time": create_time,
        "parent_pid": os.getpid(),
        "repo_root": str(REPO_ROOT),
        "python_executable": sys.executable,
        "entrypoint": str(_MOCKER_DIR / "main.py"),
        "config_path": str(config_path),
        "host": host,
        "port": port,
        "run_id": run_id,
        "case_id": case_id or "",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "command_line": [sys.executable, "main.py", str(config_path)],
    })
    return MockerHandle(
        process=proc, port=port, endpoint=endpoint,
        config_path=config_path, run_id=run_id, case_id=case_id or "",
    )


def wait_port_ready(port: int, timeout: float = 30.0, host: str = "127.0.0.1") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect((host, port))
                return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"port {port} not ready after {timeout}s")


def stop_mocker(handle: MockerHandle) -> None:
    if handle.process.poll() is not None:
        remove_registry_entry(handle.process.pid)
        return
    handle.process.terminate()
    try:
        handle.process.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
        handle.process.kill()
        handle.process.wait(timeout=5.0)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                s.connect(("127.0.0.1", handle.port))
                time.sleep(0.2)
        except OSError:
            remove_registry_entry(handle.process.pid)
            return
    raise AssertionError(f"port {handle.port} still open after stop_mocker")
