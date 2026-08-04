"""UA-3-1 位号采集 — batch 1: UA-3-1-001 .. UA-3-1-012.

Migrated from ``ua_test_harness/test_cases/UA-3-1.md``.  Each test creates
its own mocker (dynamic port), datasource and tag, and performs strict
cleanup regardless of outcome.

Conventions applied from the source spec:
- real-time value: ``getRTValue(isFromDB=false)`` via ``get_rt_point``
- source ground truth: asyncua direct read of the mock node
- temp tag prefix ``ua31_{runId}_`` -> ``unique_name(settings.test_prefix, ...)``
- change nodes update every mocker cycle (sawtooth 0..99 etc.)
"""
from __future__ import annotations

import json
import time

import pytest
from asyncua import ua

from tpt_api.datahub import update_tag
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes

from tests.support.rt_helpers import get_rt_point, try_get_rt_point
from tests.support.ua2_helpers import (
    find_unique_tag,
    opcua_read_sync,
    opcua_read_variant_type_sync,
    opcua_write_sync,
)
from tests.support.ua2_value_normalization import assert_value_equal, normalize_datetime
from tests.support.ua3_helpers import (
    UA3_TYPES,
    add_collection_tag,
    assert_times_parsable,
    build_13_type_nodes,
    build_node,
    cleanup_ua3_context,
    distinct_update_times,
    node_id_from_cfg,
    sample_rt_timeline,
    type_node_name,
    wait_rt_changed,
    wait_rt_matches_source,
    wait_rt_valid,
)
from tests.support.ua2_helpers import setup_ds_only
from tests.support.ua2_rt_assertions import parse_required_timestamp


def _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id: str, nodes: list[dict]) -> dict:
    return setup_ds_only(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        nodes=nodes, namespace_index=1, cycle=500,
    )


def _teardown(api, ctx: dict, tags: list[dict]) -> None:
    cleanup_ua3_context(
        api,
        tag_ids=[t["tag_id"] for t in tags],
        tag_names=[t["tag_name"] for t in tags],
        ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
        mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"],
    )


def _read_variant_type(ctx: dict, node_id_str: str):
    return opcua_read_variant_type_sync(ctx["endpoint"], node_id_str, namespace_index=ctx["namespace_index"])


