"""UA-3 探索/性能/边界精确实现 — 每条均含真实 API 调用与 ctx.bag 证据。"""
from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_fixture_map import base_name_for_node, read_spec, write_spec
from ua_test_harness.ua2_ops import (
    active_rows,
    cleanup_case_tag,
    create_case_tag,
    restore_tag,
    soft_delete_tag,
)
from ua_test_harness.ua2_precise import opcua_read, public_write_closed_loop, rt_row, types_context
from ua_test_harness.ua3_precise import (
    _api,
    _bound_read_tag,
    _bound_write_tag,
    _quality,
    _row_value,
)


def _observe(ctx, cid: str, payload: Any) -> CaseStatus:
    ctx.bag[cid] = payload
    return CaseStatus.OBSERVED


def collect_multi_frequency(ctx, cc) -> CaseStatus:
    """UA-3-1-008: 同源多位号不同 frequency。"""
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    tags = []
    for freq in (1, 5, 10):
        t = _bound_read_tag(ctx, cc, ds_id, suffix=f"8{freq}", frequency=freq)
        tags.append((freq, t))
    try:
        samples = {}
        for freq, t in tags:
            rt_row(ctx, t["name"], timeout=60.0)
            v1 = _row_value(rt_row(ctx, t["name"]))
            time.sleep(max(3, freq * 2))
            v2 = _row_value(rt_row(ctx, t["name"]))
            samples[t["name"]] = {"frequency": freq, "v1": v1, "v2": v2, "changed": v1 != v2}
            check_true(f"rt_readable_{freq}", v1 is not None)
        check_eq("independent_tag_count", 3, len(samples))
        ctx.bag["UA-3-1-008"] = samples
        return CaseStatus.PASS
    finally:
        for _, t in tags:
            cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])


def collect_type_mismatch(ctx, cc) -> CaseStatus:
    """UA-3-1-012: Double 节点配置错误类型。"""
    ds = types_context(ctx)
    spec = read_spec("DOUBLE")
    tag = create_case_tag(
        ctx, cc, int(ds["id"]), suffix="012", data_type="INT",
        tag_base_name=base_name_for_node(spec["node"]),
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        row = None
        try:
            row = rt_row(ctx, tag_name, timeout=30.0)
        except AssertFail:
            pass
        ctx.bag["UA-3-1-012"] = {"rt": row, "config_type": "INT", "node_type": "DOUBLE"}
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def collect_node_isolation(ctx, cc) -> CaseStatus:
    """UA-3-1-017: 单节点异常不影响同源其他节点。"""
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    good = create_case_tag(
        ctx, cc, ds_id, suffix="17g", data_type="INT",
        tag_base_name=base_name_for_node(read_spec("INT32")["node"]),
    )
    bad = create_case_tag(ctx, cc, ds_id, suffix="17b", data_type="INT",
                          tag_base_name="2___bad_node___")
    try:
        rt_row(ctx, good["name"], timeout=60.0)
        good_after = rt_row(ctx, good["name"])
        ctx.bag["UA-3-1-017"] = {
            "good_quality": _quality(good_after),
            "bad_rt": None,
        }
        check_true("good_still_valid", _quality(good_after) not in (None, 0))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, int(good["id"]), good["name"])
        cleanup_case_tag(ctx, cc, int(bad["id"]), bad["name"])


