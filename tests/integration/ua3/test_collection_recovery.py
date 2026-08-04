"""UA-3-1 位号采集 — batch 2: UA-3-1-013 .. UA-3-1-020.

Migrated from ``ua_test_harness/test_cases/UA-3-1.md``.  Each test creates
its own mocker (dynamic port), datasource and tag, and performs strict
cleanup regardless of outcome.

Conventions applied from the source spec:
- real-time value: ``getRTValue(isFromDB=false)`` via ``get_rt_point``
- source ground truth: asyncua direct read of the mock node
- data source lifecycle: ``list_ds_info(alive)`` + ``change_ds_state``
- history closure: ``getHistoryValue`` (method A automatic collection)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from tpt_api.datahub import (
    change_ds_state,
    delete_tags,
    get_history_value,
    list_ds_info,
    remove_tag_group_relation,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point, try_get_rt_point
from tests.support.ua2_helpers import (
    find_unique_tag,
    opcua_read_sync,
    opcua_write_sync,
)
from tests.support.ua3_helpers import (
    add_collection_tag,
    build_node,
    cleanup_ua3_context,
    cleanup_ua3_multi_context,
    node_id_from_cfg,
    wait_rt_matches_source,
    wait_rt_valid,
)
from tests.support.ua2_helpers import setup_ds_only


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


def _is_alive(api, ds_id: int) -> bool:
    page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", -1)) == ds_id:
            return bool(row.get("alive"))
    return False


def _restart_mocker(ctx: dict, tmp_path_factory) -> None:
    from tests.support.mocker_process import start_mocker, stop_mocker, write_mocker_config
    if ctx.get("mocker") is not None:
        stop_mocker(ctx["mocker"])
    ctx["mocker"] = None
    tmp_dir = tmp_path_factory.mktemp(f"restart_{ctx['case_id'].lower()}")
    cfg_path = write_mocker_config(
        tmp_dir, ctx["port"],
        nodes=ctx.get("nodes"), namespace_index=ctx.get("namespace_index", 1),
        cycle=ctx.get("cycle", 500),
    )
    ctx["mocker"] = start_mocker(cfg_path, ctx["port"], host=ctx["host"])


def _wait_alive_false(api, ds_id: int, timeout: float = 120.0) -> float:
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    while time.monotonic() < deadline:
        if not _is_alive(api, ds_id):
            return time.monotonic() - start
        time.sleep(1.0)
    raise AssertionError(f"ds {ds_id} still alive after {timeout}s")


def _wait_alive_true(api, ds_id: int, timeout: float = 120.0) -> float:
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    while time.monotonic() < deadline:
        if _is_alive(api, ds_id):
            return time.monotonic() - start
        time.sleep(1.0)
    raise AssertionError(f"ds {ds_id} did not recover within {timeout}s")


def _rt_quality_invalid(api, tag_name: str, timeout: float = 120.0) -> float:
    """Poll until RT quality is 0 / no value / read error; return elapsed."""
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    while time.monotonic() < deadline:
        pt = try_get_rt_point(api, tag_name)
        if not pt or pt.get("tagValue") is None or pt.get("quality", 0) in (None, 0):
            return time.monotonic() - start
        time.sleep(0.5)
    raise AssertionError(f"RT for {tag_name} still valid after {timeout}s")


# ---------------------------------------------------------------------------
# UA-3-1-013 数据源断线_停止有效采集
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-013", chapter="UA-3-1",
    title="数据源断线_停止有效采集",
    preconditions=["数据源 alive=true", "位号正常采集"],
    steps=["正常采集后停止 Mock", "轮询 ds alive", "轮询 RT 质量", "确认不产生伪造新鲜值"],
    expected=["alive=false", "质量无效", "不产生伪造的新鲜值"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_1_013_source_disconnect(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-013"
    prefix = "ua31_013"
    node = build_node(f"{prefix}_val_", "Int32", change=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="INT"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        pt_before = get_rt_point(api, tags[0]["tag_name"])
        assert pt_before.get("tagValue") is not None and pt_before.get("quality", 0) != 0

        from tests.support.mocker_process import stop_mocker
        stop_mocker(ctx["mocker"])
        ctx["mocker"] = None

        _wait_alive_false(api, ctx["ds_id"], timeout=120.0)
        _rt_quality_invalid(api, tags[0]["tag_name"], timeout=120.0)
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-014 数据源恢复_自动续采
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-014", chapter="UA-3-1",
    title="数据源恢复_自动续采",
    preconditions=["UA-3-1-013 后：mock 已停止；数据源 enabled；alive=false"],
    steps=["重启 Mock 并修改源值", "轮询 alive", "轮询 RT", "确认无需重建自动恢复"],
    expected=["alive=true", "质量和数据自动恢复", "值可被继续采集"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_1_014_source_reconnect(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-014"
    prefix = "ua31_014"
    node = build_node(f"{prefix}_val_", "Double", 100.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)
        snap0 = wait_rt_matches_source(api, ctx, tags[0]["tag_name"], node_id, "DOUBLE", timeout=30.0)
        assert snap0.get("tagValue") is not None

        from tests.support.mocker_process import stop_mocker
        stop_mocker(ctx["mocker"])
        ctx["mocker"] = None
        _wait_alive_false(api, ctx["ds_id"], timeout=120.0)

        new_value = 555.0
        _restart_mocker(ctx, tmp_path_factory)
        _wait_alive_true(api, ctx["ds_id"], timeout=120.0)
        opcua_write_sync(ctx["endpoint"], node_id, new_value, namespace_index=ctx["namespace_index"])

        snap = wait_rt_matches_source(
            api, ctx, tags[0]["tag_name"], node_id, "DOUBLE",
            expected=new_value, timeout=120.0,
        )
        assert snap.get("tagValue") is not None, "RT did not recover after reconnect"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-015 数据源禁用_停止采集
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-015", chapter="UA-3-1",
    title="数据源禁用_停止采集",
    preconditions=["数据源 alive=true", "位号正常采集"],
    steps=["changeState 禁用数据源", "轮询 RT 质量", "确认配置仍存在"],
    expected=["采集停止", "质量无效", "配置仍存在"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_1_015_ds_disable(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-015"
    prefix = "ua31_015"
    node = build_node(f"{prefix}_val_", "Int32", change=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="INT"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        change_ds_state(api, ctx["ds_id"], False)
        _rt_quality_invalid(api, tags[0]["tag_name"], timeout=120.0)

        rec = find_unique_tag(api, tags[0]["tag_name"])
        assert rec, "tag config should still exist after ds disable"
        assert int(rec.get("dsId", -1)) == ctx["ds_id"]
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-016 数据源重新启用
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-016", chapter="UA-3-1",
    title="数据源重新启用",
    preconditions=["UA-3-1-015 后：数据源已禁用；mock 仍运行"],
    steps=["重新启用数据源", "轮询 RT", "确认值与源端一致"],
    expected=["自动恢复采集", "值与源端一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_1_016_ds_reenable(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-016"
    prefix = "ua31_016"
    node = build_node(f"{prefix}_val_", "Double", 200.0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        change_ds_state(api, ctx["ds_id"], False)
        _rt_quality_invalid(api, tags[0]["tag_name"], timeout=120.0)

        change_ds_state(api, ctx["ds_id"], True)
        snap = wait_rt_matches_source(
            api, ctx, tags[0]["tag_name"], node_id, "DOUBLE", timeout=120.0,
        )
        assert snap.get("tagValue") is not None, "RT did not resume after ds re-enable"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-017 单节点异常隔离
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-017", chapter="UA-3-1",
    title="单节点异常隔离",
    preconditions=["同源有多个节点", "数据源 alive=true"],
    steps=["注册两个位号", "使一个节点读取异常（绑定不存在 NodeId）", "确认同源其他节点继续采集"],
    expected=["同源其他正常节点继续采集"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_1_017_single_node_isolation(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-017"
    prefix = "ua31_017"
    good_node = build_node(f"{prefix}_good_", "Int32", change=True)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [good_node])
    tags = []
    try:
        good_tag = add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id_from_cfg(good_node), type_key="INT")
        bad_tag = add_collection_tag(api, settings, ctx, case_id, node_id_str="ua31_017_bad", type_key="INT")
        tags = [good_tag, bad_tag]
        wait_rt_valid(api, good_tag["tag_name"], timeout=60.0)

        # 坏节点不产生伪造有效值
        try:
            pt = get_rt_point(api, bad_tag["tag_name"])
            assert pt.get("tagValue") is None or pt.get("quality", 0) in (None, 0), \
                f"bad node produced fake valid value: {pt}"
        except TptAPIError:
            pass

        # 好节点持续采集
        deadline = time.monotonic() + 15.0
        vals = set()
        while time.monotonic() < deadline:
            pt = get_rt_point(api, good_tag["tag_name"])
            if pt.get("tagValue") is not None:
                vals.add(pt["tagValue"])
            time.sleep(1.0)
        assert len(vals) >= 2, f"good node did not keep collecting: observed {sorted(vals)}"
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-018 多数据源隔离
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-018", chapter="UA-3-1",
    title="多数据源隔离",
    preconditions=["两个独立数据源 A/B", "数据源 A/B alive=true"],
    steps=["A 断线，B 保持运行", "读取 B 的值、质量和时间", "确认 B 不受 A 影响"],
    expected=["B 的值、质量和时间不受 A 影响"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_1_018_multi_ds_isolation(api, settings, tmp_path_factory, mocker_endpoint):
    from tests.support.endpoints import parse_mocker_endpoint
    from tests.support.mocker_process import find_free_port, start_mocker, stop_mocker, write_mocker_config
    from tests.support.naming import unique_name
    from tpt_api.datahub import add_ds_info
    from tpt_api.types import DsSubTypes, DsTypes

    case_id = "UA-3-1-018"
    parsed = parse_mocker_endpoint(mocker_endpoint)

    def _build_ds(letter: str, node) -> tuple[dict, dict]:
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
        wait_until(f"ds_alive:{case_id}-{letter}", lambda: _is_alive(api, ds_id), timeout=60.0)
        return {
            "ds_id": ds_id, "ds_name": ds_name, "mocker": mocker,
            "port": port, "host": parsed.host, "endpoint": endpoint,
            "cfg_path": cfg_path, "namespace_index": 1,
        }, node

    ctx_a, node_a = _build_ds("A", build_node(f"ua31_018_a_", "Int32", change=True))
    ctx_b, node_b = _build_ds("B", build_node(f"ua31_018_b_", "Int32", change=True))
    tags = []
    try:
        tag_a = add_collection_tag(api, settings, ctx_a, case_id, node_id_str=node_id_from_cfg(node_a), type_key="INT")
        tag_b = add_collection_tag(api, settings, ctx_b, case_id, node_id_str=node_id_from_cfg(node_b), type_key="INT")
        tags = [tag_a, tag_b]
        wait_rt_valid(api, tag_a["tag_name"], timeout=60.0)
        wait_rt_valid(api, tag_b["tag_name"], timeout=60.0)

        # A 断线
        stop_mocker(ctx_a["mocker"])
        ctx_a["mocker"] = None
        _wait_alive_false(api, ctx_a["ds_id"], timeout=120.0)

        # B 持续采集
        deadline = time.monotonic() + 15.0
        b_vals = []
        while time.monotonic() < deadline:
            pt = get_rt_point(api, tag_b["tag_name"])
            if pt.get("tagValue") is not None and pt.get("quality", 0) != 0:
                b_vals.append(pt["tagValue"])
            time.sleep(1.0)
        assert len(b_vals) >= 5, f"B did not keep collecting during A outage: {len(b_vals)} samples"
        assert len(set(b_vals)) >= 2, f"B values did not change during A outage: {sorted(set(b_vals))}"
    finally:
        cleanup_ua3_multi_context(api, tags=tags, ds_contexts=[ctx_a, ctx_b])


# ---------------------------------------------------------------------------
# UA-3-1-019 自动采集_历史落地
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-019", chapter="UA-3-1",
    title="自动采集_历史落地",
    preconditions=["使用方式 A 造数前置", "数据源 alive=true"],
    steps=["按方式 A 制造唯一值序列", "等待历史可见", "查询历史核对关键值、身份、时间和质量"],
    expected=["关键唯一值进入历史", "身份、时间和质量可核对"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_1_019_history_landing(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-1-019"
    prefix = "ua31_019"
    node = build_node(f"{prefix}_val_", "Int32", 0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="INT"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        t0 = datetime.now(timezone.utc)
        sequence = [310001, 310002, 310003, 310004]
        for value in sequence:
            opcua_write_sync(ctx["endpoint"], node_id, value, namespace_index=ctx["namespace_index"])
            wait_rt_matches_source(
                api, ctx, tags[0]["tag_name"], node_id, "INT",
                expected=value, timeout=60.0,
            )

        beg = (t0 - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
        end = (datetime.now(timezone.utc) + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")

        def _history_has_all():
            resp = get_history_value(api, [tags[0]["tag_name"]], beg_time=beg, end_time=end, page_size=500)
            info = resp.get(tags[0]["tag_name"], {})
            records = info.get("list") or []
            vals = {r.get("tagValue") for r in records}
            return all(v in vals for v in sequence), records, info

        ok = False
        last_records = []
        last_info = {}
        deadline = time.monotonic() + 240.0
        while time.monotonic() < deadline:
            ok, last_records, last_info = _history_has_all()
            if ok:
                break
            time.sleep(10.0)
        assert ok, (
            f"history did not contain all unique values {sequence} within timeout; "
            f"total={last_info.get('total')} records={last_records[:20]}"
        )

        for rec in last_records:
            assert rec.get("tagName") == tags[0]["tag_name"], \
                f"history record wrong identity: {rec}"
            if rec.get("tagTime"):
                from tests.support.ua2_rt_assertions import parse_required_timestamp
                parse_required_timestamp(rec["tagTime"])
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-1-020 删除恢复_采集与历史生命周期 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-1-020", chapter="UA-3-1",
    title="删除恢复_采集与历史生命周期",
    preconditions=["使用方式 A 造数前置", "数据源 alive=true"],
    steps=["按方式 A 造数", "软删、等待、恢复后继续造数", "查询历史观察删除期间与恢复后的记录"],
    expected=["记录删除期间是否停采", "恢复后实时和历史采集可继续"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_1_020_delete_restore_history(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-1-020"
    prefix = "ua31_020"
    node = build_node(f"{prefix}_val_", "Int32", 0, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    observations: dict = {}
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="INT"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        t0 = datetime.now(timezone.utc)
        for value in [320001, 320002]:
            opcua_write_sync(ctx["endpoint"], node_id, value, namespace_index=ctx["namespace_index"])
            wait_rt_matches_source(api, ctx, tags[0]["tag_name"], node_id, "INT", expected=value, timeout=60.0)

        delete_tags(api, [tags[0]["tag_id"]])
        observations["deleted"] = True
        time.sleep(15)

        # 恢复：remove_tag_group_relation(group_id="1")
        try:
            resp = remove_tag_group_relation(api, group_id="1", tag_ids=[tags[0]["tag_id"]])
            observations["restore_response"] = str(resp)
        except TptAPIError as exc:
            observations["restore_error"] = {"code": exc.code, "msg": exc.msg}

        for value in [320003, 320004]:
            opcua_write_sync(ctx["endpoint"], node_id, value, namespace_index=ctx["namespace_index"])
            try:
                wait_rt_matches_source(
                    api, ctx, tags[0]["tag_name"], node_id, "INT", expected=value, timeout=60.0,
                )
                observations.setdefault("post_restore_rt_values", []).append(value)
            except AssertionError as exc:
                observations.setdefault("post_restore_rt_errors", []).append(str(exc))

        beg = (t0 - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
        end = (datetime.now(timezone.utc) + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            resp = get_history_value(api, [tags[0]["tag_name"]], beg_time=beg, end_time=end, page_size=500)
            info = resp.get(tags[0]["tag_name"], {})
            records = info.get("list") or []
            observations["history_values"] = sorted({r.get("tagValue") for r in records})
            observations["history_total"] = info.get("total")
        except TptAPIError as exc:
            observations["history_error"] = {"code": exc.code, "msg": exc.msg}

        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _teardown(api, ctx, tags)

    pytest.xfail(
        "UA-3-1-020 delete/restore collection and history lifecycle semantics "
        "(collection stopped during delete? resumed after restore?) are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
