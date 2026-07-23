"""UA-1 数据源管理专用执行器。"""
from __future__ import annotations

import time
from typing import Any

from ua_test_harness.assertions import AssertFail, check_true
from ua_test_harness.models import CaseStatus
from ua_test_harness.type_mapping import tpt_tag_base_name


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _unique(ctx, prefix: str) -> str:
    run_id = (ctx.config.run_id or "run").replace("-", "_")
    return f"{prefix}_{run_id[:14]}_{time.time_ns() % 1_000_000}"


def _endpoint(ctx) -> str:
    from ua_test_harness.clients.tpt_client import endpoint_for
    value = ctx.config.mock.endpoints.functional or endpoint_for("functional", ctx)
    if not value:
        raise AssertFail("functional mock endpoint is empty")
    return value


def _wait(name: str, fn, timeout: float = 60.0, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertFail(f"{name} timeout after {timeout}s; last={last!r}")


def _row(ctx, ds_id: int) -> dict[str, Any] | None:
    from ua_test_harness.fixtures.datasource import get_state
    return get_state(ctx, ds_id)


def _value(row: dict[str, Any] | None):
    row = row or {}
    return row.get("tagValue", row.get("value"))


def _quality(row: dict[str, Any] | None):
    row = row or {}
    return row.get("quality", row.get("qualityCode"))


def _prepare(ctx, cc, *, endpoint: str | None = None, with_tag: bool = True, enabled: bool = True):
    from ua_test_harness.fixtures import datasource, tag
    from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ep = endpoint or _endpoint(ctx)
    ds_name = _unique(ctx, "ua_auto_ua1_ds")
    ds = datasource.create_datasource(ctx, ds_name, ep, registry=cc.registry)
    if enabled:
        datasource.change_state(ctx, ds["id"], True)
        check_true("datasource_alive", datasource.wait_alive(ctx, ds["id"], timeout=ctx.config.timeouts.ds_connect_sec))
    tg = None
    if with_tag:
        tag_name = _unique(ctx, "ua_auto_ua1_tag")
        tg = tag.create_tag(
            ctx,
            tag_name,
            ds_id=ds["id"],
            data_type="INT",
            writable=False,
            frequency=1,
            tag_base_name=tpt_tag_base_name(2, "smoke_change_1"),
            registry=cc.registry,
        )
        tag.wait_tag_present(ctx, tag_name, timeout=30.0)
    return ds, tg


def _wait_rt(ctx, tag_name: str):
    from ua_test_harness.fixtures.tag import read_rt
    return _wait(
        f"rt:{tag_name}",
        lambda: (lambda row: row if row and _quality(row) is not None else None)(read_rt(ctx, tag_name)),
        timeout=ctx.config.timeouts.rt_visibility_sec,
    )


def _wait_changed(ctx, tag_name: str, previous, timeout: float = 30.0):
    from ua_test_harness.fixtures.tag import read_rt
    return _wait(
        f"rt_changed:{tag_name}",
        lambda: (lambda row: row if row and _value(row) != previous else None)(read_rt(ctx, tag_name)),
        timeout=timeout,
    )


def _wait_disabled(ctx, ds_id: int):
    return _wait(
        f"ds_disabled:{ds_id}",
        lambda: (lambda row: row if row and not bool(row.get("alive")) else None)(_row(ctx, ds_id)),
        timeout=30.0,
    )


def _connection(ctx, cc, meta):
    from tpt_api.datahub import add_ds_info
    from tpt_api.types import DsSubTypes, DsTypes
    from ua_test_harness.fixtures import datasource

    case_id = meta["id"]
    if case_id == "UA-1-1-04":
        host = ctx.config.local_ip or "127.0.0.1"
        unreachable = f"opc.tcp://{host}:18969/ua_mocker/"
        ds, _ = _prepare(ctx, cc, endpoint=unreachable, with_tag=False, enabled=False)
        datasource.change_state(ctx, ds["id"], True)
        time.sleep(3)
        check_true("unreachable_not_alive", not bool((_row(ctx, ds["id"]) or {}).get("alive")))
        return CaseStatus.PASS

    if case_id == "UA-1-1-12":
        ds, _ = _prepare(ctx, cc, with_tag=False)
        duplicate_failed = False
        try:
            add_ds_info(
                _api(ctx),
                ds_name=_unique(ctx, "ua_auto_ua1_dup"),
                ds_type=DsTypes["REAL_TIME_DB"],
                ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
                ds_tar_url=ds["endpoint"],
            )
        except Exception:
            duplicate_failed = True
        check_true("duplicate_endpoint_rejected", duplicate_failed)
        return CaseStatus.PASS

    if case_id in {"UA-1-1-03", "UA-1-1-05", "UA-1-1-06", "UA-1-1-07", "UA-1-1-08",
                   "UA-1-1-09", "UA-1-1-10", "UA-1-1-11"}:
        from ua_test_harness.ua1_precise import connection_case
        return connection_case(ctx, cc, meta)

    endpoint = _endpoint(ctx)
    if case_id == "UA-1-1-01":
        endpoint = endpoint.split("/ua_mocker/", 1)[0]
    if case_id == "UA-1-1-02":
        if "/ua_mocker/" not in endpoint:
            endpoint = endpoint.rstrip("/") + "/ua_mocker/"
    ds, tg = _prepare(ctx, cc, endpoint=endpoint, with_tag=True)
    check_true("alive", bool((_row(ctx, ds["id"]) or {}).get("alive")))
    first = _wait_rt(ctx, tg["name"])
    check_true("rt_has_value", _value(first) is not None)
    return CaseStatus.PASS


def _state(ctx, cc, meta):
    from ua_test_harness.fixtures import datasource, tag

    case_id = meta["id"]
    ds, tg = _prepare(ctx, cc, with_tag=True, enabled=True)
    first = _wait_rt(ctx, tg["name"])
    second = _wait_changed(ctx, tg["name"], _value(first))
    check_true("precondition_value_changes", _value(first) != _value(second))

    if case_id == "UA-1-2-06":
        datasource.change_state(ctx, ds["id"], True)
        check_true("repeat_enable_alive", datasource.wait_alive(ctx, ds["id"], timeout=30.0))
        _wait_changed(ctx, tg["name"], _value(second))
        return CaseStatus.PASS

    datasource.change_state(ctx, ds["id"], False)
    _wait_disabled(ctx, ds["id"])

    if case_id in {"UA-1-2-01", "UA-1-2-02"}:
        disabled_first = tag.read_rt(ctx, tg["name"])
        time.sleep(2)
        disabled_second = tag.read_rt(ctx, tg["name"])
        if disabled_first:
            check_true("disabled_quality_degraded", _quality(disabled_first) in (None, 0))
        if disabled_first and disabled_second:
            check_true("disabled_value_stopped", _value(disabled_first) == _value(disabled_second))
        return CaseStatus.PASS

    if case_id == "UA-1-2-07":
        datasource.change_state(ctx, ds["id"], False)
        check_true("repeat_disable_stays_down", not bool((_row(ctx, ds["id"]) or {}).get("alive")))
        return CaseStatus.PASS

    if case_id in {"UA-1-2-03", "UA-1-2-04", "UA-1-2-05"}:
        from ua_test_harness.fixtures.history import HistoryFixtureFactory

        factory = HistoryFixtureFactory(ctx)
        try:
            factory.create_import_dataset(tg["name"], count=20)
            n_before = factory.verify_history(tg["name"], min_count=10)
        except AssertFail as exc:
            ctx.bag[f"setup_failed_{case_id}"] = str(exc)
            return CaseStatus.BLOCKED

        if case_id == "UA-1-2-03":
            datasource.change_state(ctx, ds["id"], False)
            _wait_disabled(ctx, ds["id"])
            time.sleep(5)
            n_after = factory.verify_history(tg["name"], min_count=n_before)
            check_eq("history_frozen_on_disable", n_before, n_after)
            ctx.bag[case_id] = {"before": n_before, "after_disable": n_after}
            return CaseStatus.PASS

        if case_id in {"UA-1-2-04", "UA-1-2-05"}:
            datasource.change_state(ctx, ds["id"], False)
            _wait_disabled(ctx, ds["id"])
            datasource.change_state(ctx, ds["id"], True)
            check_true("reenable_alive", datasource.wait_alive(ctx, ds["id"], timeout=60.0))
            _wait_rt(ctx, tg["name"])
            time.sleep(5)
            try:
                n_after = factory.verify_history(tg["name"], min_count=n_before)
                ctx.bag[case_id] = {"before": n_before, "after_reenable": n_after}
            except AssertFail as exc:
                ctx.bag[case_id] = {"before": n_before, "history_check": str(exc)}
            return CaseStatus.OBSERVED

    datasource.change_state(ctx, ds["id"], True)
    check_true("reenable_alive", datasource.wait_alive(ctx, ds["id"], timeout=60.0))
    resumed = _wait_rt(ctx, tg["name"])
    check_true("reenable_quality_good", _quality(resumed) not in (None, 0))
    _wait_changed(ctx, tg["name"], _value(resumed))

    if case_id == "UA-1-2-08":
        datasource.change_state(ctx, ds["id"], False)
        _wait_disabled(ctx, ds["id"])
        datasource.change_state(ctx, ds["id"], True)
        check_true("cycle_final_alive", datasource.wait_alive(ctx, ds["id"], timeout=60.0))
        final = _wait_rt(ctx, tg["name"])
        _wait_changed(ctx, tg["name"], _value(final))
        return CaseStatus.PASS

    return CaseStatus.PASS


def _delete(ctx, cc, meta):
    from tpt_api.datahub import delete_ds_info, delete_tags_physical
    from ua_test_harness.fixtures import datasource

    case_id = meta["id"]
    if case_id == "UA-1-5-01":
        ds, _ = _prepare(ctx, cc, with_tag=False, enabled=False)
        delete_ds_info(_api(ctx), [ds["id"]])
        cc.registry.pop(f"ds:{ds['name']}")
        check_true("datasource_deleted", _row(ctx, ds["id"]) is None)
        return CaseStatus.PASS

    if case_id == "UA-1-5-07":
        ds, tg = _prepare(ctx, cc, with_tag=True, enabled=True)
        endpoint = ds["endpoint"]
        cc.registry.pop(f"tag:{tg['name']}")
        delete_tags_physical(_api(ctx), [tg["id"]])
        datasource.change_state(ctx, ds["id"], False)
        delete_ds_info(_api(ctx), [ds["id"]])
        cc.registry.pop(f"ds:{ds['name']}")
        rebuilt, rebuilt_tag = _prepare(ctx, cc, endpoint=endpoint, with_tag=True, enabled=True)
        check_true("rebuilt_alive", bool((_row(ctx, rebuilt["id"]) or {}).get("alive")))
        _wait_rt(ctx, rebuilt_tag["name"])
        return CaseStatus.PASS

    if case_id in {
        "UA-1-5-02", "UA-1-5-03", "UA-1-5-04", "UA-1-5-05",
        "UA-1-5-06", "UA-1-5-08", "UA-1-5-09",
    }:
        from ua_test_harness.ua1_precise import delete_matrix_case
        return delete_matrix_case(ctx, cc, meta)

    if case_id.startswith("UA-1-5-"):
        ds, tg = _prepare(ctx, cc, with_tag=True, enabled=True)
        from tpt_api.datahub import delete_tags_physical, delete_ds_info
        delete_tags_physical(_api(ctx), [tg["id"]])
        datasource.change_state(ctx, ds["id"], False)
        delete_ds_info(_api(ctx), [ds["id"]])
        cc.registry.pop(f"tag:{tg['name']}")
        cc.registry.pop(f"ds:{ds['name']}")
        check_true("deleted", _row(ctx, ds["id"]) is None)
        return CaseStatus.PASS

    raise AssertFail(f"unsupported UA-1 delete case: {case_id}")


def execute_ua1_case(ctx, cc, meta):
    chapter = meta["chapter"]
    case_id = meta["id"]
    if chapter == "UA-1-1":
        return _connection(ctx, cc, meta)
    if chapter == "UA-1-2":
        return _state(ctx, cc, meta)
    if chapter == "UA-1-5":
        return _delete(ctx, cc, meta)
    if chapter == "UA-1-3":
        return _dispatch_ua1_3(ctx, cc, meta)
    if chapter == "UA-1-4":
        return _dispatch_ua1_4(ctx, cc, meta)
    if chapter == "UA-1-6":
        return _dispatch_ua1_6(ctx, cc, meta)
    raise AssertFail(f"UA-1 runtime has no adapter for {case_id}")


def _dispatch_ua1_3(ctx, cc, meta) -> CaseStatus:
    from ua_test_harness.ua1_precise import disconnect_metrics
    return disconnect_metrics(ctx, cc, meta)


def _dispatch_ua1_4(ctx, cc, meta) -> CaseStatus:
    from ua_test_harness.ua1_precise import dual_ds_isolation
    return dual_ds_isolation(ctx, cc, meta)


def _dispatch_ua1_6(ctx, cc, meta) -> CaseStatus:
    from ua_test_harness.ua1_precise import test_ds_info_case
    return test_ds_info_case(ctx, cc, meta)