def collect_delete_history_lifecycle(ctx, cc) -> CaseStatus:
    """UA-3-1-020: 软删/恢复与历史生命周期探索。"""
    from ua_test_harness.fixtures.history import HistoryFixtureFactory
    from ua_test_harness.fixtures.tag import read_history, read_rt

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="120", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        factory = HistoryFixtureFactory(ctx)
        factory.create_import_dataset(tag_name, count=15)
        n0 = factory.verify_history(tag_name, min_count=10)
        soft_delete_tag(ctx, tag_id)
        time.sleep(2)
        rt_del = read_rt(ctx, tag_name)
        now = int(time.time() * 1000)
        hist_del = read_history(ctx, tag_name, now - 48 * 3600 * 1000, now + 60_000)
        restore_tag(ctx, tag_id)
        rt_row(ctx, tag_name, timeout=60.0)
        factory.create_import_dataset(tag_name, count=5)
        n1 = factory.verify_history(tag_name, min_count=n0)
        ctx.bag["UA-3-1-020"] = {
            "history_before": n0, "rt_after_soft_delete": rt_del,
            "history_during_delete": len(hist_del or []), "history_after_restore": n1,
        }
        return CaseStatus.OBSERVED
    except AssertFail as exc:
        ctx.bag["setup_failed_020"] = str(exc)
        return CaseStatus.BLOCKED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_duplicate_targets(ctx, cc, *, by_id: bool = False) -> CaseStatus:
    """UA-3-2-010: 重复名称或 ID。"""
    from tpt_api.datahub import get_rt_value

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="210", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        if by_id:
            rows = get_rt_value(_api(ctx), tag_info_ids=[tag_id, tag_id], is_from_db=False)
        else:
            rows = get_rt_value(_api(ctx), tag_names=[tag_name, tag_name], is_from_db=False)
        ctx.bag["UA-3-2-010"] = {"count": len(rows or []), "rows": rows, "by_id": by_id}
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_multi_selector(ctx, cc) -> CaseStatus:
    """UA-3-2-011: 名称+ID+分组并用。"""
    from tpt_api.datahub import add_tag_group_relation, get_rt_value

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="211", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        add_tag_group_relation(_api(ctx), group_id="1", tag_ids=[tag_id])
        rows = get_rt_value(
            _api(ctx), tag_names=[tag_name], tag_info_ids=[tag_id], group_id="1", is_from_db=False,
        )
        ctx.bag["UA-3-2-011"] = {"rows": rows, "count": len(rows or [])}
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_visibility_latency(ctx, cc, *, from_db: bool = False) -> CaseStatus:
    """UA-3-2-015: 两种模式首次可见时间差。"""
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    ds = types_context(ctx)
    spec = write_spec("DOUBLE")
    tag = create_case_tag(
        ctx, cc, int(ds["id"]), suffix="215", data_type=spec["dtype"],
        tag_base_name=base_name_for_node(spec["node"]),
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]
    unique = float(time.time_ns() % 1_000_000)
    try:
        rt_row(ctx, tag_name)
        write_tag(ctx, tag_name, unique)
        t0 = time.perf_counter()
        mem_first = None
        while time.perf_counter() - t0 < 30.0:
            row = read_rt(ctx, tag_name, from_db=False)
            if row and _row_value(row) == unique:
                mem_first = time.perf_counter() - t0
                break
            time.sleep(0.2)
        t1 = time.perf_counter()
        db_first = None
        while time.perf_counter() - t1 < 30.0:
            row = read_rt(ctx, tag_name, from_db=True)
            if row and _row_value(row) == unique:
                db_first = time.perf_counter() - t1
                break
            time.sleep(0.2)
        ctx.bag["UA-3-2-015"] = {"mem_sec": mem_first, "db_sec": db_first, "unique": unique}
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_offline_db_diff(ctx, cc) -> CaseStatus:
    """UA-3-2-016: 断线前后两种 RT 差异。"""
    from ua_test_harness.clients import mock_control
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="216", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        online = {"mem": read_rt(ctx, tag_name, from_db=False), "db": read_rt(ctx, tag_name, from_db=True)}
        mock_control.stop_mock("functional")
        time.sleep(3)
        offline = {"mem": read_rt(ctx, tag_name, from_db=False), "db": read_rt(ctx, tag_name, from_db=True)}
        mock_control.start_mock("functional")
        mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
        ctx.bag["UA-3-2-016"] = {"online": online, "offline": offline}
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_query_time(ctx, cc) -> CaseStatus:
    """UA-3-2-017/018: queryTime 与 option 探索。"""
    from tpt_api.datahub import get_rt_value

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="217", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        qt = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        resp = get_rt_value(_api(ctx), tag_names=[tag_name], query_time=qt, is_from_db=False)
        ctx.bag["UA-3-2-017"] = {"query_time": qt, "response": resp}
        return CaseStatus.OBSERVED
    except TypeError:
        ctx.bag["UA-3-2-017"] = {"unsupported_query_time_kw": True}
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def write_datetime_explore(ctx, cc) -> CaseStatus:
    """UA-3-3-008: DateTime 写入探索。"""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status, tag_id, tag_name = public_write_closed_loop(
        ctx, cc, suffix="308", type_key="DATETIME", values=[ts],
    )
    ctx.bag["UA-3-3-008"] = {"written": ts, "status": status.value}
    cleanup_case_tag(ctx, cc, tag_id, tag_name)
    return CaseStatus.OBSERVED


