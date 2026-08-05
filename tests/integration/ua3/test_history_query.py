"""UA-3-4 历史查询 — batch 5: UA-3-4-001 .. UA-3-4-008.

Migrated from ``ua_test_harness/test_cases/UA-3-4.md``.  History data is
built with 方式 B (``importTagValue`` deterministic JSON import) per
``history-data-fixtures.md``; the datasource itself needs no live OPC UA
source for import-based queries, so each test creates a mocker-free
datasource, imports a fixed point set, queries through the basic interface
(``get_history_value`` / getHistoryValueFromDB) and/or the advanced
interface (``query_history_value`` / getHistoryValue, IPage), and performs
strict cleanup regardless of outcome.

Real-environment observations locked into the assertions:
- import lands synchronously (HTTP 200 / code=00000) and is verified by
  polling the history query until the expected value set is visible.
- history API uses local ``yyyy-MM-dd HH:mm:ss`` timestamps (no timezone).
- ``get_history_value`` returns ``{tagName: {list, total}}`` with numeric
  tagValue; ``query_history_value`` returns a MyBatis IPage dict with
  tagValue as string.
- time window closure is ``[begin, end)``: a point exactly at ``begin`` is
  returned, a point exactly at ``end`` is not (UA-3-4-006).
- invalid datetime → ``TptAPIError A0400``; reversed ``begin>end`` →
  ``TptAPIError 500 "The invalid query time"``; empty/future windows return
  ``total=0`` with an empty list (UA-3-4-007/008).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pytest

from tpt_api.datahub import (
    add_tag,
    get_history_value,
    import_tag_value,
    query_history_value,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.ua2_helpers import setup_ds_only
from tests.support.ua3_helpers import cleanup_ua3_context

_TS = "%Y-%m-%d %H:%M:%S"


def _fmt(dt: datetime) -> str:
    return dt.strftime(_TS)


def _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id: str) -> dict:
    """Create a datasource without a mocker (import-based history needs no OPC UA source)."""
    return setup_ds_only(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        nodes=None, namespace_index=1, launch_mocker=False,
    )


def _add_history_tag(api, settings, ctx: dict, case_id: str, suffix: str = "a") -> dict:
    tag_name = unique_name(settings.test_prefix, f"{case_id}-tag{suffix}")
    tag_data = add_tag(
        api, tag_name=tag_name,
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        ds_id=ctx["ds_id"],
        only_read=True,
        tag_base_name=f"1_history_{suffix}_1",
    )
    return {
        "tag_id": int(tag_data.get("id") or tag_data.get("tagId")),
        "tag_name": tag_name,
    }


def _teardown(api, ctx: dict, tags: list[dict]) -> None:
    cleanup_ua3_context(
        api,
        tag_ids=[t["tag_id"] for t in tags],
        tag_names=[t["tag_name"] for t in tags],
        ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
        mocker=None, host=None, port=None,
    )


def _import_points(api, tag_name: str, points: list[dict]) -> None:
    resp = import_tag_value(api, data=points)
    assert resp.get("is_success"), f"importTagValue failed: {resp}"


def _wait_history_values(
    api, tag_name: str, beg: str, end: str, expected: set,
    *,
    timeout: float = 180.0,
) -> dict:
    """Poll the basic interface until all expected tagValues are visible."""
    info: dict = {}

    def _ready() -> bool:
        nonlocal info
        info = get_history_value(api, [tag_name], beg_time=beg, end_time=end, page_size=500).get(
            tag_name, {}
        )
        vals = {
            float(rec.get("tagValue"))
            for rec in (info.get("list") or [])
            if rec.get("tagValue") is not None
        }
        return expected <= vals

    wait_until(f"hist:{tag_name}", _ready, timeout=timeout, interval=5.0)
    return info


def _values_of(info: dict) -> set:
    return {
        float(rec.get("tagValue"))
        for rec in (info.get("list") or [])
        if rec.get("tagValue") is not None
    }


# ---------------------------------------------------------------------------
# UA-3-4-001 基础接口_单个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-4-001", chapter="UA-3-4",
    title="基础接口_单个位号",
    preconditions=["方式 B 导入确定序列", "数据源存在"],
    steps=["importTagValue 导入 25 点", "调用 getHistoryValueFromDB", "核对返回目标窗口数据"],
    expected=["返回目标窗口数据，身份和时间正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_4_001_basic_single_tag(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-4-001"
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags = []
    try:
        tags.append(_add_history_tag(api, settings, ctx, case_id, "a"))
        tag = tags[0]["tag_name"]
        t0 = datetime.now() - timedelta(minutes=5)
        points = [
            {
                "tagName": tag, "tagValue": 340000 + i, "quality": 192,
                "tagTime": _fmt(t0 + timedelta(seconds=10 * i)),
                "appTime": _fmt(t0 + timedelta(seconds=10 * i)),
            }
            for i in range(25)
        ]
        _import_points(api, tag, points)
        expected = {340000 + i for i in range(25)}

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=6))
        info = _wait_history_values(api, tag, beg, end, expected, timeout=180.0)

        assert info.get("total") == 25, \
            f"total={info.get('total')} != 25, list={info.get('list', [])[:10]}"
        got = _values_of(info)
        assert got == expected, f"values mismatch: got={sorted(got)} expected={sorted(expected)}"
        for rec in info.get("list") or []:
            assert rec.get("tagName") == tag, f"wrong identity: {rec}"
            assert rec.get("tagTime"), f"missing tagTime: {rec}"
            from tests.support.ua2_rt_assertions import parse_required_timestamp
            parse_required_timestamp(rec["tagTime"])
            assert rec.get("quality", 0) == 192, f"quality mismatch: {rec}"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-4-002 高级接口_单个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-4-002", chapter="UA-3-4",
    title="高级接口_单个位号",
    preconditions=["方式 B 导入确定序列", "数据源存在"],
    steps=["importTagValue 导入 25 点", "调用 getHistoryValue", "核对 IPage 元数据与记录"],
    expected=["IPage 元数据和记录正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_4_002_advanced_single_tag(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-4-002"
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags = []
    try:
        tags.append(_add_history_tag(api, settings, ctx, case_id, "a"))
        tag = tags[0]["tag_name"]
        t0 = datetime.now() - timedelta(minutes=5)
        points = [
            {
                "tagName": tag, "tagValue": 340000 + i, "quality": 192,
                "tagTime": _fmt(t0 + timedelta(seconds=10 * i)),
                "appTime": _fmt(t0 + timedelta(seconds=10 * i)),
            }
            for i in range(25)
        ]
        _import_points(api, tag, points)
        expected = {340000 + i for i in range(25)}

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=6))
        _wait_history_values(api, tag, beg, end, expected, timeout=180.0)

        resp = query_history_value(
            api, [tag], beg_time=beg, end_time=end,
            interval=0, is_second=True, is_source=False, page=1, page_size=100,
        )
        assert isinstance(resp, dict), f"IPage not dict: {type(resp).__name__}"
        assert resp.get("total") == 25, f"IPage total={resp.get('total')} != 25"
        assert resp.get("current") == 1, f"IPage current={resp.get('current')}"
        assert resp.get("pages") == 1, f"IPage pages={resp.get('pages')}"
        records = resp.get("records") or []
        assert len(records) == 25, f"records len={len(records)} != 25"
        got = {
            float(rec.get("tagValue"))
            for rec in records
            if rec.get("tagValue") is not None
        }
        assert got == expected, f"values mismatch: got={sorted(got)} expected={sorted(expected)}"
        for rec in records:
            assert rec.get("tagName") == tag, f"wrong identity: {rec}"
            assert rec.get("tagTime"), f"missing tagTime: {rec}"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-4-003 两接口_基础一致性
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-4-003", chapter="UA-3-4",
    title="两接口_基础一致性",
    preconditions=["方式 B 导入确定序列", "数据源存在"],
    steps=["同窗口无采样调用两个接口", "比对核心点集合"],
    expected=["相同来源下核心点集合一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_4_003_interfaces_consistent(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-4-003"
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags = []
    try:
        tags.append(_add_history_tag(api, settings, ctx, case_id, "a"))
        tag = tags[0]["tag_name"]
        t0 = datetime.now() - timedelta(minutes=5)
        points = [
            {
                "tagName": tag, "tagValue": 340000 + i, "quality": 192,
                "tagTime": _fmt(t0 + timedelta(seconds=10 * i)),
                "appTime": _fmt(t0 + timedelta(seconds=10 * i)),
            }
            for i in range(25)
        ]
        _import_points(api, tag, points)
        expected = {340000 + i for i in range(25)}

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=6))
        _wait_history_values(api, tag, beg, end, expected, timeout=180.0)

        basic = get_history_value(api, [tag], beg_time=beg, end_time=end, page_size=500).get(tag, {})
        advanced = query_history_value(
            api, [tag], beg_time=beg, end_time=end,
            interval=0, is_second=True, is_source=False, page=1, page_size=500,
        )
        basic_vals = _values_of(basic)
        adv_records = advanced.get("records") or []
        adv_vals = {
            float(rec.get("tagValue"))
            for rec in adv_records
            if rec.get("tagValue") is not None
        }
        assert basic_vals == expected, f"basic interface missing values: {sorted(expected - basic_vals)}"
        assert adv_vals == expected, f"advanced interface missing values: {sorted(expected - adv_vals)}"
        assert basic_vals == adv_vals, \
            f"interface sets differ: basic={sorted(basic_vals)} advanced={sorted(adv_vals)}"
        assert basic.get("total") == advanced.get("total"), \
            f"totals differ: basic={basic.get('total')} advanced={advanced.get('total')}"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-4-004 多个位号查询
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-4-004", chapter="UA-3-4",
    title="多个位号查询",
    preconditions=["方式 B 导入 A/B 不同值域", "数据源存在"],
    steps=["一次查询 A、B 两个位号", "按 tagName 校验记录归属"],
    expected=["记录按 tagName 正确归属，不串位号"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_4_004_multi_tag_query(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-4-004"
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags = []
    try:
        tags.append(_add_history_tag(api, settings, ctx, case_id, "a"))
        tags.append(_add_history_tag(api, settings, ctx, case_id, "b"))
        tag_a, tag_b = tags[0]["tag_name"], tags[1]["tag_name"]
        t0 = datetime.now() - timedelta(minutes=5)
        points = []
        for i in range(10):
            tt = _fmt(t0 + timedelta(seconds=10 * i))
            points.append({"tagName": tag_a, "tagValue": 410000 + i, "quality": 192,
                           "tagTime": tt, "appTime": tt})
            points.append({"tagName": tag_b, "tagValue": 420000 + i, "quality": 192,
                           "tagTime": tt, "appTime": tt})
        _import_points(api, tag_a, points)

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=4))
        _wait_history_values(api, tag_a, beg, end, {410000 + i for i in range(10)}, timeout=180.0)
        _wait_history_values(api, tag_b, beg, end, {420000 + i for i in range(10)}, timeout=180.0)

        resp = get_history_value(api, [tag_a, tag_b], beg_time=beg, end_time=end, page_size=500)
        info_a = resp.get(tag_a, {})
        info_b = resp.get(tag_b, {})
        vals_a = _values_of(info_a)
        vals_b = _values_of(info_b)
        assert vals_a == {410000 + i for i in range(10)}, \
            f"A values wrong/crossed: got={sorted(vals_a)}"
        assert vals_b == {420000 + i for i in range(10)}, \
            f"B values wrong/crossed: got={sorted(vals_b)}"
        assert not (vals_a & vals_b), f"A and B value sets overlap: {sorted(vals_a & vals_b)}"
        for rec in info_a.get("list") or []:
            assert rec.get("tagName") == tag_a, f"record crossed to A: {rec}"
        for rec in info_b.get("list") or []:
            assert rec.get("tagName") == tag_b, f"record crossed to B: {rec}"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-4-005 时间窗口_普通范围
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-4-005", chapter="UA-3-4",
    title="时间窗口_普通范围",
    preconditions=["方式 B 导入窗口内外数据", "数据源存在"],
    steps=["窗口内外均造数", "查询窗口", "断言只返回范围内数据"],
    expected=["只返回范围内数据，不混入窗口外数据"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_4_005_window_ordinary(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-4-005"
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags = []
    try:
        tags.append(_add_history_tag(api, settings, ctx, case_id, "a"))
        tag = tags[0]["tag_name"]
        t0 = datetime.now() - timedelta(minutes=5)
        win_beg = t0
        win_end = t0 + timedelta(seconds=120)

        points = []
        # outside before window: values 0..9
        for i in range(10):
            tt = win_beg - timedelta(seconds=30 * (i + 1))
            points.append({"tagName": tag, "tagValue": 350000 + i, "quality": 192,
                           "tagTime": _fmt(tt), "appTime": _fmt(tt)})
        # inside window: values 100..119
        for i in range(20):
            tt = win_beg + timedelta(seconds=5 * i)
            points.append({"tagName": tag, "tagValue": 351000 + i, "quality": 192,
                           "tagTime": _fmt(tt), "appTime": _fmt(tt)})
        # outside after window: values 200..209
        for i in range(10):
            tt = win_end + timedelta(seconds=30 * (i + 1))
            points.append({"tagName": tag, "tagValue": 352000 + i, "quality": 192,
                           "tagTime": _fmt(tt), "appTime": _fmt(tt)})
        _import_points(api, tag, points)
        inside = {351000 + i for i in range(20)}

        beg = _fmt(win_beg)
        end = _fmt(win_end)
        info = _wait_history_values(api, tag, beg, end, inside, timeout=180.0)
        got = _values_of(info)
        assert inside <= got, f"missing in-window values: {sorted(inside - got)}"
        leaked = got - inside
        assert not leaked, f"out-of-window values leaked into result: {sorted(leaked)}"
        assert got == inside, f"unexpected extra values: {sorted(got - inside)}"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-4-006 时间窗口_起止边界 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-4-006", chapter="UA-3-4",
    title="时间窗口_起止边界",
    preconditions=["方式 B 在 begin/end 精确造点", "数据源存在"],
    steps=["在 begin-1s / begin / end / end+1s 造点", "查询 [begin, end]", "记录边界闭合规则"],
    expected=["记录边界闭合规则"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_4_006_window_boundary(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-4-006"
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags = []
    observations: dict = {}
    try:
        tags.append(_add_history_tag(api, settings, ctx, case_id, "a"))
        tag = tags[0]["tag_name"]
        t0 = datetime.now() - timedelta(minutes=5)
        begin_dt = t0 + timedelta(seconds=60)
        end_dt = begin_dt + timedelta(seconds=40)

        marker = {
            "350001_begin_minus_1s": begin_dt - timedelta(seconds=1),
            "350002_begin": begin_dt,
            "350003_end": end_dt,
            "350004_end_plus_1s": end_dt + timedelta(seconds=1),
        }
        points = [
            {
                "tagName": tag, "tagValue": int(key.split("_")[0]), "quality": 192,
                "tagTime": _fmt(dt), "appTime": _fmt(dt),
            }
            for key, dt in marker.items()
        ]
        _import_points(api, tag, points)
        expected = {350001, 350002, 350003, 350004}

        beg = _fmt(begin_dt)
        end = _fmt(end_dt)
        wide_beg = _fmt(begin_dt - timedelta(seconds=2))
        wide_end = _fmt(end_dt + timedelta(seconds=2))
        _wait_history_values(api, tag, wide_beg, wide_end, expected, timeout=180.0)
        info = get_history_value(api, [tag], beg_time=beg, end_time=end, page_size=500).get(tag, {})
        got = _values_of(info)
        observations["window"] = [beg, end]
        observations["returned_values"] = sorted(got)
        observations["rule"] = (
            "closed-on-begin_open-on-end" if 350002 in got and 350003 not in got
            else "closed-both" if 350002 in got and 350003 in got
            else "open-both" if 350002 not in got and 350003 not in got
            else "other"
        )

        assert 350002 in got, f"point exactly at begin not returned: {sorted(got)}"
        assert 350003 not in got, f"point exactly at end unexpectedly returned: {sorted(got)}"
        assert 350001 not in got, f"point before begin leaked: {sorted(got)}"
        assert 350004 not in got, f"point after end leaked: {sorted(got)}"
        assert got == {350002}, f"unexpected boundary result: {sorted(got)}"

        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)

    pytest.xfail(
        f"UA-3-4-006 boundary closure recorded: {observations['rule']} "
        f"(begin inclusive, end exclusive) returned={observations['returned_values']}; "
        "recorded as observation baseline pending spec confirmation"
    )


# ---------------------------------------------------------------------------
# UA-3-4-007 时间窗口_空区间与未来
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-4-007", chapter="UA-3-4",
    title="时间窗口_空区间与未来",
    preconditions=["方式 B 导入确定序列", "数据源存在"],
    steps=["查询无数据区间", "查询未来窗口", "断言空结果且不混入窗口外数据"],
    expected=["空结果，不混入窗口外数据"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_4_007_empty_and_future_window(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-4-007"
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags = []
    try:
        tags.append(_add_history_tag(api, settings, ctx, case_id, "a"))
        tag = tags[0]["tag_name"]
        t0 = datetime.now() - timedelta(minutes=5)
        points = [
            {
                "tagName": tag, "tagValue": 340000 + i, "quality": 192,
                "tagTime": _fmt(t0 + timedelta(seconds=10 * i)),
                "appTime": _fmt(t0 + timedelta(seconds=10 * i)),
            }
            for i in range(5)
        ]
        _import_points(api, tag, points)
        expected = {340000 + i for i in range(5)}

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=2))
        _wait_history_values(api, tag, beg, end, expected, timeout=180.0)

        # empty interval strictly between imported points
        empty_beg = _fmt(t0 + timedelta(seconds=100))
        empty_end = _fmt(t0 + timedelta(seconds=110))
        r_empty = get_history_value(api, [tag], beg_time=empty_beg, end_time=empty_end, page_size=500)
        info_empty = r_empty.get(tag, {})
        assert info_empty.get("total", 0) == 0, \
            f"empty interval returned data: total={info_empty.get('total')} list={info_empty.get('list')}"
        assert (info_empty.get("list") or []) == [], \
            f"empty interval returned records: {info_empty.get('list')}"

        # future window with no data
        future_beg = _fmt(datetime.now() + timedelta(days=1))
        future_end = _fmt(datetime.now() + timedelta(days=1, hours=1))
        r_future = get_history_value(api, [tag], beg_time=future_beg, end_time=future_end, page_size=500)
        info_future = r_future.get(tag, {})
        assert info_future.get("total", 0) == 0, \
            f"future window returned data: total={info_future.get('total')} list={info_future.get('list')}"
        assert (info_future.get("list") or []) == [], \
            f"future window returned records: {info_future.get('list')}"

        # advanced interface empty window as well
        r_adv = query_history_value(
            api, [tag], beg_time=future_beg, end_time=future_end,
            interval=0, is_second=True, is_source=False, page=1, page_size=100,
        )
        assert r_adv.get("total", 0) == 0, \
            f"advanced future window returned total={r_adv.get('total')}: {r_adv.get('records')}"
        assert (r_adv.get("records") or []) == [], f"advanced future records: {r_adv.get('records')}"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-4-008 时间参数_非法与反向
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-4-008", chapter="UA-3-4",
    title="时间参数_非法与反向",
    preconditions=["数据源存在", "位号已创建"],
    steps=["非法时间格式查询", "begin>end 反向查询", "断言明确失败且不返回错误数据"],
    expected=["明确失败，不返回错误数据"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_4_008_invalid_and_reversed_params(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-4-008"
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags = []
    try:
        tags.append(_add_history_tag(api, settings, ctx, case_id, "a"))
        tag = tags[0]["tag_name"]
        t0 = datetime.now() - timedelta(minutes=5)
        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=2))

        # invalid datetime format -> explicit A0400 parameter error
        with pytest.raises(TptAPIError) as excinfo:
            get_history_value(api, [tag], beg_time="2026-13-99 99:99:99", end_time=end, page_size=500)
        assert "A0400" in str(excinfo.value.code), \
            f"invalid format code={excinfo.value.code} msg={excinfo.value.msg}"

        # reversed begin>end -> explicit error, no data returned
        with pytest.raises(TptAPIError) as excinfo2:
            get_history_value(api, [tag], beg_time=end, end_time=beg, page_size=500)
        assert excinfo2.value.code in ("500", "A0400"), \
            f"reversed window code={excinfo2.value.code} msg={excinfo2.value.msg}"

        # advanced interface: invalid format also fails explicitly
        with pytest.raises(TptAPIError) as excinfo3:
            query_history_value(
                api, [tag], beg_time="not-a-time", end_time=end,
                interval=0, is_second=True, is_source=False, page=1, page_size=100,
            )
        assert "A0400" in str(excinfo3.value.code), \
            f"advanced invalid format code={excinfo3.value.code} msg={excinfo3.value.msg}"
    finally:
        _teardown(api, ctx, tags)
