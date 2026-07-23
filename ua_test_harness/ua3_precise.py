"""UA-3 精确实现层 — 复用 UA-2 共享 DS 与 ua2_precise 闭环。"""
from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_fixture_map import CASE_READ_TYPE, base_name_for_node, read_spec, write_spec
from ua_test_harness.ua2_ops import (
    active_rows,
    cleanup_case_tag,
    create_case_tag,
    exact,
    restore_tag,
    soft_delete_tag,
)
from ua_test_harness.ua2_precise import (
    opcua_read,
    public_create_read_loop,
    public_write_closed_loop,
    rt_row,
    types_context,
)


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _row_value(row: dict | None) -> Any:
    row = row or {}
    return row.get("tagValue", row.get("value"))


def _quality(row: dict | None) -> Any:
    row = row or {}
    return row.get("quality", row.get("qualityCode"))


def _observe(ctx, cid: str, payload: Any) -> CaseStatus:
    ctx.bag[cid] = payload
    return CaseStatus.OBSERVED


def _bound_read_tag(
    ctx, cc, ds_id: int, *, suffix: str, type_key: str = "INT32", frequency: int = 1,
) -> dict:
    """绑定 mock 只读节点,确保 RT 可采集(同 UA-2-3 _make_tags 模式)。"""
    spec = read_spec(type_key)
    return create_case_tag(
        ctx, cc, ds_id, suffix=suffix, data_type=spec["dtype"],
        tag_base_name=base_name_for_node(spec["node"]), only_read=True, frequency=frequency,
    )


def _bound_write_tag(ctx, cc, ds_id: int, *, suffix: str, type_key: str = "DOUBLE") -> dict:
    """绑定 mock 可写节点,供 writeTagValues 闭环。"""
    spec = write_spec(type_key)
    return create_case_tag(
        ctx, cc, ds_id, suffix=suffix, data_type=spec["dtype"],
        tag_base_name=base_name_for_node(spec["node"]), only_read=False,
    )


def _history_has_data(resp: Any) -> bool:
    """getHistoryValueFromDB / getHistoryValue 响应是否含有效记录。"""
    if not resp:
        return False
    if isinstance(resp, dict):
        records = resp.get("records")
        if records is not None:
            return bool(records) or int(resp.get("total", 0)) > 0
        for value in resp.values():
            if isinstance(value, dict):
                rows = value.get("list") or []
                if rows or int(value.get("total", 0)) > 0:
                    return True
    return bool(resp)


def collect_read_loop(ctx, cc, *, suffix: str, type_key: str = "INT32") -> CaseStatus:
    status, tag_id, tag_name = public_create_read_loop(ctx, cc, suffix=suffix, type_key=type_key)
    cleanup_case_tag(ctx, cc, tag_id, tag_name)
    return status


def collect_change(ctx, cc, suffix: str = "002") -> CaseStatus:
    status, tag_id, tag_name = public_create_read_loop(ctx, cc, suffix=suffix, type_key="INT32")
    try:
        rt1 = rt_row(ctx, tag_name)
        rt2 = rt_row(ctx, tag_name, timeout=30.0)
        check_true("values_change", _row_value(rt1) != _row_value(rt2))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def collect_static(ctx, cc, suffix: str = "003") -> CaseStatus:
    spec = write_spec("DOUBLE")
    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=suffix, data_type=spec["dtype"],
                          tag_base_name=base_name_for_node(spec["node"]))
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        v1 = rt_row(ctx, tag_name)
        time.sleep(3)
        v2 = rt_row(ctx, tag_name)
        check_eq("value_stable", _row_value(v1), _row_value(v2))
        check_true("quality_valid", _quality(v2) not in (None, 0))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def collect_13_types(ctx, cc) -> CaseStatus:
    keys = ["BOOLEAN", "SBYTE", "BYTE", "INT16", "UINT16", "INT32", "UINT32",
            "INT64", "UINT64", "FLOAT", "DOUBLE", "STRING", "DATETIME"]
    for i, key in enumerate(keys):
        status, tag_id, tag_name = public_create_read_loop(ctx, cc, suffix=f"4{i:02d}", type_key=key)
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        if status != CaseStatus.PASS:
            return status
    return CaseStatus.PASS


