from __future__ import annotations

import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

_MOCKER_DIR = Path(__file__).resolve().parents[2] / "ua_mocker"


@dataclass
class MockerHandle:
    process: subprocess.Popen
    port: int
    endpoint: str
    config_path: Path


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def write_mocker_config(
    tmp_dir: Path,
    port: int,
    nodes: list[dict] | None = None,
    namespace_index: int = 2,
    cycle: int = 500,
    auth: dict | None = None,
) -> Path:
    cfg: dict = {
        "server": "0.0.0.0",
        "port": port,
        "cycle": cycle,
        "namespace_index": namespace_index,
        "nodes": nodes or [
            {"name": "smoke_static_", "type": "Double", "count": 1, "change": False, "writable": True, "default": 12.5},
            {"name": "smoke_change_", "type": "Int32", "count": 1, "change": True, "writable": False},
        ],
    }
    if auth:
        cfg["auth"] = auth
    config_path = tmp_dir / f"mocker_{port}.yaml"
    config_path.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    return config_path


def start_mocker(config_path: Path, port: int, host: str = "127.0.0.1") -> MockerHandle:
    proc = subprocess.Popen(
        [sys.executable, "main.py", str(config_path)],
        cwd=str(_MOCKER_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    endpoint = f"opc.tcp://{host}:{port}/ua_mocker/"
    try:
        wait_port_ready(port, timeout=30.0)
    except Exception:
        stdout = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        proc.kill()
        raise RuntimeError(
            f"mocker on port {port} did not start.\nstdout: {stdout}\nstderr: {stderr}"
        )
    return MockerHandle(process=proc, port=port, endpoint=endpoint, config_path=config_path)


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
            return
    raise AssertionError(f"port {handle.port} still open after stop_mocker")
