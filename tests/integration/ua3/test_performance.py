"""UA-3-6 性能测试 — batch 6: UA-3-6-001 .. UA-3-6-015.

Migrated from ``ua_test_harness/test_cases/UA-3-6.md``.  All fifteen rows are
探索 (exploratory) baseline cases: no fixed QPS/latency threshold is applied
until a product SLA exists.  Each test exercises the real DataHub backend,
verifies DATA correctness on every response (100% required), records
per-level latency / QPS / error statistics via ``record_property``, performs
strict cleanup regardless of outcome, and ends with ``pytest.xfail`` carrying
the recorded baseline.

Real-environment conventions locked into the helpers:
- concurrency uses a shared ``AlgAPI`` across ``ThreadPoolExecutor`` workers
  (httpx.Client is thread-safe for concurrent requests)
- transport errors (connect / timeout / HTTP 5xx) under load are infra noise:
  they are RECORDED, never converted into fake returns; data-correctness
  failures (``AssertionError``) always fail the test
- 方式 B history data uses ``importTagValue`` on a mocker-free datasource and
  is confirmed by polling the query before the measured phase
- 方式 C history uses ``writeTagValues`` unique sequences and is confirmed via
  ``get_history_value`` polling
- groups use ``add_tag_group`` + ``add_tag_group_relation`` and are deleted in
  cleanup even when the test fails
- mocker-free datasources are disabled/deleted with a long polling helper
  (``_remove_ds``); strict cleanup's fixed 20s confirm window is too short for
  a datasource that stayed busy under load
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from tpt_api.datahub import (
    add_tag,
    add_tag_group,
    add_tag_group_relation,
    batch_add_tags,
    change_ds_state,
    delete_ds_info,
    delete_tag_group,
    get_history_value,
    get_rt_value,
    import_tag_value,
    list_ds_info,
    query_history_value,
    write_tag_values,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.infra_retry import retry_infra_noise
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    is_ds_alive,
    opcua_read_sync,
    setup_ds_only,
)
from tests.support.ua3_helpers import (
    add_collection_tag,
    build_node,
    cleanup_ua3_context,
    cleanup_ua3_multi_context,
    node_id_from_cfg,
    wait_rt_valid,
)

_TS = "%Y-%m-%d %H:%M:%S"

_CONC_LEVELS = [1, 5, 10, 20, 50]


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


def _assert_correct(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(detail)


def _measure(call_fn, verify_fn, *, warmup: int = 2, samples: int = 5, name: str = "measure"):
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


def _wave(call_fn, verify_fn) -> dict:
    start = time.monotonic()
    try:
        result = call_fn()
        elapsed = time.monotonic() - start
        verify_fn(result)
        return {"elapsed": elapsed, "ok": True, "error": None}
    except Exception as exc:
        elapsed = time.monotonic() - start
        return {"elapsed": elapsed, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _concurrent(call_fn, verify_fn, *, workers: int, rounds: int) -> tuple[list, list, list]:
    """Run ``rounds`` waves of ``workers`` concurrent calls.

    Every returned response is verified inside the worker; correctness
    failures surface as ``AssertionError`` errors.  Returns
    (latencies, errors, waves).
    """
    times: list[float] = []
    errors: list[str] = []
    waves: list[dict] = []
    for w in range(rounds):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_wave, call_fn, verify_fn) for _ in range(workers)]
            results = [f.result() for f in futures]
        times.extend(r["elapsed"] for r in results)
        errs = [r["error"] for r in results if not r["ok"]]
        errors.extend(errs)
        waves.append({
            "wave": w + 1, "workers": workers,
            "ok": sum(1 for r in results if r["ok"]),
            "failed": len(errs), "errors": errs[:3],
        })
    return times, errors, waves


def _concurrent_levels(call_fn, verify_fn, levels, rounds: int = 2) -> dict:
    out: dict = {}
    for workers in levels:
        t0 = time.monotonic()
        times, errors, waves = _concurrent(call_fn, verify_fn, workers=workers, rounds=rounds)
        wall = time.monotonic() - t0
        total_req = sum(w["workers"] for w in waves)
        out[str(workers)] = {
            "stats": _stats(times, errors),
            "qps": round(total_req / wall, 2) if wall > 0 else None,
            "wall_seconds": round(wall, 2),
            "errors": errors[:5],
            "correctness_errors": [e for e in errors if e.startswith("AssertionError")],
            "waves": waves,
        }
    return out


def _a_disabled_error_sample(api, ctx_a: dict) -> dict:
    """Read the disabled datasource once and record the actual behavior."""
    try:
        data = get_rt_value(api, tag_names=ctx_a["tag_names"])
        return {"raised": False, "returned_points": len(data) if isinstance(data, list) else data}
    except TptAPIError as exc:
        return {"raised": True, "error_type": "TptAPIError", "code": exc.code, "msg": exc.msg}
    except Exception as exc:
        return {"raised": True, "error_type": type(exc).__name__, "msg": str(exc)}


def _inflection(level_stats: dict) -> tuple:
    prev_mean = None
    for level, st in level_stats.items():
        mean = st.get("mean")
        if mean is None:
            continue
        if prev_mean and mean > 2 * prev_mean:
            return level, round(mean / prev_mean, 2)
        prev_mean = mean
    return None, None


def _stop_mocker(ctx: dict) -> None:
    mocker = ctx.get("mocker")
    if mocker is not None:
        from tests.support.mocker_process import stop_mocker
        stop_mocker(mocker)
        ctx["mocker"] = None


def _remove_ds(api, ds_id: int, ds_name: str, *, timeout: float = 1500.0) -> None:
    """Disable and delete a mocker-free datasource, confirming both by polling."""
    from tests.support.infra_retry import is_infra_noise

    deadline = time.monotonic() + timeout
    last_action = time.monotonic()
    confirmed_gone_at: float | None = None
    while time.monotonic() < deadline:
        try:
            rows = list_ds_info(api, page=1, page_size=999).get("records") or []
        except Exception as exc:
            if not is_infra_noise(exc):
                raise
            time.sleep(5.0)
            continue
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
# setup / tag helpers
# ---------------------------------------------------------------------------
def _add_tags(api, settings, ctx: dict, case_id: str, n: int, prefix: str,
              *, only_read: bool = True) -> tuple[list[int], list[str]]:
    infos = []
    tag_names = []
    for i in range(1, n + 1):
        tn = unique_name(settings.test_prefix, f"{case_id}-t{i}")
        tag_names.append(tn)
        infos.append({
            "dsId": ctx["ds_id"],
            "tagName": tn,
            "tagBaseName": f"{ctx['namespace_index']}_{prefix}_val_{i}",
            "dataType": DataTypes["DOUBLE"],
            "tagType": TagTypes["一次位号"],
            "frequency": 10,
            "isVector": True,
            "onlyRead": only_read,
        })
    result = batch_add_tags(api, infos, conflict_strategy=0)
    _assert_correct(isinstance(result, list) and len(result) == n,
                    f"batch_add_tags created {result!r}")
    tag_ids = [int(r.get("id")) for r in result]
    return tag_ids, tag_names


def _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id: str,
                  prefix: str, n: int, *, writable: bool = False) -> dict:
    node_cfg = {"name": f"{prefix}_val_", "type": "Double", "count": n,
                "change": False, "writable": writable, "default": 12.5}
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id,
                        nodes=[node_cfg], namespace_index=1)
    tag_ids, tag_names = _add_tags(api, settings, ctx, case_id, n, prefix, only_read=not writable)
    ctx["tag_ids"] = tag_ids
    ctx["tag_names"] = tag_names
    return ctx


def _wait_rt_set(api, tag_names: list[str], *, is_from_db: bool = False,
                 timeout: float = 120.0, interval: float = 2.0) -> None:
    def _ready() -> bool:
        pts = get_rt_value(api, tag_names=tag_names, is_from_db=is_from_db)
        if not isinstance(pts, list) or len(pts) != len(tag_names):
            return False
        names = {p.get("tagName") for p in pts}
        if names != set(tag_names):
            return False
        if not is_from_db:
            return all(p.get("quality", 0) != 0 for p in pts)
        return all(p.get("tagValue") is not None for p in pts)
    wait_until(f"rt_set:{len(tag_names)}:{is_from_db}", _ready, timeout=timeout, interval=interval)


def _wait_rt_value(api, tag_name: str, expected, timeout: float = 60.0, interval: float = 0.5) -> dict:
    def _match() -> bool:
        pt = get_rt_point(api, tag_name)
        return pt.get("tagValue") is not None and float(pt.get("tagValue")) == float(expected)
    wait_until(f"rt:{tag_name}", _match, timeout=timeout, interval=interval)
    return get_rt_point(api, tag_name)


def _write_one(api, tag_name: str, value) -> dict:
    try:
        resp = write_tag_values(api, {tag_name: value})
        accepted = tag_name in (resp.get("tagNames") or [])
        fail_msg = resp.get("failMsg") or {}
        if not accepted or tag_name in fail_msg:
            return {"ok": False, "error": f"AssertionError: write not accepted: {resp}"}
        return {"ok": True, "resp": resp}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _batch_write(api, values: dict) -> dict:
    resp = write_tag_values(api, values)
    ok = set(resp.get("tagNames") or [])
    fail_msg = resp.get("failMsg") or {}
    failed = set(fail_msg.keys()) if isinstance(fail_msg, dict) else set()
    exp = set(values.keys())
    if ok | failed != exp or ok != exp:
        raise AssertionError(
            f"batch write mapping bad: ok={len(ok)} failed={len(failed)} "
            f"expected={len(exp)} failMsg={fail_msg}"
        )
    return resp


def _setup_rt_and_write(api, settings, mocker_endpoint, tmp_path_factory, case_id: str,
                        prefix: str) -> dict:
    """One datasource with two static read nodes + one writable node + tags."""
    read1 = build_node(f"{prefix}_r1_", "Double", 100.0, change=False, writable=True)
    read2 = build_node(f"{prefix}_r2_", "Double", 200.0, change=False, writable=True)
    wnode = build_node(f"{prefix}_w_", "Double", 0.0, change=False, writable=True)
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id,
                        nodes=[read1, read2, wnode], namespace_index=1)
    tags = []
    try:
        for nm in (read1, read2):
            tags.append(add_collection_tag(api, settings, ctx, case_id,
                                           node_id_str=node_id_from_cfg(nm), type_key="DOUBLE"))
        tags.append(add_collection_tag(api, settings, ctx, case_id,
                                       node_id_str=node_id_from_cfg(wnode), type_key="DOUBLE",
                                       only_read=False))
        for t in tags:
            wait_rt_valid(api, t["tag_name"], timeout=60.0)
    except Exception:
        cleanup_ua3_context(api, tag_ids=[t["tag_id"] for t in tags],
                            tag_names=[t["tag_name"] for t in tags],
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"])
        raise
    ctx["tags"] = tags
    return ctx


def _import_points(api, tag_name: str, points: list[dict]) -> None:
    resp = retry_infra_noise(
        lambda: import_tag_value(api, data=points),
        name=f"import_tag_value:{tag_name}",
    )
    _assert_correct(resp.get("is_success"), f"importTagValue failed: {resp}")


def _wait_history_values(api, tag_names: list[str], beg: str, end: str, expected_by_tag: dict | set,
                         *, timeout: float = 450.0, interval: float = 5.0) -> None:
    if isinstance(expected_by_tag, (set, frozenset)):
        if len(tag_names) != 1:
            raise AssertionError("set form of expected values requires exactly one tag")
        expected_by_tag = {tag_names[0]: expected_by_tag}

    def _ready() -> bool:
        info = get_history_value(api, tag_names, beg_time=beg, end_time=end,
                                 page_size=500, is_source=False)
        for tn, exp in expected_by_tag.items():
            vals = {float(r.get("tagValue")) for r in ((info.get(tn) or {}).get("list") or [])
                    if r.get("tagValue") is not None}
            if not exp <= vals:
                return False
        return True
    wait_until(f"hist:{len(tag_names)}", _ready, timeout=timeout, interval=interval)


def _history_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id: str) -> dict:
    return setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id,
                         nodes=None, namespace_index=1, launch_mocker=False)


def _teardown_mockerfree(api, ctx: dict, tags: list[dict]) -> None:
    cleanup_ua3_context(api, tag_ids=[t["tag_id"] for t in tags],
                        tag_names=[t["tag_name"] for t in tags],
                        ds_id=None, ds_name=None, mocker=None, host=None, port=None)
    _remove_ds(api, ctx["ds_id"], ctx["ds_name"])


def _add_history_tag(api, settings, ctx: dict, case_id: str, suffix: str) -> dict:
    tag_name = unique_name(settings.test_prefix, f"{case_id}-tag{suffix}")
    tag_data = retry_infra_noise(
        lambda: add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                        tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
                        tag_base_name=f"1_perf_{suffix}_1"),
        name=f"add_tag:{tag_name}",
    )
    return {"tag_id": int(tag_data.get("id") or tag_data.get("tagId")), "tag_name": tag_name}


# ---------------------------------------------------------------------------
# UA-3-6-001 实时读_实时库并发递增
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-001", chapter="UA-3-6",
    title="实时读_实时库并发递增",
    preconditions=["数据源 alive=true", "20 个在线位号"],
    steps=["并发 1/5/10/20/50 逐级读取", "逐响应校验集合正确无串位号", "记录拐点与延迟分布"],
    expected=["记录拐点", "值不串位号"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_001_rt_concurrency(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-001"
    prefix = "ua36_001"
    ctx = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, prefix, 20)
    tag_names = ctx["tag_names"]
    observations: dict = {}
    try:
        _wait_rt_set(api, tag_names, is_from_db=False, timeout=120.0)

        def _call():
            return get_rt_value(api, tag_names=tag_names)

        def _verify(result):
            names = {p.get("tagName") for p in result}
            _assert_correct(isinstance(result, list) and len(result) == 20 and names == set(tag_names),
                            f"RT concurrent wrong set: {len(result) if isinstance(result, list) else result}")
            _assert_correct(len(names) == 20, f"duplicate tagNames: {len(names)}")
            _assert_correct(all(p.get("quality", 0) != 0 for p in result), "quality 0 in concurrent read")

        per = _concurrent_levels(_call, _verify, _CONC_LEVELS, rounds=2)
        for workers, lvl in per.items():
            _assert_correct(not lvl["correctness_errors"],
                            f"level {workers} correctness errors: {lvl['correctness_errors']}")
        observations["levels"] = per
        inf, ratio = _inflection({k: v["stats"] for k, v in per.items()})
        observations["inflection_level"] = inf
        observations["inflection_ratio"] = ratio
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(api, tag_ids=ctx["tag_ids"], tag_names=tag_names,
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=None, host=ctx["host"], port=ctx["port"])

    pytest.xfail(
        f"UA-3-6-001 RT concurrent baseline recorded; "
        f"inflection_level={inf} inflection_ratio={ratio}; threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-002 实时读_数据库并发递增
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-002", chapter="UA-3-6",
    title="实时读_数据库并发递增",
    preconditions=["数据源 alive=true", "20 个位号已采集入库"],
    steps=["isFromDB=true 并发 1/5/10/20/50 逐级读取", "校验集合正确", "记录与实时库差异"],
    expected=["记录与实时库差异", "集合正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_002_rt_db_concurrency(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-002"
    prefix = "ua36_002"
    ctx = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, prefix, 20)
    tag_names = ctx["tag_names"]
    observations: dict = {}
    try:
        _wait_rt_set(api, tag_names, is_from_db=True, timeout=180.0, interval=3.0)

        def _call():
            return get_rt_value(api, tag_names=tag_names, is_from_db=True)

        def _verify(result):
            names = {p.get("tagName") for p in result}
            _assert_correct(isinstance(result, list) and len(result) == 20 and names == set(tag_names),
                            f"DB RT concurrent wrong set: {len(result) if isinstance(result, list) else result}")
            _assert_correct(len(names) == 20, f"duplicate tagNames: {len(names)}")

        per = _concurrent_levels(_call, _verify, _CONC_LEVELS, rounds=2)
        for workers, lvl in per.items():
            _assert_correct(not lvl["correctness_errors"],
                            f"level {workers} correctness errors: {lvl['correctness_errors']}")
        observations["levels"] = per
        inf, ratio = _inflection({k: v["stats"] for k, v in per.items()})
        observations["inflection_level"] = inf
        observations["inflection_ratio"] = ratio

        rt_pts = get_rt_value(api, tag_names=tag_names, is_from_db=False)
        db_pts = get_rt_value(api, tag_names=tag_names, is_from_db=True)
        rt_map = {p.get("tagName"): p.get("tagValue") for p in rt_pts}
        db_map = {p.get("tagName"): p.get("tagValue") for p in db_pts}
        observations["diff_count"] = sum(
            1 for tn in tag_names if str(rt_map.get(tn)) != str(db_map.get(tn))
        )
        observations["sample_diff"] = [
            {"tag": tn, "rt": rt_map.get(tn), "db": db_map.get(tn)}
            for tn in tag_names if str(rt_map.get(tn)) != str(db_map.get(tn))
        ][:5]
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(api, tag_ids=ctx["tag_ids"], tag_names=tag_names,
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=None, host=ctx["host"], port=ctx["port"])

    pytest.xfail(
        f"UA-3-6-002 DB RT concurrent baseline recorded; "
        f"inflection_level={inf} inflection_ratio={ratio}; threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-003 实时读_批大小递增
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-003", chapter="UA-3-6",
    title="实时读_批大小递增",
    preconditions=["数据源 alive=true", "100 个在线位号"],
    steps=["单请求 1/10/100 个位号", "校验集合完整无重复遗漏", "记录批大小与延迟关系"],
    expected=["返回集合完整，无重复遗漏"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_003_rt_batch_size(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-003"
    prefix = "ua36_003"
    ctx = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, prefix, 100)
    tag_names = ctx["tag_names"]
    observations: dict = {}
    try:
        _wait_rt_set(api, tag_names, is_from_db=False, timeout=120.0)

        sizes = [1, 10, 100]
        for size in sizes:
            subset = tag_names[:size]

            def _call(sub=subset):
                return get_rt_value(api, tag_names=sub)

            def _verify(result, sub=subset):
                names = {p.get("tagName") for p in result}
                _assert_correct(isinstance(result, list) and len(result) == len(sub),
                                f"batch {len(sub)} expected {len(sub)} points, got {result!r}")
                _assert_correct(names == set(sub), f"batch {len(sub)} set mismatch")
                _assert_correct(len(names) == len(sub), f"batch {len(sub)} duplicate tagNames")
                _assert_correct(all(p.get("quality", 0) != 0 for p in result), "quality 0")

            stats, errors = _measure(_call, _verify, warmup=2, samples=5, name=f"size{size}")
            _assert_correct(not errors, f"size {size} errors: {errors}")
            observations[f"size_{size}"] = stats

        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(api, tag_ids=ctx["tag_ids"], tag_names=tag_names,
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=None, host=ctx["host"], port=ctx["port"])

    pytest.xfail(
        f"UA-3-6-003 RT batch-size baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-004 实时读_按分组大集合
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-004", chapter="UA-3-6",
    title="实时读_按分组大集合",
    preconditions=["数据源 alive=true", "100 个位号已分配分组"],
    steps=["按 groupId 读取大分组", "校验无跨组记录且数量正确", "记录延迟"],
    expected=["无跨组记录", "数量正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_004_rt_group(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-004"
    prefix = "ua36_004"
    ctx = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, prefix, 100)
    tag_names = ctx["tag_names"]
    observations: dict = {}
    group_id = None
    group_errors: list[str] = []
    try:
        _wait_rt_set(api, tag_names, is_from_db=False, timeout=120.0)
        group_name = unique_name(settings.test_prefix, f"{case_id}-group")
        group_data = add_tag_group(api, group_name)
        group_id = int(group_data.get("id") or group_data.get("groupId"))
        add_tag_group_relation(api, group_id=str(group_id), tag_ids=ctx["tag_ids"])

        def _group_ready() -> bool:
            pts = get_rt_value(api, group_id=group_id, is_from_db=False)
            return isinstance(pts, list) and {p.get("tagName") for p in pts} == set(tag_names)
        wait_until(f"group:{case_id}", _group_ready, timeout=120.0, interval=2.0)

        def _call():
            return get_rt_value(api, group_id=group_id, is_from_db=False)

        def _verify(result):
            names = {p.get("tagName") for p in result}
            _assert_correct(isinstance(result, list) and len(result) == 100,
                            f"group read count {len(result) if isinstance(result, list) else result} != 100")
            _assert_correct(names == set(tag_names),
                            f"group read set mismatch: missing={sorted(set(tag_names) - names)} "
                            f"extra={sorted(names - set(tag_names))}")
            _assert_correct(len(names) == 100, f"duplicate tagNames in group read: {len(names)}")
            ds_ids = {p.get("dsId") for p in result if p.get("dsId") is not None}
            _assert_correct(ds_ids == {ctx["ds_id"]}, f"group read crossed datasources: {ds_ids}")

        stats, errors = _measure(_call, _verify, warmup=2, samples=5, name="group")
        _assert_correct(not errors, f"group read errors: {errors}")
        observations["stats"] = stats
        observations["group_id"] = group_id
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        if group_id is not None:
            try:
                delete_tag_group(api, [str(group_id)])
            except Exception as exc:
                group_errors.append(f"delete group {group_id}: {exc}")
        _stop_mocker(ctx)
        cleanup_ua3_context(api, tag_ids=ctx["tag_ids"], tag_names=tag_names,
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=None, host=ctx["host"], port=ctx["port"])
        if group_errors:
            raise AssertionError("; ".join(group_errors))

    pytest.xfail(
        f"UA-3-6-004 group read baseline recorded: {json.dumps(observations['stats'], default=str)}; "
        "threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-005 实时读_多数据源混合负载
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-005", chapter="UA-3-6",
    title="实时读_多数据源混合负载",
    preconditions=["数据源 A、B 各自在线", "各自 10 个位号"],
    steps=["A、B 同时并发读取", "使 A 异常（禁用）", "校验 B 不被拖垮且不串源"],
    expected=["B 不被拖垮", "不串源"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_005_rt_mixed_ds(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-005"
    ctx_a = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, f"{case_id}-A", "ua36_005a", 10)
    ctx_b = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, f"{case_id}-B", "ua36_005b", 10)
    observations: dict = {}
    try:
        _wait_rt_set(api, ctx_a["tag_names"], is_from_db=False, timeout=120.0)
        _wait_rt_set(api, ctx_b["tag_names"], is_from_db=False, timeout=120.0)

        # phase 1: concurrent reads on both
        def _call():
            pa = get_rt_value(api, tag_names=ctx_a["tag_names"])
            pb = get_rt_value(api, tag_names=ctx_b["tag_names"])
            return pa, pb

        def _verify(result):
            pa, pb = result
            na = {p.get("tagName") for p in pa}
            nb = {p.get("tagName") for p in pb}
            _assert_correct(set(na) == set(ctx_a["tag_names"]) and set(nb) == set(ctx_b["tag_names"]),
                            f"mixed read set wrong: na={len(na)} nb={len(nb)}")
            _assert_correct(set(na).isdisjoint(set(nb)), "cross-source tag leak in concurrent read")
            for p in pa + pb:
                _assert_correct(p.get("quality", 0) != 0, f"quality 0: {p}")

        times, errors, waves = _concurrent(_call, _verify, workers=10, rounds=3)
        observations["both_online"] = {
            "stats": _stats(times, errors),
            "correctness_errors": [e for e in errors if e.startswith("AssertionError")],
            "errors": errors[:5],
        }
        _assert_correct(not observations["both_online"]["correctness_errors"],
                        f"both-online correctness: {observations['both_online']['correctness_errors']}")

        # make A abnormal: disable it
        change_ds_state(api, ctx_a["ds_id"], False)

        def _a_offline() -> bool:
            return not is_ds_alive(api, ctx_a["ds_id"])
        wait_until(f"ds_off:{case_id}", _a_offline, timeout=120.0, interval=2.0)

        def _call_a_disabled():
            a_result = {"error": None}
            try:
                a_result["data"] = get_rt_value(api, tag_names=ctx_a["tag_names"])
            except Exception as exc:
                a_result["error"] = f"{type(exc).__name__}: {exc}"
            b_result = get_rt_value(api, tag_names=ctx_b["tag_names"])
            return a_result, b_result

        def _verify_b(result):
            a_result, pb = result
            nb = {p.get("tagName") for p in pb}
            _assert_correct(set(nb) == set(ctx_b["tag_names"]) and len(nb) == len(ctx_b["tag_names"]),
                            f"B set wrong after A disabled: {len(nb)}")
            _assert_correct(all(p.get("quality", 0) != 0 for p in pb), f"B quality 0 after A disabled")
            ds_ids = {p.get("dsId") for p in pb if p.get("dsId") is not None}
            _assert_correct(ds_ids == {ctx_b["ds_id"]}, f"B crossed datasources: {ds_ids}")

        times_b, errors_b, waves_b = _concurrent(_call_a_disabled, _verify_b, workers=10, rounds=3)
        observations["a_disabled"] = {
            "b_stats": _stats(times_b, errors_b),
            "correctness_errors": [e for e in errors_b if e.startswith("AssertionError")],
            "errors": errors_b[:5],
            "a_error_sample": _a_disabled_error_sample(api, ctx_a),
            "waves": waves_b,
        }
        _assert_correct(not observations["a_disabled"]["correctness_errors"],
                        f"A-disabled correctness: {observations['a_disabled']['correctness_errors']}")
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _stop_mocker(ctx_a)
        _stop_mocker(ctx_b)
        cleanup_ua3_multi_context(
            api,
            tags=[{"tag_id": i, "tag_name": n}
                  for i, n in zip(ctx_a["tag_ids"], ctx_a["tag_names"])]
                + [{"tag_id": i, "tag_name": n}
                   for i, n in zip(ctx_b["tag_ids"], ctx_b["tag_names"])],
            ds_contexts=[
                {"ds_id": ctx_a["ds_id"], "ds_name": ctx_a["ds_name"],
                 "mocker": None, "host": ctx_a["host"], "port": ctx_a["port"]},
                {"ds_id": ctx_b["ds_id"], "ds_name": ctx_b["ds_name"],
                 "mocker": None, "host": ctx_b["host"], "port": ctx_b["port"]},
            ],
        )

    pytest.xfail(
        f"UA-3-6-005 mixed-source read baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-006 实时写_不同位号并发
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-006", chapter="UA-3-6",
    title="实时写_不同位号并发",
    preconditions=["数据源 alive=true", "20 个可写位号"],
    steps=["20 线程并发写不同位号唯一值", "成功项全部可读回", "记录并发写延迟"],
    expected=["成功项全部可读回"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_006_write_distinct_concurrent(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-006"
    prefix = "ua36_006"
    ctx = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, prefix, 20, writable=True)
    tag_names = ctx["tag_names"]
    observations: dict = {}
    try:
        _wait_rt_set(api, tag_names, is_from_db=False, timeout=120.0)

        rounds_data: list[dict] = []
        all_errors: list[str] = []
        all_times: list[float] = []
        with ThreadPoolExecutor(max_workers=20) as pool:
            for rnd in range(3):
                base = 530000 + rnd * 1000
                t0 = time.monotonic()
                futures = [pool.submit(_write_one, api, tag_names[i], base + i) for i in range(20)]
                results = [f.result() for f in futures]
                wall = time.monotonic() - t0
                mapping = {tag_names[i]: base + i for i in range(20)}
                accepted = [tag_names[i] for i, r in enumerate(results) if r.get("ok")]
                errs = [r["error"] for r in results if not r.get("ok")]
                all_errors.extend(errs)
                all_times.append(wall)
                _wait_rt_values(api, {tn: mapping[tn] for tn in accepted}, timeout=90.0)
                rounds_data.append({
                    "round": rnd + 1, "accepted": len(accepted), "failed": len(errs),
                    "wall_seconds": round(wall, 2), "errors": errs[:3],
                })
        observations["rounds"] = rounds_data
        observations["correctness_errors"] = [e for e in all_errors if e.startswith("AssertionError")]
        observations["transport_errors"] = [e for e in all_errors if not e.startswith("AssertionError")]
        observations["round_wall_stats"] = _stats(all_times, all_errors)
        _assert_correct(not observations["correctness_errors"],
                        f"correctness: {observations['correctness_errors']}")
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(api, tag_ids=ctx["tag_ids"], tag_names=tag_names,
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=None, host=ctx["host"], port=ctx["port"])

    pytest.xfail(
        f"UA-3-6-006 concurrent distinct write baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )


def _wait_rt_values(api, mapping: dict, timeout: float = 90.0, interval: float = 1.0) -> None:
    def _ready() -> bool:
        for tn, val in mapping.items():
            pt = get_rt_point(api, tn)
            if pt.get("tagValue") is None or float(pt.get("tagValue")) != float(val):
                return False
        return True
    wait_until(f"rtmap:{len(mapping)}", _ready, timeout=timeout, interval=interval)


# ---------------------------------------------------------------------------
# UA-3-6-007 实时写_批大小递增
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-007", chapter="UA-3-6",
    title="实时写_批大小递增",
    preconditions=["数据源 alive=true", "100 个可写位号"],
    steps=["单请求 1/10/100 位号批量写", "校验成功与失败映射准确", "记录批大小与延迟关系"],
    expected=["成功与失败映射准确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_007_write_batch_size(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-007"
    prefix = "ua36_007"
    ctx = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, prefix, 100, writable=True)
    tag_names = ctx["tag_names"]
    observations: dict = {}
    counter = {"n": 0}
    try:
        _wait_rt_set(api, tag_names, is_from_db=False, timeout=120.0)

        sizes = [1, 10, 100]
        for size in sizes:
            subset = tag_names[:size]

            def _call(sub=subset):
                counter["n"] += 1
                values = {tn: 560000 + counter["n"] * 100 + i for i, tn in enumerate(sub)}
                return _batch_write(api, values)

            stats, errors = _measure(_call, lambda r: None, warmup=1, samples=5, name=f"size{size}")
            _assert_correct(not errors, f"size {size} errors: {errors}")
            observations[f"size_{size}"] = stats

        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(api, tag_ids=ctx["tag_ids"], tag_names=tag_names,
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=None, host=ctx["host"], port=ctx["port"])

    pytest.xfail(
        f"UA-3-6-007 write batch-size baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-008 实时写_同一位号竞争
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-008", chapter="UA-3-6",
    title="实时写_同一位号竞争",
    preconditions=["数据源 alive=true", "1 个可写位号"],
    steps=["10 线程并发写同一位号唯一值", "记录顺序语义", "最终值必须为写入值之一"],
    expected=["记录顺序语义", "最终值可解释"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_008_write_same_tag_race(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-008"
    prefix = "ua36_008"
    node = build_node(f"{prefix}_w_", "Double", 0.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id,
                        nodes=[node], namespace_index=1)
    tags = []
    observations: dict = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id,
                                       type_key="DOUBLE", only_read=False))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        tag_name = tags[0]["tag_name"]
        values = [540000 + i for i in range(10)]

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_write_one, api, tag_name, v) for v in values]
            results = [f.result() for f in futures]
        accepted = [values[i] for i, r in enumerate(results) if r.get("ok")]
        errors = [r["error"] for r in results if not r.get("ok")]
        observations["requested"] = values
        observations["accepted"] = accepted
        observations["errors"] = errors[:5]
        observations["correctness_errors"] = [e for e in errors if e.startswith("AssertionError")]
        _assert_correct(not observations["correctness_errors"], f"correctness: {observations['correctness_errors']}")
        _assert_correct(len(accepted) >= 1, "no write accepted at all")

        final_pt = _wait_rt_settled(api, tag_name, accepted, timeout=60.0)
        final_val = float(final_pt.get("tagValue"))
        observations["final_value"] = final_val
        observations["final_in_accepted"] = final_val in accepted
        observations["final_in_requested"] = final_val in values
        _assert_correct(final_val in accepted,
                        f"same-tag race produced value {final_val} not among accepted {accepted}")
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        cleanup_ua3_context(api, tag_ids=[t["tag_id"] for t in tags], tag_names=[t["tag_name"] for t in tags],
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"])

    pytest.xfail(
        f"UA-3-6-008 same-tag write race baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )


def _wait_rt_settled(api, tag_name: str, candidates: list, timeout: float = 60.0,
                     interval: float = 0.5) -> dict:
    cset = {float(c) for c in candidates}
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        pt = get_rt_point(api, tag_name)
        v = pt.get("tagValue")
        if v is not None and float(v) in cset:
            return pt
        time.sleep(interval)
    raise AssertionError(f"RT for {tag_name} never settled to a written value; last={last}")


# ---------------------------------------------------------------------------
# UA-3-6-009 实时写_跨数据源负载
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-009", chapter="UA-3-6",
    title="实时写_跨数据源负载",
    preconditions=["数据源 A、B 各自在线", "各自 1 个可写位号"],
    steps=["A、B 同时写入不同值", "校验不串源、不互相覆盖", "asyncua 确认源端"],
    expected=["不串源", "不互相覆盖"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_009_write_cross_ds(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-009"
    ctx_a = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, f"{case_id}-A", "ua36_009a", 1, writable=True)
    ctx_b = _build_rt_ctx(api, settings, mocker_endpoint, tmp_path_factory, f"{case_id}-B", "ua36_009b", 1, writable=True)
    ta = ctx_a["tag_names"][0]
    tb = ctx_b["tag_names"][0]
    observations: dict = {}
    try:
        _wait_rt_set(api, ctx_a["tag_names"], is_from_db=False, timeout=120.0)
        _wait_rt_set(api, ctx_b["tag_names"], is_from_db=False, timeout=120.0)
        va = 570001.0
        vb = 580001.0

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(_write_one, api, ta, va)
            fb = pool.submit(_write_one, api, tb, vb)
            results = [fa.result(), fb.result()]
        observations["writes"] = results
        _assert_correct(all(r.get("ok") for r in results),
                        f"cross-source write not all accepted: {results}")

        _wait_rt_value(api, ta, va, timeout=60.0)
        _wait_rt_value(api, tb, vb, timeout=60.0)
        observations["rt_a"] = get_rt_point(api, ta).get("tagValue")
        observations["rt_b"] = get_rt_point(api, tb).get("tagValue")
        _assert_correct(float(observations["rt_a"]) == va, f"A leaked/overwritten: {observations['rt_a']}")
        _assert_correct(float(observations["rt_b"]) == vb, f"B leaked/overwritten: {observations['rt_b']}")

        src_a = opcua_read_sync(ctx_a["endpoint"], f"ua36_009a_val_1", namespace_index=1)
        src_b = opcua_read_sync(ctx_b["endpoint"], f"ua36_009b_val_1", namespace_index=1)
        observations["source_a"] = str(src_a)
        observations["source_b"] = str(src_b)
        observations["no_cross_source"] = float(src_a) == va and float(src_b) == vb
        _assert_correct(observations["no_cross_source"],
                        f"cross-source write leaked to source: a={src_a} b={src_b}")
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _stop_mocker(ctx_a)
        _stop_mocker(ctx_b)
        cleanup_ua3_multi_context(
            api,
            tags=[{"tag_id": i, "tag_name": n}
                  for i, n in zip(ctx_a["tag_ids"], ctx_a["tag_names"])]
                + [{"tag_id": i, "tag_name": n}
                   for i, n in zip(ctx_b["tag_ids"], ctx_b["tag_names"])],
            ds_contexts=[
                {"ds_id": ctx_a["ds_id"], "ds_name": ctx_a["ds_name"],
                 "mocker": None, "host": ctx_a["host"], "port": ctx_a["port"]},
                {"ds_id": ctx_b["ds_id"], "ds_name": ctx_b["ds_name"],
                 "mocker": None, "host": ctx_b["host"], "port": ctx_b["port"]},
            ],
        )

    pytest.xfail(
        f"UA-3-6-009 cross-source write baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-010 实时写_写后历史完整性
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-010", chapter="UA-3-6",
    title="实时写_写后历史完整性",
    preconditions=["数据源 alive=true", "1 个可写位号"],
    steps=["方式 C 高负载写入唯一序列", "历史中成功写入序列可核对"],
    expected=["历史中成功写入序列可核对"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_6_010_write_then_history(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-010"
    prefix = "ua36_010"
    node = build_node(f"{prefix}_w_", "Double", 0.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, case_id,
                        nodes=[node], namespace_index=1)
    tags = []
    observations: dict = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id,
                                       type_key="DOUBLE", only_read=False))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        tag_name = tags[0]["tag_name"]

        t0 = datetime.now() - timedelta(minutes=1)
        accepted: list[float] = []
        rejected: list[dict] = []
        for i in range(1, 21):
            value = 510000 + i
            try:
                resp = write_tag_values(api, {tag_name: value})
                if tag_name in (resp.get("tagNames") or []):
                    accepted.append(float(value))
                else:
                    rejected.append({"value": value, "resp": resp})
            except Exception as exc:
                rejected.append({"value": value, "error": f"{type(exc).__name__}: {exc}"})
            time.sleep(2.0)
        observations["wrote"] = 20
        observations["accepted"] = len(accepted)
        observations["rejected"] = rejected[:5]
        _assert_correct(len(accepted) >= 15,
                        f"write accepted only {len(accepted)}/20: {rejected[:3]}")

        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(datetime.now() + timedelta(minutes=3))

        def _capture() -> set:
            info = get_history_value(api, [tag_name], beg_time=beg, end_time=end,
                                     page_size=500).get(tag_name, {})
            return {float(r.get("tagValue")) for r in (info.get("list") or [])
                    if r.get("tagValue") is not None}

        captured: set = set()
        deadline = time.monotonic() + 240.0
        last_written = max(accepted) if accepted else None
        while time.monotonic() < deadline:
            try:
                captured |= _capture()
            except Exception:
                pass
            if last_written is not None and last_written in captured:
                break
            time.sleep(10.0)

        benign_initial = {0.0}
        rejected_vals = {float(r.get("value")) for r in rejected if "value" in r}
        foreign = (captured - benign_initial) - set(accepted)
        observations["captured_count"] = len(captured)
        observations["captured"] = sorted(captured)
        observations["coverage"] = round(len(captured & set(accepted)) / len(accepted), 3) if accepted else 0.0
        observations["foreign"] = sorted(foreign)
        observations["rejected_in_history"] = sorted(captured & rejected_vals)
        observations["last_written_in_history"] = last_written is not None and last_written in captured

        _assert_correct(not foreign, f"unwritten values leaked into history: {foreign}")
        _assert_correct(not (captured & rejected_vals),
                        f"rejected writes leaked into history: {sorted(captured & rejected_vals)}")
        _assert_correct(observations["last_written_in_history"],
                        "last accepted write never surfaced in history")
        _assert_correct(len(captured) > 0, "history empty after writes")
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        cleanup_ua3_context(api, tag_ids=[t["tag_id"] for t in tags], tag_names=[t["tag_name"] for t in tags],
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"])

    pytest.xfail(
        f"UA-3-6-010 write-then-history baseline: coverage={observations.get('coverage')} "
        f"captured={observations.get('captured_count')} "
        f"last_written={observations.get('last_written_in_history')}; "
        f"per-write history coverage pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-011 历史查询_并发递增
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-011", chapter="UA-3-6",
    title="历史查询_并发递增",
    preconditions=["方式 B 制造隔离历史数据", "数据源存在"],
    steps=["并发 1/5/10/20 查询", "校验无串位号且集合完整", "记录 QPS/延迟"],
    expected=["无串位号", "记录 QPS/延迟"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_6_011_history_concurrent(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-011"
    ctx = _history_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags: list[dict] = []
    observations: dict = {}
    try:
        t0 = datetime.now() - timedelta(minutes=5)
        points = []
        expected_by_tag = {}
        for j in range(10):
            t = _add_history_tag(api, settings, ctx, case_id, f"{j}")
            tags.append(t)
            tn = t["tag_name"]
            exp = set()
            for i in range(40):
                v = 610000 + j * 100 + i
                exp.add(float(v))
                tt = _fmt(t0 + timedelta(seconds=10 * i))
                points.append({"tagName": tn, "tagValue": v, "quality": 192, "tagTime": tt, "appTime": tt})
            expected_by_tag[tn] = exp
        _import_points(api, tags[0]["tag_name"], points)
        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=8))
        _wait_history_values(api, [t["tag_name"] for t in tags], beg, end, expected_by_tag,
                             timeout=450.0, interval=5.0)

        tag_names = [t["tag_name"] for t in tags]

        def _call():
            return get_history_value(api, tag_names, beg_time=beg, end_time=end,
                                     page_size=500, is_source=False)

        def _verify(result):
            for tn, exp in expected_by_tag.items():
                info = result.get(tn) or {}
                vals = {float(r.get("tagValue")) for r in (info.get("list") or []) if r.get("tagValue") is not None}
                _assert_correct(exp <= vals, f"{tn} history incomplete: {len(vals)}/{len(exp)}")
                for rec in info.get("list") or []:
                    _assert_correct(rec.get("tagName") == tn, f"cross-tag history record: {rec}")

        per = _concurrent_levels(_call, _verify, [1, 5, 10, 20], rounds=2)
        for workers, lvl in per.items():
            _assert_correct(not lvl["correctness_errors"],
                            f"level {workers} correctness errors: {lvl['correctness_errors']}")
        observations["levels"] = per
        observations["qps"] = {k: v["qps"] for k, v in per.items()}
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown_mockerfree(api, ctx, tags)

    pytest.xfail(
        f"UA-3-6-011 history concurrent baseline recorded; "
        f"qps={json.dumps(observations.get('qps'), default=str)}; threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-012 历史查询_数据量递增
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-012", chapter="UA-3-6",
    title="历史查询_数据量递增",
    preconditions=["方式 B 制造递增数据量", "数据源存在"],
    steps=["逐级增加窗口/位号/记录数", "分页合集完整无重复遗漏"],
    expected=["分页合集完整，无重复遗漏"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_6_012_history_volume_inc(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-012"
    ctx = _history_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags: list[dict] = []
    observations: dict = {}
    try:
        stages = [(1, 20), (1, 55), (2, 55)]
        stage_results = []
        t0 = datetime.now() - timedelta(minutes=8)
        for stage_idx, (n_tags, n_points) in enumerate(stages):
            stage_tags = []
            points = []
            expected_by_tag = {}
            for j in range(n_tags):
                t = _add_history_tag(api, settings, ctx, case_id, f"s{stage_idx}_{j}")
                stage_tags.append(t)
                tags.append(t)
                tn = t["tag_name"]
                exp = set()
                for i in range(n_points):
                    v = 620000 + stage_idx * 100000 + j * 100 + i
                    exp.add(float(v))
                    tt = _fmt(t0 + timedelta(seconds=10 * i + stage_idx))
                    points.append({"tagName": tn, "tagValue": v, "quality": 192, "tagTime": tt, "appTime": tt})
                expected_by_tag[tn] = exp
            _import_points(api, stage_tags[0]["tag_name"], points)
            beg = _fmt(t0 - timedelta(minutes=1))
            end = _fmt(t0 + timedelta(minutes=13))
            _wait_history_values(api, [t["tag_name"] for t in stage_tags], beg, end, expected_by_tag,
                                 timeout=450.0, interval=5.0)

            start = time.monotonic()
            all_records = _paginate_all(api, [t["tag_name"] for t in stage_tags], beg, end, page_size=20)
            wall = time.monotonic() - start

            for tn, exp in expected_by_tag.items():
                recs = all_records.get(tn) or []
                vals = [float(r.get("tagValue")) for r in recs if r.get("tagValue") is not None]
                _assert_correct(set(vals) == exp, f"stage {stage_idx} {tn} paged set mismatch")
                _assert_correct(len(vals) == len(set(vals)), f"stage {stage_idx} {tn} duplicate in pages")
                _assert_correct(len(vals) == len(exp), f"stage {stage_idx} {tn} omitted points")
            stage_results.append({
                "stage": stage_idx, "tags": n_tags, "points_per_tag": n_points,
                "total": sum(len(all_records.get(t.get("tag_name")) or []) for t in stage_tags),
                "wall_seconds": round(wall, 2),
            })
        observations["stages"] = stage_results
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown_mockerfree(api, ctx, tags)

    pytest.xfail(
        f"UA-3-6-012 history volume-递增 baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )


def _paginate_all(api, tag_names: list[str], beg: str, end: str, page_size: int = 20) -> dict:
    all_records: dict[str, list] = {}
    page = 1
    while True:
        resp = get_history_value(api, tag_names, beg_time=beg, end_time=end,
                                 page=page, page_size=page_size)
        any_remaining = False
        for tn, info in resp.items():
            recs = info.get("list") or []
            all_records.setdefault(tn, []).extend(recs)
            if len(all_records[tn]) < info.get("total", 0):
                any_remaining = True
        if not any_remaining:
            break
        page += 1
    return all_records


# ---------------------------------------------------------------------------
# UA-3-6-013 历史查询_采样性能
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-013", chapter="UA-3-6",
    title="历史查询_采样性能",
    preconditions=["方式 B 制造大窗口数据", "数据源存在"],
    steps=["同一窗口 interval=0 与 interval=N 比较", "采样结果正确并记录性能差异"],
    expected=["采样结果正确", "记录性能差异"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_6_013_history_sampling(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-013"
    ctx = _history_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id)
    tags: list[dict] = []
    observations: dict = {}
    try:
        tags.append(_add_history_tag(api, settings, ctx, case_id, "a"))
        tag_name = tags[0]["tag_name"]
        t0 = datetime.now() - timedelta(minutes=5)
        n = 55
        points = []
        for i in range(n):
            v = 630000 + i
            tt = _fmt(t0 + timedelta(seconds=10 * i))
            points.append({"tagName": tag_name, "tagValue": v, "quality": 192, "tagTime": tt, "appTime": tt})
        _import_points(api, tag_name, points)
        beg = _fmt(t0 - timedelta(minutes=1))
        end = _fmt(t0 + timedelta(minutes=12))
        _wait_history_values(api, [tag_name], beg, end, {float(630000 + i) for i in range(n)},
                             timeout=450.0, interval=5.0)

        full = query_history_value(api, [tag_name], beg_time=beg, end_time=end, interval=0,
                                   is_second=True, is_source=False, page=1, page_size=500)
        full_records = full.get("records") or []
        full_vals = {float(r.get("tagValue")) for r in full_records if r.get("tagValue") is not None}
        observations["full_count"] = len(full_vals)
        observations["full_total"] = full.get("total")
        _assert_correct(len(full_vals) == n, f"full query returned {len(full_vals)}/{n}")

        def _call_sampled():
            return query_history_value(api, [tag_name], beg_time=beg, end_time=end, interval=20,
                                       is_second=True, is_source=False, page=1, page_size=500)

        def _verify_sampled(result):
            recs = result.get("records") or []
            vals = {float(r.get("tagValue")) for r in recs if r.get("tagValue") is not None}
            _assert_correct(0 < len(vals) < n,
                            f"interval=20 returned {len(vals)} points (expected 0<..<{n})")
            _assert_correct(vals <= full_vals, "sampled values not a subset of full set")

        sampled_stats, sampled_errors = _measure(_call_sampled, _verify_sampled,
                                                 warmup=2, samples=5, name="interval20")
        _assert_correct(not sampled_errors, f"sampled errors: {sampled_errors}")
        observations["sampled_count"] = len({float(r.get("tagValue")) for r in
                                             (_call_sampled().get("records") or []) if r.get("tagValue") is not None})
        observations["interval_20"] = sampled_stats

        def _call_full():
            return query_history_value(api, [tag_name], beg_time=beg, end_time=end, interval=0,
                                       is_second=True, is_source=False, page=1, page_size=500)

        full_stats, full_errors = _measure(_call_full, lambda r: None, warmup=2, samples=5, name="interval0")
        _assert_correct(not full_errors, f"full errors: {full_errors}")
        observations["interval_0"] = full_stats
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown_mockerfree(api, ctx, tags)

    pytest.xfail(
        f"UA-3-6-013 sampling baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-014 混合负载_读写历史同时执行
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-014", chapter="UA-3-6",
    title="混合负载_读写历史同时执行",
    preconditions=["数据源 alive=true", "读位号 + 可写位号 + 历史数据"],
    steps=["实时读、实时写、历史查询并发运行", "各类结果保持正确，无资源失控"],
    expected=["各类结果保持正确", "无资源失控"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_ua3_6_014_mixed_load(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-014"
    prefix = "ua36_014"
    ctx = _setup_rt_and_write(api, settings, mocker_endpoint, tmp_path_factory, case_id, prefix)
    observations: dict = {}
    try:
        read_tags = [t["tag_name"] for t in ctx["tags"][:2]]
        write_tag = ctx["tags"][2]["tag_name"]

        t0 = datetime.now() - timedelta(minutes=3)
        points = [{"tagName": write_tag, "tagValue": 640000 + i, "quality": 192,
                   "tagTime": _fmt(t0 + timedelta(seconds=10 * i)),
                   "appTime": _fmt(t0 + timedelta(seconds=10 * i))} for i in range(20)]
        _import_points(api, write_tag, points)
        hist_beg = _fmt(t0 - timedelta(minutes=1))
        hist_end = _fmt(t0 + timedelta(minutes=5))
        _wait_history_values(api, [write_tag], hist_beg, hist_end, {float(640000 + i) for i in range(20)},
                             timeout=450.0, interval=5.0)

        correctness: list[str] = []
        transport: list[str] = []
        lock_holder = {"n": 0}
        stop_evt = threading.Event()

        def _reader():
            while not stop_evt.is_set():
                try:
                    pts = get_rt_value(api, tag_names=read_tags)
                    names = {p.get("tagName") for p in pts}
                    if not (isinstance(pts, list) and len(pts) == 2 and names == set(read_tags)):
                        correctness.append(f"reader wrong set: {len(pts) if isinstance(pts, list) else pts}")
                    elif any(p.get("quality", 0) == 0 for p in pts):
                        correctness.append("reader quality 0")
                except Exception as exc:
                    transport.append(f"reader {type(exc).__name__}: {exc}")
                time.sleep(0.3)

        def _writer():
            while not stop_evt.is_set():
                lock_holder["n"] += 1
                value = 550000 + lock_holder["n"]
                try:
                    resp = write_tag_values(api, {write_tag: value})
                    if write_tag not in (resp.get("tagNames") or []):
                        correctness.append(f"writer rejected: {resp}")
                except Exception as exc:
                    transport.append(f"writer {type(exc).__name__}: {exc}")
                time.sleep(0.3)

        def _history_query():
            while not stop_evt.is_set():
                try:
                    info = get_history_value(api, [write_tag], beg_time=hist_beg, end_time=hist_end,
                                             page_size=500, is_source=False)
                    vals = {float(r.get("tagValue")) for r in ((info.get(write_tag) or {}).get("list") or [])
                            if r.get("tagValue") is not None}
                    if not {float(640000 + i) for i in range(20)} <= vals:
                        correctness.append(f"history incomplete during mixed load: {len(vals)}")
                except Exception as exc:
                    transport.append(f"history {type(exc).__name__}: {exc}")
                time.sleep(0.5)

        threads = [threading.Thread(target=_reader, daemon=True) for _ in range(2)]
        threads.append(threading.Thread(target=_writer, daemon=True))
        threads += [threading.Thread(target=_history_query, daemon=True) for _ in range(2)]
        for t in threads:
            t.start()
        time.sleep(15)
        stop_evt.set()
        for t in threads:
            t.join(timeout=30)

        observations["correctness_errors"] = correctness[:20]
        observations["transport_errors"] = transport[:20]
        observations["writes_attempted"] = lock_holder["n"]
        observations["correctness_count"] = len(correctness)
        observations["transport_count"] = len(transport)
        _assert_correct(not correctness, f"mixed-load correctness errors: {correctness[:5]}")
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(api, tag_ids=[t["tag_id"] for t in ctx["tags"]],
                            tag_names=[t["tag_name"] for t in ctx["tags"]],
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=None, host=ctx["host"], port=ctx["port"])

    pytest.xfail(
        f"UA-3-6-014 mixed-load baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )


# ---------------------------------------------------------------------------
# UA-3-6-015 长稳与过载恢复
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-6-015", chapter="UA-3-6",
    title="长稳与过载恢复",
    preconditions=["数据源 alive=true", "读位号 + 可写位号"],
    steps=["持续负载", "短时过载后停止请求", "服务恢复正常且普通功能冒烟通过"],
    expected=["服务恢复正常", "普通功能冒烟通过"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_6_015_long_run_recovery(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-6-015"
    prefix = "ua36_015"
    ctx = _setup_rt_and_write(api, settings, mocker_endpoint, tmp_path_factory, case_id, prefix)
    observations: dict = {}
    try:
        read_tags = [t["tag_name"] for t in ctx["tags"][:2]]
        write_tag = ctx["tags"][2]["tag_name"]

        def _read_ok():
            pts = get_rt_value(api, tag_names=read_tags)
            names = {p.get("tagName") for p in pts}
            _assert_correct(isinstance(pts, list) and len(pts) == 2 and names == set(read_tags),
                            f"steady read wrong set: {pts!r}")
            _assert_correct(all(p.get("quality", 0) != 0 for p in pts), "steady read quality 0")

        steady_times: list[float] = []
        steady_errors: list[str] = []
        for i in range(20):
            start = time.monotonic()
            try:
                _read_ok()
                steady_times.append(time.monotonic() - start)
            except Exception as exc:
                steady_errors.append(f"{type(exc).__name__}: {exc}")
            time.sleep(1.0)
        observations["steady"] = _stats(steady_times, steady_errors)
        observations["steady_correctness"] = [e for e in steady_errors if e.startswith("AssertionError")]
        _assert_correct(not observations["steady_correctness"],
                        f"steady correctness: {observations['steady_correctness']}")

        overload_times, overload_errors, overload_waves = _concurrent(
            _read_ok, lambda r: None, workers=50, rounds=2)
        observations["overload"] = {
            "stats": _stats(overload_times, overload_errors),
            "correctness_errors": [e for e in overload_errors if e.startswith("AssertionError")],
            "errors": overload_errors[:5],
            "waves": overload_waves,
        }
        _assert_correct(not observations["overload"]["correctness_errors"],
                        f"overload correctness: {observations['overload']['correctness_errors']}")

        time.sleep(5)
        smoke: dict = {}
        pts = get_rt_value(api, tag_names=read_tags)
        smoke["rt_ok"] = isinstance(pts, list) and len(pts) == 2 and all(p.get("quality", 0) != 0 for p in pts)
        value = 515000 + 1
        resp = write_tag_values(api, {write_tag: value})
        smoke["write_ok"] = write_tag in (resp.get("tagNames") or [])
        if smoke["write_ok"]:
            _wait_rt_value(api, write_tag, value, timeout=60.0)
            smoke["readback_ok"] = float(get_rt_point(api, write_tag).get("tagValue")) == float(value)
        beg = (datetime.now() - timedelta(minutes=2)).strftime(_TS)
        end = (datetime.now() + timedelta(minutes=2)).strftime(_TS)
        hist = get_history_value(api, [write_tag], beg_time=beg, end_time=end, page_size=100)
        smoke["history_ok"] = isinstance(hist, dict) and write_tag in hist
        observations["smoke"] = smoke
        _assert_correct(smoke["rt_ok"], "recovery smoke: RT read failed")
        _assert_correct(smoke["write_ok"], "recovery smoke: write failed")
        _assert_correct(smoke["readback_ok"], "recovery smoke: write readback failed")
        _assert_correct(smoke["history_ok"], "recovery smoke: history query failed")
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _stop_mocker(ctx)
        cleanup_ua3_context(api, tag_ids=[t["tag_id"] for t in ctx["tags"]],
                            tag_names=[t["tag_name"] for t in ctx["tags"]],
                            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                            mocker=None, host=ctx["host"], port=ctx["port"])

    pytest.xfail(
        f"UA-3-6-015 long-run/recovery baseline recorded: "
        f"{json.dumps(observations, default=str)}; threshold pending product SLA"
    )