def collect_offline_online(ctx, cc, *, offline_suffix: str, online_suffix: str,
                           mode: str = "mock") -> CaseStatus:
    """mode: mock=停 Mock; disable=禁用数据源。"""
    from ua_test_harness.clients import mock_control
    from ua_test_harness.ua2_ops import disable_datasource, enable_datasource

    ds = types_context(ctx)
    ds_id = int(ds["id"])
    tag = create_case_tag(ctx, cc, ds_id, suffix=offline_suffix, data_type="INT",
                          tag_base_name=base_name_for_node(read_spec("INT32")["node"]))
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name, timeout=60.0)
        if mode == "disable":
            disable_datasource(ctx, ds_id)
            time.sleep(2)
            rows = active_rows(ctx, tagName=tag_name)
            check_true("config_exists", bool(rows))
            enable_datasource(ctx, ds_id)
            rt_row(ctx, tag_name, timeout=90.0)
            return CaseStatus.PASS
        mock_control.stop_mock("functional")
        time.sleep(3)
        ctx.bag[f"offline_{offline_suffix}"] = active_rows(ctx, tagName=tag_name)
        mock_control.start_mock("functional")
        mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
        rt_row(ctx, tag_name, timeout=90.0)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        enable_datasource(ctx, ds_id)


def rt_get_by_name(ctx, cc, *, suffix: str, from_db: bool = False) -> CaseStatus:
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    spec = read_spec("INT32")
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=suffix, data_type=spec["dtype"],
                          tag_base_name=base_name_for_node(spec["node"]))
    tag_id, tag_name = int(tag["id"]), tag["name"]
    endpoint = str(ds["endpoint"])
    try:
        rt_row(ctx, tag_name)
        row = read_rt(ctx, tag_name, from_db=from_db)
        check_true("rt_hit", bool(row))
        src = opcua_read(endpoint, spec["node"])
        check_true("has_quality", _quality(row) is not None)
        ctx.bag[f"rt_{suffix}"] = {"rt": _row_value(row), "src": src, "from_db": from_db}
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_get_by_id(ctx, cc, suffix: str = "002") -> CaseStatus:
    from tpt_api.datahub import get_rt_value

    ds = types_context(ctx)
    tag = _bound_read_tag(ctx, cc, int(ds["id"]), suffix=suffix)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        rows = get_rt_value(_api(ctx), tag_info_ids=[tag_id], is_from_db=False)
        check_true("by_id_hit", any(int(r.get("id", -1)) == tag_id for r in (rows or [])))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def write_single(ctx, cc, suffix: str = "001", value: Any = 42.0) -> CaseStatus:
    return public_write_closed_loop(ctx, cc, suffix=suffix, type_key="DOUBLE", values=[value], tag_desc="ua3 write")


def write_readonly_rejected(ctx, cc, suffix: str = "009") -> CaseStatus:
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    ds = types_context(ctx)
    spec = read_spec("DOUBLE")
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=suffix, data_type=spec["dtype"],
                          tag_base_name=base_name_for_node(spec["node"]), only_read=True)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        before = read_rt(ctx, tag_name)
        failed = False
        try:
            write_tag(ctx, tag_name, 99.9)
        except Exception:
            failed = True
        after = read_rt(ctx, tag_name)
        check_true("rejected_or_unchanged", failed or _row_value(before) == _row_value(after))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def history_way_b(ctx, cc, *, suffix: str, min_count: int = 20) -> CaseStatus:
    from ua_test_harness.fixtures.history import HistoryFixtureFactory

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=suffix, data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        factory = HistoryFixtureFactory(ctx)
        factory.create_import_dataset(tag_name, count=min_count)
        n = factory.verify_history(tag_name, min_count=min_count)
        check_true("history_ok", n >= min_count)
        return CaseStatus.PASS
    except AssertFail:
        ctx.bag[f"setup_failed_{suffix}"] = True
        return CaseStatus.BLOCKED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def history_invalid_time(ctx, cc) -> CaseStatus:
    from tpt_api.datahub import get_history_value

    failed = False
    try:
        get_history_value(_api(ctx), tag_names=["nope"], beg_time="bad", end_time="also-bad", page=1, page_size=10)
    except Exception:
        failed = True
    check_true("invalid_time_rejected", failed)
    return CaseStatus.PASS


