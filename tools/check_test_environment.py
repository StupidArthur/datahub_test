"""Read-only environment diagnostic for native pytest tests.

Usage:
    python -m tools.check_test_environment
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path


def main() -> int:
    ok = True

    print(f"Python: {sys.version}")

    import tpt_api.client
    print(f"tpt_api: {Path(tpt_api.client.__file__).resolve()}")

    required_vars = [
        "DATAHUB_BASE_URL",
        "DATAHUB_USER",
        "DATAHUB_PASSWORD",
    ]
    optional_vars = [
        "DATAHUB_TENANT_ID",
        "DATAHUB_TOKEN",
        "UA_MOCKER_ENDPOINT",
        "DATAHUB_TEST_PREFIX",
    ]

    print("\nEnvironment variables:")
    for var in required_vars:
        val = os.environ.get(var, "")
        if val:
            print(f"  {var}: set")
        else:
            print(f"  {var}: MISSING")
            ok = False
    for var in optional_vars:
        val = os.environ.get(var, "")
        print(f"  {var}: {'set' if val else '(not set)'}")

    base_url = os.environ.get("DATAHUB_BASE_URL", "")
    user = os.environ.get("DATAHUB_USER", "")
    password = os.environ.get("DATAHUB_PASSWORD", "")
    tenant = os.environ.get("DATAHUB_TENANT_ID", "")

    if base_url and user and password:
        print("\nDataHub login:")
        try:
            from tpt_api.client import AlgAPI
            api = AlgAPI(base_url=base_url, timeout=10.0)
            api.login(user, password, tenant)
            print("  login: OK")
            from tpt_api.datahub import list_ds_info
            page = list_ds_info(api, page=1, page_size=1)
            total = page.get("total", 0)
            print(f"  list_ds_info: OK (total={total})")
            api.client.close()
        except Exception as exc:
            print(f"  FAILED: {exc}")
            ok = False
    else:
        print("\nDataHub login: skipped (missing config)")

    endpoint = os.environ.get("UA_MOCKER_ENDPOINT", "")
    if endpoint:
        print(f"\nMocker endpoint: {endpoint}")
        import re
        m = re.match(r"opc\.tcp://([^:/]+):(\d+)", endpoint)
        if m:
            host, port = m.group(1), int(m.group(2))
            try:
                s = socket.socket()
                s.settimeout(2)
                s.connect((host, port))
                s.close()
                print(f"  port {port}: reachable")
            except OSError:
                print(f"  port {port}: NOT reachable")
                ok = False
        else:
            print("  cannot parse endpoint")
            ok = False
    else:
        print("\nMocker endpoint: (not set)")

    print(f"\nResult: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
