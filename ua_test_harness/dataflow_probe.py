"""最小真实数据流探针：ua_mocker -> TPT 数据源 -> 位号 -> 实时值 -> 清理。"""
from __future__ import annotations

import argparse
import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ua_test_harness.type_mapping import tpt_data_type_value, tpt_tag_base_name


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def _wait(name: str, fn: Callable[[], Any], timeout: float, interval: float = 1.0) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise TimeoutError(f"{name} timeout after {timeout}s; last={last!r}")


def probe(
    base_url: str,
    username: str,
    password: str,
    local_ip: str,
    mock_port: int = 18964,
    timeout: float = 90.0,
    namespace_index: int = 2,
) -> dict[str, Any]:
    from tpt_api.client import AlgAPI
    from tpt_api.datahub import (
        add_ds_info,
        add_tag,
        delete_ds_info,
        delete_tags_physical,
        get_rt_value,
        list_ds_info,
        list_recycle_tags,
        list_tags,
    )
    from tpt_api.types import DataTypes, DsSubTypes, DsTypes, TagTypes

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ds_name = f"ua_auto_flow_{stamp}"
    tag_name = f"ua_auto_flow_tag_{stamp}"
    node_name = "smoke_change_1"
    tag_base_name = tpt_tag_base_name(namespace_index, node_name)
    endpoint = f"opc.tcp://{local_ip}:{mock_port}/ua_mocker/"
    started = time.monotonic()
    ds_id: int | None = None
    tag_id: int | None = None
    api: Any = None
    result: dict[str, Any] = {
        "schemaVersion": 2,
        "generatedAt": _now(),
        "baseUrl": base_url,
        "username": username,
        "tenantId": "",
        "passwordPresent": bool(password),
        "localIp": local_ip,
        "mockPort": mock_port,
        "namespaceIndex": namespace_index,
        "datasource": {"name": ds_name, "endpoint": endpoint},
        "tag": {"name": tag_name, "nodeName": node_name, "baseName": tag_base_name},
        "checks": [],
        "cleanup": [],
    }

    def add(name: str, ok: bool, **details: Any) -> None:
        result["checks"].append({"name": name, "ok": ok, **{k: _json_safe(v) for k, v in details.items()}})

    def cleanup_add(name: str, ok: bool, **details: Any) -> None:
        result["cleanup"].append({"name": name, "ok": ok, **{k: _json_safe(v) for k, v in details.items()}})

    try:
        api = AlgAPI(base_url=base_url, timeout=20.0)
        api.login(username, password, "")
        add("login", True)

        ds = add_ds_info(
            api,
            ds_name=ds_name,
            ds_type=DsTypes["REAL_TIME_DB"],
            ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
            ds_tar_url=endpoint,
        )
        ds_id = int(ds.get("id") or ds.get("dsId"))
        add("create_datasource", ds_id > 0, dsId=ds_id, response=ds)

        def fetch_alive() -> dict[str, Any] | None:
            page = list_ds_info(api, page=1, page_size=100, data={"id": ds_id})
            rows = page.get("records") or []
            for row in rows:
                if int(row.get("id", 0)) == ds_id and bool(row.get("alive")):
                    return row
            return None

        alive_row = _wait("datasource alive", fetch_alive, timeout=timeout)
        add("datasource_alive", True, datasource=alive_row)

        existing = list_tags(api, page=1, page_size=500, data={"tagName": tag_name})
        existing_ids = [int(r["id"]) for r in existing.get("records") or [] if r.get("tagName") == tag_name]
        if existing_ids:
            delete_tags_physical(api, existing_ids)

        recycled = list_recycle_tags(api, page=1, page_size=500)
        recycle_rows = ((recycled or {}).get("tagInfoList") or {}).get("records") or []
        recycle_ids = [int(r["id"]) for r in recycle_rows if r.get("tagName") == tag_name]
        if recycle_ids:
            delete_tags_physical(api, recycle_ids)

        tag = add_tag(
            api,
            tag_name=tag_name,
            data_type=tpt_data_type_value("Int32", DataTypes),
            tag_type=TagTypes["一次位号"],
            ds_id=ds_id,
            group_id="0",
            unit="",
            only_read=True,
            frequency=1,
            need_push=True,
            tag_desc="Stage 3 minimal dataflow probe",
            is_vector=True,
            tag_base_name=tag_base_name,
        )
        tag_id = int(tag.get("id") or tag.get("tagId") or 0)
        add("create_tag", tag_id > 0, tagId=tag_id, response=tag)

        def fetch_tag() -> dict[str, Any] | None:
            page = list_tags(api, page=1, page_size=500, data={"tagName": tag_name})
            for row in page.get("records") or []:
                if row.get("tagName") == tag_name:
                    return row
            return None

        tag_row = _wait("tag present", fetch_tag, timeout=30.0)
        add("query_tag", True, tag=tag_row)

        def fetch_rt() -> dict[str, Any] | None:
            raw = get_rt_value(api, [tag_name], is_from_db=False)
            if isinstance(raw, list):
                for item in raw:
                    if item.get("tagName") == tag_name and item.get("quality") is not None:
                        return item
                return None
            if isinstance(raw, dict):
                item = raw.get(tag_name) if tag_name in raw else raw
                if isinstance(item, dict) and item:
                    return item
            return None

        first_rt = _wait("first RT value", fetch_rt, timeout=timeout)
        first_value = first_rt.get("tagValue", first_rt.get("value"))
        add("read_rt_first", True, rt=first_rt)

        def fetch_changed() -> dict[str, Any] | None:
            item = fetch_rt()
            if not item:
                return None
            value = item.get("tagValue", item.get("value"))
            return item if value != first_value else None

        changed_rt = _wait("changing RT value", fetch_changed, timeout=30.0, interval=1.0)
        add("read_rt_changed", True, firstValue=first_value, rt=changed_rt)
    except Exception as exc:
        add("probe_exception", False, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    finally:
        if api is not None and tag_id:
            try:
                delete_tags_physical(api, [tag_id])
                cleanup_add("delete_tag", True, tagId=tag_id)
            except Exception as exc:
                cleanup_add("delete_tag", False, tagId=tag_id, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        if api is not None and ds_id:
            try:
                delete_ds_info(api, [ds_id])
                cleanup_add("delete_datasource", True, dsId=ds_id)
            except Exception as exc:
                cleanup_add("delete_datasource", False, dsId=ds_id, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        if api is not None:
            try:
                ds_page = list_ds_info(api, page=1, page_size=200, data={"dsName": ds_name})
                ds_remaining = [r for r in ds_page.get("records") or [] if r.get("dsName") == ds_name or r.get("name") == ds_name]
                tag_page = list_tags(api, page=1, page_size=500, data={"tagName": tag_name})
                tag_remaining = [r for r in tag_page.get("records") or [] if r.get("tagName") == tag_name]
                cleanup_add("verify_cleanup", not ds_remaining and not tag_remaining, datasourceRemaining=ds_remaining, tagRemaining=tag_remaining)
            except Exception as exc:
                cleanup_add("verify_cleanup", False, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())

    result["elapsedMs"] = round((time.monotonic() - started) * 1000, 2)
    result["ok"] = bool(result["checks"]) and all(x["ok"] for x in result["checks"]) and all(x["ok"] for x in result["cleanup"])
    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="ua_test_harness.dataflow_probe")
    parser.add_argument("--base-url", default=os.getenv("DATAHUB_BASE_URL", ""))
    parser.add_argument("--username", default=os.getenv("DATAHUB_USER", ""))
    parser.add_argument("--local-ip", default=os.getenv("UA_LOCAL_IP", ""))
    parser.add_argument("--mock-port", type=int, default=18964)
    parser.add_argument("--namespace-index", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    password = os.getenv("DATAHUB_PASSWORD", "")
    if not password:
        raise SystemExit("DATAHUB_PASSWORD is required")
    report = probe(
        args.base_url,
        args.username,
        password,
        args.local_ip,
        args.mock_port,
        args.timeout,
        args.namespace_index,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    path = Path(args.output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