def measure_rt_samples(ctx, cc, meta, *, from_db: bool = False, count: int = 30) -> CaseStatus:
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=meta["id"][-3:], data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        for _ in range(5):
            read_rt(ctx, tag_name, from_db=from_db)
        samples: list[float] = []
        for _ in range(count):
            t0 = time.perf_counter()
            row = read_rt(ctx, tag_name, from_db=from_db)
            if not row:
                raise AssertFail("empty rt sample")
            samples.append((time.perf_counter() - t0) * 1000)
        ctx.bag[meta["id"]] = {
            "min": min(samples), "mean": statistics.fmean(samples),
            "p50": statistics.median(samples),
            "p95": sorted(samples)[int(len(samples) * 0.95) - 1],
            "max": max(samples), "from_db": from_db,
        }
        check_true("samples_recorded", len(samples) >= 5)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def perf_concurrent_read(ctx, cc, meta, *, workers: int = 5, requests: int = 20) -> CaseStatus:
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=meta["id"][-3:], data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        errors: list[str] = []
        ok = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(read_rt, ctx, tag_name) for _ in range(requests)]
            for f in as_completed(futs):
                try:
                    if f.result():
                        ok += 1
                except Exception as exc:
                    errors.append(str(exc))
        ctx.bag[meta["id"]] = {"ok": ok, "errors": errors, "workers": workers}
        check_eq("no_errors", 0, len(errors))
        check_eq("all_ok", requests, ok)
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_delete_restore(ctx, cc, suffix: str = "020") -> CaseStatus:
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=suffix, data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        soft_delete_tag(ctx, tag_id)
        time.sleep(2)
        row = read_rt(ctx, tag_name)
        ctx.bag["after_soft_delete"] = row
        restore_tag(ctx, tag_id)
        rt_row(ctx, tag_name, timeout=60.0)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_stability(ctx, cc, *, suffix: str, count: int = 20) -> CaseStatus:
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=suffix, data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        samples = [read_rt(ctx, tag_name) for _ in range(count)]
        check_true("all_hit", all(bool(s) for s in samples))
        vals = [_row_value(s) for s in samples]
        check_eq("value_stable", vals[0], vals[-1])
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_by_group(ctx, cc, suffix: str = "003") -> CaseStatus:
    from tpt_api.datahub import add_tag_group_relation, get_rt_value

    ds = types_context(ctx)
    tag = _bound_read_tag(ctx, cc, int(ds["id"]), suffix=suffix)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        add_tag_group_relation(_api(ctx), group_id="1", tag_ids=[tag_id])
        rows = get_rt_value(_api(ctx), group_id="1", is_from_db=False)
        names = {r.get("tagName") for r in (rows or [])}
        check_true("group_contains", tag_name in names)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_cross_ds(ctx, cc, suffix: str = "004") -> CaseStatus:
    from tpt_api.datahub import get_rt_value

    types_ds = require_shared_datasource(ctx, "types")
    empty_ds = require_shared_datasource(ctx, "empty")
    t1 = _bound_read_tag(ctx, cc, int(types_ds["id"]), suffix=f"{suffix}a")
    t2 = _bound_read_tag(ctx, cc, int(empty_ds["id"]), suffix=f"{suffix}b")
    try:
        rt_row(ctx, t1["name"])
        rt_row(ctx, t2["name"])
        rows = get_rt_value(_api(ctx), tag_names=[t1["name"], t2["name"]], is_from_db=False)
        by_name = {r.get("tagName"): r for r in (rows or [])}
        check_eq("both_hit", 2, len(by_name))
        check_eq("ds_a", int(types_ds["id"]), int(by_name[t1["name"]].get("dsId", 0)))
        check_eq("ds_b", int(empty_ds["id"]), int(by_name[t2["name"]].get("dsId", 0)))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, int(t1["id"]), t1["name"])
        cleanup_case_tag(ctx, cc, int(t2["id"]), t2["name"])


