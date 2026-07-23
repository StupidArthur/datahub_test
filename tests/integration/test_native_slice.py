from __future__ import annotations

import time
import uuid

import pytest

from tpt_api.datahub import (
    add_ds_info,
    change_ds_state,
    delete_ds_info,
    list_ds_info,
)
from tpt_api.types import DsSubTypes, DsTypes


def unique_name(prefix: str, case_id: str) -> str:
    return f"{prefix}{case_id}_{uuid.uuid4().hex[:8]}"


def delete_datasource_if_exists(api, ds_id: int) -> None:
    try:
        delete_ds_info(api, [ds_id])
    except Exception:
        pass
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
        rows = page.get("records") or []
        if not any(int(r.get("id", -1)) == ds_id for r in rows):
            return
        time.sleep(1.0)


def wait_ds_alive(api, ds_id: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
        for row in page.get("records") or []:
            if int(row.get("id", -1)) == ds_id and row.get("alive"):
                return True
        time.sleep(1.0)
    return False


def wait_ds_not_alive(api, ds_id: int, duration: float = 15.0) -> bool:
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
        for row in page.get("records") or []:
            if int(row.get("id", -1)) == ds_id and row.get("alive"):
                return False
        time.sleep(2.0)
    return True


@pytest.mark.case(
    id="UA-1-1-04",
    chapter="UA-1-1",
    title="不可达地址",
    preconditions=[
        "mock 未启动或错误端口",
    ],
    steps=[
        "add_ds_info 指向未监听端口",
        "启用数据源",
        "等待一段时间",
    ],
    expected=[
        "alive=false",
        "系统不崩溃",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_unreachable_address(api, settings):
    ds_name = unique_name(settings.test_prefix, "UA-1-1-04")
    bad_url = "opc.tcp://127.0.0.1:1/ua_mocker/"

    data = add_ds_info(
        api,
        ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"],
        ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=bad_url,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id, f"create datasource returned no id: {data}"

    try:
        change_ds_state(api, ds_id, True)
        stayed_offline = wait_ds_not_alive(api, ds_id, duration=15.0)
        assert stayed_offline, "datasource became alive on unreachable port"
    finally:
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id)


@pytest.mark.case(
    id="UA-1-1-12",
    chapter="UA-1-1",
    title="重复地址注册",
    preconditions=[
        "已有数据源指向 url-A",
    ],
    steps=[
        "创建数据源 A 指向 mocker endpoint",
        "再次 add_ds_info 使用相同 url-A",
    ],
    expected=[
        "第二次请求报错 Duplicate data source address",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_duplicate_url_rejected(api, settings, mocker_endpoint):
    ds_name_a = unique_name(settings.test_prefix, "UA-1-1-12a")

    data = add_ds_info(
        api,
        ds_name=ds_name_a,
        ds_type=DsTypes["REAL_TIME_DB"],
        ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=mocker_endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id, f"create datasource A returned no id: {data}"

    try:
        ds_name_b = unique_name(settings.test_prefix, "UA-1-1-12b")
        with pytest.raises(Exception, match="[Dd]uplicate"):
            add_ds_info(
                api,
                ds_name=ds_name_b,
                ds_type=DsTypes["REAL_TIME_DB"],
                ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
                ds_tar_url=mocker_endpoint,
            )
    finally:
        delete_datasource_if_exists(api, ds_id)


@pytest.mark.case(
    id="UA-1-1-01",
    chapter="UA-1-1",
    title="正常连接(URL 无 path)",
    preconditions=[
        "mock 已启动，端口可达",
    ],
    steps=[
        "add_ds_info(url=opc.tcp://ip:port)",
        "启用数据源",
        "等待采集",
    ],
    expected=[
        "alive=true",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_normal_connection_no_path(api, settings, mocker_endpoint):
    ds_name = unique_name(settings.test_prefix, "UA-1-1-01")

    data = add_ds_info(
        api,
        ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"],
        ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=mocker_endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id, f"create datasource returned no id: {data}"

    try:
        change_ds_state(api, ds_id, True)
        alive = wait_ds_alive(api, ds_id, timeout=60.0)
        assert alive, "datasource did not become alive within 60s"
    finally:
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id)
