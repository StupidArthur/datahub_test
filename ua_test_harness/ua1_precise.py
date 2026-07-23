"""UA-1 精确实现层 — 断线/多源/ds-info/test 等章节。"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.type_mapping import tpt_tag_base_name
from ua_test_harness.ua2_fixture_map import base_name_for_node, read_spec, write_spec
from ua_test_harness.ua2_ops import cleanup_case_tag, create_case_tag
from ua_test_harness.ua2_precise import opcua_read, rt_row


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _row_value(row: dict | None) -> Any:
    row = row or {}
    return row.get("tagValue", row.get("value"))


def _quality(row: dict | None) -> Any:
    row = row or {}
    return row.get("quality", row.get("qualityCode"))


def _ds_alive(ctx, ds_id: int) -> bool:
    from ua_test_harness.fixtures.datasource import get_state
    row = get_state(ctx, ds_id) or {}
    return bool(row.get("alive"))


def _poll_metric(name: str, fn: Callable[[], Any], timeout: float = 60.0, interval: float = 1.0) -> float:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if fn():
            return time.monotonic() - t0
        time.sleep(interval)
    raise AssertFail(f"{name} not observed within {timeout}s")


def disconnect_metrics(ctx, cc, meta) -> CaseStatus:
    """UA-1-3-01~08: 断线/重连/写值/增删位号时序探索。"""
    from ua_test_harness.clients import mock_control
    from ua_test_harness.fixtures.datasource import create_datasource, change_state, wait_alive
    from ua_test_harness.fixtures.tag import create_tag, read_rt, write_tag

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    cid = meta["id"]
    num = int(cid.split("-")[-1])

    from ua_test_harness.clients.tpt_client import endpoint_for
    endpoint = ctx.config.mock.endpoints.functional or endpoint_for("functional", ctx)
    ds = create_datasource(ctx, f"ua_auto_ua1_3_{num}", endpoint, registry=cc.registry)
    change_state(ctx, ds["id"], True)
    wait_alive(ctx, ds["id"], timeout=60.0)
    tag = create_tag(
        ctx, f"ua1_3_tag_{num}", ds_id=ds["id"], data_type="INT", frequency=1,
        tag_base_name=tpt_tag_base_name(2, "smoke_change_1"), registry=cc.registry,
    )
    tag_name = tag["name"]

    try:
        v1 = read_rt(ctx, tag_name)
        v2 = read_rt(ctx, tag_name)
        check_true("changing", _row_value(v1) != _row_value(v2))

        if num == 4:
            mock_control.stop_mock("functional")
            time.sleep(2)
            err = None
            try:
                write_tag(ctx, tag_name, 99.0)
                wr = "ok"
            except Exception as exc:
                wr = "fail"
                err = str(exc)
            ctx.bag[cid] = {"write": wr, "error": err}
            mock_control.start_mock("functional")
            mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
            return CaseStatus.OBSERVED

        if num == 5:
            mock_control.stop_mock("functional")
            time.sleep(2)
            try:
                write_tag(ctx, tag_name, 123.45)
            except Exception:
                pass
            mock_control.start_mock("functional")
            mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
            time.sleep(5)
            src = opcua_read(endpoint, "smoke_change_1")
            ctx.bag[cid] = {"asyncua_after_reconnect": src}
            return CaseStatus.OBSERVED

        if num == 6:
            mock_control.stop_mock("functional")
            time.sleep(2)
            mock_control.start_mock("functional")
            mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
            wait_alive(ctx, ds["id"], timeout=60.0)
            rt_row(ctx, tag_name, timeout=60.0)
            return CaseStatus.PASS

        if num == 7:
            mock_control.stop_mock("functional")
            time.sleep(30)
            mock_control.start_mock("functional")
            mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
            wait_alive(ctx, ds["id"], timeout=90.0)
            rt_row(ctx, tag_name, timeout=90.0)
            ctx.bag[cid] = {"long_disconnect_sec": 30}
            return CaseStatus.OBSERVED

        if num == 8:
            mock_control.stop_mock("functional")
            time.sleep(2)
            new_tag = create_tag(
                ctx, f"ua1_3_new_{num}", ds_id=ds["id"], data_type="INT", frequency=1,
                tag_base_name=tpt_tag_base_name(2, "smoke_static_1"), registry=cc.registry,
            )
            mock_control.start_mock("functional")
            mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
            rt_row(ctx, new_tag["name"], timeout=90.0)
            return CaseStatus.PASS

        if num == 1:
            mock_control.stop_mock("functional")
            t0 = time.monotonic()
            alive_delay = _poll_metric("alive_false", lambda: not _ds_alive(ctx, ds["id"]), timeout=30.0)
            qual_delay = _poll_metric(
                "quality_bad",
                lambda: (lambda r: r and _quality(r) in (None, 0))(read_rt(ctx, tag_name)),
                timeout=30.0,
            )
            mock_control.start_mock("functional")
            mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
            ctx.bag[cid] = {
                "alive_delay_sec": alive_delay, "quality_delay_sec": qual_delay,
                "disconnect_started_at": t0,
            }
            return CaseStatus.OBSERVED

        if num == 2:
            mock_control.stop_mock("functional")
            time.sleep(3)
            mock_control.start_mock("functional")
            mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
            t0 = time.monotonic()
            alive_rec = _poll_metric("alive_true", lambda: _ds_alive(ctx, ds["id"]), timeout=60.0)
            rt_rec = _poll_metric(
                "rt_good",
                lambda: (lambda r: r and _quality(r) not in (None, 0))(read_rt(ctx, tag_name)),
                timeout=60.0,
            )
            ctx.bag[cid] = {"alive_recovery_sec": alive_rec, "rt_recovery_sec": rt_rec, "t0": t0}
            return CaseStatus.OBSERVED

        if num == 3:
            rounds = []
            for i in range(3):
                mock_control.stop_mock("functional")
                d_alive = _poll_metric(f"r{i}_down", lambda: not _ds_alive(ctx, ds["id"]), timeout=30.0)
                time.sleep(2)
                mock_control.start_mock("functional")
                mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
                u_alive = _poll_metric(f"r{i}_up", lambda: _ds_alive(ctx, ds["id"]), timeout=60.0)
                rounds.append({"down": d_alive, "up": u_alive})
            ctx.bag[cid] = {"rounds": rounds, "note": "reduced_3_rounds_for_impl"}
            return CaseStatus.OBSERVED

        return CaseStatus.OBSERVED
    except AssertFail:
        raise


def dual_ds_isolation(ctx, cc, meta) -> CaseStatus:
    """UA-1-4-01~06: 使用共享 types + empty 双数据源。"""
    from ua_test_harness.clients import mock_control
    from ua_test_harness.fixtures.datasource import change_state
    from ua_test_harness.fixtures.tag import read_rt, write_tag
    from ua_test_harness.ua2_helpers import try_add_tag
    from tpt_api.datahub import list_ds_info

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)

    # 启动共享 mock: types(18965) + empty(18967) 如果没跑
    import subprocess, sys
    from pathlib import Path
    mock_dir = Path(__file__).resolve().parents[1] / "ua_mocker"
    for port, yaml_name in [(18965, "ua2_types.yaml"), (18967, "ua2_empty.yaml")]:
        if not mock_control._port_listening("127.0.0.1", port):
            subprocess.Popen(
                [sys.executable, "main.py", str(mock_dir / yaml_name)],
                cwd=str(mock_dir),
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            time.sleep(5)

    # 直接查 TPT 已有的共享 DS,不检查 endpoint(可能指向 18965 或 18960)
    api = _api(ctx)
    all_ds = list_ds_info(api, page=1, page_size=500)
    types_row = empty_row = None
    for d in (all_ds or {}).get("records") or []:
        if d.get("dsName") == "ua_shared_ua2_types_ds":
            types_row = d
        if d.get("dsName") == "ua_shared_ua2_empty_ds":
            empty_row = d
    if not types_row:
        raise AssertFail("UA-1-4: ua_shared_ua2_types_ds 不存在,先跑 UA-2 baseline")
    if not empty_row:
        raise AssertFail("UA-1-4: ua_shared_ua2_empty_ds 不存在,先跑 UA-2 baseline")
    # 确保 empty DS enabled + alive
    if not empty_row.get("alive"):
        change_state(ctx, int(empty_row["id"]), True)
        time.sleep(5)
    if not types_row.get("alive"):
        change_state(ctx, int(types_row["id"]), True)
        time.sleep(5)
    t_id, e_id = int(types_row["id"]), int(empty_row["id"])
    cid = meta["id"]
    num = int(cid.split("-")[-1])

    ta = create_case_tag(ctx, cc, t_id, suffix=f"4a{num}", data_type="INT")
    tb = create_case_tag(ctx, cc, e_id, suffix=f"4b{num}", data_type="INT")
    try:
        rt_row(ctx, ta["name"])
        rt_row(ctx, tb["name"])

        if num == 1:
            check_true("types_alive", _ds_alive(ctx, t_id))
            check_true("empty_alive", _ds_alive(ctx, e_id))
            return CaseStatus.PASS

        if num == 2:
            from ua_test_harness.ua2_ops import disable_datasource, enable_datasource
            disable_datasource(ctx, t_id)
            time.sleep(3)
            b_ok = _ds_alive(ctx, e_id)
            enable_datasource(ctx, t_id)
            ctx.bag[cid] = {"empty_still_alive": b_ok}
            check_true("empty_unaffected", b_ok)
            return CaseStatus.OBSERVED

        if num == 3:
            from ua_test_harness.ua2_ops import disable_datasource, enable_datasource
            disable_datasource(ctx, t_id)
            time.sleep(3)
            enable_datasource(ctx, t_id)
            rt_row(ctx, ta["name"], timeout=90.0)
            check_true("empty_still_alive", _ds_alive(ctx, e_id))
            return CaseStatus.PASS

        if num == 4:
            change_state(ctx, t_id, False)
            time.sleep(2)
            b1 = read_rt(ctx, tb["name"])
            change_state(ctx, t_id, True)
            time.sleep(5)
            b2 = read_rt(ctx, tb["name"])
            ctx.bag[cid] = {"empty_rt_before": b1, "empty_rt_after": b2}
            check_true("empty_alive_after", _ds_alive(ctx, e_id))
            return CaseStatus.OBSERVED

        if num == 5:
            base = base_name_for_node(write_spec("DOUBLE")["node"])
            dup_a = f"ua1_4_tag_a_{num}"
            cleanup_case_tag(ctx, cc, int(ta["id"]), ta["name"])
            cleanup_case_tag(ctx, cc, int(tb["id"]), tb["name"])
            a = create_case_tag(ctx, cc, t_id, suffix="5a", data_type="DOUBLE", tag_base_name=base)
            b = create_case_tag(ctx, cc, e_id, suffix="5b", data_type="DOUBLE", tag_base_name=base)
            write_tag(ctx, a["name"], 11.1)
            write_tag(ctx, b["name"], 22.2)
            ra = read_rt(ctx, a["name"])
            rb = read_rt(ctx, b["name"])
            check_true("values_distinct", _row_value(ra) != _row_value(rb))
            cleanup_case_tag(ctx, cc, int(a["id"]), a["name"])
            cleanup_case_tag(ctx, cc, int(b["id"]), b["name"])
            return CaseStatus.PASS

        if num == 6:
            ok, detail = try_add_tag(ctx, e_id, tag_name=ta["name"])
            check_true("dup_name_rejected", not ok)
            ctx.bag[cid] = detail
            return CaseStatus.PASS

        return CaseStatus.OBSERVED
    finally:
        cleanup_case_tag(ctx, cc, int(ta["id"]), ta["name"])
        cleanup_case_tag(ctx, cc, int(tb["id"]), tb["name"])


def test_ds_info_case(ctx, cc, meta) -> CaseStatus:
    """UA-1-6-01~13: ds-info/test 五类 testType。"""
    from tpt_api.datahub import test_ds_info, DsTestEnumerate, DsTestReadRT, DsTestReadRTDB, DsTestHistory, DsTestWrite
    from ua_test_harness.fixtures.datasource import change_state, create_datasource, wait_alive

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    cid = meta["id"]
    num = int(cid.split("-")[-1])

    from ua_test_harness.clients.tpt_client import endpoint_for
    endpoint = ctx.config.mock.endpoints.functional or endpoint_for("functional", ctx)
    ds = create_datasource(ctx, f"ua_auto_ua1_6_{num}", endpoint, registry=cc.registry)
    change_state(ctx, ds["id"], True)
    wait_alive(ctx, ds["id"], timeout=60.0)
    ds_id = int(ds["id"])
    # smoke.yaml: ns=2, 节点 smoke_change_1(Int32,只读)/ smoke_static_1(Double,可写)
    FUNC_NS = 2
    node = "smoke_change_1"
    browse_name = tpt_tag_base_name(FUNC_NS, node)

    try:
        if num == 1:
            resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestEnumerate)
            successes = resp.get("successes") or []
            ctx.bag[cid] = {"total": resp.get("total"), "count": len(successes)}
            check_true("has_nodes", len(successes) > 0)
            return CaseStatus.PASS

        if num == 2:
            change_state(ctx, ds_id, False)
            time.sleep(2)
            try:
                resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestEnumerate)
            except Exception as e:
                resp = {"error": str(e)}
            ctx.bag[cid] = resp
            return CaseStatus.OBSERVED

        if num == 3:
            resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestEnumerate)
            ctx.bag[cid] = {
                "total": resp.get("total"), "pageNum": resp.get("pageNum"),
                "pageSize": resp.get("pageSize"), "totalPage": resp.get("totalPage"),
            }
            return CaseStatus.OBSERVED

        if num == 4:
            resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestReadRT, tag_name=browse_name)
            src = opcua_read(endpoint, node, namespace_index=FUNC_NS)
            ctx.bag[cid] = {"test": resp, "asyncua": src}
            check_true("has_success", bool(resp.get("successes")))
            return CaseStatus.PASS

        if num == 5:
            tag = create_case_tag(ctx, cc, ds_id, suffix=f"6{num}", data_type="INT", tag_base_name=browse_name)
            rt_row(ctx, tag["name"])
            r2 = test_ds_info(_api(ctx), ds_id, test_type=DsTestReadRT, tag_name=tag["name"])
            r3 = test_ds_info(_api(ctx), ds_id, test_type=DsTestReadRTDB, tag_name=tag["name"])
            ctx.bag[cid] = {"type2": r2, "type3": r3}
            cleanup_case_tag(ctx, cc, int(tag["id"]), tag["name"])
            return CaseStatus.OBSERVED

        if num == 6:
            resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestReadRT, tag_name="__nonexistent__")
            ctx.bag[cid] = resp
            check_true("failed", not resp.get("isAllSuccess", True))
            return CaseStatus.PASS

        if num == 7:
            change_state(ctx, ds_id, False)
            try:
                resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestReadRT, tag_name=browse_name)
            except Exception as e:
                resp = {"error": str(e)}
            ctx.bag[cid] = resp
            return CaseStatus.OBSERVED

        if num == 8:
            tag = create_case_tag(ctx, cc, ds_id, suffix=f"6{num}", data_type="INT")
            from ua_test_harness.fixtures.history import HistoryFixtureFactory
            factory = HistoryFixtureFactory(ctx)
            factory.create_import_dataset(tag["name"], count=10)
            end = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            beg = "2000-01-01 00:00:00"
            resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestHistory, tag_name=tag["name"],
                                begin_time=beg, end_time=end)
            ctx.bag[cid] = resp
            cleanup_case_tag(ctx, cc, int(tag["id"]), tag["name"])
            return CaseStatus.OBSERVED

        if num == 9:
            failed = False
            try:
                test_ds_info(_api(ctx), ds_id, test_type=DsTestHistory, tag_name=browse_name)
            except Exception as exc:
                failed = True
                ctx.bag[cid] = str(exc)
            check_true("missing_time_rejected", failed)
            return CaseStatus.PASS

        if num == 10:
            wnode = "smoke_static_1"
            wbase = tpt_tag_base_name(FUNC_NS, wnode)
            resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestWrite, tag_name=wbase, tag_value="123.45")
            after = opcua_read(endpoint, wnode, namespace_index=FUNC_NS)
            ctx.bag[cid] = {"resp": resp, "asyncua": after}
            return CaseStatus.OBSERVED

        if num == 11:
            rnode = "smoke_change_1"
            rbase = tpt_tag_base_name(FUNC_NS, rnode)
            resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestWrite, tag_name=rbase, tag_value="1")
            ctx.bag[cid] = resp
            return CaseStatus.OBSERVED

        if num == 12:
            wbase = tpt_tag_base_name(FUNC_NS, "smoke_static_1")
            resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestWrite, tag_name=wbase, tag_value="abc")
            ctx.bag[cid] = resp
            check_true("type_mismatch", not resp.get("isAllSuccess", True))
            return CaseStatus.PASS

        if num == 13:
            change_state(ctx, ds_id, False)
            resp = test_ds_info(_api(ctx), ds_id, test_type=DsTestWrite, tag_name=browse_name, tag_value="1")
            ctx.bag[cid] = resp
            return CaseStatus.OBSERVED

        return CaseStatus.OBSERVED
    except AssertFail:
        raise


def _unique(ctx, prefix: str) -> str:
    run_id = (ctx.config.run_id or "run").replace("-", "_")
    return f"{prefix}_{run_id[:14]}_{time.time_ns() % 1_000_000}"


def _owned_ds(
    ctx,
    cc,
    name: str,
    endpoint: str,
    *,
    ds_ext_info: dict | None = None,
    enabled: bool = True,
) -> dict:
    """创建 ua_auto_ 前缀数据源并登记 LIFO 清理。"""
    from tpt_api.datahub import add_ds_info
    from tpt_api.types import DsSubTypes, DsTypes
    from ua_test_harness.fixtures.datasource import _safe_delete, change_state, wait_alive

    if not name.startswith("ua_auto_"):
        name = f"ua_auto_{name}"
    api = _api(ctx)
    kwargs: dict = {}
    if ds_ext_info is not None:
        kwargs["ds_ext_info"] = ds_ext_info
    data = add_ds_info(
        api,
        ds_name=name,
        ds_type=DsTypes["REAL_TIME_DB"],
        ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
        **kwargs,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    cc.registry.register(f"ds:{name}", "datasource", lambda: _safe_delete(api, ds_id))
    if enabled:
        change_state(ctx, ds_id, True)
        wait_alive(ctx, ds_id, timeout=60.0)
    return {"id": ds_id, "name": name, "endpoint": endpoint}


def connection_case(ctx, cc, meta) -> CaseStatus:
    """UA-1-1-03/05~11: URL 双格式、可达恢复、鉴权、好值质量码。"""
    from ua_test_harness.clients.tpt_client import endpoint_for
    from ua_test_harness.fixtures.datasource import change_state, wait_alive
    from ua_test_harness.fixtures.tag import create_tag, read_rt, wait_tag_present

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    cid = meta["id"]
    num = int(cid.split("-")[-1])
    base_ep = ctx.config.mock.endpoints.functional or endpoint_for("functional", ctx)

    if num == 3:
        ep_a = base_ep.split("/ua_mocker/", 1)[0].rstrip("/")
        ep_b = base_ep if "/ua_mocker/" in base_ep else base_ep.rstrip("/") + "/ua_mocker/"
        ds_a = _owned_ds(ctx, cc, _unique(ctx, "ua1_1_03a"), ep_a)
        ds_b = _owned_ds(ctx, cc, _unique(ctx, "ua1_1_03b"), ep_b)
        tg_a = create_tag(
            ctx, _unique(ctx, "ua1_1_t03a"), ds_id=ds_a["id"], data_type="INT", frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_change_1"), registry=cc.registry,
        )
        tg_b = create_tag(
            ctx, _unique(ctx, "ua1_1_t03b"), ds_id=ds_b["id"], data_type="INT", frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_change_1"), registry=cc.registry,
        )
        wait_tag_present(ctx, tg_a["name"])
        wait_tag_present(ctx, tg_b["name"])
        check_true("both_alive", _ds_alive(ctx, ds_a["id"]) and _ds_alive(ctx, ds_b["id"]))
        ctx.bag[cid] = {"ds_a": ds_a["id"], "ds_b": ds_b["id"], "ep_a": ep_a, "ep_b": ep_b}
        return CaseStatus.PASS

    if num == 5:
        from ua_test_harness.clients import mock_control
        from ua_test_harness.fixtures.datasource import wait_alive
        from ua_test_harness.fixtures.environment import ensure_mock_ready

        reconnect_ep = ensure_mock_ready(ctx, "reconnect")
        mock_control.stop_mock("reconnect")
        import time as _time
        _time.sleep(2)
        ds = _owned_ds(ctx, cc, _unique(ctx, "ua1_1_05"), reconnect_ep, enabled=False)
        change_state(ctx, ds["id"], True)
        _time.sleep(3)
        alive_before = _ds_alive(ctx, ds["id"])
        if alive_before:
            ctx.bag[cid] = {"alive_before": True, "note": "reconnect mock 未停净,无法测不可达起点"}
            return CaseStatus.OBSERVED
        t_start = _time.monotonic()
        try:
            mock_control.start_mock("reconnect")
            mock_control.wait_ready("reconnect", timeout=60.0, ctx=ctx)
        except Exception as exc:
            ctx.bag[cid] = {
                "alive_before": alive_before,
                "reconnect_mock_error": str(exc),
                "endpoint": reconnect_ep,
            }
            return CaseStatus.OBSERVED
        recovered = wait_alive(ctx, ds["id"], timeout=90.0)
        delay = _time.monotonic() - t_start
        rt_ok = False
        if recovered:
            tg = create_tag(
                ctx, _unique(ctx, "ua1_1_t05"), ds_id=ds["id"], data_type="INT", frequency=1,
                tag_base_name=tpt_tag_base_name(2, "smoke_change_1"), registry=cc.registry,
            )
            rt_ok = wait_tag_present(ctx, tg["name"], timeout=60.0)
        ctx.bag[cid] = {
            "alive_before": alive_before,
            "recovered": recovered,
            "recovery_delay_sec": delay,
            "rt_after_alive": rt_ok,
            "endpoint": reconnect_ep,
        }
        if recovered and rt_ok:
            return CaseStatus.PASS
        return CaseStatus.OBSERVED

    ext_auth = {"username": "uauser", "password": "uapass"}
    ext_quality_192 = {"goodQualityCode": 192, "goodQuality": 192}
    ext_quality_0 = {"goodQualityCode": 0, "goodQuality": 0}

    ext_map = {
        6: (None, "auth_no_creds"),
        7: (ext_auth, "auth_with_creds"),
        8: (ext_auth, "auth_extra_creds"),
        9: (None, "quality_default"),
        10: (ext_quality_192, "quality_192"),
        11: (ext_quality_0, "quality_0"),
    }
    if num in ext_map:
        ds_ext, label = ext_map[num]
        abnormal = ctx.config.mock.endpoints.abnormal or endpoint_for("abnormal", ctx)
        endpoint = abnormal if num in (6, 7) and abnormal else base_ep
        ds = _owned_ds(ctx, cc, _unique(ctx, f"ua1_1_{num:02d}"), endpoint, ds_ext_info=ds_ext)
        tag = create_tag(
            ctx, _unique(ctx, f"ua1_1_tag_{num}"), ds_id=ds["id"], data_type="INT", frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_change_1"), registry=cc.registry,
        )
        wait_tag_present(ctx, tag["name"])
        row = read_rt(ctx, tag["name"])
        ctx.bag[cid] = {
            "label": label,
            "alive": _ds_alive(ctx, ds["id"]),
            "quality": _quality(row),
            "ds_ext_info": ds_ext,
            "endpoint": endpoint,
            "mock_auth_available": bool(abnormal and num in (6, 7)),
        }
        if num == 6:
            if ctx.bag[cid].get("mock_auth_available"):
                check_eq("alive_false_without_creds", False, _ds_alive(ctx, ds["id"]))
            return CaseStatus.PASS if not _ds_alive(ctx, ds["id"]) else CaseStatus.OBSERVED
        if num in (7, 8):
            check_true("alive", _ds_alive(ctx, ds["id"]))
            return CaseStatus.PASS
        return CaseStatus.OBSERVED

    ctx.bag[cid] = "unsupported_connection_case"
    return CaseStatus.BLOCKED


def delete_matrix_case(ctx, cc, meta) -> CaseStatus:
    """UA-1-5-02~09: 删除矩阵、回收站、双源隔离。"""
    from tpt_api.datahub import delete_ds_info, list_recycle_tags
    from ua_test_harness.clients.tpt_client import endpoint_for
    from ua_test_harness.fixtures.datasource import change_state, create_datasource, get_state
    from ua_test_harness.fixtures.tag import create_tag, read_rt, wait_tag_present
    from ua_test_harness.ua2_ops import all_recycle_rows, soft_delete_tag

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    cid = meta["id"]
    num = int(cid.split("-")[-1])
    api = _api(ctx)
    endpoint = ctx.config.mock.endpoints.functional or endpoint_for("functional", ctx)

    if num == 2:
        ds = create_datasource(ctx, _unique(ctx, "ua1_5_02"), endpoint, registry=cc.registry)
        change_state(ctx, ds["id"], False)
        tg = create_tag(
            ctx, _unique(ctx, "ua1_5_t02"), ds_id=ds["id"], data_type="INT", frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_static_1"), registry=cc.registry,
        )
        err = None
        deleted = False
        try:
            delete_ds_info(api, [ds["id"]])
            deleted = True
            cc.registry.pop(f"ds:{ds['name']}")
            cc.registry.pop(f"tag:{tg['name']}")
        except Exception as exc:
            err = str(exc)
        ctx.bag[cid] = {"deleted": deleted, "error": err}
        return CaseStatus.OBSERVED

    if num == 3:
        ds = create_datasource(ctx, _unique(ctx, "ua1_5_03"), endpoint, registry=cc.registry)
        err = None
        deleted = False
        try:
            delete_ds_info(api, [ds["id"]])
            deleted = get_state(ctx, ds["id"]) is None
            cc.registry.pop(f"ds:{ds['name']}")
        except Exception as exc:
            err = str(exc)
        ctx.bag[cid] = {"deleted": deleted, "error": err}
        return CaseStatus.OBSERVED

    if num == 4:
        ds = create_datasource(ctx, _unique(ctx, "ua1_5_04"), endpoint, registry=cc.registry)
        tg = create_tag(
            ctx, _unique(ctx, "ua1_5_t04"), ds_id=ds["id"], data_type="INT", frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_change_1"), registry=cc.registry,
        )
        wait_tag_present(ctx, tg["name"])
        read_rt(ctx, tg["name"])
        err = None
        deleted = False
        try:
            delete_ds_info(api, [ds["id"]])
            deleted = True
        except Exception as exc:
            err = str(exc)
        ctx.bag[cid] = {"deleted": deleted, "error": err, "ds_still_exists": get_state(ctx, ds["id"]) is not None}
        return CaseStatus.OBSERVED

    if num == 5:
        ds = create_datasource(ctx, _unique(ctx, "ua1_5_05"), endpoint, registry=cc.registry)
        tg = create_tag(
            ctx, _unique(ctx, "ua1_5_t05"), ds_id=ds["id"], data_type="INT", frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_static_1"), registry=cc.registry,
        )
        soft_delete_tag(ctx, int(tg["id"]))
        rec = [r for r in all_recycle_rows(ctx) if int(r.get("id", -1)) == int(tg["id"])]
        check_eq("in_recycle", 1, len(rec))
        err = None
        deleted = False
        try:
            change_state(ctx, ds["id"], False)
            delete_ds_info(api, [ds["id"]])
            deleted = get_state(ctx, ds["id"]) is None
            cc.registry.pop(f"ds:{ds['name']}")
        except Exception as exc:
            err = str(exc)
        recycle_after = list_recycle_tags(api, page=1, page_size=50)
        ctx.bag[cid] = {"ds_deleted": deleted, "error": err, "recycle_after": recycle_after}
        return CaseStatus.OBSERVED

    if num == 6:
        ds = create_datasource(ctx, _unique(ctx, "ua1_5_06"), endpoint, registry=cc.registry)
        tg = create_tag(
            ctx, _unique(ctx, "ua1_5_t06"), ds_id=ds["id"], data_type="INT", frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_static_1"), registry=cc.registry,
        )
        soft_delete_tag(ctx, int(tg["id"]))
        change_state(ctx, ds["id"], False)
        try:
            delete_ds_info(api, [ds["id"]])
            cc.registry.pop(f"ds:{ds['name']}")
        except Exception:
            pass
        rebuilt = create_datasource(ctx, _unique(ctx, "ua1_5_06b"), endpoint, registry=cc.registry)
        rec = list_recycle_tags(api, page=1, page_size=100)
        ctx.bag[cid] = {"rebuilt_id": rebuilt["id"], "recycle": rec}
        return CaseStatus.OBSERVED

    if num == 8:
        ep_b = ctx.config.mock.endpoints.reconnect or endpoint_for("reconnect", ctx)
        if not ep_b or ep_b == endpoint:
            types = require_shared_datasource(ctx, "types")
            empty = require_shared_datasource(ctx, "empty")
            ctx.bag[cid] = {
                "fallback": "no_second_ephemeral_endpoint",
                "types_alive": _ds_alive(ctx, int(types["id"])),
                "empty_alive": _ds_alive(ctx, int(empty["id"])),
            }
            check_true("types_alive", _ds_alive(ctx, int(types["id"])))
            check_true("empty_alive", _ds_alive(ctx, int(empty["id"])))
            return CaseStatus.OBSERVED
        ds_a = create_datasource(ctx, _unique(ctx, "ua1_5_08a"), endpoint, registry=cc.registry)
        ds_b = create_datasource(ctx, _unique(ctx, "ua1_5_08b"), ep_b, registry=cc.registry)
        tg_b = create_tag(
            ctx, _unique(ctx, "ua1_5_t08b"), ds_id=ds_b["id"], data_type="INT", frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_change_1"), registry=cc.registry,
        )
        wait_tag_present(ctx, tg_b["name"])
        delete_ds_info(api, [ds_a["id"]])
        cc.registry.pop(f"ds:{ds_a['name']}")
        check_true("ds_b_alive", _ds_alive(ctx, ds_b["id"]))
        read_rt(ctx, tg_b["name"])
        return CaseStatus.PASS

    if num == 9:
        ds = create_datasource(ctx, _unique(ctx, "ua1_5_09"), endpoint, registry=cc.registry)
        tg = create_tag(
            ctx, _unique(ctx, "ua1_5_t09"), ds_id=ds["id"], data_type="INT", frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_static_1"), registry=cc.registry,
        )
        wait_tag_present(ctx, tg["name"])
        tag_name = tg["name"]
        change_state(ctx, ds["id"], False)
        from ua_test_harness.ua2_ops import physical_delete_tag
        physical_delete_tag(ctx, int(tg["id"]))
        try:
            delete_ds_info(api, [ds["id"]])
            cc.registry.pop(f"ds:{ds['name']}")
        except Exception as exc:
            ctx.bag[cid] = {"delete_error": str(exc)}
            return CaseStatus.OBSERVED
        row = None
        err = None
        try:
            row = read_rt(ctx, tag_name)
        except Exception as exc:
            err = str(exc)
        ctx.bag[cid] = {"rt_after_delete": row, "error": err}
        return CaseStatus.OBSERVED

    ctx.bag[cid] = "delete_case_not_implemented"
    return CaseStatus.BLOCKED