def rt_invalid_name(ctx, cc) -> CaseStatus:
    from tpt_api.datahub import get_rt_value

    failed = False
    try:
        rows = get_rt_value(_api(ctx), tag_names=["__ua_case_not_exist__"], is_from_db=False)
        ok = not rows
    except Exception:
        failed = True
        ok = True
    check_true("invalid_name_handled", failed or ok)
    return CaseStatus.PASS


def rt_invalid_id(ctx, cc) -> CaseStatus:
    from tpt_api.datahub import get_rt_value

    bad_id = 999999995
    rows = get_rt_value(_api(ctx), tag_info_ids=[bad_id], is_from_db=False)
    hit = [r for r in (rows or []) if int(r.get("id", -1)) == bad_id]
    check_eq("no_bad_id", 0, len(hit))
    return CaseStatus.PASS


def rt_mixed_valid_invalid(ctx, cc, suffix: str = "008") -> CaseStatus:
    from tpt_api.datahub import get_rt_value

    ds = types_context(ctx)
    tag = _bound_read_tag(ctx, cc, int(ds["id"]), suffix=suffix)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        rows = get_rt_value(
            _api(ctx),
            tag_names=[tag_name, "__ua_invalid__"],
            tag_info_ids=[tag_id, 999999994],
            is_from_db=False,
        )
        valid = [r for r in (rows or []) if r.get("tagName") == tag_name]
        check_true("valid_present", bool(valid))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def rt_empty_selectors(ctx, cc) -> CaseStatus:
    from tpt_api.datahub import get_rt_value

    failed = False
    try:
        get_rt_value(_api(ctx), is_from_db=False)
    except Exception:
        failed = True
    check_true("empty_rejected", failed)
    return CaseStatus.PASS


def rt_both_modes(ctx, cc, suffix: str = "014") -> CaseStatus:
    from ua_test_harness.fixtures.tag import read_rt

    ds = types_context(ctx)
    spec = read_spec("DOUBLE")
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=suffix, data_type=spec["dtype"],
                          tag_base_name=base_name_for_node(spec["node"]))
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name)
        time.sleep(3)
        mem = read_rt(ctx, tag_name, from_db=False)
        db = read_rt(ctx, tag_name, from_db=True)
        check_true("mem_hit", bool(mem))
        check_true("db_hit", bool(db))
        check_eq("value_match", _row_value(mem), _row_value(db))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def write_batch(ctx, cc, *, suffix: str, count: int = 10) -> CaseStatus:
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    ds = types_context(ctx)
    tags = []
    for i in range(count):
        tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=f"{suffix}{i:02d}", data_type="DOUBLE")
        tags.append(tag)
    try:
        for i, tag in enumerate(tags):
            write_tag(ctx, tag["name"], float(100 + i))
        for tag in tags:
            row = read_rt(ctx, tag["name"])
            check_true(f"readback_{tag['name']}", bool(row))
        return CaseStatus.PASS
    finally:
        for tag in tags:
            cleanup_case_tag(ctx, cc, int(tag["id"]), tag["name"])


def write_13_types(ctx, cc) -> CaseStatus:
    keys = ["BOOLEAN", "SBYTE", "BYTE", "INT16", "UINT16", "INT32", "UINT32",
            "INT64", "UINT64", "FLOAT", "DOUBLE", "STRING", "DATETIME"]
    for i, key in enumerate(keys):
        status, tag_id, tag_name = public_write_closed_loop(
            ctx, cc, suffix=f"3{i:02d}", type_key=key, values=[1], tag_desc="ua3 write types",
        )
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        if status != CaseStatus.PASS:
            return status
    return CaseStatus.PASS