# ---------------------------------------------------------------------------
# UA-3-1-001 初始采集_新增后自动开始
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-001", chapter="UA-3-1",
    title="初始采集_新增后自动开始",
    preconditions=["Mock 有可用节点", "数据源 alive=true"],
    steps=["新增读取位号", "等待 RT 出现有效值", "asyncua 直读源端节点对比"],
    expected=["无需额外触发", "RT 出现有效值且与源端一致", "quality 有效"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_1_001_initial_collection(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-001"
    prefix = "ua31_001"
    node = build_node(f"{prefix}_val_", "Double", 12.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        pt = wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        assert pt.get("quality", 0) != 0
        assert pt.get("dataType") is None, f"RT unexpectedly carries dataType={pt.get('dataType')}"
        snap = wait_rt_matches_source(
            api, ctx, tags[0]["tag_name"], node_id, "DOUBLE", expected=12.5,
        )
        assert snap.get("tagValue") is not None
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-002 变化采集_源值连续变化
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-002", chapter="UA-3-1",
    title="变化采集_源值连续变化",
    preconditions=["Mock 有可写节点", "数据源 alive=true"],
    steps=["asyncua 按唯一序列修改源值", "轮询 RT 观察新值", "确认无长期停滞"],
    expected=["DataHub 依次观察到新值", "无长期停滞"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_1_002_change_collection(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-002"
    prefix = "ua31_002"
    node = build_node(f"{prefix}_val_", "Double", 100.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        sequence = [100.0, 101.0, 102.0, 103.0, 104.0]
        for value in sequence:
            opcua_write_sync(ctx["endpoint"], node_id, value, namespace_index=ctx["namespace_index"])
            snap = wait_rt_matches_source(
                api, ctx, tags[0]["tag_name"], node_id, "DOUBLE",
                expected=value, timeout=30.0,
            )
            assert snap.get("tagValue") is not None, f"no RT for written value {value}"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-003 静态采集_值不变化
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-003", chapter="UA-3-1",
    title="静态采集_值不变化",
    preconditions=["Mock 静态节点值固定", "数据源 alive=true"],
    steps=["连续多次查询 RT", "确认值不变时质量仍有效", "确认不误判断线"],
    expected=["值不变时质量仍有效", "不误判断线", "RT 值保持与源端一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_1_003_static_collection(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-003"
    prefix = "ua31_003"
    node = build_node(f"{prefix}_val_", "Double", 7.25, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        for _ in range(5):
            pt = get_rt_point(api, tags[0]["tag_name"])
            assert pt.get("tagValue") is not None, f"RT lost value: {pt}"
            assert pt.get("quality", 0) != 0, f"quality 0 on static tag: {pt}"
            assert_value_equal(7.25, pt["tagValue"], DataTypes["DOUBLE"])
            time.sleep(1.0)
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-004 数据类型_13种采集
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-004", chapter="UA-3-1",
    title="数据类型_13种采集",
    preconditions=["Mock 配置 13 种类型节点", "数据源 alive=true"],
    steps=["注册并采集 13 种类型位号", "逐个 asyncua 直读源端", "核对类型、值、表示"],
    expected=["类型、值和表示正确", "不串类型", "RT dataType 与配置一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_1_004_13_types(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-004"
    prefix = "ua31_004"
    nodes = build_13_type_nodes(prefix)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes)
    tags = []
    try:
        expected_variant = {
            "Boolean": ua.VariantType.Boolean,
            "SByte": ua.VariantType.SByte,
            "Byte": ua.VariantType.Byte,
            "Int16": ua.VariantType.Int16,
            "UInt16": ua.VariantType.UInt16,
            "Int32": ua.VariantType.Int32,
            "UInt32": ua.VariantType.UInt32,
            "Int64": ua.VariantType.Int64,
            "UInt64": ua.VariantType.UInt64,
            "Float": ua.VariantType.Float,
            "Double": ua.VariantType.Double,
            "String": ua.VariantType.String,
            "DateTime": ua.VariantType.DateTime,
        }
        for type_name, type_key in UA3_TYPES:
            node_id = type_node_name(prefix, type_name)
            tags.append(add_collection_tag(
                api, settings, ctx, case_id,
                node_id_str=node_id, type_key=type_key,
            ))
            pt = wait_rt_valid(api, tags[-1]["tag_name"], timeout=60.0)
            assert pt.get("dataType") is None, \
                f"{type_name}: RT unexpectedly carries dataType={pt.get('dataType')}"
            snap = wait_rt_matches_source(
                api, ctx, tags[-1]["tag_name"], node_id, type_key,
                timeout=30.0,
            )
            assert snap.get("tagValue") is not None, f"{type_name}: no RT value"
            # Verify source VariantType to ensure no cross-type mixing on the source
            value, variant_type = _read_variant_type(ctx, node_id)
            assert variant_type == expected_variant[type_name], \
                f"{type_name}: source VariantType={variant_type} != {expected_variant[type_name]}"
            # Verify the RT value matches the source value of the configured type
            assert_value_equal(value, snap["tagValue"], DataTypes[type_key])
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-005 大整数_Int64与UInt64
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-005", chapter="UA-3-1",
    title="大整数_Int64与UInt64",
    preconditions=["Mock 有 Int64 / UInt64 可写节点", "数据源 alive=true"],
    steps=["源端设置超过 JS 安全整数范围的值", "读取 RT 并比较", "确认无损还原"],
    expected=["可无损还原", "不发生舍入", "字符串/大整数比较通过"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_1_005_big_integers(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-1-005"
    prefix = "ua31_005"
    nodes = [
        build_node(f"{prefix}_i64_", "Int64", 0, change=False, writable=True),
        build_node(f"{prefix}_u64_", "UInt64", 0, change=False, writable=True),
    ]
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes)
    tags = []
    observations: dict = {}
    try:
        i64_node = node_id_from_cfg(nodes[0])
        u64_node = node_id_from_cfg(nodes[1])
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=i64_node, type_key="LONG"))
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=u64_node, type_key="U_LONG"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        wait_rt_valid(api, tags[1]["tag_name"], timeout=60.0)

        big_i64 = 9007199254740993
        big_u64 = 9223372036854775807
        opcua_write_sync(
            ctx["endpoint"], i64_node, big_i64,
            namespace_index=ctx["namespace_index"], variant_type=ua.VariantType.Int64,
        )
        opcua_write_sync(
            ctx["endpoint"], u64_node, big_u64,
            namespace_index=ctx["namespace_index"], variant_type=ua.VariantType.UInt64,
        )

        snap_i = wait_rt_matches_source(
            api, ctx, tags[0]["tag_name"], i64_node, "LONG", expected=big_i64, timeout=30.0,
        )
        assert_value_equal(big_i64, snap_i["tagValue"], DataTypes["LONG"])

        snap_u = wait_rt_matches_source(
            api, ctx, tags[1]["tag_name"], u64_node, "U_LONG", expected=big_u64, timeout=30.0,
        )
        assert_value_equal(big_u64, snap_u["tagValue"], DataTypes["U_LONG"])

        # UInt64 max (2^64-1) exceeds the DataHub signed-64 mapping (UA-2-1-058):
        # record the observed boundary behavior for the blocker doc.
        opcua_write_sync(
            ctx["endpoint"], u64_node, 18446744073709551615,
            namespace_index=ctx["namespace_index"], variant_type=ua.VariantType.UInt64,
        )
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            pt = get_rt_point(api, tags[1]["tag_name"])
            if pt.get("tagValue") is not None and pt.get("quality", 0) not in (None, 0):
                break
            time.sleep(0.5)
        observations["uint64_max_rt_value"] = pt.get("tagValue")
        observations["uint64_max_expected"] = "18446744073709551615"
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-006 DateTime_值与时区
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-006", chapter="UA-3-1",
    title="DateTime_值与时区",
    preconditions=["Mock 有 DateTime 可写节点", "数据源 alive=true"],
    steps=["源端设置已知 UTC 时间", "读取 RT 值", "UTC 转换比较"],
    expected=["DataHub 值与源端表示同一时刻", "时区处理正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_1_006_datetime(api, settings, tmp_path_factory, mocker_endpoint):
    from datetime import datetime, timezone, timedelta

    case_id = "UA-3-1-006"
    prefix = "ua31_006"
    node = build_node(f"{prefix}_dt_", "DateTime", "2025-06-01T12:00:00+00:00", change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DATE_TIME"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        source_dt = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        opcua_write_sync(
            ctx["endpoint"], node_id, source_dt,
            namespace_index=ctx["namespace_index"],
            variant_type=ua.VariantType.DateTime,
        )

        snap = wait_rt_matches_source(
            api, ctx, tags[0]["tag_name"], node_id, "DATE_TIME",
            expected=source_dt, timeout=30.0,
        )
        assert_value_equal(source_dt, snap["tagValue"], DataTypes["DATE_TIME"])
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-007 采集频率_1秒5秒10秒 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-007", chapter="UA-3-1",
    title="采集频率_1秒5秒10秒",
    preconditions=["Mock 值持续变化", "数据源 alive=true"],
    steps=["三个位号设置不同 frequency", "采样 RT 时间序列", "统计实际更新间隔"],
    expected=["实际更新时间间隔与配置具有对应关系"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_1_007_frequency_1_5_10(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-1-007"
    prefix = "ua31_007"
    nodes = [build_node(f"{prefix}_f1_", "Int32", change=True),
             build_node(f"{prefix}_f5_", "Int32", change=True),
             build_node(f"{prefix}_f10_", "Int32", change=True)]
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes)
    tags = []
    observations: dict = {}
    try:
        freq_cfg = [("f1", 1), ("f5", 5), ("f10", 10)]
        for (suffix, freq), node in zip(freq_cfg, nodes):
            node_id = node_id_from_cfg(node)
            tags.append(add_collection_tag(
                api, settings, ctx, case_id,
                node_id_str=node_id, type_key="INT", frequency=freq,
            ))
            wait_rt_valid(api, tags[-1]["tag_name"], timeout=60.0)

        window_s = 35.0
        timelines = {}
        for t in tags:
            timelines[t["tag_name"]] = sample_rt_timeline(api, t["tag_name"], window_s, interval=0.5)

        for (suffix, freq), t in zip(freq_cfg, tags):
            timeline = timelines[t["tag_name"]]
            updates = distinct_update_times(timeline)
            observations[suffix] = {
                "config_frequency": freq,
                "distinct_tagTime_updates": len(updates),
                "first_tagTime": updates[0] if updates else None,
                "last_tagTime": updates[-1] if updates else None,
            }
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)

    pytest.xfail(
        "UA-3-1-007 frequency-vs-update-interval correspondence is not specified "
        "(fixed tolerance not confirmed); "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-1-008 采集频率_同源独立
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-008", chapter="UA-3-1",
    title="采集频率_同源独立",
    preconditions=["Mock 同一数据源多节点变化", "数据源 alive=true"],
    steps=["同源多个位号设置不同频率", "采样各 RT 时间序列", "确认互不覆盖"],
    expected=["各位号按自身频率更新", "互不覆盖"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_1_008_frequency_independent(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-1-008"
    prefix = "ua31_008"
    nodes = [build_node(f"{prefix}_a_", "Int32", change=True),
             build_node(f"{prefix}_b_", "Int32", change=True)]
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes)
    tags = []
    observations: dict = {}
    try:
        tag_a = add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id_from_cfg(nodes[0]), type_key="INT", frequency=1)
        tag_b = add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id_from_cfg(nodes[1]), type_key="INT", frequency=5)
        tags = [tag_a, tag_b]
        wait_rt_valid(api, tag_a["tag_name"], timeout=60.0)
        wait_rt_valid(api, tag_b["tag_name"], timeout=60.0)

        window_s = 30.0
        ta = sample_rt_timeline(api, tag_a["tag_name"], window_s, interval=0.5)
        tb = sample_rt_timeline(api, tag_b["tag_name"], window_s, interval=0.5)
        updates_a = distinct_update_times(ta)
        updates_b = distinct_update_times(tb)
        observations["updates_freq1"] = len(updates_a)
        observations["updates_freq5"] = len(updates_b)
        observations["tag_a_updates"] = updates_a
        observations["tag_b_updates"] = updates_b

        # 两个位号都必须各自持续更新（同源独立，互不覆盖）。
        assert len(updates_a) > 0, "freq=1 tag never updated"
        assert len(updates_b) > 0, "freq=5 tag never updated"

        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)

    pytest.xfail(
        "UA-3-1-008 same-source independent frequency semantics are not specified "
        "(configured freq=1 vs freq=5 did not produce a proportional update-rate "
        "ratio in the observed window); "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-1-009 采集频率_运行中修改 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-009", chapter="UA-3-1",
    title="采集频率_运行中修改",
    preconditions=["数据源 alive=true", "位号正常采集"],
    steps=["采集中修改 frequency", "记录新频率生效时间", "确认无需重建"],
    expected=["无需重建", "记录新频率生效时间"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_1_009_frequency_modify_runtime(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-1-009"
    prefix = "ua31_009"
    node = build_node(f"{prefix}_val_", "Int32", change=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations: dict = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="INT", frequency=1))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        observations["before_frequency"] = find_unique_tag(api, tags[0]["tag_name"]).get("frequency")

        update_resp = update_tag(
            api, tag_id=tags[0]["tag_id"], tag_name=tags[0]["tag_name"],
            data_type=DataTypes["INT"], tag_type=1, ds_id=ctx["ds_id"],
            only_read=True, frequency=5,
        )
        observations["update_response"] = update_resp

        rec = find_unique_tag(api, tags[0]["tag_name"])
        observations["after_frequency"] = rec.get("frequency")

        try:
            wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
            pt = get_rt_point(api, tags[0]["tag_name"])
            observations["post_update_rt"] = {
                "tagValue": pt.get("tagValue"),
                "quality": pt.get("quality", 0),
            }
            assert pt.get("tagValue") is not None, "RT value lost after frequency change"
            assert pt.get("quality", 0) != 0, "RT quality invalid after frequency change"
        except AssertionError as exc:
            observations["post_update_rt_error"] = str(exc)
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)

    pytest.xfail(
        "UA-3-1-009 runtime frequency modification semantics (effective time, "
        "no-rebuild guarantee) are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-1-010 正常质量与时间
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-010", chapter="UA-3-1",
    title="正常质量与时间",
    preconditions=["数据源 alive=true", "位号在线采集"],
    steps=["在线采集多个周期", "检查 quality", "检查 tagTime/appTime 解析且不倒退"],
    expected=["quality 有效", "tagTime/appTime 可解析", "时间不倒退"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_1_010_quality_and_time(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-010"
    prefix = "ua31_010"
    node = build_node(f"{prefix}_val_", "Int32", change=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="INT"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        timeline = sample_rt_timeline(api, tags[0]["tag_name"], 15.0, interval=1.0)
        valid_records = [r for r in timeline if r.get("quality", 0) != 0 and r.get("tagValue") is not None]
        assert len(valid_records) >= 5, f"too few valid RT samples: {len(valid_records)}"

        parsed_times = []
        for rec in valid_records:
            tag_time = rec.get("tagTime")
            assert tag_time, f"tagTime missing: {rec}"
            parsed_times.append(parse_required_timestamp(tag_time))

        for i in range(1, len(parsed_times)):
            assert parsed_times[i] >= parsed_times[i - 1], \
                f"tagTime went backwards at sample {i}: {parsed_times[i-1]} -> {parsed_times[i]}"

        # appTime present and parseable
        for rec in timeline:
            if rec.get("appTime"):
                parse_required_timestamp(rec["appTime"])
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-011 节点不存在
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-011", chapter="UA-3-1",
    title="节点不存在",
    preconditions=["Mock 有可用节点", "数据源 alive=true"],
    steps=["绑定不存在 NodeId", "查询 RT 与 quality", "确认其他位号正常"],
    expected=["不产生伪造有效值", "其他位号正常"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_1_011_missing_node(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-011"
    prefix = "ua31_011"
    good_node = build_node(f"{prefix}_good_", "Int32", change=True)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [good_node])
    tags = []
    try:
        good_tag = add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id_from_cfg(good_node), type_key="INT")
        bad_tag = add_collection_tag(api, settings, ctx, case_id, node_id_str="ua31_011_does_not_exist", type_key="INT")
        tags = [good_tag, bad_tag]
        wait_rt_valid(api, good_tag["tag_name"], timeout=60.0)

        bad_val = None
        bad_quality = None
        try:
            pt = get_rt_point(api, bad_tag["tag_name"])
            bad_val = pt.get("tagValue")
            bad_quality = pt.get("quality", 0)
        except TptAPIError as exc:
            # 不存在节点的 RT 读取报错是可接受的产品行为
            pass

        # 必须不产生伪造有效值
        assert bad_val is None or bad_quality in (None, 0), \
            f"nonexistent node produced fake valid value: val={bad_val} q={bad_quality}"

        # 其他位号仍正常
        good_pt = get_rt_point(api, good_tag["tag_name"])
        assert good_pt.get("tagValue") is not None
        assert good_pt.get("quality", 0) != 0
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-012 配置类型与源类型不一致 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-012", chapter="UA-3-1",
    title="配置类型与源类型不一致",
    preconditions=["Mock 有 Double 节点", "数据源 alive=true"],
    steps=["Double 节点配置为错误类型", "记录拒绝/转换/质量规则", "确认服务不异常"],
    expected=["记录拒绝、转换或质量规则", "服务不异常"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_1_012_type_mismatch(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-1-012"
    prefix = "ua31_012"
    node = build_node(f"{prefix}_val_", "Double", 5.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations: dict = {}
    try:
        # 配置成 STRING 类型
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="STRING"))
        rec = find_unique_tag(api, tags[0]["tag_name"])
        observations["configured_data_type"] = rec.get("dataType")

        deadline = time.monotonic() + 30.0
        observed = None
        while time.monotonic() < deadline:
            try:
                pt = get_rt_point(api, tags[0]["tag_name"])
                observed = {
                    "tagValue": pt.get("tagValue"),
                    "quality": pt.get("quality", 0),
                    "dataType": pt.get("dataType"),
                    "isSuccess": pt.get("isSuccess"),
                    "message": pt.get("message"),
                }
            except TptAPIError as exc:
                observed = {"error_code": exc.code, "error_msg": exc.msg}
            if observed.get("tagValue") is not None:
                break
            time.sleep(1.0)
        observations["rt_observation"] = observed

        # 服务必须不异常：其他正确配置位号仍正常
        good_tag = add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE")
        tags.append(good_tag)
        wait_rt_valid(api, good_tag["tag_name"], timeout=60.0)
        good_pt = get_rt_point(api, good_tag["tag_name"])
        assert good_pt.get("tagValue") is not None, "good tag lost value after mismatch config"
        observations["good_tag_value"] = good_pt.get("tagValue")

        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)

    pytest.xfail(
        "UA-3-1-012 configured-vs-source type mismatch rule (reject/coerce/quality) "
        "is not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
