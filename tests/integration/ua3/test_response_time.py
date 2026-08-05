"""UA-3-5 系统响应时间 — batch 5: UA-3-5-001 .. UA-3-5-012.

Migrated from ``ua_test_harness/test_cases/UA-3-5.md``.  These are 探索
(exploratory) baseline cases: no millisecond pass/fail threshold is applied;
each test warms up 5 times, executes at least 30 timed requests with a
monotonic clock over the full HTTP call, verifies data correctness on every
sample (100% required), records min/mean/P50/P95/P99/max/error-rate via
``record_property``, and ends with ``pytest.xfail`` carrying the recorded
baseline as observation (threshold pending a product SLA).

Real-environment notes locked into the helpers:
- a mocker node with ``count=N`` expands to node ids ``<name>1..<name>N``;
  ``batch_add_tags`` binds 100 tags in one request for the multi-tag cases
- ``get_rt_value`` returns one point per requested tag; a 100-tag request
  returns a 100-element list (complete set, no cross-tag)
- history cases use 方式 B (``importTagValue``) on a mocker-free datasource;
  import lands synchronously and is confirmed by polling the query
- offline (UA-3-5-011): requests complete and raise a locatable
  ``TptAPIError`` instead of hanging
- cold/hot (UA-3-5-012): first request after an idle gap is recorded
  separately from consecutive requests; no request hangs
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pytest

from tpt_api.datahub import (
    add_tag,
    batch_add_tags,
    change_ds_state,
    get_history_value,
    get_rt_value,
    import_tag_value,
    list_ds_info,
    write_tag_values,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import setup_ds_and_tag, setup_ds_only
from tests.support.ua3_helpers import (
    add_collection_tag,
    build_node,
    cleanup_ua3_context,
    cleanup_ua3_multi_context,
    node_id_from_cfg,
)

_TS = "%Y-%m-%d %H:%M:%S"


def _fmt(dt: datetime) -> str:
    return dt.strftime(_TS)


def _percentile(sorted_times: list[float], p: float) -> float:
    if not sorted_times:
        return 0.0
    k = (len(sorted_times) - 1) * p / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_times) - 1)
    if lo == hi:
        return sorted_times[lo]
    return sorted_times[lo] + (sorted_times[hi] - sorted_times[lo]) * (k - lo)


def _stats(times: list[float], errors: list[str]) -> dict:
    st = sorted(times)
    return {
        "count": len(times),
        "min": round(st[0], 4) if st else None,
        "mean": round(sum(times) / len(times), 4) if times else None,
        "p50": round(_percentile(st, 50), 4) if st else None,
        "p95": round(_percentile(st, 95), 4) if st else None,
        "p99": round(_percentile(st, 99), 4) if st else None,
        "max": round(st[-1], 4) if st else None,
        "error_rate": round(len(errors) / max(1, len(times) + len(errors)), 4),
        "errors": errors[:5],
    }


def _measure(
    call_fn,
    verify_fn,
    *,
    warmup: int = 5,
    samples: int = 30,
    name: str = "measure",
) -> tuple[dict, list[str]]:
    """Warm up then time ``samples`` calls; every result must pass ``verify_fn``.

    Latency covers the complete HTTP request (monotonic clock).  Any
    exception in a sampled call is collected into ``errors``; correctness is
    checked per sample so a wrong result can never count as low latency.
    """
    for _ in range(warmup):
        try:
            call_fn()
        except Exception:
            pass
    times: list[float] = []
    errors: list[str] = []
    for _ in range(samples):
        start = time.monotonic()
        try:
            result = call_fn()
            elapsed = time.monotonic() - start
            times.append(elapsed)
            verify_fn(result)
        except Exception as exc:
            elapsed = time.monotonic() - start
            errors.append(f"{type(exc).__name__}: {exc} (latency={elapsed:.3f}s)")
    return _stats(times, errors), errors


def _assert_correct(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(detail)


def _stop_mocker(ctx: dict) -> None:
    """Stop the mocker for this context and forget it so strict cleanup skips it."""
    mocker = ctx.get("mocker")
    if mocker is not None:
        from tests.support.mocker_process import stop_mocker
        stop_mocker(mocker)
        ctx["mocker"] = None


def _remove_ds(api, ds_id: int, ds_name: str, *, timeout: float = 900.0) -> None:
    """Disable and delete a mocker-free datasource, confirming both by polling.

    A mocker-free datasource can stay busy long after its last query (the
    platform keeps a dead-endpoint collection task running); disabling and
    deleting can each take many minutes under load and strict cleanup's fixed
    20s delete confirm window is sometimes not enough.  This re-issues the
    disable/delete periodically while polling for dsStatus==0 and absence by
    id/name, so the caller can skip the datasource in strict cleanup without
    leaking it.
    """
    from tpt_api.datahub import delete_ds_info

    deadline = time.monotonic() + timeout
    last_action = time.monotonic()
    confirmed_gone_at: float | None = None
    while time.monotonic() < deadline:
        rows = list_ds_info(api, page=1, page_size=999).get("records") or []
        rec = next((r for r in rows if int(r.get("id", -1)) == ds_id), None)
        gone = rec is None
        if gone:
            if confirmed_gone_at is None:
                confirmed_gone_at = time.monotonic()
            elif time.monotonic() - confirmed_gone_at >= 45.0:
                return
        else:
            confirmed_gone_at = None
            if int(rec.get("dsStatus", -1)) == 0 and time.monotonic() - last_action >= 15.0:
                try:
                    delete_ds_info(api, [ds_id])
                    last_action = time.monotonic()
                except Exception:
                    pass
            elif int(rec.get("dsStatus", -1)) != 0 and time.monotonic() - last_action >= 15.0:
                try:
                    change_ds_state(api, ds_id, False)
                    last_action = time.monotonic()
                except Exception:
                    pass
        time.sleep(5.0)
    raise AssertionError(
        f"datasource id={ds_id} name={ds_name!r} could not be disabled/deleted "
        f"within {timeout:.0f}s"
    )


# ---------------------------------------------------------------------------
# UA-3-5-001 实时读_实时库单个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-001", chapter="UA-3-5",
    title="实时读_实时库单个位号",
    preconditions=["数据源 alive=true", "在线可读位号"],
    steps=["预热 5 次", "读取 1 个位号至少 30 次", "逐次校验数据正确", "记录延迟分布"],
    expected=["输出延迟分布", "数据正确率 100%"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_5_001_rt_single(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-001"
    prefix = "ua35_001"
    node = build_node(f"{prefix}_val_", "Double", 12.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=[node], namespace_index=1)
    tags = []
    observations: dict = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        from tests.support.ua3_helpers import wait_rt_valid
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        tag_name = tags[0]["tag_name"]

        stats, errors = _measure(
            lambda: get_rt_value(api, tag_names=[tag_name]),
            lambda result: _assert_correct(
                isinstance(result, list) and len(result) == 1
                and result[0].get("tagName") == tag_name
                and result[0].get("quality", 0) != 0
                and result[0].get("tagValue") is not None,
                f"bad RT single read: {result}",
            ),
            name="rt_single",
        )
        observations["stats"] = stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert not errors, f"errors in samples: {errors}"
        assert stats["count"] == 30, f"sample count {stats['count']} != 30"
    finally:
        cleanup_ua3_context(
            api, tag_ids=[t["tag_id"] for t in tags], tag_names=[t["tag_name"] for t in tags],
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        f"UA-3-5-001 baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-002 实时读_实时库100个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-002", chapter="UA-3-5",
    title="实时读_实时库100个位号",
    preconditions=["数据源 alive=true", "100 个可读位号"],
    steps=["预热 5 次", "单请求读取 100 个位号至少 30 次", "校验集合完整", "记录延迟分布"],
    expected=["返回集合完整，无串值"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_5_002_rt_100(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-002"
    prefix = "ua35_002"
    node_cfg = {"name": f"{prefix}_val_", "type": "Double", "count": 100,
                "change": False, "writable": True, "default": 7.5}
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=[node_cfg], namespace_index=1)
    tag_ids: list[int] = []
    tag_names = []
    observations: dict = {}
    try:
        infos = []
        for i in range(1, 101):
            tn = unique_name(settings.test_prefix, f"{case_id}-t{i}")
            tag_names.append(tn)
            infos.append({
                "dsId": ctx["ds_id"],
                "tagName": tn,
                "tagBaseName": f"1_{prefix}_val_{i}",
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
            })
        result = batch_add_tags(api, infos, conflict_strategy=0)
        _assert_correct(isinstance(result, list) and len(result) == 100,
                        f"batch_add_tags created {len(result) if isinstance(result, list) else result} tags")
        tag_ids = [int(r.get("id")) for r in result]

        def _all_rt_valid() -> bool:
            pts = get_rt_value(api, tag_names=tag_names)
            return isinstance(pts, list) and len(pts) == 100 and all(
                p.get("tagName") in tag_names and p.get("quality", 0) != 0 for p in pts
            )
        wait_until(f"rt100:{case_id}", _all_rt_valid, timeout=90.0, interval=1.0)

        def _call():
            return get_rt_value(api, tag_names=tag_names)

        def _verify(result):
            names = {p.get("tagName") for p in result}
            _assert_correct(
                isinstance(result, list) and len(result) == 100,
                f"expected 100 points, got {len(result) if isinstance(result, list) else result}",
            )
            _assert_correct(names == set(tag_names),
                            f"set mismatch: missing={sorted(set(tag_names) - names)}")
            _assert_correct(len(names) == 100, f"duplicate tagNames in response: {len(names)}")
            _assert_correct(all(p.get("quality", 0) != 0 for p in result),
                            f"quality 0 in response: {result[:3]}")

        stats, errors = _measure(_call, _verify, name="rt_100")
        observations["stats"] = stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert not errors, f"errors in samples: {errors}"
        assert stats["count"] == 30
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(
            api, tag_ids=tag_ids, tag_names=tag_names,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=None, host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        f"UA-3-5-002 baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-003 实时读_数据库单个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-003", chapter="UA-3-5",
    title="实时读_数据库单个位号",
    preconditions=["数据源 alive=true", "位号已采集入库"],
    steps=["预热 5 次", "isFromDB=true 读取 1 个位号至少 30 次", "校验数据正确", "记录延迟分布"],
    expected=["输出数据库模式基线"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_5_003_rt_db_single(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-003"
    prefix = "ua35_003"
    node = build_node(f"{prefix}_val_", "Int32", 42, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=[node], namespace_index=1)
    tags = []
    observations: dict = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="INT"))
        from tests.support.ua3_helpers import wait_rt_valid
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        tag_name = tags[0]["tag_name"]

        def _call():
            return get_rt_value(api, tag_names=[tag_name], is_from_db=True)

        def _verify(result):
            _assert_correct(
                isinstance(result, list) and len(result) == 1
                and result[0].get("tagName") == tag_name,
                f"bad DB single read: {result}",
            )

        stats, errors = _measure(_call, _verify, name="rt_db_single")
        observations["stats"] = stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert not errors, f"errors in samples: {errors}"
    finally:
        cleanup_ua3_context(
            api, tag_ids=[t["tag_id"] for t in tags], tag_names=[t["tag_name"] for t in tags],
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        f"UA-3-5-003 baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-004 实时读_数据库100个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-004", chapter="UA-3-5",
    title="实时读_数据库100个位号",
    preconditions=["数据源 alive=true", "100 个位号已采集入库"],
    steps=["预热 5 次", "isFromDB=true 读取 100 个位号至少 30 次", "校验集合完整", "记录延迟分布"],
    expected=["返回集合完整，无随机失败"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_5_004_rt_db_100(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-004"
    prefix = "ua35_004"
    node_cfg = {"name": f"{prefix}_val_", "type": "Double", "count": 100,
                "change": False, "writable": True, "default": 3.5}
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=[node_cfg], namespace_index=1)
    tag_ids: list[int] = []
    tag_names = []
    observations: dict = {}
    try:
        infos = []
        for i in range(1, 101):
            tn = unique_name(settings.test_prefix, f"{case_id}-t{i}")
            tag_names.append(tn)
            infos.append({
                "dsId": ctx["ds_id"],
                "tagName": tn,
                "tagBaseName": f"1_{prefix}_val_{i}",
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
            })
        result = batch_add_tags(api, infos, conflict_strategy=0)
        _assert_correct(isinstance(result, list) and len(result) == 100,
                        f"batch_add_tags created {len(result) if isinstance(result, list) else result} tags")
        tag_ids = [int(r.get("id")) for r in result]

        def _all_rt_valid() -> bool:
            pts = get_rt_value(api, tag_names=tag_names, is_from_db=True)
            return isinstance(pts, list) and len(pts) == 100 and all(
                p.get("tagName") in tag_names for p in pts
            )
        wait_until(f"rtdb100:{case_id}", _all_rt_valid, timeout=120.0, interval=2.0)

        def _call():
            return get_rt_value(api, tag_names=tag_names, is_from_db=True)

        def _verify(result):
            names = {p.get("tagName") for p in result}
            _assert_correct(
                isinstance(result, list) and len(result) == 100,
                f"expected 100 points, got {len(result) if isinstance(result, list) else result}",
            )
            _assert_correct(names == set(tag_names),
                            f"set mismatch: missing={sorted(set(tag_names) - names)}")
            _assert_correct(len(names) == 100, f"duplicate tagNames: {len(names)}")

        stats, errors = _measure(_call, _verify, name="rt_db_100")
        observations["stats"] = stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert not errors, f"errors in samples: {errors}"
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(
            api, tag_ids=tag_ids, tag_names=tag_names,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=None, host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        f"UA-3-5-004 baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-005 实时写_单个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-005", chapter="UA-3-5",
    title="实时写_单个位号",
    preconditions=["数据源 alive=true", "可写位号"],
    steps=["预热 5 次", "每次写入唯一递增值至少 30 次", "读回校验", "记录延迟分布"],
    expected=["响应成功项与读回一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_5_005_write_single(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-005"
    prefix = "ua35_005"
    node = build_node(f"{prefix}_val_", "Double", 0.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        tag_base_name=f"1_{node_id}", data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"], only_read=False,
        nodes=[node], namespace_index=1, cycle=500,
    )
    tag_name = ctx["tag_name"]
    observations: dict = {}
    counter = {"n": 0}
    try:
        def _call():
            counter["n"] += 1
            value = 510000 + counter["n"]
            resp = write_tag_values(api, {tag_name: value})
            return resp, value

        def _verify(result):
            resp, value = result
            tag_names = resp.get("tagNames") or []
            fail_msg = resp.get("failMsg") or ""
            _assert_correct(tag_name in tag_names, f"write not accepted: {resp}")
            _assert_correct(tag_name not in fail_msg, f"write rejected: {fail_msg}")
            from tests.support.ua2_helpers import assert_write_accepted
            assert_write_accepted(resp, tag_name)

            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                pt = get_rt_point(api, tag_name)
                if pt.get("tagValue") is not None and float(pt.get("tagValue")) == float(value):
                    return
                time.sleep(0.5)
            raise AssertionError(f"readback mismatch: expected {value}, rt={pt}")

        stats, errors = _measure(_call, _verify, name="write_single")
        observations["stats"] = stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert not errors, f"errors in samples: {errors}"
    finally:
        cleanup_ua3_context(
            api, tag_ids=[ctx["tag_id"]], tag_names=[tag_name],
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        f"UA-3-5-005 baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-006 实时写_100个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-006", chapter="UA-3-5",
    title="实时写_100个位号",
    preconditions=["数据源 alive=true", "100 个可写位号"],
    steps=["预热 5 次", "单请求批量写 100 个位号至少 30 次", "校验成功/失败映射与读回", "记录延迟分布"],
    expected=["成功/失败映射准确，读回正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_5_006_write_100(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-006"
    prefix = "ua35_006"
    node_cfg = {"name": f"{prefix}_val_", "type": "Double", "count": 100,
                "change": False, "writable": True, "default": 1.0}
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=[node_cfg], namespace_index=1)
    tag_ids: list[int] = []
    tag_names = []
    observations: dict = {}
    counter = {"n": 0}
    try:
        infos = []
        for i in range(1, 101):
            tn = unique_name(settings.test_prefix, f"{case_id}-t{i}")
            tag_names.append(tn)
            infos.append({
                "dsId": ctx["ds_id"],
                "tagName": tn,
                "tagBaseName": f"1_{prefix}_val_{i}",
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
                "onlyRead": False,
            })
        result = batch_add_tags(api, infos, conflict_strategy=0)
        _assert_correct(isinstance(result, list) and len(result) == 100,
                        f"batch_add_tags created {len(result) if isinstance(result, list) else result} tags")
        tag_ids = [int(r.get("id")) for r in result]

        def _call():
            counter["n"] += 1
            values = {tn: 520000 + counter["n"] + i for i, tn in enumerate(tag_names)}
            return write_tag_values(api, values)

        def _verify(resp):
            ok_names = set(resp.get("tagNames") or [])
            fail_msg = resp.get("failMsg") or {}
            failed = set(fail_msg.keys()) if isinstance(fail_msg, dict) else set()
            _assert_correct(ok_names | failed == set(tag_names),
                            f"success/failure mapping incomplete: ok={len(ok_names)} failed={len(failed)}")
            _assert_correct(ok_names == set(tag_names),
                            f"some writes failed: {fail_msg}")

        stats, errors = _measure(_call, _verify, name="write_100")
        observations["stats"] = stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert not errors, f"errors in samples: {errors}"
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(
            api, tag_ids=tag_ids, tag_names=tag_names,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=None, host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        f"UA-3-5-006 baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-007 历史查询_短窗口单个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-007", chapter="UA-3-5",
    title="历史查询_短窗口单个位号",
    preconditions=["方式 B 制造小结果集", "数据源存在"],
    steps=["预热 5 次", "查询短窗口至少 30 次", "校验结果完整", "记录延迟分布"],
    expected=["输出短窗口基线", "结果完整"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_5_007_history_short_single(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-007"
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=None, namespace_index=1, launch_mocker=False)
    tags = []
    observations: dict = {}
    try:
        tag_name = unique_name(settings.test_prefix, f"{case_id}-t")
        tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                           tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
                           tag_base_name="1_hist_1")
        tags.append({"tag_id": int(tag_data.get("id") or tag_data.get("tagId")), "tag_name": tag_name})

        t0 = datetime.now() - timedelta(minutes=5)
        points = [{"tagName": tag_name, "tagValue": 340000 + i, "quality": 192,
                   "tagTime": _fmt(t0 + timedelta(seconds=10 * i)),
                   "appTime": _fmt(t0 + timedelta(seconds=10 * i))} for i in range(10)]
        resp = import_tag_value(api, data=points)
        _assert_correct(resp.get("is_success"), f"importTagValue failed: {resp}")

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=3))
        expected = {340000 + i for i in range(10)}

        def _ready() -> bool:
            info = get_history_value(api, [tag_name], beg_time=beg, end_time=end, page_size=500, is_source=False).get(tag_name, {})
            vals = {float(r.get("tagValue")) for r in (info.get("list") or []) if r.get("tagValue") is not None}
            return expected <= vals
        wait_until(f"hist:{case_id}", _ready, timeout=300.0, interval=5.0)

        def _call():
            return get_history_value(api, [tag_name], beg_time=beg, end_time=end, page_size=500, is_source=False)

        def _verify(result):
            info = result.get(tag_name, {})
            vals = {float(r.get("tagValue")) for r in (info.get("list") or []) if r.get("tagValue") is not None}
            _assert_correct(expected <= vals, f"history result incomplete: got={sorted(vals)}")

        stats, errors = _measure(_call, _verify, name="hist_short_single")
        observations["stats"] = stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert not errors, f"errors in samples: {errors}"
    finally:
        cleanup_ua3_context(
            api, tag_ids=[t["tag_id"] for t in tags], tag_names=[t["tag_name"] for t in tags],
            ds_id=None, ds_name=None, mocker=None, host=None, port=None,
        )
        _remove_ds(api, ctx["ds_id"], ctx["ds_name"])

    pytest.xfail(
        f"UA-3-5-007 baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-008 历史查询_短窗口10个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-008", chapter="UA-3-5",
    title="历史查询_短窗口10个位号",
    preconditions=["方式 B 制造 10 位号数据", "数据源存在"],
    steps=["预热 5 次", "查询 10 个位号至少 30 次", "校验无串位号与完整性", "记录延迟分布"],
    expected=["无串位号", "输出多位号基线"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_5_008_history_short_10(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-008"
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=None, namespace_index=1, launch_mocker=False)
    tag_ids: list[int] = []
    tag_names = []
    observations: dict = {}
    try:
        t0 = datetime.now() - timedelta(minutes=5)
        points = []
        for j in range(10):
            tn = unique_name(settings.test_prefix, f"{case_id}-t{j}")
            tag_names.append(tn)
            tag_data = add_tag(api, tag_name=tn, data_type=DataTypes["DOUBLE"],
                               tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
                               tag_base_name=f"1_hist_{j}")
            tag_ids.append(int(tag_data.get("id") or tag_data.get("tagId")))
            for i in range(8):
                tt = _fmt(t0 + timedelta(seconds=10 * i))
                points.append({"tagName": tn, "tagValue": 430000 + j * 100 + i, "quality": 192,
                               "tagTime": tt, "appTime": tt})
        resp = import_tag_value(api, data=points)
        _assert_correct(resp.get("is_success"), f"importTagValue failed: {resp}")

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=3))
        expected_by_tag = {
            tn: {430000 + j * 100 + i for i in range(8)}
            for j, tn in enumerate(tag_names)
        }

        def _ready() -> bool:
            info = get_history_value(api, tag_names, beg_time=beg, end_time=end, page_size=500, is_source=False)
            for tn, exp in expected_by_tag.items():
                vals = {float(r.get("tagValue")) for r in ((info.get(tn) or {}).get("list") or []) if r.get("tagValue") is not None}
                if not exp <= vals:
                    return False
            return True
        wait_until(f"hist10:{case_id}", _ready, timeout=300.0, interval=5.0)

        def _call():
            return get_history_value(api, tag_names, beg_time=beg, end_time=end, page_size=500, is_source=False)

        def _verify(result):
            for tn, exp in expected_by_tag.items():
                info = result.get(tn) or {}
                vals = {float(r.get("tagValue")) for r in (info.get("list") or []) if r.get("tagValue") is not None}
                _assert_correct(exp <= vals, f"{tn} history incomplete: got={sorted(vals)}")
                for rec in info.get("list") or []:
                    _assert_correct(rec.get("tagName") == tn, f"cross-tag record: {rec}")

        stats, errors = _measure(_call, _verify, name="hist_short_10")
        observations["stats"] = stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert not errors, f"errors in samples: {errors}"
    finally:
        cleanup_ua3_context(
            api, tag_ids=tag_ids, tag_names=tag_names,
            ds_id=None, ds_name=None, mocker=None, host=None, port=None,
        )
        _remove_ds(api, ctx["ds_id"], ctx["ds_name"])

    pytest.xfail(
        f"UA-3-5-008 baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-009 历史查询_中等窗口
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-009", chapter="UA-3-5",
    title="历史查询_中等窗口",
    preconditions=["方式 B 制造多页数据", "数据源存在"],
    steps=["预热 5 次", "查询多页数据至少 30 次", "校验数量正确", "记录延迟分布"],
    expected=["输出中等结果集基线", "数量正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_5_009_history_medium(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-009"
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=None, namespace_index=1, launch_mocker=False)
    tags = []
    observations: dict = {}
    try:
        tag_name = unique_name(settings.test_prefix, f"{case_id}-t")
        tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                           tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
                           tag_base_name="1_hist_med")
        tags.append({"tag_id": int(tag_data.get("id") or tag_data.get("tagId")), "tag_name": tag_name})

        t0 = datetime.now() - timedelta(minutes=5)
        n = 55  # three pages of 20 + a 15-point tail
        points = [{"tagName": tag_name, "tagValue": 340000 + i, "quality": 192,
                   "tagTime": _fmt(t0 + timedelta(seconds=10 * i)),
                   "appTime": _fmt(t0 + timedelta(seconds=10 * i))} for i in range(n)]
        resp = import_tag_value(api, data=points)
        _assert_correct(resp.get("is_success"), f"importTagValue failed: {resp}")

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=12))
        expected = {340000 + i for i in range(n)}

        def _ready() -> bool:
            info = get_history_value(api, [tag_name], beg_time=beg, end_time=end, page_size=500, is_source=False).get(tag_name, {})
            vals = {float(r.get("tagValue")) for r in (info.get("list") or []) if r.get("tagValue") is not None}
            return expected <= vals and info.get("total", 0) >= n
        wait_until(f"histmed:{case_id}", _ready, timeout=300.0, interval=5.0)

        def _call():
            return get_history_value(api, [tag_name], beg_time=beg, end_time=end, page_size=500, is_source=False)

        def _verify(result):
            info = result.get(tag_name, {})
            vals = {float(r.get("tagValue")) for r in (info.get("list") or []) if r.get("tagValue") is not None}
            _assert_correct(expected <= vals, f"medium result incomplete: got {len(vals)}/{n}")

        stats, errors = _measure(_call, _verify, name="hist_medium")
        observations["stats"] = stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert not errors, f"errors in samples: {errors}"
    finally:
        cleanup_ua3_context(
            api, tag_ids=[t["tag_id"] for t in tags], tag_names=[t["tag_name"] for t in tags],
            ds_id=None, ds_name=None, mocker=None, host=None, port=None,
        )
        _remove_ds(api, ctx["ds_id"], ctx["ds_name"])

    pytest.xfail(
        f"UA-3-5-009 baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-010 历史查询_后续分页
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-010", chapter="UA-3-5",
    title="历史查询_后续分页",
    preconditions=["方式 B 制造多页数据", "数据源存在"],
    steps=["预热 5 次", "测首页/中间页/尾页至少各 10 次", "校验各页数据正确", "记录页间延迟差异"],
    expected=["各页数据正确", "记录页间延迟差异"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_5_010_history_paging(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-010"
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=None, namespace_index=1, launch_mocker=False)
    tags = []
    observations: dict = {}
    try:
        tag_name = unique_name(settings.test_prefix, f"{case_id}-t")
        tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                           tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
                           tag_base_name="1_hist_page")
        tags.append({"tag_id": int(tag_data.get("id") or tag_data.get("tagId")), "tag_name": tag_name})

        t0 = datetime.now() - timedelta(minutes=5)
        n = 55
        points = [{"tagName": tag_name, "tagValue": 340000 + i, "quality": 192,
                   "tagTime": _fmt(t0 + timedelta(seconds=10 * i)),
                   "appTime": _fmt(t0 + timedelta(seconds=10 * i))} for i in range(n)]
        resp = import_tag_value(api, data=points)
        _assert_correct(resp.get("is_success"), f"importTagValue failed: {resp}")

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=12))
        all_expected = {340000 + i for i in range(n)}

        def _ready() -> bool:
            info = get_history_value(api, [tag_name], beg_time=beg, end_time=end, page_size=500, is_source=False).get(tag_name, {})
            vals = {float(r.get("tagValue")) for r in (info.get("list") or []) if r.get("tagValue") is not None}
            return all_expected <= vals
        wait_until(f"histpage:{case_id}", _ready, timeout=300.0, interval=5.0)

        full_info = get_history_value(api, [tag_name], beg_time=beg, end_time=end,
                                      page_size=500, is_source=False).get(tag_name, {})
        full_records = [r for r in (full_info.get("list") or []) if r.get("tagValue") is not None]
        _assert_correct(len(full_records) == n,
                        f"expected {n} records in full query, got {len(full_records)}")

        pages_stats: dict = {}
        for page in (1, 2, 3):
            slice_records = full_records[(page - 1) * 20:page * 20]
            expected_page = {float(r["tagValue"]) for r in slice_records}
            _assert_correct(len(expected_page) == len(slice_records),
                            f"page {page} slice has duplicates: {sorted(expected_page)[:5]}")

            def _call(p=page):
                return get_history_value(api, [tag_name], beg_time=beg, end_time=end,
                                         page=p, page_size=20)

            def _verify(result, exp=expected_page):
                info = result.get(tag_name, {})
                vals = {float(r.get("tagValue")) for r in (info.get("list") or []) if r.get("tagValue") is not None}
                _assert_correct(exp == vals, f"page {page} mismatch: got={sorted(vals)} expected={sorted(exp)}")

            stats, errors = _measure(_call, _verify, warmup=5, samples=10, name=f"page{page}")
            pages_stats[f"page{page}"] = stats
            _assert_correct(not errors, f"page {page} errors: {errors}")

        observations["pages"] = pages_stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        cleanup_ua3_context(
            api, tag_ids=[t["tag_id"] for t in tags], tag_names=[t["tag_name"] for t in tags],
            ds_id=None, ds_name=None, mocker=None, host=None, port=None,
        )
        _remove_ds(api, ctx["ds_id"], ctx["ds_name"])

    pytest.xfail(
        f"UA-3-5-010 baseline recorded: {json.dumps(observations, default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-011 在线与断线响应差异
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-011", chapter="UA-3-5",
    title="在线与断线响应差异",
    preconditions=["数据源 alive=true", "可读位号"],
    steps=["在线态同请求测 10 次", "断线后同请求测 10 次", "校验断线请求可结束且错误可定位"],
    expected=["断线请求可结束且错误可定位"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_5_011_online_offline(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-011"
    prefix = "ua35_011"
    node = build_node(f"{prefix}_val_", "Int32", 0, change=True)
    node_id = node_id_from_cfg(node)
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=[node], namespace_index=1)
    tags = []
    observations: dict = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="INT"))
        from tests.support.ua3_helpers import wait_rt_valid
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        tag_name = tags[0]["tag_name"]

        def _read():
            return get_rt_value(api, tag_names=[tag_name])

        online_times: list[float] = []
        online_errors: list[str] = []
        for _ in range(10):
            start = time.monotonic()
            try:
                result = _read()
                elapsed = time.monotonic() - start
                online_times.append(elapsed)
                _assert_correct(len(result) == 1 and result[0].get("quality", 0) != 0,
                                f"online read bad: {result}")
            except Exception as exc:
                online_errors.append(str(exc))

        # disable the datasource (keeps the platform endpoint but stops the source)
        from tpt_api.datahub import change_ds_state
        change_ds_state(api, ctx["ds_id"], False)

        from tests.support.ua2_helpers import is_ds_alive

        def _offline() -> bool:
            return not is_ds_alive(api, ctx["ds_id"])
        wait_until(f"ds_off:{case_id}", _offline, timeout=120.0, interval=2.0)

        offline_times: list[float] = []
        offline_errors: list[str] = []
        for _ in range(10):
            start = time.monotonic()
            try:
                _read()
                elapsed = time.monotonic() - start
                offline_times.append(elapsed)
                offline_errors.append("offline read unexpectedly succeeded")
            except TptAPIError as exc:
                elapsed = time.monotonic() - start
                offline_times.append(elapsed)
                observations.setdefault("offline_error_codes", []).append(exc.code)
            except Exception as exc:
                offline_times.append(time.monotonic() - start)
                offline_errors.append(f"offline read non-TptAPIError: {type(exc).__name__}: {exc}")

        _assert_correct(len(online_times) >= 10, f"online reads failed: {online_errors}")
        _assert_correct(len(offline_times) >= 10, f"offline reads failed: {offline_errors}")
        _assert_correct(not offline_errors, f"offline errors: {offline_errors}")
        observations["online"] = _stats(online_times, [])
        observations["offline"] = _stats(offline_times, [])
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        cleanup_ua3_context(
            api, tag_ids=[t["tag_id"] for t in tags], tag_names=[t["tag_name"] for t in tags],
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        f"UA-3-5-011 baseline recorded: {json.dumps(observations, default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-5-012 冷请求与热请求差异
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-5-012", chapter="UA-3-5",
    title="冷请求与热请求差异",
    preconditions=["数据源 alive=true", "可读位号"],
    steps=["服务空闲后首请求", "连续请求 30 次", "记录冷启动影响", "无请求挂死"],
    expected=["记录冷启动影响，无请求挂死"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_5_012_cold_hot(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-5-012"
    prefix = "ua35_012"
    node = build_node(f"{prefix}_val_", "Double", 9.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes=[node], namespace_index=1)
    tags = []
    observations: dict = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        from tests.support.ua3_helpers import wait_rt_valid
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        tag_name = tags[0]["tag_name"]

        def _read():
            return get_rt_value(api, tag_names=[tag_name])

        # cold: first request after a 10s idle gap
        time.sleep(10)
        cold_start = time.monotonic()
        cold_result = _read()
        cold_elapsed = time.monotonic() - cold_start
        _assert_correct(isinstance(cold_result, list) and len(cold_result) == 1,
                        f"cold read bad: {cold_result}")

        hot_times: list[float] = []
        hot_errors: list[str] = []
        for _ in range(30):
            start = time.monotonic()
            try:
                result = _read()
                hot_times.append(time.monotonic() - start)
                _assert_correct(len(result) == 1 and result[0].get("tagValue") is not None,
                                f"hot read bad: {result}")
            except Exception as exc:
                hot_errors.append(str(exc))

        _assert_correct(not hot_errors, f"hot errors: {hot_errors}")
        _assert_correct(len(hot_times) == 30, f"hot sample count {len(hot_times)}")
        observations["cold_seconds"] = round(cold_elapsed, 4)
        observations["hot"] = _stats(hot_times, [])
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        cleanup_ua3_context(
            api, tag_ids=[t["tag_id"] for t in tags], tag_names=[t["tag_name"] for t in tags],
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        f"UA-3-5-012 baseline recorded: {json.dumps(observations, default=str)}; "
        "threshold pending product SLA"
    )