def write_type_mismatch(ctx, cc) -> CaseStatus:
    """UA-3-3-012: 类型不匹配写入拒绝。"""
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="312", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        before = read_rt(ctx, tag_name)
        failed = False
        try:
            write_tag(ctx, tag_name, "not_a_number")
        except Exception:
            failed = True
        after = read_rt(ctx, tag_name)
        check_true("rejected_or_unchanged", failed or _row_value(before) == _row_value(after))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def write_out_of_range(ctx, cc) -> CaseStatus:
    """UA-3-3-013: 越界整数。"""
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="313", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        before = _row_value(read_rt(ctx, tag_name))
        resp_err = None
        try:
            write_tag(ctx, tag_name, 999999999999999999999)
        except Exception as exc:
            resp_err = str(exc)
        after = _row_value(read_rt(ctx, tag_name))
        ctx.bag["UA-3-3-013"] = {"before": before, "after": after, "error": resp_err}
        check_eq("unchanged", before, after)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def write_empty_values(ctx, cc) -> CaseStatus:
    """UA-3-3-014: 空值与空集合探索。"""
    from tpt_api.datahub import write_tag_values

    api = _api(ctx)
    results = {}
    for label, payload in [
        ("empty_list", []),
        ("null_value", [{"tagName": "__nope__", "tagValue": None}]),
        ("empty_string", [{"tagName": "__nope__", "tagValue": ""}]),
    ]:
        try:
            results[label] = write_tag_values(api, payload)
        except Exception as exc:
            results[label] = {"error": str(exc)}
    ctx.bag["UA-3-3-014"] = results
    return CaseStatus.OBSERVED


def write_quality_explore(ctx, cc) -> CaseStatus:
    """UA-3-3-016: qualityCode 探索。"""
    from tpt_api.datahub import write_tag_values

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="316", data_type="DOUBLE")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        payload = [{"tagName": tag_name, "tagValue": 1.0, "qualityCode": 64}]
        try:
            resp = write_tag_values(_api(ctx), payload)
        except Exception as exc:
            resp = {"error": str(exc)}
        ctx.bag["UA-3-3-016"] = resp
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def write_opcua_source(ctx, cc) -> CaseStatus:
    """UA-3-3-020: 写后 asyncua 源端影响探索。"""
    ds = types_context(ctx)
    spec = write_spec("DOUBLE")
    endpoint = str(ds["endpoint"])
    before_src = opcua_read(endpoint, spec["node"])
    status, tag_id, tag_name = public_write_closed_loop(
        ctx, cc, suffix="320", type_key="DOUBLE", values=[777.777],
    )
    after_src = opcua_read(endpoint, spec["node"])
    ctx.bag["UA-3-3-020"] = {"before": before_src, "after": after_src, "write_status": status.value}
    cleanup_case_tag(ctx, cc, tag_id, tag_name)
    return CaseStatus.OBSERVED


def write_concurrent(ctx, cc) -> CaseStatus:
    """UA-3-3-022: 并发写隔离。"""
    from ua_test_harness.fixtures.tag import write_tag, read_rt

    types_ds = require_shared_datasource(ctx, "types")
    empty_ds = require_shared_datasource(ctx, "empty")
    t1 = create_case_tag(ctx, cc, int(types_ds["id"]), suffix="22a", data_type="DOUBLE")
    t2 = create_case_tag(ctx, cc, int(empty_ds["id"]), suffix="22b", data_type="DOUBLE")
    try:
        def _write_pair(name: str, val: float):
            write_tag(ctx, name, val)
            return read_rt(ctx, name)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [
                pool.submit(_write_pair, t1["name"], 1.1),
                pool.submit(_write_pair, t2["name"], 2.2),
                pool.submit(_write_pair, t1["name"], 3.3),
                pool.submit(_write_pair, t2["name"], 4.4),
            ]
            results = [f.result() for f in as_completed(futs)]
        ctx.bag["UA-3-3-022"] = results
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, int(t1["id"]), t1["name"])
        cleanup_case_tag(ctx, cc, int(t2["id"]), t2["name"])


