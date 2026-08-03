"""UA-1-4 multi-datasource isolation cases.

Migrated from the legacy Harness specification
(ua_test_harness/test_cases/UA-1-4.md). All six cases implemented.

Each test allocates two independent free ports, creates its own mocker /
datasource / tag pairs, and cleans up explicitly. Scenarios (stop,
restart, disable/enable) live in the test body, never in fixtures.
"""
from __future__ import annotations

import time

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    list_ds_info,
    write_tag_values,
)
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

_WRITABLE_TEST_NODE = [
    {"name": "test_wr_", "type": "Double", "default": 0.0, "writable": True, "change": False, "count": 1},
]


def _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, case_id: str, suffix: str, nodes=None, namespace_index: int = 2) -> dict:
    """Create one mocker + datasource (+ nothing else) on a free port."""
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, f"{case_id}-{suffix}-ds")

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
        "ds_id": ds_id, "ds_name": ds_name,
        "mocker": mocker, "port": port, "host": parsed.host,
        "endpoint": endpoint, "case_id": case_id, "suffix": suffix,
    }


def _register_change_tag(api, ctx: dict, settings, tag_suffix: str) -> dict:
    """Register a change=true tag bound to 2_smoke_change_1 on ctx's ds."""
    tag_name = unique_name(settings.test_prefix, f"{ctx['case_id']}-{ctx['suffix']}-{tag_suffix}")
    tag_data = add_tag(
        api, tag_name=tag_name, data_type=DataTypes["INT"],
        tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
        tag_base_name="2_smoke_change_1",
    )
    tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
    ctx["tag_id"] = tag_id
    ctx["tag_name"] = tag_name
    return ctx


def _wait_rt_changing(api, tag_name: str, timeout: float = 60.0) -> None:
    def _changing():
        try:
            v1 = get_rt_point(api, tag_name).get("tagValue")
        except TptAPIError:
            return False
        time.sleep(2)
        try:
            v2 = get_rt_point(api, tag_name).get("tagValue")
        except TptAPIError:
            return False
        return v1 is not None and v2 is not None and v1 != v2
    wait_until(f"rt_changing:{tag_name}", _changing, timeout=timeout)


def _teardown_single(api, ctx: dict) -> None:
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


def _teardown_pair(api, ctx_a: dict, ctx_b: dict) -> None:
    _teardown_single(api, ctx_a)
    _teardown_single(api, ctx_b)


def _restart_mocker(ctx: dict, tmp_path_factory) -> None:
    if ctx.get("mocker") is not None:
        stop_mocker(ctx["mocker"])
    ctx["mocker"] = None
    tmp_dir = tmp_path_factory.mktemp(f"restart_{ctx['case_id'].lower()}_{ctx['suffix']}")
    cfg_path = write_mocker_config(tmp_dir, ctx["port"])
    ctx["mocker"] = start_mocker(cfg_path, ctx["port"], host=ctx["host"])


def _source_value_matches(api, ctx: dict, tag_name: str, ns_idx: int, node_name: str) -> bool:
    """Return True if RT value falls within the source node's sample span.

    The change=true node is a 0-99 sawtooth (step 1 per cycle), so an
    exact single-read match is inherently racy. Collect several source
    samples over ~2s and require the RT value to lie inside the observed
    span (plus one step of slack on each side).
    """
    try:
        rt_val = float(get_rt_point(api, tag_name)["tagValue"])
    except (TptAPIError, TypeError, KeyError):
        return False
    samples = [
        float(opcua_read_sync(ctx["endpoint"], node_name, namespace_index=ns_idx))
        for _ in range(4)
    ]
    lo, hi = min(samples) - 1.0, max(samples) + 1.0
    return lo <= rt_val <= hi


