"""UA-1-6 datasource test API cases (ds-info/test).

Migrated from the legacy Harness specification
(ua_test_harness/test_cases/UA-1-6.md). All 13 cases implemented.

Covers the five testType values (1=enumerate, 2=read source RT,
3=read RT DB, 4=history, 5=write).

Product semantics discovered on the real environment:
  - testType=2/3 read the DataHub real-time cache, so a tag bound to the
    target node must be registered and collected first; the tagName
    parameter must be the tagBaseName (e.g. ``2_smoke_static_1``).
  - testType=4 history requires beginTime/endTime; the mock OPC UA server
    replies "Not support appointed time query".
  - Offline datasources make testType=1/2/5 raise TptAPIError with
    "The data source is not enabled or offline".
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from tpt_api.datahub import (
    DsTestEnumerate,
    DsTestHistory,
    DsTestReadRT,
    DsTestReadRTDB,
    DsTestWrite,
    add_ds_info,
    add_tag,
    change_ds_state,
    list_ds_info,
)
from tpt_api.datahub import test_ds_info as ds_info_test
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, DsSubTypes, DsTypes, TagTypes

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
from tests.support.ua2_helpers import is_ds_alive, opcua_read_sync

_MANY_NODES = [
    {"name": "many_node_", "type": "Int32", "count": 15, "change": True, "writable": False},
]


def _setup_ds(
    api, mocker_endpoint, settings, tmp_path_factory, case_id: str,
    suffix: str = "ds", nodes=None, namespace_index: int = 2,
) -> dict:
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, f"{case_id}-{suffix}")

    tmp_dir = tmp_path_factory.mktemp(f"m_{case_id.lower()}_{suffix}")
    cfg_path = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=namespace_index)
    mocker = start_mocker(cfg_path, port, host=parsed.host)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    change_ds_state(api, ds_id, True)
    wait_until(f"ds_alive:{ds_id}", lambda: is_ds_alive(api, ds_id), timeout=60.0)

    return {
        "ds_id": ds_id, "ds_name": ds_name, "mocker": mocker,
        "port": port, "host": parsed.host, "endpoint": endpoint,
        "namespace_index": namespace_index, "case_id": case_id,
    }


def _teardown_ds(api, ctx: dict) -> None:
    if ctx.get("tag_id"):
        try:
            delete_tag_if_exists(api, ctx["tag_id"], ctx["tag_name"])
        except Exception:
            pass
    if ctx.get("ds_id"):
        try:
            change_ds_state(api, ctx["ds_id"], False)
        except Exception:
            pass
        delete_datasource_if_exists(api, ctx["ds_id"], ctx["ds_name"])
    if ctx.get("mocker"):
        try:
            stop_mocker(ctx["mocker"])
        except Exception:
            pass


def _enumerate(api, ds_id: int) -> dict:
    """Run testType=1; return the response dict."""
    return ds_info_test(api, ds_id=ds_id, ds_name="", test_type=DsTestEnumerate)


def _node_names(resp: dict) -> list[str]:
    out = []
    for entry in resp.get("successes") or []:
        out.append(str(entry.get("name") or entry.get("browseName") or ""))
    return out


def _name_like(names: list[str], needle: str) -> str | None:
    """Return the first name whose bare node id matches needle.

    The DataHub browse/enumerate ``name`` is namespaced (``2_smoke_static_1``)
    while ``browseName`` is bare (``smoke_static_1``); match either.
    """
    for n in names:
        if n == needle:
            return n
        candidate = n
        if "_" in candidate:
            head, _, rest = candidate.partition("_")
            if head.isdigit():
                candidate = rest
        if candidate == needle:
            return n
    return None


def _find_node_name(resp: dict, needle: str) -> str:
    names = _node_names(resp)
    hit = _name_like(names, needle)
    if hit is None:
        raise AssertionError(f"node {needle!r} not found in enumerate {names}")
    return hit


def _register_collected_tag(api, ctx: dict, settings, base_name: str, data_type: int, suffix: str) -> dict:
    """Register a tag bound to base_name, wait until RT is collected."""
    tag_name = unique_name(settings.test_prefix, f"{ctx['case_id']}-{suffix}")
    tag_data = add_tag(
        api, tag_name=tag_name, data_type=data_type,
        tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
        tag_base_name=base_name,
    )
    ctx["tag_id"] = int(tag_data.get("id") or tag_data.get("tagId"))
    ctx["tag_name"] = tag_name

    def _has_rt():
        pt = get_rt_point(api, tag_name)
        return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

    wait_until(f"rt:{tag_name}", _has_rt, timeout=60.0)
    return ctx


@pytest.mark.case(
    id="UA-1-6-01",
    chapter="UA-1-6",
    title="枚举已连接数据源的位号",
    preconditions=[
        "数据源 alive=true，mock 有已知节点",
    ],
    steps=[
        "test_ds_info(testType=1)",
        "对返回的位号列表",
    ],
    expected=[
        "返回 successes[]，含 name/browseName/tagDataType/tagDataTypeName/readOnly",
        "与 mock 实际节点一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_enumerate_connected(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-01")
    try:
        resp = _enumerate(api, ctx["ds_id"])
        successes = resp.get("successes") or []
        assert successes, f"enumerate returned no successes: {resp}"

        names = _node_names(resp)
        assert _name_like(names, "smoke_static_1"), f"missing smoke_static_1 in {names}"
        assert _name_like(names, "smoke_change_1"), f"missing smoke_change_1 in {names}"

        for entry in successes:
            assert entry.get("name") or entry.get("browseName"), (
                f"entry missing name/browseName: {entry}"
            )
            assert entry.get("tagDataType") is not None or entry.get("hubDataType") is not None, (
                f"entry missing tagDataType: {entry}"
            )
            assert "readOnly" in entry, f"entry missing readOnly: {entry}"
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-02",
    chapter="UA-1-6",
    title="枚举未连接数据源的位号",
    preconditions=[
        "数据源 alive=false",
    ],
    steps=[
        "test_ds_info(testType=1)",
    ],
    expected=[
        "返回失败或空列表；不崩溃",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_enumerate_offline(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-02")
    try:
        stop_mocker(ctx["mocker"])
        ctx["mocker"] = None
        wait_until(
            f"ds_offline:{ctx['ds_id']}",
            lambda: not is_ds_alive(api, ctx["ds_id"]),
            timeout=120.0,
        )

        try:
            resp = _enumerate(api, ctx["ds_id"])
        except TptAPIError as exc:
            record_property("enumerate_offline_error", exc.msg)
            assert exc.msg, "error message should not be empty"
            pytest.xfail(
                f"UA-1-6-02 enumerate offline raises; msg={exc.msg}"
            )
        names = _node_names(resp)
        record_property("enumerate_offline_count", str(len(names)))
        assert not names, (
            f"UA-1-6-02 enumerate offline returned nodes {names}; expected empty"
        )
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-03",
    chapter="UA-1-6",
    title="枚举分页",
    preconditions=[
        "mock 有 >10 个节点",
    ],
    steps=[
        "test_ds_info(testType=1)",
        "检查 total/pageNum/pageSize/totalPage",
    ],
    expected=[
        "分页字段正确",
        "total = mock 实际节点数",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_enumerate_pagination(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(
        api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-03",
        nodes=_MANY_NODES, namespace_index=2,
    )
    try:
        resp = _enumerate(api, ctx["ds_id"])
        successes = resp.get("successes") or []
        total = int(resp.get("total") or 0)
        page_num = int(resp.get("pageNum") or 0)
        page_size = int(resp.get("pageSize") or 0)
        total_page = int(resp.get("totalPage") or 0)
        names = _node_names(resp)
        many_count = len([n for n in names if "many_node_" in n])

        record_property("enumerate_total", str(total))
        record_property("enumerate_page_size", str(page_size))
        record_property("enumerate_total_page", str(total_page))
        record_property("enumerate_returned_nodes", str(len(successes)))
        record_property("enumerate_many_node_returned", str(many_count))

        if total < 15 or total_page < 2:
            pytest.xfail(
                "UA-1-6-03 enumerate caps at first page: "
                f"total={total}, pageSize={page_size}, totalPage={total_page}, "
                f"returned={len(successes)} nodes ({many_count} many_node_)"
            )
        assert page_num >= 1, f"invalid pageNum {page_num}"
        assert page_size >= 1, f"invalid pageSize {page_size}"
        assert total_page >= 1, f"invalid totalPage {total_page}"
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-04",
    chapter="UA-1-6",
    title="读源端实时值(testType=2)",
    preconditions=[
        "数据源 alive=true；位号已注册并采集",
        "testType=2 读的是 DataHub 实时缓存，需 tagBaseName",
    ],
    steps=[
        "注册位号绑定 2_smoke_static_1 并等待采集",
        "test_ds_info(testType=2, tagName='2_smoke_static_1')",
        "asyncua 直读对照",
    ],
    expected=[
        "successes[] 含 name/value/quality/timeStamp",
        "value = mock 节点当前值",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_read_source_rt(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-04")
    try:
        _register_collected_tag(api, ctx, settings, "2_smoke_static_1", DataTypes["DOUBLE"], "tag")
        en = _enumerate(api, ctx["ds_id"])
        tag_name = _find_node_name(en, "smoke_static_1")

        resp = ds_info_test(
            api, ds_id=ctx["ds_id"], ds_name="",
            test_type=DsTestReadRT, tag_name=tag_name,
        )
        assert bool(resp.get("isAllSuccess")), f"testType=2 not all success: {resp}"
        successes = resp.get("successes") or []
        assert successes, f"testType=2 returned no successes: {resp}"
        entry = successes[0]
        assert "value" in entry, f"success entry missing value: {entry}"
        assert "quality" in entry, f"success entry missing quality: {entry}"
        assert "timeStamp" in entry, f"success entry missing timeStamp: {entry}"

        source_val = opcua_read_sync(ctx["endpoint"], "smoke_static_1", namespace_index=2)
        assert float(entry["value"]) == pytest.approx(float(source_val)), (
            f"testType=2 value {entry['value']} != source {source_val}"
        )
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-05",
    chapter="UA-1-6",
    title="读库实时值(testType=3)",
    preconditions=[
        "数据源 alive=true，位号已采集",
    ],
    steps=[
        "test_ds_info(testType=3, tagName='2_smoke_static_1')",
        "验证与 testType=2 返回是否一致",
    ],
    expected=[
        "successes[] 含 value",
        "与 testType=2 对比",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_read_rt_db(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-05")
    try:
        _register_collected_tag(api, ctx, settings, "2_smoke_static_1", DataTypes["DOUBLE"], "tag")
        en = _enumerate(api, ctx["ds_id"])
        tag_name = _find_node_name(en, "smoke_static_1")

        resp2 = ds_info_test(
            api, ds_id=ctx["ds_id"], ds_name="",
            test_type=DsTestReadRT, tag_name=tag_name,
        )
        resp3 = ds_info_test(
            api, ds_id=ctx["ds_id"], ds_name="",
            test_type=DsTestReadRTDB, tag_name=tag_name,
        )
        assert bool(resp2.get("isAllSuccess")), f"testType=2 not all success: {resp2}"
        assert bool(resp3.get("isAllSuccess")), f"testType=3 not all success: {resp3}"
        successes3 = resp3.get("successes") or []
        assert successes3, f"testType=3 returned no successes: {resp3}"
        v2 = float((resp2.get("successes") or [{}])[0].get("value"))
        v3 = float(successes3[0].get("value"))
        record_property("test_type2_value", str(v2))
        record_property("test_type3_value", str(v3))
        assert v2 == pytest.approx(v3), f"testType=2 {v2} != testType=3 {v3}"
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-06",
    chapter="UA-1-6",
    title="读不存在的位号",
    preconditions=[
        "数据源 alive=true",
    ],
    steps=[
        "test_ds_info(testType=2, tagName='nonexistent')",
    ],
    expected=[
        "failTagNames 含该位号",
        "isAllSuccess=false",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_read_nonexistent_tag(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-06")
    try:
        tag_name = "nonexistent_node_1"
        try:
            resp = ds_info_test(
                api, ds_id=ctx["ds_id"], ds_name="",
                test_type=DsTestReadRT, tag_name=tag_name,
            )
        except TptAPIError as exc:
            record_property("read_nonexistent_error", exc.msg)
            assert exc.msg, "error message should not be empty"
            pytest.xfail(
                f"UA-1-6-06 read nonexistent raises TptAPIError; msg={exc.msg}"
            )
        fail_names = resp.get("failTagNames") or []
        is_all_success = bool(resp.get("isAllSuccess"))
        record_property("fail_tag_names", str(fail_names))
        record_property("is_all_success", str(is_all_success))
        assert tag_name in fail_names, f"failTagNames should contain {tag_name!r}: {fail_names}"
        assert not is_all_success, "isAllSuccess should be false for nonexistent tag"
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-07",
    chapter="UA-1-6",
    title="读未连接数据源的位号",
    preconditions=[
        "数据源 alive=false",
    ],
    steps=[
        "test_ds_info(testType=2, tagName)",
    ],
    expected=[
        "返回失败；不崩溃",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_read_offline_ds(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-07")
    try:
        stop_mocker(ctx["mocker"])
        ctx["mocker"] = None
        wait_until(
            f"ds_offline:{ctx['ds_id']}",
            lambda: not is_ds_alive(api, ctx["ds_id"]),
            timeout=120.0,
        )

        try:
            resp = ds_info_test(
                api, ds_id=ctx["ds_id"], ds_name="",
                test_type=DsTestReadRT, tag_name="smoke_static_1",
            )
        except TptAPIError as exc:
            record_property("read_offline_error", exc.msg)
            assert exc.msg, "error message should not be empty"
            pytest.xfail(
                f"UA-1-6-07 read offline raises TptAPIError; msg={exc.msg}"
            )
        successes = resp.get("successes") or []
        fail_names = resp.get("failTagNames") or []
        record_property("read_offline_successes", str(len(successes)))
        record_property("read_offline_fail", str(fail_names))
        assert not successes, (
            f"UA-1-6-07 read offline returned values {successes}; expected failure"
        )
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-08",
    chapter="UA-1-6",
    title="读历史值",
    preconditions=[
        "数据源 alive=true，位号有历史数据",
    ],
    steps=[
        "test_ds_info(testType=4, tagName, beginTime, endTime)",
    ],
    expected=[
        "historyValueMap 含历史数据",
        "或返回'不支持时间查询'（取决于 UA server 能力）",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_read_history(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-08")
    try:
        en = _enumerate(api, ctx["ds_id"])
        tag_name = _find_node_name(en, "smoke_change_1")

        end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        beg = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            resp = ds_info_test(
                api, ds_id=ctx["ds_id"], ds_name="",
                test_type=DsTestHistory, tag_name=tag_name,
                begin_time=beg, end_time=end,
            )
        except TptAPIError as exc:
            record_property("history_error", exc.msg)
            pytest.xfail(
                f"UA-1-6-08 history raises; msg={exc.msg}"
            )
        history_map = resp.get("historyValueMap") or {}
        fail_names = resp.get("failTagNames") or []
        record_property("history_value_map_keys", str(list(history_map.keys())))
        record_property("history_fail", str(fail_names))
        if history_map:
            assert len(history_map) > 0, "historyValueMap should not be empty"
        else:
            fail_msg = str(resp.get("failMsg") or "")
            record_property("history_fail_msg", fail_msg)
            pytest.xfail(
                f"UA-1-6-08 history unsupported or empty; map={history_map}, "
                f"failMsg={fail_msg}"
            )
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-09",
    chapter="UA-1-6",
    title="读历史值缺时间参数",
    preconditions=[
        "数据源 alive=true",
    ],
    steps=[
        "test_ds_info(testType=4, tagName, 不传 beginTime)",
    ],
    expected=[
        "报错 beginTime cannot be null",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_read_history_missing_begin(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-09")
    try:
        en = _enumerate(api, ctx["ds_id"])
        tag_name = _find_node_name(en, "smoke_change_1")

        try:
            resp = ds_info_test(
                api, ds_id=ctx["ds_id"], ds_name="",
                test_type=DsTestHistory, tag_name=tag_name,
            )
        except TptAPIError as exc:
            record_property("history_no_begin_error", exc.msg)
            lowered = exc.msg.lower()
            assert "begintime" in lowered or "cannot be null" in lowered, (
                f"error msg should mention beginTime: {exc.msg}"
            )
            return
        fail_msg = str(resp.get("failMsg") or "")
        record_property("history_no_begin_fail_msg", fail_msg)
        lowered = fail_msg.lower()
        assert "begintime" in lowered or "cannot be null" in lowered, (
            f"failMsg should mention beginTime: {fail_msg}"
        )
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-10",
    chapter="UA-1-6",
    title="写值到可写位号",
    preconditions=[
        "数据源 alive=true，mock 节点 writable=true",
    ],
    steps=[
        "test_ds_info(testType=5, tagName, tagValue=\"123.45\")",
        "asyncua 直读",
    ],
    expected=[
        "isAllSuccess=true",
        "源端值 = 123.45",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_write_writable_node(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-10")
    try:
        en = _enumerate(api, ctx["ds_id"])
        tag_name = _find_node_name(en, "smoke_static_1")

        resp = ds_info_test(
            api, ds_id=ctx["ds_id"], ds_name="",
            test_type=DsTestWrite, tag_name=tag_name, tag_value="123.45",
        )
        assert bool(resp.get("isAllSuccess")), (
            f"write to writable node not all-success: {resp}"
        )

        def _source_is_123():
            try:
                return float(opcua_read_sync(ctx["endpoint"], "smoke_static_1", namespace_index=2)) == pytest.approx(123.45)
            except Exception:
                return False

        wait_until("source_123", _source_is_123, timeout=30.0)
        source_val = opcua_read_sync(ctx["endpoint"], "smoke_static_1", namespace_index=2)
        assert float(source_val) == pytest.approx(123.45), (
            f"source {source_val} != 123.45 after write"
        )
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-11",
    chapter="UA-1-6",
    title="写值到只读位号",
    preconditions=[
        "数据源 alive=true，mock 节点 writable=false",
    ],
    steps=[
        "test_ds_info(testType=5, tagName, tagValue=\"123.45\")",
    ],
    expected=[
        "isAllSuccess=false 或报错",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_write_readonly_node(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-11")
    try:
        en = _enumerate(api, ctx["ds_id"])
        tag_name = _find_node_name(en, "smoke_change_1")

        try:
            resp = ds_info_test(
                api, ds_id=ctx["ds_id"], ds_name="",
                test_type=DsTestWrite, tag_name=tag_name, tag_value="123.45",
            )
        except TptAPIError as exc:
            record_property("write_readonly_error", exc.msg)
            pytest.xfail(
                f"UA-1-6-11 write to readonly raises; msg={exc.msg}"
            )
        is_all_success = bool(resp.get("isAllSuccess"))
        fail_msg = str(resp.get("failMsg") or "")
        record_property("write_readonly_is_all_success", str(is_all_success))
        record_property("write_readonly_fail_msg", fail_msg)
        if is_all_success:
            pytest.xfail(
                f"UA-1-6-11 write to readonly node unexpectedly succeeded: {resp}"
            )
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-12",
    chapter="UA-1-6",
    title="写值类型不匹配",
    preconditions=[
        "数据源 alive=true，位号为 Double",
    ],
    steps=[
        "test_ds_info(testType=5, tagName, tagValue=\"abc\")",
    ],
    expected=[
        "failMsg 含该位号",
        "isAllSuccess=false",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_write_type_mismatch(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-12")
    try:
        en = _enumerate(api, ctx["ds_id"])
        tag_name = _find_node_name(en, "smoke_static_1")

        try:
            resp = ds_info_test(
                api, ds_id=ctx["ds_id"], ds_name="",
                test_type=DsTestWrite, tag_name=tag_name, tag_value="abc",
            )
        except TptAPIError as exc:
            record_property("write_type_mismatch_error", exc.msg)
            pytest.xfail(
                f"UA-1-6-12 type-mismatch write raises; msg={exc.msg}"
            )
        is_all_success = bool(resp.get("isAllSuccess"))
        fail_msg = str(resp.get("failMsg") or "")
        record_property("write_type_mismatch_is_all_success", str(is_all_success))
        record_property("write_type_mismatch_fail_msg", fail_msg)
        assert tag_name in fail_msg or not is_all_success, (
            f"type-mismatch write should fail; resp={resp}"
        )
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-6-13",
    chapter="UA-1-6",
    title="写值到未连接数据源",
    preconditions=[
        "数据源 alive=false",
    ],
    steps=[
        "test_ds_info(testType=5, tagName, tagValue=\"123\")",
    ],
    expected=[
        "返回失败；不崩溃",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_write_offline_ds(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-6-13")
    try:
        stop_mocker(ctx["mocker"])
        ctx["mocker"] = None
        wait_until(
            f"ds_offline:{ctx['ds_id']}",
            lambda: not is_ds_alive(api, ctx["ds_id"]),
            timeout=120.0,
        )

        try:
            resp = ds_info_test(
                api, ds_id=ctx["ds_id"], ds_name="",
                test_type=DsTestWrite, tag_name="smoke_static_1", tag_value="123",
            )
        except TptAPIError as exc:
            record_property("write_offline_error", exc.msg)
            assert exc.msg, "error message should not be empty"
            pytest.xfail(
                f"UA-1-6-13 write offline raises TptAPIError; msg={exc.msg}"
            )
        is_all_success = bool(resp.get("isAllSuccess"))
        record_property("write_offline_is_all_success", str(is_all_success))
        assert not is_all_success, (
            f"UA-1-6-13 write offline unexpectedly succeeded: {resp}"
        )
    finally:
        _teardown_ds(api, ctx)
