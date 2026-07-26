from __future__ import annotations

import asyncio
import time

from asyncua import Client

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    list_ds_info,
    list_tags,
    query_tags_with_quality,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DsSubTypes, DsTypes

from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists
from tests.support.endpoints import parse_mocker_endpoint
from tests.support.mocker_process import (
    find_free_port,
    start_mocker,
    stop_mocker,
    write_mocker_config,
)
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point


def is_ds_alive(api, ds_id: int) -> bool:
    page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", -1)) == ds_id:
            return bool(row.get("alive"))
    return False


def wait_ds_alive(api, ds_id: int, timeout: float = 60.0) -> None:
    wait_until(f"ds_alive:{ds_id}", lambda: is_ds_alive(api, ds_id), timeout=timeout)


def wait_ds_offline(api, ds_id: int, timeout: float = 60.0) -> None:
    wait_until(f"ds_offline:{ds_id}", lambda: not is_ds_alive(api, ds_id), timeout=timeout)


def setup_ds_and_tag(
    api, settings, mocker_endpoint, tmp_path_factory, case_id: str,
    *,
    tag_base_name: str,
    data_type: int,
    tag_type: int = 1,
    only_read: bool = True,
    nodes: list | None = None,
    namespace_index: int = 2,
    launch_mocker: bool = True,
    wait_for_rt: bool = True,
    cycle: int = 500,
) -> dict:
    """Create mocker + datasource + tag, return context dict."""
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, f"{case_id}-ds")
    tag_name = unique_name(settings.test_prefix, f"{case_id}-tag")

    tmp_dir = tmp_path_factory.mktemp(f"m_{case_id.lower()}")
    cfg_path = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=namespace_index, cycle=cycle)
    mocker = None
    if launch_mocker:
        mocker = start_mocker(cfg_path, port, host=parsed.host)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))

    if launch_mocker:
        wait_ds_alive(api, ds_id, timeout=60.0)

    tag_data = add_tag(
        api, tag_name=tag_name, data_type=data_type,
        tag_type=tag_type, ds_id=ds_id, only_read=only_read,
        tag_base_name=tag_base_name,
    )
    tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

    if launch_mocker and wait_for_rt:
        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt:{tag_name}", _has_rt, timeout=60.0)

    return {
        "ds_id": ds_id, "ds_name": ds_name,
        "tag_id": tag_id, "tag_name": tag_name,
        "mocker": mocker, "port": port, "host": parsed.host,
        "endpoint": endpoint, "cfg_path": cfg_path,
        "tmp_dir": tmp_dir, "case_id": case_id,
        "namespace_index": namespace_index,
        "cycle": cycle,
    }


def teardown_ds_tag_mocker(api, ctx: dict) -> None:
    tag_id = ctx.pop("tag_id", None)
    tag_name = ctx.pop("tag_name", None)
    ds_id = ctx.pop("ds_id", None)
    ds_name = ctx.pop("ds_name", None)
    mocker = ctx.pop("mocker", None)
    if tag_id:
        delete_tag_if_exists(api, tag_id, tag_name)
    if ds_id:
        try:
            change_ds_state(api, ds_id, False)
        except Exception:
            pass
        delete_datasource_if_exists(api, ds_id, ds_name)
    if mocker:
        try:
            stop_mocker(mocker)
        except Exception:
            pass


def wait_qtq_valid(api, ds_id: int, tag_name: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qwq = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
        for r in ((qwq.get("tagInfoList") or {}).get("records") or []):
            if r.get("tagName") == tag_name and r.get("quality") not in (None, 0):
                return r
        time.sleep(2.0)
    return {}


def find_unique_tag(api, tag_name: str) -> dict:
    page = list_tags(api, page=1, page_size=50, data={"tagName": tag_name})
    records = page.get("records") or []
    match = [r for r in records if r.get("tagName") == tag_name]
    if len(match) == 1:
        return match[0]
    if not match:
        return {}
    raise AssertionError(f"multiple tags match {tag_name!r}: {len(match)}")


def opcua_read_sync(endpoint: str, node_name: str, namespace_index: int = 2):
    async def _read():
        async with Client(endpoint) as client:
            nid = f"ns={namespace_index};s={node_name}"
            return await client.get_node(nid).read_value()
    return asyncio.run(_read())


def opcua_write_sync(endpoint: str, node_name: str, value: object, *, namespace_index: int = 1) -> None:
    async def _write():
        async with Client(endpoint) as client:
            nid = f"ns={namespace_index};s={node_name}"
            node = client.get_node(nid)
            await node.write_value(value)
            readback = await node.read_value()
        actual_type = type(readback)
        actual_val = readback
        if isinstance(value, bool) and actual_type is not bool:
            raise AssertionError(
                f"OPC UA readback type mismatch after write: expected bool, got {actual_type.__name__} "
                f"(value={actual_val!r})"
            )
    asyncio.run(_write())


def assert_write_accepted(response: dict, tag_name: str) -> None:
    assert isinstance(response, dict), f"write response is not dict: {type(response).__name__}"
    tag_names = response.get("tagNames") or []
    assert tag_name in tag_names, \
        f"tag_name {tag_name!r} not in write response tagNames={tag_names}"
    fail_msg = response.get("failMsg") or ""
    if fail_msg:
        assert tag_name not in fail_msg, \
            f"write response failMsg references {tag_name!r}: {fail_msg}"
    err_msg = response.get("msg") or ""
    if err_msg:
        assert tag_name not in err_msg, \
            f"write response msg references {tag_name!r}: {err_msg}"


def setup_ds_only(
    api, settings, mocker_endpoint, tmp_path_factory, case_id: str,
    *,
    nodes: list | None = None,
    namespace_index: int = 2,
    launch_mocker: bool = True,
    cycle: int = 500,
) -> dict:
    """Create mocker + datasource only (no tag)."""
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, f"{case_id}-ds")

    tmp_dir = tmp_path_factory.mktemp(f"m_{case_id.lower()}")
    cfg_path = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=namespace_index, cycle=cycle)
    mocker = None
    if launch_mocker:
        mocker = start_mocker(cfg_path, port, host=parsed.host)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))

    if launch_mocker:
        wait_ds_alive(api, ds_id, timeout=60.0)

    return {
        "ds_id": ds_id, "ds_name": ds_name,
        "mocker": mocker, "port": port, "host": parsed.host,
        "endpoint": endpoint, "cfg_path": cfg_path,
        "tmp_dir": tmp_dir, "case_id": case_id,
        "namespace_index": namespace_index,
        "cycle": cycle,
    }


def find_all_tags(api, tag_name: str) -> list[dict]:
    """Return ALL tag records matching tag_name exactly."""
    page = list_tags(api, page=1, page_size=200, data={"tagName": tag_name})
    records = page.get("records") or []
    return [r for r in records if r.get("tagName") == tag_name]


def try_add_tag(api, **kwargs) -> dict:
    """Call add_tag safely, return structured result.

    Returns {"ok": True, "data": <tag_data>} on success,
    or {"ok": False, "error": <TptAPIError>} on TptAPIError.
    """
    try:
        data = add_tag(api, **kwargs)
        return {"ok": True, "data": data}
    except TptAPIError as exc:
        return {"ok": False, "error": exc}


def delete_tags_safe(api, tag_ids: list[int]) -> None:
    """Hard-delete a list of tag IDs, ignoring already-deleted errors."""
    if not tag_ids:
        return
    from tpt_api.datahub import delete_tags_physical
    try:
        delete_tags_physical(api, tag_ids)
    except TptAPIError as exc:
        if "not exist" in exc.msg.lower() or "不存在" in exc.msg:
            return
        raise
