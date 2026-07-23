"""Collect a reproducible environment snapshot before running UA automation."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import socket
import sys
import time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PACKAGES = ("asyncua", "PyYAML", "pytest", "psutil")
MODULES = ("ua_test_harness", "asyncua", "yaml", "tpt_api")
MOCK_PORTS = (18960, 18961, 18962, 18963)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def repo_root() -> Path | None:
    for start in (Path.cwd(), Path(__file__).resolve().parent):
        for path in (start, *start.parents):
            if all((path / name).exists() for name in ("ua_test_gui", "ua_test_harness", "ua_mocker")):
                return path
    return None


def package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def import_state(name: str) -> dict[str, Any]:
    try:
        spec = importlib.util.find_spec(name)
        return {"ok": spec is not None, "origin": getattr(spec, "origin", None) if spec else None}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def local_ipv4() -> list[str]:
    values: set[str] = set()
    try:
        values.update(x[4][0] for x in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            values.add(sock.getsockname()[0])
    except OSError:
        pass
    values.discard("127.0.0.1")
    return sorted(values)


def tcp_check(host: str, port: int, timeout: float = 2.0) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True, "host": host, "port": port, "elapsedMs": round((time.monotonic()-started)*1000, 2)}
    except OSError as exc:
        return {"ok": False, "host": host, "port": port, "elapsedMs": round((time.monotonic()-started)*1000, 2), "error": str(exc)}


def url_target(value: str) -> tuple[str, int] | None:
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"http://{value}")
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def collect(base_url: str, username: str, local_ip: str) -> dict[str, Any]:
    root = repo_root()
    ips = local_ipv4()
    target = url_target(base_url)
    return {
        "schemaVersion": 1,
        "generatedAt": now(),
        "system": {"platform": platform.platform(), "machine": platform.machine(), "hostname": socket.gethostname()},
        "python": {"version": sys.version, "versionInfo": list(sys.version_info[:3]), "executable": sys.executable, "is64Bit": sys.maxsize > 2**32},
        "process": {"pid": os.getpid(), "cwd": str(Path.cwd()), "argv": sys.argv},
        "repository": {"found": root is not None, "root": str(root) if root else ""},
        "packages": {name: package_version(name) for name in PACKAGES},
        "imports": {name: import_state(name) for name in MODULES},
        "configuration": {
            "baseUrl": base_url,
            "username": username,
            "tenantId": "",
            "passwordPresent": bool(os.getenv("DATAHUB_PASSWORD")),
            "localIp": local_ip,
            "localIpDetected": local_ip in ips,
        },
        "network": {
            "localIPv4": ips,
            "tptTcp": tcp_check(*target) if target else {"ok": False, "skipped": True},
            "mockTcp": [tcp_check("127.0.0.1", port, 0.5) for port in MOCK_PORTS],
        },
    }


def failures(report: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if not report["repository"]["found"]:
        out.append("repository root not found")
    if report["python"]["versionInfo"][:2] != [3, 11]:
        out.append(f"expected Python 3.11, got {report['python']['versionInfo']}")
    for name in ("ua_test_harness", "asyncua", "yaml"):
        if not report["imports"][name]["ok"]:
            out.append(f"import failed: {name}")
    cfg = report["configuration"]
    if cfg["localIp"] and not cfg["localIpDetected"]:
        out.append(f"configured local IP not detected: {cfg['localIp']}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="ua_test_harness.doctor")
    parser.add_argument("--base-url", default=os.getenv("DATAHUB_BASE_URL", ""))
    parser.add_argument("--username", default=os.getenv("DATAHUB_USER", ""))
    parser.add_argument("--local-ip", default=os.getenv("UA_LOCAL_IP", ""))
    parser.add_argument("--output", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = collect(args.base_url, args.username, args.local_ip)
    report["failures"] = failures(report)
    path = Path(args.output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if args.strict and report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
