from __future__ import annotations

import time

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    list_ds_info,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, DsSubTypes, DsTypes, TagTypes

from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists
from tests.support.endpoints import parse_mocker_endpoint
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point


def _is_alive(api, ds_id: int) -> bool:
    page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", -1)) == ds_id:
            return bool(row.get("alive"))
    return False


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
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt_visible:{tag_name}", _has_rt, timeout=60.0)

        pt = get_rt_point(api, tag_name)
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


@pytest.mark.case(
    id="UA-1-1-02",
    chapter="UA-1-1",
    title="正常连接(URL 有 path)",
    preconditions=[
        "mock 已启动，endpoint 带 path",
    ],
    steps=[
        "add_ds_info(url=opc.tcp://ip:port/path)",
        "启用数据源",
        "创建位号",
        "等待实时值",
    ],
    expected=[
        "alive=true",
        "getRTValue 返回有效值",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_normal_connection_with_path(api, settings, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    url_with_path = parsed.url_with_path
    ds_name = unique_name(settings.test_prefix, "UA-1-1-02")
    tag_name = unique_name(settings.test_prefix, "UA-1-1-02-tag")

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=url_with_path,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id

    tag_id = None
    try:
        change_ds_state(api, ds_id, True)
        wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=60.0)

        tag_data = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
        assert tag_id

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt_visible:{tag_name}", _has_rt, timeout=60.0)
        pt = get_rt_point(api, tag_name)
        assert pt.get("tagValue") is not None
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)


@pytest.mark.case(
    id="UA-1-1-03",
    chapter="UA-1-1",
    title="两种 URL 格式区别",
    preconditions=[
        "同一 mock server",
    ],
    steps=[
        "用 opc.tcp://ip:port 注册数据源 A",
        "用 opc.tcp://ip:port/path 注册数据源 B",
        "都启用",
        "各注册位号并读取 RT",
    ],
    expected=[
        "两条数据源都 alive=true",
        "位号独立采集",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_two_url_formats(api, settings, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    ds_name_a = unique_name(settings.test_prefix, "UA-1-1-03a")
    ds_name_b = unique_name(settings.test_prefix, "UA-1-1-03b")
    tag_name_a = unique_name(settings.test_prefix, "UA-1-1-03a-tag")
    tag_name_b = unique_name(settings.test_prefix, "UA-1-1-03b-tag")

    data_a = add_ds_info(
        api, ds_name=ds_name_a,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=parsed.url_no_path,
    )
    ds_id_a = int(data_a.get("id") or data_a.get("dsId"))
    assert ds_id_a

    data_b = add_ds_info(
        api, ds_name=ds_name_b,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=parsed.url_with_path,
    )
    ds_id_b = int(data_b.get("id") or data_b.get("dsId"))
    assert ds_id_b

    tag_id_a = None
    tag_id_b = None
    try:
        change_ds_state(api, ds_id_a, True)
        change_ds_state(api, ds_id_b, True)
        wait_until(f"ds_a_alive:{ds_id_a}", lambda: _is_alive(api, ds_id_a), timeout=60.0)
        wait_until(f"ds_b_alive:{ds_id_b}", lambda: _is_alive(api, ds_id_b), timeout=60.0)

        tag_data_a = add_tag(
            api, tag_name=tag_name_a, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id_a, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id_a = int(tag_data_a.get("id") or tag_data_a.get("tagId"))

        tag_data_b = add_tag(
            api, tag_name=tag_name_b, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id_b, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id_b = int(tag_data_b.get("id") or tag_data_b.get("tagId"))

        def _both_have_rt():
            pa = get_rt_point(api, tag_name_a)
            pb = get_rt_point(api, tag_name_b)
            return (pa.get("tagValue") is not None and pb.get("tagValue") is not None)

        wait_until("both_rt", _both_have_rt, timeout=60.0)
    finally:
        if tag_id_a:
            delete_tag_if_exists(api, tag_id_a, tag_name_a)
        if tag_id_b:
            delete_tag_if_exists(api, tag_id_b, tag_name_b)
        change_ds_state(api, ds_id_a, False)
        change_ds_state(api, ds_id_b, False)
        delete_datasource_if_exists(api, ds_id_a, ds_name_a)
        delete_datasource_if_exists(api, ds_id_b, ds_name_b)


@pytest.mark.case(
    id="UA-1-1-05",
    chapter="UA-1-1",
    title="不可达变可达",
    preconditions=[
        "数据源已配置但 alive=false",
    ],
    steps=[
        "获取动态空闲端口",
        "创建数据源指向该端口(未启动)",
        "启用，确认 alive=false",
        "在同一端口启动 mocker",
        "轮询 alive 变 true",
        "验证位号 RT 值出现",
        "停止 mocker，清理",
    ],
    expected=[
        "alive 从 false 变 true",
        "RT 值出现",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_offline_to_online(api, settings, tmp_path_factory):
    from tests.support.mocker_process import (
        find_free_port, write_mocker_config, start_mocker, stop_mocker,
    )

    local_ip = settings.mocker_endpoint.split("//")[1].split(":")[0] if settings.mocker_endpoint else "127.0.0.1"
    port = find_free_port()
    endpoint = f"opc.tcp://{local_ip}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, "UA-1-1-05")
    tag_name = unique_name(settings.test_prefix, "UA-1-1-05-tag")

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id

    mocker = None
    tag_id = None
    try:
        change_ds_state(api, ds_id, True)
        time.sleep(5)
        assert not _is_alive(api, ds_id), "ds should be offline before mocker starts"

        tmp_dir = tmp_path_factory.mktemp("mocker_ua1105")
        cfg_path = write_mocker_config(tmp_dir, port)
        mocker = start_mocker(cfg_path, port, host=local_ip)

        wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=90.0)

        tag_data = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None

        wait_until(f"rt:{tag_name}", _has_rt, timeout=60.0)
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)
        if mocker:
            stop_mocker(mocker)


@pytest.mark.case(
    id="UA-1-1-06",
    chapter="UA-1-1",
    title="数据源有鉴权，不配凭据",
    preconditions=[
        "mock 配置用户名密码鉴权",
    ],
    steps=[
        "启动带认证的 mocker",
        "add_ds_info 不带凭据",
        "启用数据源",
        "等待观察 alive",
    ],
    expected=[
        "alive=false（鉴权失败）",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_auth_required_no_creds(api, settings, tmp_path_factory):
    from tests.support.mocker_process import (
        find_free_port, write_mocker_config, start_mocker, stop_mocker,
    )

    local_ip = settings.mocker_endpoint.split("//")[1].split(":")[0] if settings.mocker_endpoint else "127.0.0.1"
    port = find_free_port()
    endpoint = f"opc.tcp://{local_ip}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, "UA-1-1-06")

    tmp_dir = tmp_path_factory.mktemp("mocker_ua1106")
    cfg_path = write_mocker_config(tmp_dir, port, auth={"enabled": True, "username": "u1", "password": "p1"})
    mocker = start_mocker(cfg_path, port, host=local_ip)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id

    try:
        change_ds_state(api, ds_id, True)
        time.sleep(10)
        assert not _is_alive(api, ds_id), "ds should stay offline without credentials"
    finally:
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)
        stop_mocker(mocker)


@pytest.mark.case(
    id="UA-1-1-07",
    chapter="UA-1-1",
    title="数据源有鉴权，配正确凭据",
    preconditions=[
        "mock 配置用户名密码鉴权",
    ],
    steps=[
        "启动带认证的 mocker",
        "add_ds_info 带正确 dsExtInfo 凭据",
        "启用数据源",
        "创建位号，验证 RT",
    ],
    expected=[
        "alive=true（产品能力缺失：当前 DataHub 不使用 dsExtInfo 中的 OPC UA 凭据）",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.xfail(
    strict=True,
    reason="DataHub 当前不消费 dsExtInfo 中的 OPC UA username/password，认证 mock 上 alive 无法变 true",
)
def test_auth_correct_creds(api, settings, tmp_path_factory):
    from tests.support.mocker_process import (
        find_free_port, write_mocker_config, start_mocker, stop_mocker,
    )

    local_ip = settings.mocker_endpoint.split("//")[1].split(":")[0] if settings.mocker_endpoint else "127.0.0.1"
    port = find_free_port()
    endpoint = f"opc.tcp://{local_ip}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, "UA-1-1-07")
    tag_name = unique_name(settings.test_prefix, "UA-1-1-07-tag")

    tmp_dir = tmp_path_factory.mktemp("mocker_ua1107")
    cfg_path = write_mocker_config(tmp_dir, port, auth={"enabled": True, "username": "u1", "password": "p1"})
    mocker = start_mocker(cfg_path, port, host=local_ip)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
        ds_ext_info={"username": "u1", "password": "p1"},
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id

    tag_id = None
    try:
        change_ds_state(api, ds_id, True)
        wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=60.0)

        tag_data = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None

        wait_until(f"rt:{tag_name}", _has_rt, timeout=60.0)
        pt = get_rt_point(api, tag_name)
        assert pt.get("tagValue") is not None
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)
        stop_mocker(mocker)


@pytest.mark.case(
    id="UA-1-1-08",
    chapter="UA-1-1",
    title="数据源无鉴权，配了凭据",
    preconditions=[
        "mock 无鉴权",
    ],
    steps=[
        "add_ds_info 带多余 dsExtInfo 凭据",
        "启用数据源",
        "创建位号，验证 RT",
    ],
    expected=[
        "alive=true（多余凭据不影响连接）",
        "getRTValue 返回值正确",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_no_auth_extra_creds(api, settings, mocker_endpoint):
    ds_name = unique_name(settings.test_prefix, "UA-1-1-08")
    tag_name = unique_name(settings.test_prefix, "UA-1-1-08-tag")

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=mocker_endpoint,
        ds_ext_info={"username": "unused_user", "password": "unused_pass"},
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id

    tag_id = None
    try:
        change_ds_state(api, ds_id, True)
        wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=60.0)

        tag_data = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None

        wait_until(f"rt:{tag_name}", _has_rt, timeout=60.0)
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)


@pytest.mark.case(
    id="UA-1-1-09",
    chapter="UA-1-1",
    title="不配好值质量码",
    preconditions=[
        "mock 已启动",
    ],
    steps=[
        "add_ds_info 不设好值质量码",
        "启用，创建位号",
        "读取 RT quality",
    ],
    expected=[
        "RT quality 为平台默认好值(192)",
        "值正常采集",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_quality_default(api, settings, mocker_endpoint):
    ds_name = unique_name(settings.test_prefix, "UA-1-1-09")
    tag_name = unique_name(settings.test_prefix, "UA-1-1-09-tag")

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=mocker_endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id

    tag_id = None
    try:
        change_ds_state(api, ds_id, True)
        wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=60.0)

        tag_data = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt:{tag_name}", _has_rt, timeout=60.0)
        pt = get_rt_point(api, tag_name)
        assert pt.get("quality") == 192, f"default quality should be 192, got {pt.get('quality')}"
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)


@pytest.mark.case(
    id="UA-1-1-10",
    chapter="UA-1-1",
    title="配置正常好值(192)",
    preconditions=[
        "mock 已启动",
    ],
    steps=[
        "add_ds_info 好值质量码=192",
        "启用，创建位号",
        "读取 RT quality",
    ],
    expected=[
        "RT quality=192",
        "值正常采集",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_quality_192(api, settings, mocker_endpoint):
    ds_name = unique_name(settings.test_prefix, "UA-1-1-10")
    tag_name = unique_name(settings.test_prefix, "UA-1-1-10-tag")

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=mocker_endpoint,
        ds_ext_info={"goodQuality": "192"},
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id

    tag_id = None
    try:
        change_ds_state(api, ds_id, True)
        wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=60.0)

        tag_data = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt:{tag_name}", _has_rt, timeout=60.0)
        pt = get_rt_point(api, tag_name)
        assert pt.get("quality") == 192, f"quality should be 192, got {pt.get('quality')}"
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)


@pytest.mark.case(
    id="UA-1-1-11",
    chapter="UA-1-1",
    title="配置非标准好值(如 0)",
    preconditions=[
        "mock 已启动",
    ],
    steps=[
        "add_ds_info 好值质量码=0",
        "启用，创建位号",
        "读取 RT quality 和采集行为",
    ],
    expected=[
        "quality=0 的值被系统视为好值正常采集",
        "RT 有值",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_quality_zero(api, settings, mocker_endpoint):
    ds_name = unique_name(settings.test_prefix, "UA-1-1-11")
    tag_name = unique_name(settings.test_prefix, "UA-1-1-11-tag")

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=mocker_endpoint,
        ds_ext_info={"goodQuality": "0"},
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    assert ds_id

    tag_id = None
    try:
        change_ds_state(api, ds_id, True)
        wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=60.0)

        tag_data = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None

        wait_until(f"rt:{tag_name}", _has_rt, timeout=60.0)
        pt = get_rt_point(api, tag_name)
        assert pt.get("tagValue") is not None, "RT should have value even with goodQuality=0"
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        change_ds_state(api, ds_id, False)
        delete_datasource_if_exists(api, ds_id, ds_name)
