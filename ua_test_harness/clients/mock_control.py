"""clients/mock_control.py:Mock 启停 / 状态查询。

automation 使用 controlMode=external-script 时,按 run-config endpoint 端口
启停 ua_mocker YAML(18965/18967),而非 MockManager 默认 18960 套。
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from ua_test_harness.context import RunContext

_REPO = Path(__file__).resolve().parents[2]
_MOCK_DIR = _REPO / "ua_mocker"
_YAML_BY_PORT = {18960: "smoke.yaml", 18965: "ua2_types.yaml", 18967: "ua2_empty.yaml"}
_DEFAULT_PORTS = {
    "functional": 18960,
    "reconnect": 18961,
    "performance": 18962,
    "abnormal": 18963,
}


def _ensure_tpt_manager_path() -> None:
    import ua_test_harness._paths  # noqa: F401


def _endpoint_for(ctx: RunContext, key: str) -> str:
    eps = ctx.config.mock.endpoints
    return {
        "functional": eps.functional,
        "reconnect": eps.reconnect,
        "performance": eps.performance,
        "abnormal": eps.abnormal,
    }.get(key, "")


def _parse_host_port(endpoint: str) -> tuple[str, int]:
    m = re.match(r"opc\.tcp://([^:/]+):(\d+)/", endpoint)
    if not m:
        raise ValueError(f"cannot parse mock endpoint: {endpoint!r}")
    return m.group(1), int(m.group(2))


def _port_listening(host: str, port: int) -> bool:
    try:
        sock = socket.socket()
        sock.settimeout(0.5)
        sock.connect((host, port))
        sock.close()
        return True
    except OSError:
        return False


def _is_external(ctx: RunContext | None) -> bool:
    return bool(ctx and ctx.config.mock.control_mode == "external-script")


def start_mock(key: str, ctx: RunContext | None = None) -> int:
    if _is_external(ctx):
        ep = _endpoint_for(ctx, key)
        if not ep:
            raise RuntimeError(f"external-script mock missing endpoint for {key!r}")
        host, port = _parse_host_port(ep)
        yaml_name = _YAML_BY_PORT.get(port)
        if not yaml_name:
            raise RuntimeError(f"no ua_mocker yaml mapped for port {port}")
        if _port_listening(host, port):
            return 0
        yaml_path = _MOCK_DIR / yaml_name
        proc = subprocess.Popen(
            [sys.executable, "main.py", str(yaml_path)],
            cwd=str(_MOCK_DIR),
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if _port_listening(host, port):
                return proc.pid
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        proc.kill()
        raise RuntimeError(f"external mock on port {port} did not become ready")
    _ensure_tpt_manager_path()
    from ua_test_harness.env.mock_manager import MockManager, all_specs

    mgr = MockManager()
    spec = {s.key: s for s in all_specs()}[key]
    rt = mgr.start(spec)
    return rt.pid


def stop_mock(key: str, ctx: RunContext | None = None) -> None:
    if _is_external(ctx):
        ep = _endpoint_for(ctx, key)
        if ep:
            _, port = _parse_host_port(ep)
            from ua_test_harness.env.os_env import kill_port
            kill_port(port)
        return
    _ensure_tpt_manager_path()
    from ua_test_harness.env.mock_manager import MockManager

    MockManager().stop(key)


def status(key: str, ctx: RunContext | None = None) -> str:
    if _is_external(ctx):
        ep = _endpoint_for(ctx, key)
        if not ep:
            return "stopped"
        host, port = _parse_host_port(ep)
        return "running" if _port_listening(host, port) else "stopped"
    _ensure_tpt_manager_path()
    from ua_test_harness.env.mock_manager import MockManager

    return MockManager().status(key)


def wait_ready(key: str, timeout: float = 60.0, ctx: RunContext | None = None) -> None:
    from ua_test_harness.polling import wait_until

    if _is_external(ctx):
        ep = _endpoint_for(ctx, key)
        host, port = _parse_host_port(ep)
        wait_until(
            f"mock_{key}_ready",
            lambda: _port_listening(host, port),
            timeout=timeout,
            interval=0.5,
        )
        return
    wait_until(
        f"mock_{key}_ready",
        lambda: status(key, ctx=ctx) in ("ready", "running"),
        timeout=timeout,
        interval=1.0,
    )


def get_endpoint(key: str, ctx: RunContext | None = None) -> str:
    """从 RunConfig 取 mock endpoint;无则按 key + 本机 IP 兜底。"""
    if ctx is not None:
        ep = _endpoint_for(ctx, key)
        if ep:
            return ep
        from .tpt_client import endpoint_for
        return endpoint_for(key, ctx)
    port = _DEFAULT_PORTS.get(key, 18960)
    return f"opc.tcp://127.0.0.1:{port}/ua_mocker/"
