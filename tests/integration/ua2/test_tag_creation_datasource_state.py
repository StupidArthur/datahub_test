from __future__ import annotations

import time

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    list_ds_info,
    list_tags,
    query_tags_with_quality,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, DsSubTypes, DsTypes, TagTypes

from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists
from tests.support.endpoints import parse_mocker_endpoint
from tests.support.mocker_process import (
    find_free_port,
    start_mocker,
    stop_mocker,
    wait_port_ready,
    write_mocker_config,
)
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import assert_rt_unavailable, get_rt_point, try_get_rt_point


def _is_alive(api, ds_id: int) -> bool:
    page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", -1)) == ds_id:
            return bool(row.get("alive"))
    return False


def _setup_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id: str, start_mocker_now: bool = True) -> dict:
    """Create datasource + mocker + tag and return context."""
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, f"{case_id}-ds")
    tag_name = unique_name(settings.test_prefix, f"{case_id}-tag")

    tmp_dir = tmp_path_factory.mktemp(f"mocker_{case_id.lower()}")
    cfg_path = write_mocker_config(tmp_dir, port)
    mocker = None
    if start_mocker_now:
        mocker = start_mocker(cfg_path, port, host=parsed.host)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))

    if start_mocker_now:
        wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=60.0)

    tag_data = add_tag(
        api, tag_name=tag_name, data_type=DataTypes["INT"],
        tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
        tag_base_name="2_smoke_change_1",
    )
    tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

    if start_mocker_now:
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
    }


def _teardown(api, ctx: dict) -> None:
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