@pytest.mark.case(
    id="UA-1-4-01",
    chapter="UA-1-4",
    title="两数据源各自正常采集",
    preconditions=[
        "mock-A、mock-B 均已启动，配置 change=true",
    ],
    steps=[
        "分别注册 ds-A、ds-B",
        "各注册位号",
        "等待采集",
        "各自 getRTValue 2 次确认值在变化",
    ],
    expected=[
        "两个 ds 均 alive=true",
        "各自位号 RT 值 = 各自 mock 节点当前值",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_two_sources_normal_collect(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-01", "a")
    ctx_b = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-01", "b")
    try:
        _register_change_tag(api, ctx_a, settings, "tag")
        _register_change_tag(api, ctx_b, settings, "tag")
        _wait_rt_changing(api, ctx_a["tag_name"])
        _wait_rt_changing(api, ctx_b["tag_name"])

        assert is_ds_alive(api, ctx_a["ds_id"]), "ds-A not alive"
        assert is_ds_alive(api, ctx_b["ds_id"]), "ds-B not alive"

        va = get_rt_point(api, ctx_a["tag_name"])
        vb = get_rt_point(api, ctx_b["tag_name"])
        assert va.get("tagValue") is not None, "ds-A tag has no RT value"
        assert vb.get("tagValue") is not None, "ds-B tag has no RT value"
        assert va.get("quality", 0) != 0, "ds-A tag quality is 0"
        assert vb.get("quality", 0) != 0, "ds-B tag quality is 0"

        wait_until(
            "rt_a_in_source_span",
            lambda: _source_value_matches(api, ctx_a, ctx_a["tag_name"], 2, "smoke_change_1"),
            timeout=30.0,
        )
        wait_until(
            "rt_b_in_source_span",
            lambda: _source_value_matches(api, ctx_b, ctx_b["tag_name"], 2, "smoke_change_1"),
            timeout=30.0,
        )
    finally:
        _teardown_pair(api, ctx_a, ctx_b)


@pytest.mark.case(
    id="UA-1-4-02",
    chapter="UA-1-4",
    title="一源断连不影响另一源",
    preconditions=[
        "UA-1-4-01 状态",
    ],
    steps=[
        "停止 mock-A",
        "等待 2s",
        "验证 ds-A 和 ds-B",
    ],
    expected=[
        "ds-A alive=false",
        "ds-B 不受影响、alive=true、值继续变化",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_one_source_disconnect_other_untouched(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-02", "a")
    ctx_b = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-02", "b")
    try:
        _register_change_tag(api, ctx_a, settings, "tag")
        _register_change_tag(api, ctx_b, settings, "tag")
        _wait_rt_changing(api, ctx_a["tag_name"])
        _wait_rt_changing(api, ctx_b["tag_name"])

        stop_mocker(ctx_a["mocker"])
        ctx_a["mocker"] = None

        wait_until(
            f"ds_a_offline:{ctx_a['ds_id']}",
            lambda: not is_ds_alive(api, ctx_a["ds_id"]),
            timeout=120.0,
        )
        time.sleep(2)
        assert not is_ds_alive(api, ctx_a["ds_id"]), "ds-A should be offline"

        assert is_ds_alive(api, ctx_b["ds_id"]), "ds-B should stay alive"
        _wait_rt_changing(api, ctx_b["tag_name"])
    finally:
        _teardown_pair(api, ctx_a, ctx_b)


@pytest.mark.case(
    id="UA-1-4-03",
    chapter="UA-1-4",
    title="一源恢复不影响另一源",
    preconditions=[
        "UA-1-4-02 后",
    ],
    steps=[
        "重启 mock-A",
        "等待重连",
        "验证 ds-A 和 ds-B",
    ],
    expected=[
        "ds-A 恢复 alive=true、采集恢复",
        "ds-B 全程不受影响",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_one_source_recover_other_untouched(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-03", "a")
    ctx_b = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-03", "b")
    try:
        _register_change_tag(api, ctx_a, settings, "tag")
        _register_change_tag(api, ctx_b, settings, "tag")
        _wait_rt_changing(api, ctx_a["tag_name"])
        _wait_rt_changing(api, ctx_b["tag_name"])

        stop_mocker(ctx_a["mocker"])
        ctx_a["mocker"] = None
        wait_until(
            f"ds_a_offline:{ctx_a['ds_id']}",
            lambda: not is_ds_alive(api, ctx_a["ds_id"]),
            timeout=120.0,
        )

        _restart_mocker(ctx_a, tmp_path_factory)
        wait_until(
            f"ds_a_alive:{ctx_a['ds_id']}",
            lambda: is_ds_alive(api, ctx_a["ds_id"]),
            timeout=120.0,
        )

        def _a_has_rt():
            pt = get_rt_point(api, ctx_a["tag_name"])
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt_a_recovered:{ctx_a['tag_name']}", _a_has_rt, timeout=120.0)
        assert is_ds_alive(api, ctx_a["ds_id"]), "ds-A should be alive after restart"

        assert is_ds_alive(api, ctx_b["ds_id"]), "ds-B should stay alive throughout"
        _wait_rt_changing(api, ctx_b["tag_name"])
    finally:
        _teardown_pair(api, ctx_a, ctx_b)


@pytest.mark.case(
    id="UA-1-4-04",
    chapter="UA-1-4",
    title="一源启停不影响另一源",
    preconditions=[
        "UA-1-4-01 状态",
    ],
    steps=[
        "禁用 ds-A",
        "验证 ds-B",
        "启用 ds-A",
        "验证 ds-B",
    ],
    expected=[
        "ds-B 全程 alive=true、值持续变化",
        "ds-A 启停对 ds-B 无影响",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_one_source_disable_enable_other_untouched(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-04", "a")
    ctx_b = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-04", "b")
    try:
        _register_change_tag(api, ctx_a, settings, "tag")
        _register_change_tag(api, ctx_b, settings, "tag")
        _wait_rt_changing(api, ctx_a["tag_name"])
        _wait_rt_changing(api, ctx_b["tag_name"])

        change_ds_state(api, ctx_a["ds_id"], False)
        wait_until(
            f"ds_a_offline:{ctx_a['ds_id']}",
            lambda: not is_ds_alive(api, ctx_a["ds_id"]),
            timeout=60.0,
        )
        assert is_ds_alive(api, ctx_b["ds_id"]), "ds-B should stay alive while ds-A disabled"
        _wait_rt_changing(api, ctx_b["tag_name"])

        change_ds_state(api, ctx_a["ds_id"], True)
        wait_until(
            f"ds_a_alive:{ctx_a['ds_id']}",
            lambda: is_ds_alive(api, ctx_a["ds_id"]),
            timeout=60.0,
        )
        assert is_ds_alive(api, ctx_b["ds_id"]), "ds-B should stay alive after ds-A re-enabled"
        _wait_rt_changing(api, ctx_b["tag_name"])
    finally:
        _teardown_pair(api, ctx_a, ctx_b)


@pytest.mark.case(
    id="UA-1-4-05",
    chapter="UA-1-4",
    title="不同数据源相同底层位号",
    preconditions=[
        "mock-A、mock-B 各有节点 ns=1, nodeid='test_wr_1'",
        "两位号均可写，值稳定（change=false）以便验证写入值不回写冲突",
    ],
    steps=[
        "ds-A 注册位号 tagName='tag_A'，tagBaseName='1_test_wr_1'",
        "ds-B 注册位号 tagName='tag_B'，tagBaseName='1_test_wr_1'",
        "等待采集",
        "各自 writeTagValues 写不同值",
        "各自 getRTValue",
    ],
    expected=[
        "两个位号都注册成功、各自独立采集",
        "各自 RT 值 = 各自写入值，互不串值",
        "不同数据源下相同 ns+nodeid 可以并存",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_same_underlying_node_two_sources(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = _setup_single_ds(
        api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-05", "a",
        nodes=_WRITABLE_TEST_NODE, namespace_index=1,
    )
    ctx_b = _setup_single_ds(
        api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-05", "b",
        nodes=_WRITABLE_TEST_NODE, namespace_index=1,
    )
    try:
        tag_a_name = unique_name(settings.test_prefix, "UA-1-4-05-tag_a")
        tag_b_name = unique_name(settings.test_prefix, "UA-1-4-05-tag_b")
        tag_a = add_tag(
            api, tag_name=tag_a_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx_a["ds_id"], only_read=False,
            tag_base_name="1_test_wr_1",
        )
        tag_a_id = int(tag_a.get("id") or tag_a.get("tagId"))
        tag_b = add_tag(
            api, tag_name=tag_b_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx_b["ds_id"], only_read=False,
            tag_base_name="1_test_wr_1",
        )
        tag_b_id = int(tag_b.get("id") or tag_b.get("tagId"))
        ctx_a["tag_id"], ctx_a["tag_name"] = tag_a_id, tag_a_name
        ctx_b["tag_id"], ctx_b["tag_name"] = tag_b_id, tag_b_name

        def _has_rt_a():
            pt = get_rt_point(api, tag_a_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        def _has_rt_b():
            pt = get_rt_point(api, tag_b_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt_a:{tag_a_name}", _has_rt_a, timeout=60.0)
        wait_until(f"rt_b:{tag_b_name}", _has_rt_b, timeout=60.0)

        write_tag_values(api, {tag_a_name: 111.0})
        write_tag_values(api, {tag_b_name: 222.0})

        def _rt_is(api, tag_name: str, expect: float):
            def check():
                try:
                    return float(get_rt_point(api, tag_name)["tagValue"]) == pytest.approx(expect)
                except (TptAPIError, TypeError, KeyError):
                    return False
            return check

        wait_until(f"rt_a_111:{tag_a_name}", _rt_is(api, tag_a_name, 111.0), timeout=30.0)
        wait_until(f"rt_b_222:{tag_b_name}", _rt_is(api, tag_b_name, 222.0), timeout=30.0)

        va = get_rt_point(api, tag_a_name)
        vb = get_rt_point(api, tag_b_name)
        assert float(va["tagValue"]) == pytest.approx(111.0), (
            f"tag_A RT {va['tagValue']} != 111 (cross-talk?)"
        )
        assert float(vb["tagValue"]) == pytest.approx(222.0), (
            f"tag_B RT {vb['tagValue']} != 222 (cross-talk?)"
        )

        src_a = opcua_read_sync(ctx_a["endpoint"], "test_wr_1", namespace_index=1)
        src_b = opcua_read_sync(ctx_b["endpoint"], "test_wr_1", namespace_index=1)
        assert float(src_a) == pytest.approx(111.0), f"mock-A source {src_a} != 111"
        assert float(src_b) == pytest.approx(222.0), f"mock-B source {src_b} != 222"
    finally:
        _teardown_pair(api, ctx_a, ctx_b)


@pytest.mark.case(
    id="UA-1-4-06",
    chapter="UA-1-4",
    title="系统位号名重复拒绝",
    preconditions=[
        "已注册 tagName='tag_A'",
    ],
    steps=[
        "在 ds-B 下注册 tagName='tag_A'（与已有重名）",
    ],
    expected=[
        "被拒绝，报错位号名重复",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_duplicate_system_tag_name_rejected(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-06", "a")
    ctx_b = _setup_single_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-4-06", "b")
    try:
        tag_a_name = unique_name(settings.test_prefix, "UA-1-4-06-tag")
        tag_a = add_tag(
            api, tag_name=tag_a_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx_a["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        ctx_a["tag_id"] = int(tag_a.get("id") or tag_a.get("tagId"))
        ctx_a["tag_name"] = tag_a_name

        with pytest.raises(TptAPIError) as exc_info:
            add_tag(
                api, tag_name=tag_a_name, data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"], ds_id=ctx_b["ds_id"], only_read=True,
                tag_base_name="2_smoke_static_1",
            )
        assert exc_info.value.msg, "duplicate-name error message should not be empty"
    finally:
        _teardown_pair(api, ctx_a, ctx_b)
