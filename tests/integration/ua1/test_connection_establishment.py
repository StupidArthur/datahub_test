from __future__ import annotations

import time

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    get_rt_value,
    list_ds_info,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, DsSubTypes, DsTypes, TagTypes

from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists
from tests.support.endpoints import parse_mocker_endpoint
from tests.support.naming import unique_name
from tests.support.polling import wait_until


def _is_alive(api, ds_id: int) -> bool:
    page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", -1)) == ds_id:
            return bool(row.get("alive"))
    return False


def _get_rt_point(api, tag_name: str) -> dict:
    points = get_rt_value(api, tag_names=[tag_name])
    if isinstance(points, list) and points:
        return points[0]
    return {}


@pytest.mark.case(
    id="UA-1-1-01",
    chapter="UA-1-1",
    title="正常连接(URL 无 path)",
    preconditions=[
        "mock 已启动，端口可达",
    ],
    steps=[
        "add_ds_info(url=opc.tcp://ip:port)，不带 path",
        "启用数据源",
        "创建一次位号绑定 mocker 节点",
        "等待实时值出现",
        "验证实时值与质量码",
    ],
    expected=[
        "alive=true",
        "getRTValue 返回有效值",
        "quality 有效(非0)",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_normal_connection_no_path(api, settings, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    url_no_path = parsed.url_no_path
    ds_name = unique_name(settings.test_prefix, "UA-1-1-01")
    tag_name = unique_name(settings.test_prefix, "UA-1-1-01-tag")

    data = add_ds_info(
        api,
        ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"],
        ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=url_no_path,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id, f"create datasource returned no id: {data}"

    tag_id = None
    try:
        change_ds_state(api, ds_id, True)
        wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=60.0)

        tag_data = add_tag(
            api,
            tag_name=tag_name,
            data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"],
            ds_id=ds_id,
            only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
        assert tag_id, f"create tag returned no id: {tag_data}"

        def _has_rt():
            pt = _get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt_visible:{tag_name}", _has_rt, timeout=60.0)

        pt = _get_rt_point(api, tag_name)
        assert pt.get("tagValue") is not None, "RT tagValue is None"
        assert pt.get("quality", 0) != 0, f"RT quality is 0: {pt}"
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)


@pytest.mark.case(
    id="UA-1-1-04",
    chapter="UA-1-1",
    title="不可达地址",
    preconditions=[
        "目标端口未监听",
    ],
    steps=[
        "获取动态空闲端口(确保未监听)",
        "add_ds_info 指向该端口",
        "启用数据源",
        "观察窗口内持续检查 alive",
    ],
    expected=[
        "alive=false",
        "系统不崩溃",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_unreachable_address(api, settings):
    from tests.support.mocker_process import find_free_port

    free_port = find_free_port()
    bad_url = f"opc.tcp://127.0.0.1:{free_port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, "UA-1-1-04")

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
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
            for row in page.get("records") or []:
                if int(row.get("id", -1)) == ds_id:
                    assert not row.get("alive"), f"ds became alive on unreachable port {free_port}"
            time.sleep(2.0)
    finally:
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)


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
        "第二次请求抛出 TptAPIError",
        "错误码为 A0001",
        "错误信息包含 Duplicate",
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
        with pytest.raises(TptAPIError) as exc_info:
            add_ds_info(
                api,
                ds_name=ds_name_b,
                ds_type=DsTypes["REAL_TIME_DB"],
                ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
                ds_tar_url=mocker_endpoint,
            )
        assert exc_info.value.code == "A0001", f"unexpected code: {exc_info.value.code}"
        assert "duplicate" in exc_info.value.msg.lower()
    finally:
        delete_datasource_if_exists(api, ds_id, ds_name_a)
