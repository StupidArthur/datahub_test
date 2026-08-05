"""UA-3-2 实时读取 — batch 3: UA-3-2-005 .. UA-3-2-021.

Migrated from ``ua_test_harness/test_cases/UA-3-2.md`` (rows 005..021).
Each test creates its own mocker (dynamic port), datasource and tag(s), and
performs strict cleanup regardless of outcome.

Conventions applied from the source spec:
- real-time library: ``isFromDB=false``; database: ``isFromDB=true``
- query by ``tagNames`` / ``tagInfoIds`` / ``groupId`` / ``queryTime`` / ``option``
- dynamic values compared within an allowed time window
- exploration rows record full request/response/timeline, never fake returns
"""
from __future__ import annotations

import json
import time
from datetime import datetime

import pytest

from tpt_api.datahub import (
    add_tag_group,
    add_tag_group_relation,
    delete_tags,
    delete_tag_group,
    list_recycle_tags,
    remove_tag_group_relation,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.naming import unique_name
from tests.support.ua2_helpers import opcua_read_sync, opcua_write_sync, setup_ds_only
from tests.support.ua2_rt_assertions import parse_required_timestamp
from tests.support.ua2_value_normalization import assert_value_equal
from tests.support.ua3_helpers import (
    UA3_TYPES,
    add_collection_tag,
    build_13_type_nodes,
    build_node,
    cleanup_ua3_context,
    cleanup_ua3_multi_context,
    node_id_from_cfg,
    rt_query,
    wait_rt_matches_source,
    wait_rt_valid,
)

_TAG_MISSING = ("tag dose not exist", "tag does not exist")


def _is_tag_missing(exc: TptAPIError) -> bool:
    msg = (exc.msg or "").lower()
    return any(sub in msg for sub in _TAG_MISSING)


def _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id: str, nodes: list[dict]) -> dict:
    ctx = setup_ds_only(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        nodes=nodes, namespace_index=1, cycle=500,
    )
    ctx["nodes"] = nodes
    return ctx


def _teardown(api, ctx: dict, tags: list[dict]) -> None:
    cleanup_ua3_context(
        api,
        tag_ids=[t["tag_id"] for t in tags],
        tag_names=[t["tag_name"] for t in tags],
        ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
        mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"],
    )


def _by_name(points: list[dict], tag_name: str) -> dict:
    return next((p for p in points if p.get("tagName") == tag_name), {})


def _recycle_ids(api) -> set[int]:
    resp = list_recycle_tags(api, page=1, page_size=999)
    recs = resp.get("records") or resp.get("list") or []
    return {int(r.get("id", -1)) for r in recs}