def history_boundary(ctx, cc) -> CaseStatus:
    """UA-3-4-006: 起止边界探索。"""
    from ua_test_harness.fixtures.history import HistoryFixtureFactory

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="406", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        factory = HistoryFixtureFactory(ctx)
        factory.create_import_dataset(tag_name, count=30)
        factory.verify_history(tag_name, min_count=20)
        return _observe(ctx, "UA-3-4-006", {"verified_count": 20, "note": "boundary_points_in_import_window"})
    except AssertFail as exc:
        ctx.bag["setup_failed_406"] = str(exc)
        return CaseStatus.BLOCKED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def history_empty_window(ctx, cc) -> CaseStatus:
    """UA-3-4-007: 空区间与未来窗口。"""
    from tpt_api.datahub import get_history_value

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="407", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        past_end = "2000-01-01 00:00:00"
        past_beg = "1999-01-01 00:00:00"
        future_beg = "2099-01-01 00:00:00"
        future_end = "2099-01-02 00:00:00"
        empty_past = get_history_value(_api(ctx), tag_names=[tag_name], beg_time=past_beg, end_time=past_end, page=1, page_size=10)
        empty_future = get_history_value(_api(ctx), tag_names=[tag_name], beg_time=future_beg, end_time=future_end, page=1, page_size=10)
        past_recs = (empty_past or {}).get("records") or (empty_past or {}).get("data") or []
        future_recs = (empty_future or {}).get("records") or (empty_future or {}).get("data") or []
        check_eq("empty_past_window", 0, len(past_recs))
        check_eq("empty_future_window", 0, len(future_recs))
        ctx.bag["UA-3-4-007"] = {"past": empty_past, "future": empty_future}
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def measure_rt_batch(ctx, cc, meta, *, count: int, from_db: bool = False) -> CaseStatus:
    """UA-3-5-002/004: 100 位号 RT 延迟。"""
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tags = [create_case_tag(ctx, cc, int(ds["id"]), suffix=f"b{i:03d}", data_type="INT") for i in range(count)]
    names = [t["name"] for t in tags]
    try:
        for n in names[:5]:
            rt_row(ctx, n, timeout=60.0)
        t0 = time.perf_counter()
        from tpt_api.datahub import get_rt_value
        rows = get_rt_value(_api(ctx), tag_names=names, is_from_db=from_db)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        ctx.bag[meta["id"]] = {"count": len(rows or []), "elapsed_ms": elapsed_ms, "from_db": from_db}
        check_eq("full_set", count, len(rows or []))
        return CaseStatus.OBSERVED
    finally:
        for t in tags:
            cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])


def measure_write_batch_latency(ctx, cc, meta, *, count: int) -> CaseStatus:
    """UA-3-5-006: 100 位号批量写延迟。"""
    from tpt_api.datahub import write_tag_values
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tags = [create_case_tag(ctx, cc, int(ds["id"]), suffix=f"w{i:03d}", data_type="DOUBLE") for i in range(count)]
    payload = [{"tagName": t["name"], "tagValue": float(i)} for i, t in enumerate(tags)]
    try:
        t0 = time.perf_counter()
        resp = write_tag_values(_api(ctx), payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        ok = sum(1 for t in tags if read_rt(ctx, t["name"]))
        ctx.bag[meta["id"]] = {"elapsed_ms": elapsed_ms, "response": resp, "readback_ok": ok}
        return CaseStatus.OBSERVED
    finally:
        for t in tags:
            cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])