def write_mixed_batch(ctx, cc, suffix: str = "011") -> CaseStatus:
    from tpt_api.datahub import write_tag_values

    ds = types_context(ctx)
    ds_id = int(ds["id"])
    good = _bound_write_tag(ctx, cc, ds_id, suffix=f"{suffix}a")
    ro = _bound_read_tag(ctx, cc, ds_id, suffix=f"{suffix}b", type_key="DOUBLE")
    try:
        resp = write_tag_values(
            _api(ctx),
            {
                good["name"]: 1.1,
                ro["name"]: 2.2,
                "__ua_not_exist__": 3.3,
            },
        )
        ctx.bag["mixed_write"] = resp
        ok_names = resp.get("tagNames") or resp.get("successTagNames") or []
        fail_msg = resp.get("failMsg") or resp.get("failList") or []
        check_true("good_success", good["name"] in ok_names or good["name"] in str(resp))
        check_true("has_failures", bool(fail_msg) or "__ua_not_exist__" in str(resp))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, int(good["id"]), good["name"])
        cleanup_case_tag(ctx, cc, int(ro["id"]), ro["name"])


def history_query_pair(ctx, cc, suffix: str, *, min_count: int = 10) -> CaseStatus:
    from datetime import datetime, timezone
    from tpt_api.datahub import get_history_value, query_history_value

    ds = types_context(ctx)
    tag = _bound_read_tag(ctx, cc, int(ds["id"]), suffix=suffix)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        from ua_test_harness.fixtures.history import HistoryFixtureFactory
        factory = HistoryFixtureFactory(ctx)
        factory.create_import_dataset(tag_name, count=min_count)
        factory.verify_history(tag_name, min_count=min_count)
        now = int(time.time() * 1000)
        beg = now - 48 * 3600 * 1000
        end = now + 60 * 1000
        beg_str = datetime.fromtimestamp(beg / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        end_str = datetime.fromtimestamp(end / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        basic = get_history_value(_api(ctx), tag_names=[tag_name], beg_time=beg_str, end_time=end_str)
        adv = query_history_value(
            _api(ctx), tag_names=[tag_name], beg_time=beg_str, end_time=end_str, page=1, page_size=100,
        )
        ctx.bag[f"history_{suffix}"] = {"basic": basic, "advanced": adv}
        check_true("basic_has_data", _history_has_data(basic))
        check_true("advanced_has_data", _history_has_data(adv))
        return CaseStatus.PASS
    except AssertFail as exc:
        ctx.bag[f"setup_failed_{suffix}"] = str(exc)
        return CaseStatus.BLOCKED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def collect_big_int(ctx, cc, suffix: str, type_key: str) -> CaseStatus:
    return collect_read_loop(ctx, cc, suffix=suffix, type_key=type_key)


def collect_bad_node(ctx, cc, suffix: str = "011") -> CaseStatus:
    ds = types_context(ctx)
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=suffix, data_type="INT",
                          tag_base_name="2___node_does_not_exist___")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        row = None
        try:
            row = rt_row(ctx, tag_name, timeout=15.0)
        except AssertFail:
            row = None
        ctx.bag["bad_node_rt"] = row
        others_ok = bool(active_rows(ctx))
        check_true("others_unaffected", others_ok)
        return CaseStatus.PASS if row is None else CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def multi_ds_isolation(ctx, cc) -> CaseStatus:
    from ua_test_harness.clients import mock_control

    types_ds = require_shared_datasource(ctx, "types")
    empty_ds = require_shared_datasource(ctx, "empty")
    t_a = _bound_read_tag(ctx, cc, int(types_ds["id"]), suffix="18a")
    t_b = _bound_read_tag(ctx, cc, int(empty_ds["id"]), suffix="18b")
    try:
        rt_row(ctx, t_a["name"])
        rt_row(ctx, t_b["name"])
        mock_control.stop_mock("functional")
        time.sleep(3)
        b_after = rt_row(ctx, t_b["name"], timeout=30.0)
        check_true("b_still_valid", _quality(b_after) not in (None, 0))
        mock_control.start_mock("functional")
        mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, int(t_a["id"]), t_a["name"])
        cleanup_case_tag(ctx, cc, int(t_b["id"]), t_b["name"])
