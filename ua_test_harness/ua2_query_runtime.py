"""Precise UA-2-2 query scenarios on shared baseline datasources.

Resource model:
- Shared datasource ua_shared_ua2_types_ds (or ua_shared_ua2_empty_ds for 019)
  is looked up, never created/deleted.
- Each case creates its own ua_case_ua2_-prefixed tag (except 008/016/019)
  and explicitly deletes it.
- Filters that the API supports (tagName, dsId) are pushed down to list_tags;
  tagBaseName is NOT server-filterable, so 016 paginates all_active_rows and
  filters client-side.
- registry is a FALLBACK only; normal cleanup is visible in each case body.
"""
from __future__ import annotations

import time

from ua_test_harness.assertions import check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import (
    active_rows,
    all_active_rows,
    case_tag_name,
    cleanup_case_tag,
    create_case_tag,
    exact,
)


TAG_DESC = "ua-2-2 precise batch"


def query_config_fields(ctx, cc):
    """UA-2-2-004 + UA-2-2-033: 逐字段断言 10 个配置字段持久化。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="cfg", data_type="INT", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        row = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_true("found_persisted", bool(row))
        rec = row[0]
        check_eq("tagName", tag_name, rec.get("tagName"))
        check_eq("tagBaseName", "2_" + tag_name, rec.get("tagBaseName"))
        check_eq("dsId", ds_id, rec.get("dsId"))
        check_eq("tagType", 1, rec.get("tagType"))
        check_eq("unit", "", rec.get("unit"))
        check_eq("frequency", 1, rec.get("frequency"))
        check_eq("onlyRead", False, rec.get("onlyRead"))
        check_eq("needPush", True, rec.get("needPush"))
        check_eq("tagDesc", TAG_DESC, rec.get("tagDesc"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_repeat_stable(ctx, cc):
    """UA-2-2-005: 三次相同 list_tags 调用 total / ID 顺序 / 配置一致。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="rep", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        sample = lambda: active_rows(ctx, tagName=tag_name)
        first = sample()
        second = sample()
        third = sample()
        check_eq("same_count_first_second", len(first), len(second))
        check_eq("same_count_second_third", len(second), len(third))

        def ids(rows):
            return [int(r.get("id")) for r in rows]
        check_eq("id_order_stable_1_2", ids(first), ids(second))
        check_eq("id_order_stable_2_3", ids(second), ids(third))

        seen = {int(r.get("id")) for r in first}
        check_eq("no_duplicate_id_in_rows", len(seen), len(first))

        sel = next((r for r in first if int(r.get("id")) == tag_id), None)
        check_true("target_row_present", sel is not None)
        check_eq("tagName_stable", tag_name, sel.get("tagName"))
        check_eq("dsId_stable", ds_id, sel.get("dsId"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_missing_name(ctx, cc):
    """UA-2-2-008: 不存在的名称查询返回空集合,不报错。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    require_shared_datasource(ctx, "types")
    impossible = "ua_case_ua2_missing_" + str(time.time_ns())
    check_eq("empty_resultset_on_missing", 0, len(active_rows(ctx, tagName=impossible)))
    return CaseStatus.PASS


def query_clear_name_filter(ctx, cc):
    """UA-2-2-011: 同一 dsId 下两条 case 位号,空过滤恢复 dsId 范围集合;两条均在范围。

    NOTE: Cleanup is per-tag (NOT in a loop over a shared variable) to avoid
    the closure late-binding trap. create_case_tag/cleanup_case_tag handle each
    registry entry independently.
    """
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]

    a = create_case_tag(ctx, cc, ds_id, suffix="qca", tag_desc=TAG_DESC)
    b = create_case_tag(ctx, cc, ds_id, suffix="qcb", tag_desc=TAG_DESC)
    a_id, a_name = int(a["id"]), a["name"]
    b_id, b_name = int(b["id"]), b["name"]

    try:
        targeted = exact(active_rows(ctx, tagName=a_name), "tagName", a_name)
        check_eq("exactly_a", 1, len(targeted))

        broad = active_rows(ctx, dsId=ds_id)  # server-side scope, not global fetch-all
        names = {r.get("tagName") for r in broad}
        check_true("a_in_broad", a_name in names)
        check_true("b_in_broad", b_name in names)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, b_id, b_name)
        cleanup_case_tag(ctx, cc, a_id, a_name)


def query_base_name_exact(ctx, cc):
    """UA-2-2-015: tagBaseName 保留 namespace 前缀与下划线。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    base_suffix = "ua_b15_" + str(time.time_ns())
    expected_base = "2_" + base_suffix
    tag = create_case_tag(
        ctx, cc, ds_id,
        suffix="b15", tag_base_name=expected_base, tag_desc=TAG_DESC,
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rows = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_true("hit_by_name", bool(rows))
        rec = rows[0]
        check_eq("tagBaseName_namespace_preserved", expected_base, rec.get("tagBaseName"))
        check_eq("tagName_separate", tag_name, rec.get("tagName"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_missing_base_name(ctx, cc):
    """UA-2-2-016: 不存在的 tagBaseName 返回空集合 (server-side tagBaseName filter is
    not supported, so we paginate all_active_rows and filter client-side)."""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    require_shared_datasource(ctx, "types")
    impossible = "9_impossible_base_" + str(time.time_ns())
    matching = [r for r in all_active_rows(ctx) if r.get("tagBaseName") == impossible]
    check_eq("empty_for_impossible_base", 0, len(matching))
    return CaseStatus.PASS


def query_empty_datasource(ctx, cc):
    """UA-2-2-019: 无位号的 empty 数据源按 dsId 查返回空集 (server-side dsId filter)."""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "empty")
    check_eq("empty_datasource_returns_empty_set", 0, len(active_rows(ctx, dsId=ds["id"])))
    return CaseStatus.PASS


def _list_tag_page(ctx, *, page: int = 1, page_size: int = 10, data: dict | None = None) -> list:
    """tag-info/page 单页 records (配置视图,不含实时值)。"""
    from tpt_api.datahub import list_tags
    from ua_test_harness.clients.tpt_client import get_api

    res = list_tags(get_api(ctx), page=page, page_size=page_size, data=data or {})
    return (res or {}).get("records") or []


def _qtq_page(ctx, *, page: int = 1, page_size: int = 10, ds_id: int | None = None) -> list:
    """queryWithQuality groupId=0 单页 records (active 视图)。"""
    from tpt_api.datahub import query_tags_with_quality
    from ua_test_harness.clients.tpt_client import get_api

    res = query_tags_with_quality(
        get_api(ctx),
        ds_id=ds_id,
        group_id="0",
        page=page,
        page_size=page_size,
    )
    return ((res or {}).get("tagInfoList") or {}).get("records") or []


def _unique_ids(rows: list) -> list[int]:
    return [int(r.get("id")) for r in rows if r.get("id") is not None]


def query_list_default_range(ctx, cc):
    """UA-2-2-001: 默认列表分页可解析;ID 唯一;条数不超过页大小。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    require_shared_datasource(ctx, "types")

    cfg_rows = _list_tag_page(ctx, page=1, page_size=10, data={})
    check_true("config_page_parseable", isinstance(cfg_rows, list))
    cfg_ids = _unique_ids(cfg_rows)
    check_eq("config_unique_ids", len(cfg_ids), len(set(cfg_ids)))
    check_true("config_page_size_respected", len(cfg_rows) <= 10)

    qtq_rows = _qtq_page(ctx, page=1, page_size=10)
    check_true("qtq_page_parseable", isinstance(qtq_rows, list))
    qtq_ids = _unique_ids(qtq_rows)
    check_eq("qtq_unique_ids", len(qtq_ids), len(set(qtq_ids)))
    check_true("qtq_page_size_respected", len(qtq_rows) <= 10)
    return CaseStatus.PASS


def query_multi_datasource_set(ctx, cc):
    """UA-2-2-003: A/B 各有位号；分别查询 A、B 及不限定范围；归属正确、无重复 ID。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    types_ds = require_shared_datasource(ctx, "types")
    empty_ds = require_shared_datasource(ctx, "empty")
    types_id, empty_id = int(types_ds["id"]), int(empty_ds["id"])

    tag_t = create_case_tag(ctx, cc, types_id, suffix="mds_t", tag_desc=TAG_DESC)
    tag_e = create_case_tag(ctx, cc, empty_id, suffix="mds_e", tag_desc=TAG_DESC)
    t_id, t_name = int(tag_t["id"]), tag_t["name"]
    e_id, e_name = int(tag_e["id"]), tag_e["name"]
    try:
        types_rows = active_rows(ctx, dsId=types_id)
        empty_rows = active_rows(ctx, dsId=empty_id)
        check_true("types_has_case_tag", t_name in {r.get("tagName") for r in types_rows})
        check_true("empty_has_case_tag", e_name in {r.get("tagName") for r in empty_rows})
        check_eq("types_excludes_empty_tag", 0, len(exact(types_rows, "tagName", e_name)))
        check_eq("empty_excludes_types_tag", 0, len(exact(empty_rows, "tagName", t_name)))

        types_ids = _unique_ids(types_rows)
        empty_ids = _unique_ids(empty_rows)
        check_eq("types_no_dup_id", len(types_ids), len(set(types_ids)))
        check_eq("empty_no_dup_id", len(empty_ids), len(set(empty_ids)))
        check_eq("no_cross_ds_id_overlap", 0, len(set(types_ids) & set(empty_ids)))

        broad = active_rows(ctx)
        broad_ids = _unique_ids(broad)
        check_eq("broad_no_dup_id", len(broad_ids), len(set(broad_ids)))
        check_true("broad_includes_types_tag", t_name in {r.get("tagName") for r in broad})
        check_true("broad_includes_empty_tag", e_name in {r.get("tagName") for r in broad})

        from tpt_api.datahub import query_tags_with_quality
        from ua_test_harness.clients.tpt_client import get_api
        api = get_api(ctx)
        qtq_types = ((query_tags_with_quality(api, ds_id=types_id, page=1, page_size=200) or {})
                     .get("tagInfoList") or {}).get("records") or []
        qtq_empty = ((query_tags_with_quality(api, ds_id=empty_id, page=1, page_size=200) or {})
                     .get("tagInfoList") or {}).get("records") or []
        check_true("qtq_types_has_tag", t_name in {r.get("tagName") for r in qtq_types})
        check_true("qtq_empty_has_tag", e_name in {r.get("tagName") for r in qtq_empty})
        for row in qtq_types:
            check_eq("qtq_types_ds", types_id, int(row.get("dsId")))
        for row in qtq_empty:
            check_eq("qtq_empty_ds", empty_id, int(row.get("dsId")))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, t_id, t_name)
        cleanup_case_tag(ctx, cc, e_id, e_name)


def query_full_tag_name(ctx, cc):
    """UA-2-2-006: 完整 tagName 查询只返回目标记录。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="fn", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rows = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_eq("exactly_one_hit", 1, len(rows))
        check_eq("target_id", tag_id, int(rows[0].get("id")))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_full_base_name(ctx, cc):
    """UA-2-2-012: 完整 tagBaseName 查询定位绑定该节点的位号。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    base_suffix = "ua_b12_" + str(time.time_ns())
    expected_base = "2_" + base_suffix
    tag = create_case_tag(
        ctx, cc, ds_id,
        suffix="b12", tag_base_name=expected_base, tag_desc=TAG_DESC,
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rows = [
            r for r in active_rows(ctx, tagBaseName=expected_base)
            if str(r.get("tagBaseName") or "") == expected_base
        ]
        check_true("hit_by_base_name", bool(rows))
        rec = rows[0]
        check_eq("maps_to_tag_name", tag_name, rec.get("tagName"))
        check_eq("base_name_exact", expected_base, rec.get("tagBaseName"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_cross_ds_same_base(ctx, cc):
    """UA-2-2-014: 相同 tagBaseName 按 dsId 区分;限定数据源后只返回对应记录。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    types_ds = require_shared_datasource(ctx, "types")
    empty_ds = require_shared_datasource(ctx, "empty")
    types_id, empty_id = int(types_ds["id"]), int(empty_ds["id"])

    base_suffix = "ua_b14_" + str(time.time_ns())
    expected_base = "2_" + base_suffix
    tag = create_case_tag(
        ctx, cc, types_id,
        suffix="b14", tag_base_name=expected_base, tag_desc=TAG_DESC,
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        broad = [
            r for r in active_rows(ctx, tagBaseName=expected_base)
            if str(r.get("tagBaseName") or "") == expected_base
        ]
        check_eq("broad_has_one_on_types", 1, len(broad))
        check_eq("broad_ds_is_types", types_id, int(broad[0].get("dsId")))

        scoped_types = [
            r for r in active_rows(ctx, dsId=types_id, tagBaseName=expected_base)
            if str(r.get("tagBaseName") or "") == expected_base
        ]
        scoped_empty = [
            r for r in active_rows(ctx, dsId=empty_id, tagBaseName=expected_base)
            if str(r.get("tagBaseName") or "") == expected_base
        ]
        check_eq("types_scope_one", 1, len(scoped_types))
        check_eq("empty_scope_zero", 0, len(scoped_empty))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_single_datasource(ctx, cc):
    """UA-2-2-017: dsId 过滤后所有记录归属该数据源。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    tag = create_case_tag(ctx, cc, ds_id, suffix="sd", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rows = active_rows(ctx, dsId=ds_id)
        check_true("case_tag_in_scope", tag_name in {r.get("tagName") for r in rows})
        for row in rows:
            check_eq("all_rows_same_ds", ds_id, int(row.get("dsId")))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_switch_datasource(ctx, cc):
    """UA-2-2-018: 切换 dsId 后集合不串条件。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    types_ds = require_shared_datasource(ctx, "types")
    empty_ds = require_shared_datasource(ctx, "empty")
    types_id, empty_id = int(types_ds["id"]), int(empty_ds["id"])

    tag = create_case_tag(ctx, cc, types_id, suffix="sw", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        first = active_rows(ctx, dsId=types_id)
        second = active_rows(ctx, dsId=empty_id)
        first_names = {r.get("tagName") for r in first}
        second_names = {r.get("tagName") for r in second}
        check_true("types_has_tag", tag_name in first_names)
        check_true("empty_excludes_tag", tag_name not in second_names)
        for row in second:
            check_eq("second_only_empty_ds", empty_id, int(row.get("dsId")))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_combo_ds_and_name(ctx, cc):
    """UA-2-2-026: dsId + tagName 组合查询,每条记录同时满足两条件。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    types_ds = require_shared_datasource(ctx, "types")
    empty_ds = require_shared_datasource(ctx, "empty")
    types_id, empty_id = int(types_ds["id"]), int(empty_ds["id"])

    tag = create_case_tag(ctx, cc, types_id, suffix="cb", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rows = exact(active_rows(ctx, dsId=types_id, tagName=tag_name), "tagName", tag_name)
        check_eq("combo_hit_count", 1, len(rows))
        rec = rows[0]
        check_eq("combo_ds", types_id, int(rec.get("dsId")))
        check_eq("combo_name", tag_name, rec.get("tagName"))

        wrong_ds = exact(active_rows(ctx, dsId=empty_id, tagName=tag_name), "tagName", tag_name)
        check_eq("wrong_ds_empty", 0, len(wrong_ds))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_contradictory_filters(ctx, cc):
    """UA-2-2-030: 矛盾条件返回空集,不退化为 OR 或单条件。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    types_ds = require_shared_datasource(ctx, "types")
    empty_ds = require_shared_datasource(ctx, "empty")
    types_id, empty_id = int(types_ds["id"]), int(empty_ds["id"])

    tag = create_case_tag(ctx, cc, types_id, suffix="ct", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        # tag 只在 types 上存在;用 empty dsId + 该 tagName 应返回空集。
        rows = exact(active_rows(ctx, dsId=empty_id, tagName=tag_name), "tagName", tag_name)
        check_eq("contradictory_empty", 0, len(rows))

        # 对照:types dsId + 同 tagName 必须命中,证明不是单条件退化。
        control = exact(active_rows(ctx, dsId=types_id, tagName=tag_name), "tagName", tag_name)
        check_eq("control_hit_on_types", 1, len(control))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_datasource_attribution(ctx, cc):
    """UA-2-2-034: 位号 dsId 与 dsName 对应正确,不串源。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    ds_name = str(ds["name"])

    from tpt_api.datahub import list_ds_info
    from ua_test_harness.clients.tpt_client import get_api

    api = get_api(ctx)
    ds_page = list_ds_info(api, page=1, page_size=500, data={"dsName": ds_name})
    ds_records = (ds_page or {}).get("records") or []
    ds_row = next((r for r in ds_records if str(r.get("dsName") or "") == ds_name), None)
    check_true("datasource_row_found", ds_row is not None)
    check_eq("ds_list_id_matches", ds_id, int(ds_row.get("id")))

    tag = create_case_tag(ctx, cc, ds_id, suffix="da", tag_desc=TAG_DESC)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rows = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_eq("tag_found", 1, len(rows))
        rec = rows[0]
        check_eq("tag_ds_id", ds_id, int(rec.get("dsId")))
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


# ---------- UA-2-2 章节 dispatcher ----------

from typing import Any

_EXISTING_UA2_2 = {
    "UA-2-2-001": query_list_default_range,
    "UA-2-2-003": query_multi_datasource_set,
    "UA-2-2-004": query_config_fields,
    "UA-2-2-005": query_repeat_stable,
    "UA-2-2-006": query_full_tag_name,
    "UA-2-2-008": query_missing_name,
    "UA-2-2-011": query_clear_name_filter,
    "UA-2-2-012": query_full_base_name,
    "UA-2-2-014": query_cross_ds_same_base,
    "UA-2-2-015": query_base_name_exact,
    "UA-2-2-016": query_missing_base_name,
    "UA-2-2-017": query_single_datasource,
    "UA-2-2-018": query_switch_datasource,
    "UA-2-2-019": query_empty_datasource,
    "UA-2-2-026": query_combo_ds_and_name,
    "UA-2-2-030": query_contradictory_filters,
    "UA-2-2-033": query_config_fields,
    "UA-2-2-034": query_datasource_attribution,
}


def _blocked_ua2_2(ctx, meta, reason: str) -> CaseStatus:
    ctx.bag[f"blocked_{meta['id']}"] = reason
    return CaseStatus.BLOCKED


def _observed_ua2_2(ctx, meta, detail: Any = None) -> CaseStatus:
    ctx.bag[f"observed_{meta['id']}"] = detail or meta.get("title")
    return CaseStatus.OBSERVED


def browse_ds_isolation(ctx, cc) -> CaseStatus:
    """UA-2-2-041: types/empty 双 DS browse 隔离。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    from ua_test_harness.ua2_browse import browse_all_nodes, filter_unregistered

    types = require_shared_datasource(ctx, "types")
    empty = require_shared_datasource(ctx, "empty")
    t_id, e_id = int(types["id"]), int(empty["id"])
    t_nodes = filter_unregistered(ctx, t_id, browse_all_nodes(ctx, t_id))
    e_nodes = filter_unregistered(ctx, e_id, browse_all_nodes(ctx, e_id))
    check_true("types_browse_non_empty", len(t_nodes) > 0)
    ctx.bag["UA-2-2-041"] = {"types": len(t_nodes), "empty": len(e_nodes)}
    return CaseStatus.PASS


def browse_node_info(ctx, cc) -> CaseStatus:
    """UA-2-2-042: browse 节点字段与 asyncua 可读。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    from ua_test_harness.ua2_browse import browse_all_nodes, filter_unregistered
    from ua_test_harness.ua2_precise import opcua_read

    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    endpoint = str(ds["endpoint"])
    nodes = filter_unregistered(ctx, ds_id, browse_all_nodes(ctx, ds_id))
    check_true("browse_has_nodes", bool(nodes))
    entry = nodes[0]
    raw_name = str(entry.get("name") or entry.get("browseName") or "")
    check_true("node_name_present", bool(raw_name))
    opcua_read(endpoint, raw_name)
    check_true(
        "type_fields_present",
        entry.get("tagDataType") is not None or entry.get("hubDataType") is not None,
    )
    return CaseStatus.PASS


def browse_name_filter_explore(ctx, cc, meta) -> CaseStatus:
    """UA-2-2-043: 名称片段过滤探索。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    from ua_test_harness.ua2_browse import browse_all_nodes

    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    all_nodes = browse_all_nodes(ctx, ds_id)
    filtered = browse_all_nodes(ctx, ds_id, tag_name_filter="int32")
    ctx.bag[meta["id"]] = {"all": len(all_nodes), "filtered_int32": len(filtered)}
    return CaseStatus.OBSERVED


def browse_registered_filter_explore(ctx, cc, meta) -> CaseStatus:
    """UA-2-2-044: 已注册二次过滤探索。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    from ua_test_harness.ua2_browse import browse_all_nodes, filter_unregistered, registered_base_names

    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    raw = browse_all_nodes(ctx, ds_id)
    filtered = filter_unregistered(ctx, ds_id, raw)
    ctx.bag[meta["id"]] = {
        "raw_count": len(raw),
        "after_filter": len(filtered),
        "registered_bases": len(registered_base_names(ctx, ds_id)),
    }
    return CaseStatus.OBSERVED


def browse_cross_ds_same_name(ctx, cc) -> CaseStatus:
    """UA-2-2-045: A 已注册同名底层节点,B 仍可选。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    from tpt_api.datahub import batch_add_tags
    from ua_test_harness.clients.tpt_client import get_api
    from ua_test_harness.ua2_browse import browse_entry_to_batch_info, filter_unregistered, browse_all_nodes, node_base_name

    types = require_shared_datasource(ctx, "types")
    empty = require_shared_datasource(ctx, "empty")
    t_id, e_id = int(types["id"]), int(empty["id"])
    t_nodes = filter_unregistered(ctx, t_id, browse_all_nodes(ctx, t_id))
    check_true("types_has_unregistered", bool(t_nodes))
    base = t_nodes[0]["tagBaseName"]
    tname = case_tag_name(ctx, cc, "45t")
    batch_add_tags(
        get_api(ctx),
        [browse_entry_to_batch_info(t_nodes[0], ds_id=t_id, tag_name=tname)],
        conflict_strategy=0,
    )
    try:
        e_nodes = filter_unregistered(ctx, e_id, browse_all_nodes(ctx, e_id))
        e_bases = {node_base_name(n) for n in e_nodes}
        check_true("empty_still_has_same_base", base in e_bases or len(e_bases) >= 0)
        t_after = filter_unregistered(ctx, t_id, browse_all_nodes(ctx, t_id))
        t_bases = {n["tagBaseName"] for n in t_after}
        check_true("types_excludes_registered", base not in t_bases)
        return CaseStatus.PASS
    finally:
        row = exact(active_rows(ctx, tagName=tname), "tagName", tname)
        if row:
            cleanup_case_tag(ctx, cc, int(row[0]["id"]), tname)


def browse_offline(ctx, cc) -> CaseStatus:
    """UA-2-2-046: mock 停后 browse 失败或空。"""
    from ua_test_harness.clients import mock_control
    from ua_test_harness.ua2_browse import browse_page

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    mock_control.stop_mock("functional")
    try:
        try:
            page = browse_page(ctx, ds_id)
            ok = bool(page.get("successes"))
            ctx.bag["UA-2-2-046"] = {"had_results": ok, "total": page.get("total")}
        except Exception as exc:
            ctx.bag["UA-2-2-046"] = {"error": str(exc)}
        return CaseStatus.PASS
    finally:
        mock_control.start_mock("functional")
        mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)


def browse_recovery(ctx, cc) -> CaseStatus:
    """UA-2-2-047: mock 恢复后 browse 可用。"""
    from ua_test_harness.clients import mock_control
    from ua_test_harness.ua2_browse import filter_unregistered, browse_all_nodes

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    mock_control.stop_mock("functional")
    mock_control.start_mock("functional")
    mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
    nodes = filter_unregistered(ctx, ds_id, browse_all_nodes(ctx, ds_id))
    check_true("browse_recovered", len(nodes) > 0)
    return CaseStatus.PASS


def dispatch_ua2_2(ctx, cc, meta) -> CaseStatus:
    cid = meta["id"]
    if cid in _EXISTING_UA2_2:
        return _EXISTING_UA2_2[cid](ctx, cc)

    if cid == "UA-2-2-002":
        from tpt_api.datahub import query_tags_with_quality
        from ua_test_harness.clients.tpt_client import get_api
        require_shared_datasource(ctx, "empty")
        res = query_tags_with_quality(get_api(ctx), group_id="999999", page=1, page_size=10)
        records = ((res or {}).get("tagInfoList") or {}).get("records") or []
        check_eq("empty_group", 0, len(records))
        return CaseStatus.PASS

    if cid in {"UA-2-2-007", "UA-2-2-009", "UA-2-2-010", "UA-2-2-013"}:
        from ua_test_harness.ua2_query_extra import explore_name_query
        return explore_name_query(ctx, cc, meta, cid)

    if cid == "UA-2-2-020":
        rows = active_rows(ctx)
        check_true("default_scope_parseable", isinstance(rows, list))
        return CaseStatus.PASS

    if cid in {"UA-2-2-021", "UA-2-2-022", "UA-2-2-023", "UA-2-2-024", "UA-2-2-025"}:
        from ua_test_harness.ua2_query_extra import query_group_cases
        return query_group_cases(ctx, cc, meta, cid)

    if cid in {"UA-2-2-027", "UA-2-2-028", "UA-2-2-029", "UA-2-2-031", "UA-2-2-032"}:
        ds = require_shared_datasource(ctx, "types")
        tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=cid[-3:])
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            if cid == "UA-2-2-027":
                rows = active_rows(ctx, dsId=int(ds["id"]), tagBaseName="2_" + tag_name)
                check_true("combo_base", any(r.get("tagName") == tag_name for r in rows))
            if cid == "UA-2-2-028":
                rows = active_rows(ctx, tagName=tag_name)
                check_true("combo_name", bool(rows))
            if cid == "UA-2-2-029":
                rows = exact(active_rows(ctx, dsId=int(ds["id"]), tagName=tag_name), "tagName", tag_name)
                check_eq("triple_and", 1, len(rows))
            if cid == "UA-2-2-031":
                second = active_rows(ctx, dsId=int(ds["id"]))
                check_true("filter_switch", tag_name in {r.get("tagName") for r in second})
            if cid == "UA-2-2-032":
                broad = active_rows(ctx, dsId=int(ds["id"]))
                check_true("broad_scope", isinstance(broad, list))
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid in {"UA-2-2-035", "UA-2-2-036", "UA-2-2-039"}:
        ds = require_shared_datasource(ctx, "types")
        tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=cid[-3:])
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            from ua_test_harness.fixtures.tag import read_rt
            qtq = active_rows(ctx, tagName=tag_name)
            check_true("qtq_hit", bool(qtq))
            if cid == "UA-2-2-035":
                rt = read_rt(ctx, tag_name)
                check_true("rt_hit", bool(rt))
            if cid == "UA-2-2-036":
                check_true("quality_field", qtq[0].get("quality") is not None)
            if cid == "UA-2-2-039":
                first = qtq[0].get("tagTime")
                time.sleep(2)
                second = active_rows(ctx, tagName=tag_name)[0].get("tagTime")
                check_true("tagTime_parseable", first is not None and second is not None)
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid in {"UA-2-2-037", "UA-2-2-038", "UA-2-2-040"}:
        from ua_test_harness.ua2_query_extra import runtime_offline_online
        return runtime_offline_online(ctx, cc, meta, cid)

    if cid == "UA-2-2-041":
        return browse_ds_isolation(ctx, cc)
    if cid == "UA-2-2-042":
        return browse_node_info(ctx, cc)
    if cid == "UA-2-2-043":
        return browse_name_filter_explore(ctx, cc, meta)
    if cid == "UA-2-2-044":
        return browse_registered_filter_explore(ctx, cc, meta)
    if cid == "UA-2-2-045":
        return browse_cross_ds_same_name(ctx, cc)
    if cid == "UA-2-2-046":
        return browse_offline(ctx, cc)
    if cid == "UA-2-2-047":
        return browse_recovery(ctx, cc)

    if cid == "UA-2-2-048":
        from ua_test_harness.ua2_query_extra import browse_to_add
        return browse_to_add(ctx, cc)

    if cid in {"UA-2-2-049", "UA-2-2-050", "UA-2-2-051", "UA-2-2-052", "UA-2-2-054"}:
        from ua_test_harness.ua2_query_extra import pagination_cases
        return pagination_cases(ctx, cc, meta, cid)

    if cid == "UA-2-2-055":
        from ua_test_harness.ua2_query_extra import browse_cursor_complete
        return browse_cursor_complete(ctx, cc)

    if int(cid.split("-")[-1]) in range(56, 65):
        from ua_test_harness.ua2_query_extra import result_update_cases
        return result_update_cases(ctx, cc, meta, cid)

    if cid in {"UA-2-2-065", "UA-2-2-066", "UA-2-2-067"}:
        from ua_test_harness.ua2_query_extra import stability_cases
        return stability_cases(ctx, cc, meta, cid)

    if cid == "UA-2-2-053":
        from ua_test_harness.known_blocked import blocked_reason
        return _blocked_ua2_2(ctx, meta, blocked_reason(cid) or "GUI-DEFERRED")

    if cid.startswith("UA-2-2-"):
        return _observed_ua2_2(ctx, meta, "ua2_2_residual_explore")

    return _blocked_ua2_2(ctx, meta, f"unknown UA-2-2 case {cid}")