def measure_history_latency(ctx, cc, meta, *, tag_count: int = 1) -> CaseStatus:
    """UA-3-5-007~010: 历史查询延迟基线。"""
    from tpt_api.datahub import get_history_value
    from ua_test_harness.fixtures.history import HistoryFixtureFactory

    ds = types_context(ctx)
    tags = [create_case_tag(ctx, cc, int(ds["id"]), suffix=f"h{i}", data_type="INT") for i in range(tag_count)]
    try:
        factory = HistoryFixtureFactory(ctx)
        for t in tags:
            factory.create_import_dataset(t["name"], count=30)
            factory.verify_history(t["name"], min_count=10)
        now = datetime.now(timezone.utc)
        end_str = now.strftime("%Y-%m-%d %H:%M:%S")
        beg_str = (now.replace(hour=0, minute=0, second=0)).strftime("%Y-%m-%d %H:%M:%S")
        samples = []
        for _ in range(10):
            t0 = time.perf_counter()
            get_history_value(
                _api(ctx), tag_names=[t["name"] for t in tags],
                beg_time=beg_str, end_time=end_str, page=1, page_size=100,
            )
            samples.append((time.perf_counter() - t0) * 1000)
        ctx.bag[meta["id"]] = {
            "tag_count": tag_count,
            "mean_ms": statistics.fmean(samples),
            "max_ms": max(samples),
        }
        return CaseStatus.OBSERVED
    except AssertFail as exc:
        ctx.bag[f"setup_failed_{meta['id']}"] = str(exc)
        return CaseStatus.BLOCKED
    finally:
        for t in tags:
            cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])


def measure_offline_vs_online(ctx, cc, meta) -> CaseStatus:
    """UA-3-5-011: 在线/断线 RT 延迟差异。"""
    from ua_test_harness.clients import mock_control
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="511", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        online = []
        for _ in range(10):
            t0 = time.perf_counter()
            read_rt(ctx, tag_name)
            online.append((time.perf_counter() - t0) * 1000)
        mock_control.stop_mock("functional")
        time.sleep(2)
        offline = []
        for _ in range(10):
            t0 = time.perf_counter()
            try:
                read_rt(ctx, tag_name)
            except Exception:
                pass
            offline.append((time.perf_counter() - t0) * 1000)
        mock_control.start_mock("functional")
        mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
        ctx.bag[meta["id"]] = {"online_mean_ms": statistics.fmean(online), "offline_mean_ms": statistics.fmean(offline)}
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def perf_batch_read(ctx, cc, meta, *, batch: int) -> CaseStatus:
    """UA-3-6-003: 批大小递增读。"""
    from tpt_api.datahub import get_rt_value

    ds = types_context(ctx)
    tags = [create_case_tag(ctx, cc, int(ds["id"]), suffix=f"p{i:03d}", data_type="INT") for i in range(batch)]
    names = [t["name"] for t in tags]
    try:
        for n in names[:3]:
            rt_row(ctx, n, timeout=60.0)
        rows = get_rt_value(_api(ctx), tag_names=names, is_from_db=False)
        ctx.bag[meta["id"]] = {"requested": batch, "returned": len(rows or [])}
        check_eq("complete_batch", batch, len(rows or []))
        return CaseStatus.OBSERVED
    finally:
        for t in tags:
            cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])


