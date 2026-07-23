"""UA-3 精确执行器派发 — 按章节 dispatcher 路由全部 UA-3 case。"""
from __future__ import annotations

import inspect
import time
from typing import Any, Callable

from ua_test_harness.assertions import AssertFail
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import BaselineError
from ua_test_harness import ua3_precise as p
from ua_test_harness import ua3_extra as x


def _observed(ctx, meta, detail: Any = None) -> CaseStatus:
    ctx.bag[f"observed_{meta['id']}"] = detail or meta.get("title")
    return CaseStatus.OBSERVED


def _num(meta) -> int:
    return int(meta["id"].split("-")[-1])


def dispatch_ua3_1(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    n = _num(meta)
    if n == 1:
        return p.collect_read_loop(ctx, cc, suffix="001")
    if n == 2:
        return p.collect_change(ctx, cc)
    if n == 3:
        return p.collect_static(ctx, cc)
    if n == 4:
        return p.collect_13_types(ctx, cc)
    if n == 5:
        return p.collect_big_int(ctx, cc, "005", "INT64")
    if n == 6:
        return p.collect_read_loop(ctx, cc, suffix="006", type_key="DATETIME")
    if n in (7, 9):
        from ua_test_harness.ua2_precise import precise_frequency
        return precise_frequency(ctx, cc, meta)
    if n == 8:
        return x.collect_multi_frequency(ctx, cc)
    if n == 10:
        return p.collect_read_loop(ctx, cc, suffix="010")
    if n == 11:
        return p.collect_bad_node(ctx, cc)
    if n == 12:
        return x.collect_type_mismatch(ctx, cc)
    if n == 13:
        return p.collect_offline_online(ctx, cc, offline_suffix="013", online_suffix="014")
    if n == 14:
        return p.collect_offline_online(ctx, cc, offline_suffix="014", online_suffix="014")
    if n == 15:
        return p.collect_offline_online(ctx, cc, offline_suffix="150", online_suffix="151", mode="disable")
    if n == 16:
        return p.collect_offline_online(ctx, cc, offline_suffix="160", online_suffix="161", mode="disable")
    if n == 17:
        return x.collect_node_isolation(ctx, cc)
    if n == 18:
        return p.multi_ds_isolation(ctx, cc)
    if n == 19:
        try:
            from ua_test_harness.fixtures.history import HistoryFixtureFactory
            from ua_test_harness.ua2_ops import cleanup_case_tag, create_case_tag

            ds = p.types_context(ctx)
            tag = p._bound_read_tag(ctx, cc, int(ds["id"]), suffix="019")
            try:
                factory = HistoryFixtureFactory(ctx)
                factory.create_acquisition_dataset(tag["name"], count=20)
                factory.verify_history(tag["name"], min_count=10)
                return CaseStatus.PASS
            finally:
                cleanup_case_tag(ctx, cc, int(tag["id"]), tag["name"])
        except AssertFail as exc:
            ctx.bag["setup_failed_019"] = str(exc)
            return CaseStatus.BLOCKED
    if n == 20:
        return x.collect_delete_history_lifecycle(ctx, cc)
    return _observed(ctx, meta)


def dispatch_ua3_2(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    n = _num(meta)
    if n == 1:
        return p.rt_get_by_name(ctx, cc, suffix="001")
    if n == 2:
        return p.rt_get_by_id(ctx, cc)
    if n == 3:
        return p.rt_by_group(ctx, cc)
    if n == 4:
        return p.rt_cross_ds(ctx, cc)
    if n == 5:
        return p.collect_13_types(ctx, cc)
    if n == 6:
        return p.rt_invalid_name(ctx, cc)
    if n == 7:
        return p.rt_invalid_id(ctx, cc)
    if n == 8:
        return p.rt_mixed_valid_invalid(ctx, cc)
    if n == 9:
        return p.rt_empty_selectors(ctx, cc)
    if n == 10:
        return x.rt_duplicate_targets(ctx, cc, by_id=False)
    if n == 11:
        return x.rt_multi_selector(ctx, cc)
    if n == 15:
        return x.rt_visibility_latency(ctx, cc)
    if n == 16:
        return x.rt_offline_db_diff(ctx, cc)
    if n in (17, 18):
        return x.rt_query_time(ctx, cc)
    if n == 12:
        return p.rt_get_by_name(ctx, cc, suffix="012", from_db=True)
    if n == 13:
        return p.rt_get_by_id(ctx, cc, suffix="013")
    if n == 14:
        return p.rt_both_modes(ctx, cc)
    if n == 19:
        return p.rt_mixed_valid_invalid(ctx, cc, suffix="019")
    if n == 20:
        return p.rt_delete_restore(ctx, cc)
    if n == 21:
        return p.rt_stability(ctx, cc, suffix="021")
    return _observed(ctx, meta)


def dispatch_ua3_3(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    n = _num(meta)
    if n == 1:
        return p.write_single(ctx, cc)
    if n == 2:
        return p.write_batch(ctx, cc, suffix="002", count=10)
    if n == 3:
        return p.write_13_types(ctx, cc)
    if n == 4:
        return p.write_single(ctx, cc, suffix="004", value=0)
    if n == 5:
        status, tag_id, tag_name = p.public_write_closed_loop(
            ctx, cc, suffix="005", type_key="INT64", values=[9223372036854775807],
        )
        p.cleanup_case_tag(ctx, cc, tag_id, tag_name)
        return status
    if n == 6:
        return p.write_single(ctx, cc, suffix="006", value=-3.14159)
    if n == 7:
        status, tag_id, tag_name = p.public_write_closed_loop(
            ctx, cc, suffix="007", type_key="STRING", values=["中文 ABC !@#"],
        )
        p.cleanup_case_tag(ctx, cc, tag_id, tag_name)
        return status
    if n == 8:
        return x.write_datetime_explore(ctx, cc)
    if n == 9:
        return p.write_readonly_rejected(ctx, cc)
    if n == 10:
        return p.write_mixed_batch(ctx, cc, suffix="010")
    if n == 11:
        return p.write_mixed_batch(ctx, cc)
    if n == 12:
        return x.write_type_mismatch(ctx, cc)
    if n == 13:
        return x.write_out_of_range(ctx, cc)
    if n == 14:
        return x.write_empty_values(ctx, cc)
    if n == 16:
        return x.write_quality_explore(ctx, cc)
    if n == 20:
        return x.write_opcua_source(ctx, cc)
    if n == 22:
        return x.write_concurrent(ctx, cc)
    if n == 15:
        return p.write_single(ctx, cc, suffix="015")
    if n == 17:
        return p.write_mixed_batch(ctx, cc, suffix="017")
    if n == 18:
        return p.rt_both_modes(ctx, cc, suffix="018")
    if n == 19:
        try:
            from ua_test_harness.fixtures.history import HistoryFixtureFactory
            from ua_test_harness.ua2_ops import cleanup_case_tag, create_case_tag

            ds = p.types_context(ctx)
            tag = p._bound_write_tag(ctx, cc, int(ds["id"]), suffix="019w")
            try:
                factory = HistoryFixtureFactory(ctx)
                factory.create_write_dataset(tag["name"], count=5)
                factory.verify_history(tag["name"], min_count=3)
                return CaseStatus.PASS
            finally:
                cleanup_case_tag(ctx, cc, int(tag["id"]), tag["name"])
        except AssertFail as exc:
            ctx.bag["setup_failed_019"] = str(exc)
            return CaseStatus.BLOCKED
    if n == 21:
        return x.write_offline_disabled(ctx, cc, meta)
    return _observed(ctx, meta)


def dispatch_ua3_4(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    n = _num(meta)
    if n == 8:
        return p.history_invalid_time(ctx, cc)
    if n == 6:
        return x.history_boundary(ctx, cc)
    if n == 7:
        return x.history_empty_window(ctx, cc)
    if n in (1, 2, 3, 4, 5):
        return p.history_query_pair(ctx, cc, suffix=f"4{n:03d}")
    return _observed(ctx, meta)


def dispatch_ua3_5(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    n = _num(meta)
    if n == 1:
        return p.measure_rt_samples(ctx, cc, meta, from_db=False)
    if n == 3:
        return p.measure_rt_samples(ctx, cc, meta, from_db=True)
    if n == 5:
        return p.write_single(ctx, cc, suffix="005")
    if n == 2:
        return x.measure_rt_batch(ctx, cc, meta, count=100, from_db=False)
    if n == 4:
        return x.measure_rt_batch(ctx, cc, meta, count=100, from_db=True)
    if n == 6:
        return x.measure_write_batch_latency(ctx, cc, meta, count=100)
    if n == 7:
        return x.measure_history_latency(ctx, cc, meta, tag_count=1)
    if n == 8:
        return x.measure_history_latency(ctx, cc, meta, tag_count=10)
    if n in (9, 10):
        return x.measure_history_pagination(ctx, cc, meta)
    if n == 11:
        return x.measure_offline_vs_online(ctx, cc, meta)
    if n == 12:
        return x.measure_cold_warm(ctx, cc, meta)
    return _observed(ctx, meta)


def dispatch_ua3_6(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    n = _num(meta)
    if n == 1:
        return p.perf_concurrent_read(ctx, cc, meta, workers=5, requests=20)
    if n == 2:
        return p.perf_concurrent_read(ctx, cc, meta, workers=10, requests=30)
    if n == 3:
        return x.perf_batch_read(ctx, cc, meta, batch=10)
    if n == 4:
        return p.rt_by_group(ctx, cc, suffix="604")
    if n == 5:
        return p.multi_ds_isolation(ctx, cc)
    if n == 6:
        return x.write_concurrent(ctx, cc)
    if n == 7:
        return p.write_batch(ctx, cc, suffix="607", count=10)
    if n == 8:
        return x.write_same_tag_race(ctx, cc, meta)
    if n == 9:
        return x.write_concurrent(ctx, cc)
    if n == 10:
        return p.history_query_pair(ctx, cc, suffix="610", min_count=5)
    if n == 11:
        return x.measure_history_latency(ctx, cc, meta, tag_count=3)
    if n == 12:
        return x.measure_history_latency(ctx, cc, meta, tag_count=5)
    if n == 13:
        return x.history_boundary(ctx, cc)
    if n == 14:
        return x.perf_mixed_load(ctx, cc, meta)
    if n == 15:
        return x.perf_overload_recovery(ctx, cc, meta)
    return _observed(ctx, meta)


_CHAPTER_DISPATCH: dict[str, Callable] = {
    "UA-3-1": dispatch_ua3_1,
    "UA-3-2": dispatch_ua3_2,
    "UA-3-3": dispatch_ua3_3,
    "UA-3-4": dispatch_ua3_4,
    "UA-3-5": dispatch_ua3_5,
    "UA-3-6": dispatch_ua3_6,
}


def _all_ua3_ids() -> list[str]:
    from pathlib import Path
    from ua_test_harness.case_inventory import load_documented_cases

    rows, _ = load_documented_cases(Path(__file__).resolve().parents[1])
    return sorted(r["id"] for r in rows if r["id"].startswith("UA-3-"))


_EXECUTE_UA3: dict[str, Callable] = {}
for case_id in _all_ua3_ids():
    parts = case_id.split("-")
    chapter = f"{parts[0]}-{parts[1]}-{parts[2]}"
    handler = _CHAPTER_DISPATCH.get(chapter)
    if handler is not None:
        _EXECUTE_UA3[case_id] = handler


def supported_ua3_ids() -> list[str]:
    return sorted(_EXECUTE_UA3.keys())


def is_supported_ua3(case_id: str) -> bool:
    return case_id in _EXECUTE_UA3


def execute_ua3_case(ctx, cc, meta) -> CaseStatus:
    case_id = meta["id"]
    handler = _EXECUTE_UA3.get(case_id)
    if handler is None:
        raise AssertFail(f"UA-3 precise runtime has no adapter for {case_id}")
    sig = inspect.signature(handler)
    kwargs: dict[str, Any] = {}
    accepted = ("ctx", "cc", "meta")
    for name in sig.parameters:
        if name in accepted:
            kwargs[name] = {"ctx": ctx, "cc": cc, "meta": meta}[name]
    try:
        return handler(**kwargs)
    except BaselineError:
        return CaseStatus.BLOCKED