# ---------------------------------------------------------------------------
# UA-3-2-005 实时库_13种类型与字段
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-005", chapter="UA-3-2",
    title="实时库_13种类型与字段",
    preconditions=["数据源 alive=true", "13 种类型位号已创建"],
    steps=["批量查询 13 种类型位号", "核对 value/dataType/quality/时间字段"],
    expected=["value、dataType、quality、时间字段正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_2_005_13_types(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-2-005"
    prefix = "ua32_005"
    nodes = build_13_type_nodes(prefix)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes)
    tags = []
    try:
        for node, (type_name, type_key) in zip(nodes, UA3_TYPES):
            tags.append(add_collection_tag(
                api, settings, ctx, case_id,
                node_id_str=node_id_from_cfg(node), type_key=type_key,
            ))
        for t in tags:
            wait_rt_valid(api, t["tag_name"], timeout=60.0)

        points = rt_query(api, tag_names=[t["tag_name"] for t in tags], is_from_db=False)
        assert isinstance(points, list) and len(points) == len(tags), \
            f"expected {len(tags)} points, got {len(points)}: {points}"

        observations = {}
        for t, node, (type_name, type_key) in zip(tags, nodes, UA3_TYPES):
            pt = _by_name(points, t["tag_name"])
            assert pt, f"missing {t['tag_name']} in batch response: {[p.get('tagName') for p in points]}"
            assert pt.get("quality", 0) != 0, f"quality 0 for {t['tag_name']}"
            for field in ("tagTime", "appTime"):
                if pt.get(field):
                    parse_required_timestamp(pt[field])
                else:
                    observations.setdefault("missing_fields", []).append(
                        {"tag": t["tag_name"], "type": type_name, "field": field})
            src = opcua_read_sync(ctx["endpoint"], node_id_from_cfg(node), namespace_index=1)
            assert_value_equal(src, pt.get("tagValue"), DataTypes[type_key])
            observations.setdefault("dataType", {})[t["tag_name"]] = pt.get("dataType")
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-2-006 实时库_不存在名称
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-006", chapter="UA-3-2",
    title="实时库_不存在名称",
    preconditions=["数据源 alive=true"],
    steps=["查询不存在的 tagName", "确认明确失败或空结果"],
    expected=["明确失败或空结果，无 5xx"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_006_nonexistent_name(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-2-006"
    prefix = "ua32_006"
    node = build_node(f"{prefix}_val_", "Double", 1.0, change=False, writable=True)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    try:
        try:
            rt_query(api, tag_names=[f"{settings.test_prefix}no_such_UA-3-2-006_zzz"], is_from_db=False)
        except TptAPIError as exc:
            assert _is_tag_missing(exc), f"unexpected error: {exc.code} {exc.msg}"
            return
        raise AssertionError("expected TptAPIError for non-existent tagName")
    finally:
        _teardown(api, ctx, [])


# ---------------------------------------------------------------------------
# UA-3-2-007 实时库_不存在ID
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-007", chapter="UA-3-2",
    title="实时库_不存在ID",
    preconditions=["数据源 alive=true"],
    steps=["查询不存在的 tagInfoId", "确认不返回错误位号"],
    expected=["不返回错误位号"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_007_nonexistent_id(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-2-007"
    prefix = "ua32_007"
    node = build_node(f"{prefix}_val_", "Double", 1.0, change=False, writable=True)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    try:
        try:
            rt_query(api, tag_info_ids=[999999999], is_from_db=False)
        except TptAPIError as exc:
            assert _is_tag_missing(exc), f"unexpected error: {exc.code} {exc.msg}"
            return
        raise AssertionError("expected TptAPIError for non-existent tagInfoId")
    finally:
        _teardown(api, ctx, [])


# ---------------------------------------------------------------------------
# UA-3-2-008 实时库_有效无效混合
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-008", chapter="UA-3-2",
    title="实时库_有效无效混合",
    preconditions=["数据源 alive=true", "有效位号已创建"],
    steps=["同批查询有效和无效目标", "核对有效项正确、失败项可定位"],
    expected=["有效项保持正确，失败项可定位"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_008_mixed_valid_invalid(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-2-008"
    prefix = "ua32_008"
    node = build_node(f"{prefix}_val_", "Double", 8.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        bad_name = f"{settings.test_prefix}no_such_UA-3-2-008_zzz"
        points = rt_query(api, tag_names=[tags[0]["tag_name"], bad_name], is_from_db=False)
        observations["returned"] = json.loads(json.dumps(points, ensure_ascii=False, default=str))
        pt = _by_name(points, tags[0]["tag_name"])
        assert pt and pt.get("tagValue") == 8.5, \
            f"valid tag lost/incorrect in mixed batch: {points}"
        bad = _by_name(points, bad_name)
        assert bad.get("isSuccess") is False, f"invalid entry not locatable: {points}"
        msg = (bad.get("message") or "").lower()
        assert any(sub in msg for sub in _TAG_MISSING), f"invalid entry reason unclear: {points}"
        observations["invalid_locatable"] = True
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-2-009 查询条件_全部为空
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-009", chapter="UA-3-2",
    title="查询条件_全部为空",
    preconditions=["数据源 alive=true"],
    steps=["不传名称、ID、分组查询", "确认明确拒绝、不误触发全量查询"],
    expected=["明确拒绝，不误触发全量查询"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_009_empty_selectors(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-2-009"
    prefix = "ua32_009"
    node = build_node(f"{prefix}_val_", "Double", 1.0, change=False, writable=True)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    try:
        try:
            rt_query(api, is_from_db=False)
        except TptAPIError as exc:
            assert _is_tag_missing(exc), f"unexpected error: {exc.code} {exc.msg}"
            return
        raise AssertionError("expected TptAPIError for empty selectors (no full-table query)")
    finally:
        _teardown(api, ctx, [])


# ---------------------------------------------------------------------------
# UA-3-2-010 查询条件_重复目标 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-010", chapter="UA-3-2",
    title="查询条件_重复目标",
    preconditions=["数据源 alive=true", "位号已创建"],
    steps=["重复传入名称或 ID", "记录去重/重复规则，确认不错配"],
    expected=["记录去重/重复规则，不错配"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_010_duplicate_targets(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-2-010"
    prefix = "ua32_010"
    node = build_node(f"{prefix}_val_", "Double", 10.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        points = rt_query(api, tag_names=[tags[0]["tag_name"], tags[0]["tag_name"]], is_from_db=False)
        observations["returned"] = json.loads(json.dumps(points, ensure_ascii=False, default=str))
        assert isinstance(points, list) and len(points) == 1, \
            f"duplicate-name query must dedupe to a single point: {points}"
        pt = points[0]
        assert pt.get("tagName") == tags[0]["tag_name"], f"dup query mismatched identity: {pt}"
        assert pt.get("tagValue") == 10.0, f"dup query wrong value: {pt}"
        observations["deduped_single_point"] = True
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-2-011 查询条件_多选择器并用 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-011", chapter="UA-3-2",
    title="查询条件_多选择器并用",
    preconditions=["数据源 alive=true", "位号已创建并分配分组"],
    steps=["同时传名称、ID、分组", "记录并集、交集或优先级规则"],
    expected=["记录并集、交集或优先级规则"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_2_011_multi_selector(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-2-011"
    prefix = "ua32_011"
    node = build_node(f"{prefix}_val_", "Double", 11.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    group_id = None
    observations = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        group_name = unique_name(settings.test_prefix, f"{case_id}-group")
        group_data = add_tag_group(api, group_name)
        group_id = int(group_data.get("id") or group_data.get("groupId"))
        add_tag_group_relation(api, group_id=str(group_id), tag_ids=[tags[0]["tag_id"]])

        try:
            observations["name_id_group"] = json.loads(json.dumps(
                rt_query(api, tag_names=[tags[0]["tag_name"]], tag_info_ids=[tags[0]["tag_id"]],
                         group_id=group_id, is_from_db=False),
                ensure_ascii=False, default=str))
        except TptAPIError as exc:
            observations["name_id_group_error"] = {"code": exc.code, "msg": exc.msg}
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)
        if group_id is not None:
            delete_tag_group(api, [str(group_id)])
    pytest.xfail(
        "UA-3-2-011 multi-selector precedence rule is not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-2-012 数据库_按名称读取
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-012", chapter="UA-3-2",
    title="数据库_按名称读取",
    preconditions=["数据源 alive=true", "位号已创建"],
    steps=["isFromDB=true 查询名称", "返回数据库实时值，身份正确"],
    expected=["返回数据库实时值，身份正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_012_db_by_name(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-2-012"
    prefix = "ua32_012"
    node = build_node(f"{prefix}_val_", "Double", 12.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        points = rt_query(api, tag_names=[tags[0]["tag_name"]], is_from_db=True)
        assert isinstance(points, list) and len(points) == 1, f"expected 1 point, got {points}"
        pt = points[0]
        assert pt.get("tagName") == tags[0]["tag_name"], f"identity mismatch: {pt}"
        assert pt.get("quality", 0) != 0, f"quality 0: {pt}"
        assert_value_equal(12.5, pt.get("tagValue"), DataTypes["DOUBLE"])
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-2-013 数据库_按ID和分组读取
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-013", chapter="UA-3-2",
    title="数据库_按ID和分组读取",
    preconditions=["数据源 alive=true", "位号已创建并分配分组"],
    steps=["分别用 ID、groupId 查询", "查询范围与选择器一致"],
    expected=["查询范围与选择器一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_013_db_by_id_and_group(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-2-013"
    prefix = "ua32_013"
    nodes = [
        build_node(f"{prefix}_a_", "Double", 13.1, change=False, writable=True),
        build_node(f"{prefix}_b_", "Double", 13.2, change=False, writable=True),
    ]
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes)
    tags = []
    group_id = None
    try:
        for i, node in enumerate(nodes):
            tags.append(add_collection_tag(
                api, settings, ctx, case_id,
                node_id_str=node_id_from_cfg(node), type_key="DOUBLE",
            ))
            wait_rt_valid(api, tags[-1]["tag_name"], timeout=60.0)

        group_name = unique_name(settings.test_prefix, f"{case_id}-group")
        group_data = add_tag_group(api, group_name)
        group_id = int(group_data.get("id") or group_data.get("groupId"))
        add_tag_group_relation(api, group_id=str(group_id), tag_ids=[tags[0]["tag_id"]])

        by_id = rt_query(api, tag_info_ids=[tags[1]["tag_id"]], is_from_db=True)
        assert isinstance(by_id, list) and len(by_id) == 1, f"by-id scope mismatch: {by_id}"
        assert by_id[0].get("tagName") == tags[1]["tag_name"], f"by-id wrong tag: {by_id[0]}"

        by_group = rt_query(api, group_id=group_id, is_from_db=True)
        names = {p.get("tagName") for p in by_group}
        assert tags[0]["tag_name"] in names, f"group query missing tag: {sorted(names)}"
        assert not any(n == tags[1]["tag_name"] for n in names), \
            f"group query crossed scope: {sorted(names)}"
    finally:
        _teardown(api, ctx, tags)
        if group_id is not None:
            delete_tag_group(api, [str(group_id)])


# ---------------------------------------------------------------------------
# UA-3-2-014 两种方式_最终值一致
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-014", chapter="UA-3-2",
    title="两种方式_最终值一致",
    preconditions=["数据源 alive=true", "位号已创建"],
    steps=["源端停止变化后查询两种模式", "允许落地窗口后值最终一致"],
    expected=["允许落地窗口后值最终一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_014_final_value_consistent(api, settings, tmp_path_factory, mocker_endpoint):
    from asyncua import ua

    case_id = "UA-3-2-014"
    prefix = "ua32_014"
    node = build_node(f"{prefix}_val_", "Double", 0.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        target = 314.5
        opcua_write_sync(ctx["endpoint"], node_id, target, namespace_index=1,
                         variant_type=ua.VariantType.Double)
        wait_rt_matches_source(api, ctx, tags[0]["tag_name"], node_id, "DOUBLE",
                               expected=target, timeout=60.0)

        def _db_value():
            pts = rt_query(api, tag_names=[tags[0]["tag_name"]], is_from_db=True)
            return pts[0].get("tagValue") if pts else None

        wait_until(f"db_value:{tags[0]['tag_name']}",
                   lambda: _db_value() is not None, timeout=120.0)
        rt = rt_query(api, tag_names=[tags[0]["tag_name"]], is_from_db=False)[0]
        db = rt_query(api, tag_names=[tags[0]["tag_name"]], is_from_db=True)[0]
        assert_value_equal(db.get("tagValue"), rt.get("tagValue"), DataTypes["DOUBLE"])
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-2-015 两种方式_可见延迟 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-015", chapter="UA-3-2",
    title="两种方式_可见延迟",
    preconditions=["数据源 alive=true", "位号已创建"],
    steps=["源端写唯一值并轮询", "记录两种模式首次可见时间差"],
    expected=["记录两种模式首次可见时间差"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_2_015_visible_latency(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    from asyncua import ua

    case_id = "UA-3-2-015"
    prefix = "ua32_015"
    node = build_node(f"{prefix}_val_", "Double", 0.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        target = 12345.678
        opcua_write_sync(ctx["endpoint"], node_id, target, namespace_index=1,
                         variant_type=ua.VariantType.Double)

        def _poll(is_db: bool):
            t0 = time.monotonic()
            while time.monotonic() - t0 < 120.0:
                pts = rt_query(api, tag_names=[tags[0]["tag_name"]], is_from_db=is_db)
                if pts:
                    try:
                        assert_value_equal(target, pts[0].get("tagValue"), DataTypes["DOUBLE"])
                        return time.monotonic()
                    except AssertionError:
                        pass
                time.sleep(0.5)
            return None

        rt_visible = _poll(False)
        db_visible = _poll(True)
        observations["target"] = target
        observations["rt_first_visible_at"] = rt_visible
        observations["db_first_visible_at"] = db_visible
        if rt_visible is not None and db_visible is not None:
            observations["delta_s"] = round(db_visible - rt_visible, 2)
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)
    pytest.xfail(
        "UA-3-2-015 realtime-vs-database first-visible latency is not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-2-016 两种方式_断线差异 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-016", chapter="UA-3-2",
    title="两种方式_断线差异",
    preconditions=["数据源 alive=true", "位号已创建", "RT 可读"],
    steps=["断线前后查询两种模式", "记录缓存值、质量和时间差异"],
    expected=["记录缓存值、质量和时间差异"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_2_016_disconnect_difference(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    from tests.support.mocker_process import stop_mocker

    case_id = "UA-3-2-016"
    prefix = "ua32_016"
    node = build_node(f"{prefix}_val_", "Double", 16.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        def _snapshot():
            return {
                "rt": json.loads(json.dumps(
                    rt_query(api, tag_names=[tags[0]["tag_name"]], is_from_db=False),
                    ensure_ascii=False, default=str)),
                "db": json.loads(json.dumps(
                    rt_query(api, tag_names=[tags[0]["tag_name"]], is_from_db=True),
                    ensure_ascii=False, default=str)),
            }

        observations["before"] = _snapshot()
        stop_mocker(ctx["mocker"])
        observations["mocker_stopped"] = True
        time.sleep(2)
        try:
            observations["after"] = _snapshot()
        except TptAPIError as exc:
            observations["after_error"] = {"code": exc.code, "msg": exc.msg}
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)
    pytest.xfail(
        "UA-3-2-016 disconnect cache/quality/time behavior is not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-2-017 指定时间_queryTime (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-017", chapter="UA-3-2",
    title="指定时间_queryTime",
    preconditions=["数据源 alive=true", "位号已创建"],
    steps=["传有效 queryTime", "支持时返回对应结果，身份正确"],
    expected=["支持时返回对应结果，身份正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_2_017_query_time(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-2-017"
    prefix = "ua32_017"
    node = build_node(f"{prefix}_val_", "Double", 17.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        q = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            points = rt_query(api, tag_names=[tags[0]["tag_name"]], query_time=q, is_from_db=False)
            observations["returned"] = json.loads(json.dumps(points, ensure_ascii=False, default=str))
            pt = _by_name(points, tags[0]["tag_name"])
            assert pt, f"queryTime response missing tag: {points}"
        except TptAPIError as exc:
            observations["error"] = {"code": exc.code, "msg": exc.msg}
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)
    pytest.xfail(
        "UA-3-2-017 queryTime support/behavior is not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-2-018 指定时间_option组合 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-018", chapter="UA-3-2",
    title="指定时间_option组合",
    preconditions=["数据源 alive=true", "位号已创建"],
    steps=["不同 option 与 queryTime", "记录采样规则；服务不异常"],
    expected=["记录采样规则；服务不异常"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_2_018_option_combos(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-2-018"
    prefix = "ua32_018"
    node = build_node(f"{prefix}_val_", "Double", 18.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        q = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for option in (1, 2, 3):
            try:
                points = rt_query(api, tag_names=[tags[0]["tag_name"]], option=option,
                                  query_time=q, is_from_db=False)
                observations[f"option_{option}"] = json.loads(json.dumps(
                    points, ensure_ascii=False, default=str))
            except TptAPIError as exc:
                observations[f"option_{option}_error"] = {"code": exc.code, "msg": exc.msg}
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)
    pytest.xfail(
        "UA-3-2-018 option sampling rule is not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-2-019 指定时间_部分源不支持
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-019", chapter="UA-3-2",
    title="指定时间_部分源不支持",
    preconditions=["两个数据源 A/B", "数据源 alive=true"],
    steps=["同批查询支持和不支持的数据源", "失败项可定位，其他项正常"],
    expected=["失败项可定位，其他项正常"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
@pytest.mark.spec_pending
def test_ua3_2_019_partial_source_query_time(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    from tests.support.endpoints import parse_mocker_endpoint
    from tests.support.mocker_process import find_free_port, start_mocker, write_mocker_config
    from tpt_api.datahub import add_ds_info
    from tpt_api.types import DsSubTypes, DsTypes

    case_id = "UA-3-2-019"
    parsed = parse_mocker_endpoint(mocker_endpoint)

    def _build_ds(letter: str, node) -> dict:
        port = find_free_port()
        endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
        tmp_dir = tmp_path_factory.mktemp(f"m_{case_id.lower()}_{letter}")
        cfg_path = write_mocker_config(tmp_dir, port, nodes=[node], namespace_index=1, cycle=500)
        mocker = start_mocker(cfg_path, port, host=parsed.host)
        ds_name = unique_name(settings.test_prefix, f"{case_id}-ds-{letter}")
        data = add_ds_info(
            api, ds_name=ds_name,
            ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
            ds_tar_url=endpoint,
        )
        ds_id = int(data.get("id") or data.get("dsId"))
        from tests.support.ua2_helpers import is_ds_alive
        wait_until(f"ds_alive:{case_id}-{letter}", lambda: is_ds_alive(api, ds_id), timeout=60.0)
        return {
            "ds_id": ds_id, "ds_name": ds_name, "mocker": mocker,
            "port": port, "host": parsed.host, "endpoint": endpoint,
            "cfg_path": cfg_path, "namespace_index": 1,
        }

    ctx_a = _build_ds("A", build_node("ua32_019_a_", "Double", 19.1, change=False, writable=True))
    ctx_b = _build_ds("B", build_node("ua32_019_b_", "Double", 19.2, change=False, writable=True))
    ctxs = [ctx_a, ctx_b]
    tags = []
    observations = {}
    try:
        tag_a = add_collection_tag(api, settings, ctx_a, case_id, node_id_str="ua32_019_a_1", type_key="DOUBLE")
        tag_b = add_collection_tag(api, settings, ctx_b, case_id, node_id_str="ua32_019_b_1", type_key="DOUBLE")
        tags = [tag_a, tag_b]
        wait_rt_valid(api, tag_a["tag_name"], timeout=60.0)
        wait_rt_valid(api, tag_b["tag_name"], timeout=60.0)

        q = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        points = rt_query(api, tag_names=[tag_a["tag_name"], tag_b["tag_name"]],
                          query_time=q, is_from_db=False)
        observations["returned"] = json.loads(json.dumps(points, ensure_ascii=False, default=str))
        observations["per_item_success"] = {
            t["tag_name"]: bool(_by_name(points, t["tag_name"]).get("isSuccess"))
            for t in tags
        }
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        cleanup_ua3_multi_context(api, tags=tags, ds_contexts=ctxs)
    pytest.xfail(
        "UA-3-2-019 appointed-time (queryTime) query is not supported by the OPC UA "
        "source (per-item 'Not support appointed time query'); mixed supported/unsupported "
        "scenario cannot be demonstrated with the mocker. "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-2-020 删除恢复后的读取
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-020", chapter="UA-3-2",
    title="删除恢复后的读取",
    preconditions=["数据源 alive=true", "位号已创建", "RT 可读"],
    steps=["软删后查询，再恢复查询", "删除后不正常返回；恢复后可读"],
    expected=["删除后不正常返回；恢复后可读"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_020_delete_restore_read(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-2-020"
    prefix = "ua32_020"
    node = build_node(f"{prefix}_val_", "Double", 20.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        delete_tags(api, [tags[0]["tag_id"]])
        observations["deleted"] = True

        def _rt_gone() -> bool:
            try:
                get_rt_point(api, tags[0]["tag_name"])
                return False
            except TptAPIError as exc:
                return _is_tag_missing(exc)

        wait_until(f"rt_gone:{tags[0]['tag_name']}", _rt_gone, timeout=60.0)
        observations["deleted_rt_unavailable"] = True

        resp = remove_tag_group_relation(api, group_id="1", tag_ids=[tags[0]["tag_id"]])
        observations["restore_response"] = json.loads(json.dumps(resp, ensure_ascii=False, default=str))
        assert tags[0]["tag_id"] not in _recycle_ids(api), \
            f"tag {tags[0]['tag_id']} still in recycle after restore"

        wait_rt_valid(api, tags[0]["tag_name"], timeout=120.0)
        observations["restored_rt_available"] = True
        pt = get_rt_point(api, tags[0]["tag_name"])
        assert pt.get("tagName") == tags[0]["tag_name"], f"identity mismatch after restore: {pt}"
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-2-021 连续读取稳定性
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-021", chapter="UA-3-2",
    title="连续读取稳定性",
    preconditions=["数据源 alive=true", "静态位号已创建"],
    steps=["静态数据下执行 20 次连续读取", "无随机失败，集合和值稳定"],
    expected=["无随机失败，集合和值稳定"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_021_consecutive_reads(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-2-021"
    prefix = "ua32_021"
    node = build_node(f"{prefix}_val_", "Double", 21.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        values: list = []
        names: set = set()
        for i in range(20):
            points = rt_query(api, tag_names=[tags[0]["tag_name"]], is_from_db=False)
            assert isinstance(points, list) and len(points) == 1, \
                f"iteration {i}: unexpected points {points}"
            pt = points[0]
            assert pt.get("tagName") == tags[0]["tag_name"], f"iteration {i}: identity {pt}"
            assert pt.get("quality", 0) != 0, f"iteration {i}: quality 0"
            names.add(pt.get("tagName"))
            values.append(pt.get("tagValue"))
        assert names == {tags[0]["tag_name"]}, f"tag set unstable across 20 reads: {names}"
        assert len(set(values)) == 1, f"values unstable across 20 reads: {set(values)}"
    finally:
        _teardown(api, ctx, tags)
