"""Datasource fixtures with ownership-safe creation and LIFO cleanup."""
from __future__ import annotations

import time

from tpt_api.datahub import add_ds_info, change_ds_state, delete_ds_info, list_ds_info
from tpt_api.types import DsSubTypes, DsTypes

from ua_test_harness.assertions import AssertFail
from ua_test_harness.context import RunContext
from ua_test_harness.resources import ResourceRegistry

_AUTOMATION_PREFIXES = ("ua_auto_", "ua_test_")


def find_ds_by_name(api, name: str) -> dict | None:
    page = list_ds_info(api, page=1, page_size=500, data={"dsName": name})
    for row in page.get("records") or []:
        if row.get("name") == name or row.get("dsName") == name:
            return row
    return None


def find_ds_by_id(api, ds_id: int) -> dict | None:
    page = list_ds_info(api, page=1, page_size=500, data={"id": ds_id})
    for row in page.get("records") or []:
        try:
            if int(row.get("id")) == int(ds_id):
                return row
        except (TypeError, ValueError):
            continue
    return None


def _is_automation_name(name: str) -> bool:
    return name.startswith(_AUTOMATION_PREFIXES)


def _delete_owned_stale(api, row: dict, requested_name: str) -> None:
    actual_name = str(row.get("dsName") or row.get("name") or "")
    if actual_name != requested_name or not _is_automation_name(actual_name):
        raise AssertFail(
            "refusing to delete or reuse a datasource not owned by this automation: "
            f"requested={requested_name!r} existing={actual_name!r} id={row.get('id')!r}"
        )
    _safe_delete(api, int(row["id"]))


def create_datasource(
    ctx: RunContext,
    name: str,
    endpoint: str,
    sub_type: str = "OPC_UA_SERVER",
    registry: ResourceRegistry | None = None,
) -> dict:
    """创建全新自动化数据源并登记到 Case 或 Run 资源栈。

    不复用用户数据源；只有同名且带自动化前缀的陈旧资源允许删除。
    """
    from ua_test_harness.clients.tpt_client import get_api

    if not _is_automation_name(name):
        raise AssertFail(f"automation datasource name must use an owned prefix: {name!r}")
    if not endpoint:
        raise AssertFail("datasource endpoint is empty")

    api = get_api(ctx)
    stale = find_ds_by_name(api, name)
    if stale:
        _delete_owned_stale(api, stale, name)

    endpoint_page = list_ds_info(api, page=1, page_size=500, data={"dsTarUrl": endpoint})
    endpoint_rows = [row for row in endpoint_page.get("records") or [] if row.get("dsTarUrl") == endpoint]
    if endpoint_rows:
        conflicts = [
            {"id": row.get("id"), "name": row.get("dsName") or row.get("name"), "endpoint": row.get("dsTarUrl")}
            for row in endpoint_rows
        ]
        raise AssertFail(f"datasource endpoint already exists; refusing to reuse/delete it: {conflicts}")

    data = add_ds_info(
        api,
        ds_name=name,
        ds_type=DsTypes["REAL_TIME_DB"],
        ds_sub_type=DsSubTypes[sub_type],
        ds_tar_url=endpoint,
    )
    ds_id = data.get("id") or data.get("dsId")
    if not ds_id:
        raise AssertFail(f"create datasource {name} returned no id: {data}")

    owned_id = int(ds_id)
    (registry or ctx.registry).register(
        f"ds:{name}",
        "datasource",
        lambda: _safe_delete(api, owned_id),
        payload={"id": owned_id, "name": name, "endpoint": endpoint},
    )
    return {"id": owned_id, "name": name, "endpoint": endpoint, "reused": False}


def _safe_delete(api, ds_id: int) -> None:
    current = find_ds_by_id(api, ds_id)
    if not current:
        return
    actual_name = str(current.get("dsName") or current.get("name") or "")
    if not _is_automation_name(actual_name):
        raise RuntimeError(f"refusing to delete non-automation datasource id={ds_id} name={actual_name!r}")
    delete_error: Exception | None = None
    try:
        delete_ds_info(api, [ds_id])
    except Exception as exc:
        delete_error = exc

    deadline = time.monotonic() + 15.0
    last_lookup_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if find_ds_by_id(api, ds_id) is None:
                return
            last_lookup_error = None
        except Exception as exc:
            last_lookup_error = exc
        time.sleep(1.0)

    detail = delete_error or last_lookup_error or RuntimeError("datasource still exists after delete")
    raise RuntimeError(f"delete ds {ds_id} failed: {detail}") from detail


def change_state(ctx: RunContext, ds_id: int, enabled: bool) -> None:
    from ua_test_harness.clients.tpt_client import get_api
    change_ds_state(get_api(ctx), ds_id, enabled)


def get_state(ctx: RunContext, ds_id: int) -> dict | None:
    from ua_test_harness.clients.tpt_client import get_api
    return find_ds_by_id(get_api(ctx), ds_id)


def wait_alive(ctx: RunContext, ds_id: int, timeout: float = 60.0) -> bool:
    from ua_test_harness.clients.tpt_client import get_api
    from ua_test_harness.polling import wait_until
    api = get_api(ctx)

    def fetch() -> bool:
        row = find_ds_by_id(api, ds_id)
        return bool(row) and bool(row.get("alive"))

    try:
        wait_until(f"ds_alive:{ds_id}", fetch, timeout=timeout, interval=1.0)
        return True
    except Exception:
        return False