def _wait_qtq_valid(api, ds_id: int, tag_name: str, timeout: float = 30.0) -> dict:
    """Poll query_tags_with_quality until quality is non-zero and return the record."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qwq = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
        for r in ((qwq.get("tagInfoList") or {}).get("records") or []):
            if r.get("tagName") == tag_name and r.get("quality") not in (None, 0):
                return r
        time.sleep(2.0)
    return {}


def _wait_for_alive_true(api, ds_id: int, timeout: float = 60.0) -> None:
    wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=timeout)


def _wait_for_alive_false(api, ds_id: int, timeout: float = 60.0) -> None:
    wait_until(f"ds_offline:{ds_id}", lambda: not _is_alive(api, ds_id), timeout=timeout)


@pytest.mark.case(
    id="UA-2-1-001",
    chapter="UA-2-1",
    title="位号类型_一次位号新增",
    preconditions=[
        "数据源 alive=true；存在匹配的 *_r_* 节点",
    ],
    steps=[
        "使用 tagType=1 add_tag",
        "查询 tag 配置确认 tagType=1",
        "等待并读取 RT 与 quality",
        "queryWithQuality 确认值一致",
    ],
    expected=[
        "新增成功",
        "tagType 精确为 1",
        "配置字段与请求一致",
        "RT 可读取且 quality 有效",
        "RT 与源端值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_tag_type_read_only(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _setup_ctx(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-001")
    try:
        page = list_tags(api, page=1, page_size=50, data={"tagName": ctx["tag_name"]})
        records = page.get("records") or []
        match = [r for r in records if r.get("tagName") == ctx["tag_name"]]
        assert len(match) == 1, f"expected 1 tag record, got {len(match)}"
        rec = match[0]
        assert int(rec.get("tagType", -1)) == TagTypes["一次位号"], (
            f"tagType should be {TagTypes['一次位号']}, got {rec.get('tagType')}"
        )
        assert int(rec.get("dsId", -1)) == ctx["ds_id"], "dsId mismatch"
        assert rec.get("onlyRead") is True or str(rec.get("onlyRead")).lower() == "true"

        pt = get_rt_point(api, ctx["tag_name"])
        assert pt.get("tagValue") is not None, "RT value should not be None"
        assert pt.get("quality", 0) != 0, "quality should be non-zero"

        qr = _wait_qtq_valid(api, ctx["ds_id"], ctx["tag_name"], timeout=30.0)
        assert qr.get("tagValue") is not None, (
            f"queryWithQuality tagValue should not be None"
        )
        assert qr.get("quality") not in (None, 0), (
            f"queryWithQuality quality should be valid, got {qr.get('quality')}"
        )
    finally:
        _teardown(api, ctx)


@pytest.mark.case(
    id="UA-2-1-002",
    chapter="UA-2-1",
    title="数据源_已组态运行",
    preconditions=[
        "数据源已创建并启用；Mock 运行；alive=true",
    ],
    steps=[
        "新增读取位号",
        "查询配置",
        "等待并读取实时值",
    ],
    expected=[
        "add_tag 成功",
        "位号配置字段正确",
        "getRTValue 与 queryWithQuality 均返回有效值",
        "两入口值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ds_running(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _setup_ctx(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-002")
    try:
        page = list_tags(api, page=1, page_size=50, data={"tagName": ctx["tag_name"]})
        records = page.get("records") or []
        match = [r for r in records if r.get("tagName") == ctx["tag_name"]]
        assert len(match) == 1
        rec = match[0]
        assert int(rec.get("dsId", -1)) == ctx["ds_id"]

        pt = get_rt_point(api, ctx["tag_name"])
        assert pt.get("tagValue") is not None
        assert pt.get("quality", 0) != 0

        qr = _wait_qtq_valid(api, ctx["ds_id"], ctx["tag_name"], timeout=30.0)
        assert qr.get("tagValue") is not None
        assert qr.get("quality") not in (None, 0)
    finally:
        _teardown(api, ctx)


@pytest.mark.case(
    id="UA-2-1-003",
    chapter="UA-2-1",
    title="数据源_未组态",
    preconditions=[
        "TPT 中不存在目标 dsId",
    ],
    steps=[
        "使用不存在的 dsId 调用 add_tag",
        "按 tagName 查询",
    ],
    expected=[
        "请求被拒绝",
        "返回明确错误",
        "系统中不存在该位号",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_nonexistent_ds(api, settings, mocker_endpoint):
    bad_tag_name = unique_name(settings.test_prefix, "UA-2-1-003-nonexistent")
    bad_ds_id = 99999
    page = list_ds_info(api, page=1, page_size=50, data={"id": bad_ds_id})
    records = page.get("records") or []
    exists = any(int(r.get("id", -1)) == bad_ds_id for r in records)
    if exists:
        bad_ds_id = 999999
        page2 = list_ds_info(api, page=1, page_size=50, data={"id": bad_ds_id})
        records2 = page2.get("records") or []
        exists = any(int(r.get("id", -1)) == bad_ds_id for r in records2)
    assert not exists, f"ds_id {bad_ds_id} already exists, cannot test nonexistent scenario"
    try:
        with pytest.raises(TptAPIError) as exc_info:
            add_tag(api, tag_name=bad_tag_name, data_type=DataTypes["INT"],
                    tag_type=TagTypes["一次位号"], ds_id=bad_ds_id, only_read=True,
                    tag_base_name="2_smoke_change_1")
        err_msg = (exc_info.value.msg or "").lower()
        assert err_msg, "error message should not be empty"
        page3 = list_tags(api, page=1, page_size=50, data={"tagName": bad_tag_name})
        remaining = [r for r in (page3.get("records") or []) if r.get("tagName") == bad_tag_name]
        assert len(remaining) == 0, (
            f"tag {bad_tag_name} should not exist after rejected add"
        )
    finally:
        pass


@pytest.mark.case(
    id="UA-2-1-004",
    chapter="UA-2-1",
    title="数据源_组态未启服务",
    preconditions=[
        "数据源已创建并启用；Mock 未运行；alive=false",
    ],
    steps=[
        "新增读取位号",
        "查询配置",
        "查询 RT 与 quality",
    ],
    expected=[
        "位号配置创建成功",
        "配置字段正确",
        "RT 无有效采集值",
        "queryWithQuality quality=0",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ds_enabled_mocker_stopped(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _setup_ctx(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-004", start_mocker_now=False)
    try:
        _wait_for_alive_false(api, ctx["ds_id"], timeout=60.0)

        page = list_tags(api, page=1, page_size=50, data={"tagName": ctx["tag_name"]})
        records = page.get("records") or []
        match = [r for r in records if r.get("tagName") == ctx["tag_name"]]
        assert len(match) == 1, f"tag config should exist: {len(match)}"
        rec = match[0]
        assert int(rec.get("dsId", -1)) == ctx["ds_id"]

        assert_rt_unavailable(api, ctx["tag_name"], timeout=10.0)

        qwq = query_tags_with_quality(api, ds_id=ctx["ds_id"], tag_name=ctx["tag_name"])
        qrecs = (qwq.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == ctx["tag_name"]]
        assert len(qmatch) == 1, "queryWithQuality should return the tag"
        qval = qmatch[0].get("quality")
        assert qval is None or qval == 0, (
            f"quality should be None/0 when mocker is offline, got {qval!r}"
        )
    finally:
        _teardown(api, ctx)


@pytest.mark.case(
    id="UA-2-1-005",
    chapter="UA-2-1",
    title="数据源_未启服务后恢复",
    preconditions=[
        "数据源已创建并启用；Mock 初始未运行",
    ],
    steps=[
        "新增位号并确认 offline",
        "同端口启动 Mock",
        "等待 alive=true",
        "连续读取两次 RT",
        "读取 quality",
    ],
    expected=[
        "不需要重新新增位号",
        "数据源恢复 alive=true",
        "RT 开始更新",
        "quality 从不可用恢复为有效值",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ds_offline_then_start_mocker(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _setup_ctx(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-005", start_mocker_now=False)
    try:
        _wait_for_alive_false(api, ctx["ds_id"], timeout=60.0)
        assert_rt_unavailable(api, ctx["tag_name"], timeout=10.0)

        ctx["mocker"] = start_mocker(ctx["cfg_path"], ctx["port"], host=ctx["host"])

        _wait_for_alive_true(api, ctx["ds_id"], timeout=120.0)

        def _has_rt():
            pt = get_rt_point(api, ctx["tag_name"])
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt_ok:{ctx['tag_name']}", _has_rt, timeout=120.0)

        pt1 = get_rt_point(api, ctx["tag_name"])
        assert pt1.get("tagValue") is not None
        assert pt1.get("quality", 0) != 0

        time.sleep(2)
        pt2 = get_rt_point(api, ctx["tag_name"])
        assert pt2.get("tagValue") is not None
        assert pt2.get("quality", 0) != 0
        assert pt1.get("tagValue") != pt2.get("tagValue"), (
            "RT value should change after mocker starts"
        )
    finally:
        _teardown(api, ctx)


@pytest.mark.case(
    id="UA-2-1-006",
    chapter="UA-2-1",
    title="数据源_组态已禁用",
    preconditions=[
        "数据源已创建但禁用；Mock 正常运行",
    ],
    steps=[
        "新增读取位号",
        "查询配置",
        "查询 RT 与 quality",
    ],
    expected=[
        "位号配置创建成功",
        "RT 无有效采集值",
        "queryWithQuality quality=0",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ds_disabled(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, "UA-2-1-006-ds")
    tag_name = unique_name(settings.test_prefix, "UA-2-1-006-tag")

    tmp_dir = tmp_path_factory.mktemp("mocker_ua_2_1_006")
    cfg_path = write_mocker_config(tmp_dir, port)
    mocker = start_mocker(cfg_path, port, host=parsed.host)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    change_ds_state(api, ds_id, False)
    try:
        tag_data = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["INT"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name="2_smoke_change_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

        page = list_tags(api, page=1, page_size=50, data={"tagName": tag_name})
        records = page.get("records") or []
        match = [r for r in records if r.get("tagName") == tag_name]
        assert len(match) == 1

        assert_rt_unavailable(api, tag_name, timeout=10.0)

        qwq = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
        qrecs = (qwq.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == tag_name]
        assert len(qmatch) == 1
        qval = qmatch[0].get("quality")
        assert qval is None or qval == 0, (
            f"quality should be None/0 when DS disabled, got {qval!r}"
        )
    finally:
        delete_tag_if_exists(api, tag_id, tag_name)
        try:
            change_ds_state(api, ds_id, False)
        except Exception:
            pass
        delete_datasource_if_exists(api, ds_id, ds_name)
        if mocker:
            stop_mocker(mocker)


@pytest.mark.case(
    id="UA-2-1-007",
    chapter="UA-2-1",
    title="数据源_禁用后启用",
    preconditions=[
        "数据源禁用；位号已存在",
    ],
    steps=[
        "启用数据源",
        "等待 alive=true",
        "连续读取两次 RT",
    ],
    expected=[
        "不需要重新新增位号",
        "RT 开始更新",
        "quality 恢复为有效值",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ds_disabled_then_enable(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, "UA-2-1-007-ds")
    tag_name = unique_name(settings.test_prefix, "UA-2-1-007-tag")

    tmp_dir = tmp_path_factory.mktemp("mocker_ua_2_1_007")
    cfg_path = write_mocker_config(tmp_dir, port)
    mocker = start_mocker(cfg_path, port, host=parsed.host)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    change_ds_state(api, ds_id, False)
    try:
        tag_data = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["INT"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name="2_smoke_change_1",
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

        assert_rt_unavailable(api, tag_name, timeout=10.0)

        change_ds_state(api, ds_id, True)

        _wait_for_alive_true(api, ds_id, timeout=120.0)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt_ok:{tag_name}", _has_rt, timeout=120.0)

        pt1 = get_rt_point(api, tag_name)
        assert pt1.get("tagValue") is not None
        assert pt1.get("quality", 0) != 0

        time.sleep(2)
        pt2 = get_rt_point(api, tag_name)
        assert pt2.get("tagValue") is not None
        assert pt2.get("quality", 0) != 0
        assert pt1.get("tagValue") != pt2.get("tagValue"), (
            "RT value should change after DS is enabled"
        )
    finally:
        delete_tag_if_exists(api, tag_id, tag_name)
        try:
            change_ds_state(api, ds_id, False)
        except Exception:
            pass
        delete_datasource_if_exists(api, ds_id, ds_name)
        if mocker:
            stop_mocker(mocker)
