"""TPT 登录与临时数据源生命周期探针。"""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if k.lower() in {"password", "token", "authorization", "cookie"} else _safe(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe(v) for v in value]
    return value


def probe(base_url: str, username: str, password: str, local_ip: str) -> dict[str, Any]:
    from tpt_api.client import AlgAPI
    from tpt_api.datahub import add_ds_info, delete_ds_info, list_ds_info
    from tpt_api.types import DsSubTypes, DsTypes

    started = time.monotonic()
    name = f"ua_auto_probe_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    endpoint = f"opc.tcp://{local_ip}:18999/ua_mocker/"
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "generatedAt": _now(),
        "baseUrl": base_url,
        "username": username,
        "tenantId": "",
        "passwordPresent": bool(password),
        "localIp": local_ip,
        "datasource": {"name": name, "endpoint": endpoint},
        "checks": [],
    }
    ds_id: int | None = None

    def add(name_: str, ok: bool, **details: Any) -> None:
        result["checks"].append({"name": name_, "ok": ok, **_safe(details)})

    try:
        api = AlgAPI(base_url=base_url, timeout=20.0)
        api.login(username, password, "")
        add("login", True)

        created = add_ds_info(
            api,
            ds_name=name,
            ds_type=DsTypes["REAL_TIME_DB"],
            ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
            ds_tar_url=endpoint,
        )
        ds_id_raw = created.get("id") or created.get("dsId")
        ds_id = int(ds_id_raw) if ds_id_raw is not None else None
        add("create_datasource", ds_id is not None, dsId=ds_id, response=created)

        page = list_ds_info(api, page=1, page_size=50, data={"dsName": name})
        rows = page.get("records") or []
        matched = [row for row in rows if row.get("dsName") == name or row.get("name") == name]
        add("query_datasource", bool(matched), matched=matched)
    except Exception as exc:
        add("probe_exception", False, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        if ds_id is not None:
            try:
                delete_ds_info(api, [ds_id])
                add("delete_datasource", True, dsId=ds_id)
                page = list_ds_info(api, page=1, page_size=50, data={"dsName": name})
                rows = page.get("records") or []
                remaining = [row for row in rows if row.get("dsName") == name or row.get("name") == name]
                add("verify_deleted", not remaining, remaining=remaining)
            except Exception as exc:
                add("cleanup_exception", False, dsId=ds_id, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())

    result["elapsedMs"] = round((time.monotonic() - started) * 1000, 2)
    result["ok"] = bool(result["checks"]) and all(item["ok"] for item in result["checks"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="ua_test_harness.tpt_probe")
    parser.add_argument("--base-url", default=os.getenv("DATAHUB_BASE_URL", ""))
    parser.add_argument("--username", default=os.getenv("DATAHUB_USER", ""))
    parser.add_argument("--password", default=os.getenv("DATAHUB_PASSWORD", ""))
    parser.add_argument("--local-ip", default=os.getenv("UA_LOCAL_IP", ""))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = probe(args.base_url, args.username, args.password, args.local_ip)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    path = Path(args.output).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