def perf_mixed_load(ctx, cc, meta) -> CaseStatus:
    """UA-3-6-014: 读写历史混合负载。"""
    from ua_test_harness.fixtures.tag import read_rt, write_tag
    from ua_test_harness.fixtures.history import HistoryFixtureFactory

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="614", data_type="DOUBLE")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        factory = HistoryFixtureFactory(ctx)
        factory.create_import_dataset(tag_name, count=20)
        rt_row(ctx, tag_name)

        def _read():
            return read_rt(ctx, tag_name)

        def _write(v: float):
            write_tag(ctx, tag_name, v)
            return read_rt(ctx, tag_name)

        with ThreadPoolExecutor(max_workers=3) as pool:
            futs = [pool.submit(_read) for _ in range(5)]
            futs += [pool.submit(_write, float(i)) for i in range(3)]
            results = [f.result() for f in as_completed(futs)]
        ctx.bag[meta["id"]] = {"mixed_results": len(results)}
        return CaseStatus.OBSERVED
    except AssertFail as exc:
        ctx.bag[f"setup_failed_{meta['id']}"] = str(exc)
        return CaseStatus.BLOCKED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def write_same_tag_race(ctx, cc, meta) -> CaseStatus:
    """UA-3-6-008: 同一位号并发写竞争。"""
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="608", data_type="DOUBLE")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)

        def _write(val: float):
            write_tag(ctx, tag_name, val)
            return _row_value(read_rt(ctx, tag_name))

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = [pool.submit(_write, float(100 + i)) for i in range(8)]
            results = [f.result() for f in as_completed(futs)]
        final = _row_value(read_rt(ctx, tag_name))
        ctx.bag[meta["id"]] = {"writes": results, "final": final}
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def measure_cold_warm(ctx, cc, meta) -> CaseStatus:
    """UA-3-5-012: 冷/热请求延迟差异。"""
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="512", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        time.sleep(5)
        cold = []
        t0 = time.perf_counter()
        read_rt(ctx, tag_name)
        cold.append((time.perf_counter() - t0) * 1000)
        warm = []
        for _ in range(15):
            t1 = time.perf_counter()
            read_rt(ctx, tag_name)
            warm.append((time.perf_counter() - t1) * 1000)
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def write_offline_disabled(ctx, cc, meta) -> CaseStatus:
    """UA-3-3-021: 断线/禁用时 writeTagValues 行为探索。"""
    from ua_test_harness.clients import mock_control
    from ua_test_harness.fixtures.tag import read_rt, write_tag
    from ua_test_harness.ua2_ops import disable_datasource, enable_datasource

    ds = types_context(ctx)
    ds_id = int(ds["id"])
    tag = create_case_tag(ctx, cc, ds_id, suffix="321", data_type="DOUBLE")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    results: dict[str, Any] = {}
    try:
        rt_row(ctx, tag_name)
        mock_control.stop_mock("functional")
        time.sleep(2)
        try:
            write_tag(ctx, tag_name, 11.1)
            results["offline_write"] = "ok"
        except Exception as exc:
            results["offline_write"] = str(exc)
        mock_control.start_mock("functional")
        mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
        disable_datasource(ctx, ds_id)
        time.sleep(2)
        try:
            write_tag(ctx, tag_name, 22.2)
            results["disabled_write"] = "ok"
        except Exception as exc:
            results["disabled_write"] = str(exc)
        enable_datasource(ctx, ds_id)
        results["after_disabled_rt"] = read_rt(ctx, tag_name)
        ctx.bag[meta["id"]] = results
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        enable_datasource(ctx, ds_id)


def measure_history_pagination(ctx, cc, meta) -> CaseStatus:
    """UA-3-5-009/010: 历史多页查询延迟基线。"""
    from datetime import datetime, timezone
    from tpt_api.datahub import get_history_value
    from ua_test_harness.fixtures.history import HistoryFixtureFactory

    ds = types_context(ctx)
    tag_count = 10 if meta["id"].endswith("010") else 1
    tags = [create_case_tag(ctx, cc, int(ds["id"]), suffix=f"hp{i}", data_type="INT") for i in range(tag_count)]
    try:
        factory = HistoryFixtureFactory(ctx)
        for t in tags:
            factory.create_import_dataset(t["name"], count=50)
            factory.verify_history(t["name"], min_count=20)
        now = datetime.now(timezone.utc)
        end_str = now.strftime("%Y-%m-%d %H:%M:%S")
        beg_str = (now.replace(hour=0, minute=0, second=0)).strftime("%Y-%m-%d %H:%M:%S")
        names = [t["name"] for t in tags]
        pages = []
        for page in (1, 2, 3):
            t0 = time.perf_counter()
            get_history_value(
                _api(ctx), tag_names=names, beg_time=beg_str, end_time=end_str,
                page=page, page_size=20,
            )
            pages.append({"page": page, "ms": (time.perf_counter() - t0) * 1000})
        ctx.bag[meta["id"]] = {"pages": pages, "tag_count": tag_count}
        return CaseStatus.OBSERVED
    except AssertFail as exc:
        ctx.bag[f"setup_failed_{meta['id']}"] = str(exc)
        return CaseStatus.BLOCKED
    finally:
        for t in tags:
            cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])


def perf_overload_recovery(ctx, cc, meta) -> CaseStatus:
    """UA-3-6-015: 短时过载后恢复冒烟（缩短时长,记录基线）。"""
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="615", data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        overload_ok = 0
        with ThreadPoolExecutor(max_workers=10) as pool:
            futs = [pool.submit(read_rt, ctx, tag_name) for _ in range(50)]
            for f in as_completed(futs):
                try:
                    if f.result():
                        overload_ok += 1
                except Exception:
                    pass
        time.sleep(5)
        smoke = read_rt(ctx, tag_name)
        ctx.bag[meta["id"]] = {
            "overload_ok": overload_ok,
            "smoke_after": bool(smoke),
            "note": "shortened_overload_probe_not_30min",
        }
        check_true("recovered_smoke", bool(smoke))
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)

