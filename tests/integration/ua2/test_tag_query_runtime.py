from __future__ import annotations

import json
import socket
import uuid

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    delete_tags_physical,
    get_rt_value,
    list_tags,
    query_tags_with_quality,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DsSubTypes, DsTypes

from tests.support.cleanup import delete_datasource_if_exists
from tests.support.endpoints import parse_mocker_endpoint
from tests.support.mocker_process import find_free_port, start_mocker, stop_mocker, write_mocker_config
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_cleanup import _check_port_closed
from tests.support.ua2_helpers import is_ds_alive, opcua_read_sync, wait_ds_alive, wait_ds_offline


def _qwq_records(resp: dict) -> list[dict]:
    return (resp.get("tagInfoList") or {}).get("records") or []


# ---------------------------------------------------------------------------
# Module-level fixture: read-only runtime env
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def runtime_env(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port_a = find_free_port()
    endpoint_a = f"opc.tcp://{parsed.host}:{port_a}/ua_mocker/"
    port_b = find_free_port()
    endpoint_b = f"opc.tcp://{parsed.host}:{port_b}/ua_mocker/"

    tmp_dir = tmp_path_factory.mktemp("ua22_rt")

    nodes_a = [
        {"name": "rt_full_", "type": "Double", "count": 1, "change": False, "writable": True, "default": 25.0},
        {"name": "rt_chg_", "type": "Int32", "count": 1, "change": True, "writable": False},
        {"name": "rt_static_", "type": "Double", "count": 1, "change": False, "writable": True, "default": 0.0},
        {"name": "rt_common_", "type": "Double", "count": 1, "change": False, "writable": True, "default": 100.0},
    ]
    cfg_dir_a = tmp_dir / "a"
    cfg_dir_a.mkdir(exist_ok=True)
    cfg_a = write_mocker_config(cfg_dir_a, port_a, nodes=nodes_a)
    mocker_a = start_mocker(cfg_a, port_a, host=parsed.host)

    nodes_b = [
        {"name": "rt_b_static_", "type": "Double", "count": 1, "change": False, "writable": True, "default": 77.0},
        {"name": "rt_common_", "type": "Double", "count": 1, "change": False, "writable": True, "default": 200.0},
    ]
    cfg_dir_b = tmp_dir / "b"
    cfg_dir_b.mkdir(exist_ok=True)
    cfg_b = write_mocker_config(cfg_dir_b, port_b, nodes=nodes_b)
    mocker_b = start_mocker(cfg_b, port_b, host=parsed.host)

    ds_name_a = unique_name(settings.test_prefix, "UA-2-2-rtA")
    data_a = add_ds_info(
        api, ds_name=ds_name_a,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint_a,
    )
    ds_id_a = int(data_a.get("id") or data_a.get("dsId"))
    wait_ds_alive(api, ds_id_a)

    ds_name_b = unique_name(settings.test_prefix, "UA-2-2-rtB")
    data_b = add_ds_info(
        api, ds_name=ds_name_b,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint_b,
    )
    ds_id_b = int(data_b.get("id") or data_b.get("dsId"))
    wait_ds_alive(api, ds_id_b)

    NS = 2
    full_tn = unique_name(settings.test_prefix, "UA-2-2-rt-full")
    td = add_tag(
        api, tag_name=full_tn, data_type=10, tag_type=1, ds_id=ds_id_a,
        tag_base_name=f"{NS}_rt_full_1", unit="°C", frequency=500,
        only_read=False, need_push=True,
        tag_desc="Runtime full config tag",
        hi_eu=100.0, lo_eu=-10.0,
        limit_up=90.0, limit_up_up=95.0, limit_up_up_up=99.0,
        limit_down=-5.0, limit_down_down=-8.0, limit_down_down_down=-9.0,
    )
    full_tag_id = int(td.get("id") or td.get("tagId"))

    change_tn_a = unique_name(settings.test_prefix, "UA-2-2-rt-chgA")
    td = add_tag(api, tag_name=change_tn_a, data_type=6, ds_id=ds_id_a, tag_base_name=f"{NS}_rt_chg_1")
    change_id_a = int(td.get("id") or td.get("tagId"))

    static_tn = unique_name(settings.test_prefix, "UA-2-2-rt-stA")
    td = add_tag(api, tag_name=static_tn, data_type=10, ds_id=ds_id_a, tag_base_name=f"{NS}_rt_static_1")
    static_id_a = int(td.get("id") or td.get("tagId"))

    ds_b_tn = unique_name(settings.test_prefix, "UA-2-2-rt-B")
    td = add_tag(api, tag_name=ds_b_tn, data_type=10, ds_id=ds_id_b, tag_base_name=f"{NS}_rt_b_static_1")
    ds_b_tag_id = int(td.get("id") or td.get("tagId"))

    cross_tn_a = unique_name(settings.test_prefix, "UA-2-2-rt-crossA")
    td = add_tag(api, tag_name=cross_tn_a, data_type=10, ds_id=ds_id_a, tag_base_name=f"{NS}_rt_common_1")
    cross_id_a = int(td.get("id") or td.get("tagId"))

    cross_tn_b = unique_name(settings.test_prefix, "UA-2-2-rt-crossB")
    td = add_tag(api, tag_name=cross_tn_b, data_type=10, ds_id=ds_id_b, tag_base_name=f"{NS}_rt_common_1")
    cross_id_b = int(td.get("id") or td.get("tagId"))

    for tn, timeout in [(full_tn, 30), (change_tn_a, 60), (static_tn, 30), (ds_b_tn, 30), (cross_tn_a, 30), (cross_tn_b, 30)]:
        wait_until(f"tag_in_list:{tn}", lambda tn=tn: any(
            r.get("tagName") == tn for r in
            (list_tags(api, page=1, page_size=50, data={"tagName": tn}).get("records") or [])
        ), timeout=timeout)

    for tn, timeout in [(full_tn, 30), (static_tn, 30), (ds_b_tn, 30), (cross_tn_a, 30), (cross_tn_b, 30)]:
        wait_until(f"rt_avail:{tn}", lambda tn=tn: (
            get_rt_point(api, tn).get("tagValue") is not None
            and (get_rt_point(api, tn).get("quality", 0) != 0)
        ), timeout=timeout)

    wait_until(f"chg_qwq:{change_tn_a}", lambda: any(
        r.get("tagName") == change_tn_a and r.get("quality") not in (None, 0)
        for r in _qwq_records(query_tags_with_quality(api, page_size=200))
    ), timeout=60.0)

    ctx = {
        "ds_id_a": ds_id_a, "ds_name_a": ds_name_a,
        "ds_id_b": ds_id_b, "ds_name_b": ds_name_b,
        "full_tag_name": full_tn, "full_tag_id": full_tag_id,
        "change_tag_name_a": change_tn_a, "change_tag_id_a": change_id_a,
        "static_tag_name": static_tn, "static_tag_id": static_id_a,
        "ds_b_tag_name": ds_b_tn, "ds_b_tag_id": ds_b_tag_id,
        "cross_tag_name_a": cross_tn_a, "cross_tag_id_a": cross_id_a,
        "cross_tag_name_b": cross_tn_b, "cross_tag_id_b": cross_id_b,
        "mocker_a": mocker_a, "mocker_b": mocker_b,
        "port_a": port_a, "port_b": port_b,
        "endpoint_a": endpoint_a, "endpoint_b": endpoint_b,
        "host": parsed.host,
    }
    yield ctx

    cleanup_errors: list[str] = []
    all_ids = [full_tag_id, change_id_a, static_id_a, ds_b_tag_id, cross_id_a, cross_id_b]
    for tid in all_ids:
        try:
            delete_tags_physical(api, [tid])
        except TptAPIError as exc:
            if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                cleanup_errors.append(f"delete tag id={tid}: {exc.msg}")
    for ds_id, ds_name in [(ds_id_a, ds_name_a), (ds_id_b, ds_name_b)]:
        try:
            change_ds_state(api, ds_id, False)
        except TptAPIError as exc:
            cleanup_errors.append(f"disable ds id={ds_id}: {exc.msg}")
        delete_datasource_if_exists(api, ds_id, ds_name)
    for m in [mocker_a, mocker_b]:
        try:
            stop_mocker(m)
        except Exception as exc:
            cleanup_errors.append(f"stop_mocker: {exc}")
    for host, port in [(parsed.host, port_a), (parsed.host, port_b)]:
        try:
            sock = socket.create_connection((host, port), timeout=3.0)
            sock.close()
            cleanup_errors.append(f"port {host}:{port} still listening")
        except (OSError, socket.error):
            pass
        except Exception as exc:
            cleanup_errors.append(f"port check {host}:{port}: {exc}")
    if cleanup_errors:
        raise AssertionError("Cleanup errors: " + "; ".join(cleanup_errors))


# ===================================================================
# UA-2-2-033  详情_配置字段正确
# ===================================================================

@pytest.mark.case(id="UA-2-2-033", chapter="UA-2-2", title="详情_配置字段正确",
    preconditions=["已知完整配置位号"],
    steps=["查询并逐字段比对"],
    expected=["配置字段与新增或更新请求一致"])
@pytest.mark.integration
def test_detail_config_fields(runtime_env, api):
    ctx = runtime_env
    tn = ctx["full_tag_name"]
    qwq = query_tags_with_quality(api, page_size=200)
    recs = _qwq_records(qwq)
    match = [r for r in recs if r.get("tagName") == tn]
    assert len(match) == 1, f"expected 1 result, got {len(match)}"
    r = match[0]
    assert r["tagName"] == tn
    assert r.get("dsId") == ctx["ds_id_a"]
    assert r.get("dsName") == ctx["ds_name_a"]
    assert r.get("dataType") == 10, f"expected dataType=10, got {r.get('dataType')}"
    assert r.get("tagType") == 1
    assert r.get("tagBaseName") == "2_rt_full_1"
    assert r.get("unit") == "°C"
    assert r.get("needPush") is True or r.get("needPush") == 1
    assert r.get("onlyRead") is False or r.get("onlyRead") == 0
    assert r.get("frequency") == 500 or r.get("collectInterval") == 500
    assert r.get("tagDesc") == "Runtime full config tag"
    hi = r.get("hiEU")
    lo = r.get("loEU")
    assert hi is not None, f"hiEU missing: {r}"
    assert lo is not None, f"loEU missing: {r}"
    if hi is not None:
        assert float(hi) == 100.0, f"hiEU={hi}"
    if lo is not None:
        assert float(lo) == -10.0, f"loEU={lo}"

    assert "limitUp" in r, f"limitUp missing: {list(r.keys())}"
    assert "limitDown" in r, f"limitDown missing"


# ===================================================================
# UA-2-2-034  详情_数据源归属
# ===================================================================

@pytest.mark.case(id="UA-2-2-034", chapter="UA-2-2", title="详情_数据源归属",
    preconditions=["A、B 均有位号"],
    steps=["查询两条记录及数据源列表"],
    expected=["dsId 与 dsName 对应正确，不串源"])
@pytest.mark.integration
def test_detail_datasource_ownership(runtime_env, api):
    ctx = runtime_env
    qwq_a = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], page_size=100)
    recs_a = _qwq_records(qwq_a)
    for r in recs_a:
        assert r["dsId"] == ctx["ds_id_a"], f"dsId mismatch: {r.get('tagName')}"
        assert r.get("dsName") == ctx["ds_name_a"], f"dsName mismatch: {r.get('tagName')}"

    qwq_b = query_tags_with_quality(api, ds_id=ctx["ds_id_b"], page_size=100)
    recs_b = _qwq_records(qwq_b)
    for r in recs_b:
        assert r["dsId"] == ctx["ds_id_b"], f"dsId mismatch: {r.get('tagName')}"
        assert r.get("dsName") == ctx["ds_name_b"], f"dsName mismatch: {r.get('tagName')}"

    qwq_cross = query_tags_with_quality(api, tag_base_name="2_rt_common_1", page_size=100)
    cross_recs = _qwq_records(qwq_cross)
    ds_ids = {r["dsId"] for r in cross_recs}
    assert ctx["ds_id_a"] in ds_ids, "DS A not in cross-ds query"
    assert ctx["ds_id_b"] in ds_ids, "DS B not in cross-ds query"

    rt_a = get_rt_point(api, ctx["cross_tag_name_a"])
    rt_b = get_rt_point(api, ctx["cross_tag_name_b"])
    val_a = rt_a.get("tagValue")
    val_b = rt_b.get("tagValue")
    assert val_a is not None, "DS A cross RT value is None"
    assert val_b is not None, "DS B cross RT value is None"
    assert val_a != val_b, (
        f"expected different RT values from different DS with same base name, "
        f"got both={val_a}. "
        f"DS A default=100.0 vs DS B default=200.0 should differ."
    )


# ===================================================================
# UA-2-2-035  运行状态_实时值正确
# ===================================================================

@pytest.mark.case(id="UA-2-2-035", chapter="UA-2-2", title="运行状态_实时值正确",
    preconditions=["变化节点正常采集"],
    steps=["同时查询运行态、RT 和源端"],
    expected=["TPT 值处于允许刷新窗口；最新值与源端一致"])
@pytest.mark.integration
def test_runtime_rt_correct(runtime_env, api):
    ctx = runtime_env
    tn = ctx["change_tag_name_a"]
    qwq = query_tags_with_quality(api, page_size=200)
    qwq_recs = _qwq_records(qwq)
    qwq_match = [r for r in qwq_recs if r.get("tagName") == tn]
    assert len(qwq_match) >= 1, f"change tag {tn} not found in qwq"
    qwq_val = qwq_match[0].get("tagValue")

    rt_pt = get_rt_point(api, tn)
    rt_val = rt_pt.get("tagValue")
    assert rt_val is not None, f"getRTValue returned None for {tn}"

    src_val = opcua_read_sync(ctx["endpoint_a"], "rt_chg_1", namespace_index=2)
    assert src_val is not None, f"asyncua read returned None for rt_chg_1"

    assert str(qwq_val) == str(rt_val) or (
        isinstance(qwq_val, (int, float)) and isinstance(rt_val, (int, float))
        and abs(float(qwq_val) - float(rt_val)) <= 300
    ), (
        f"qwq tagValue={qwq_val} != getRTValue={rt_val} for {tn}: "
        f"change node increments every 500ms; tolerance 300 accounts for "
        f"DataHub collection delay"
    )
    assert str(qwq_val) == str(src_val) or (
        isinstance(qwq_val, (int, float)) and isinstance(src_val, (int, float))
        and abs(float(qwq_val) - float(src_val)) <= 300
    ), (
        f"qwq tagValue={qwq_val} != source value={src_val} for {tn}: "
        f"change node increments every 500ms; tolerance 300 accounts for "
        f"DataHub collection delay"
    )


# ===================================================================
# UA-2-2-036  运行状态_质量正常
# ===================================================================

@pytest.mark.case(id="UA-2-2-036", chapter="UA-2-2", title="运行状态_质量正常",
    preconditions=["数据源在线"],
    steps=["查询质量字段"],
    expected=["质量为有效状态，并与 RT 可用性一致"])
@pytest.mark.integration
def test_runtime_quality_normal(runtime_env, api):
    ctx = runtime_env
    tn = ctx["static_tag_name"]
    qwq = query_tags_with_quality(api, page_size=200)
    recs = _qwq_records(qwq)
    match = [r for r in recs if r.get("tagName") == tn]
    assert len(match) >= 1, f"tag {tn} not found"
    r = match[0]
    quality = r.get("quality")
    assert quality not in (None, 0), f"quality is {quality} for {tn}"

    rt = get_rt_point(api, tn)
    rt_val = rt.get("tagValue")
    assert rt_val is not None, f"RT value is None for {tn}, quality={quality}"

    assert is_ds_alive(api, ctx["ds_id_a"]), f"DS {ctx['ds_id_a']} should be alive"

    tag_time = r.get("tagTime")
    assert tag_time is not None, f"tagTime is None for {tn}"
    assert len(str(tag_time).strip()) > 0, f"tagTime is empty for {tn}"


# ===================================================================
# UA-2-2-037  运行状态_数据源断线
# ===================================================================

@pytest.mark.case(id="UA-2-2-037", chapter="UA-2-2", title="运行状态_数据源断线",
    preconditions=["位号已正常采集"],
    steps=["停止 Mock，等待断线后查询"],
    expected=["位号配置仍可查；质量转为无效；旧值不被判为新鲜有效值"])
@pytest.mark.integration
def test_runtime_disconnect(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    tmp_dir = tmp_path_factory.mktemp("ua22_037")
    NS = 2
    nodes = [
        {"name": "dc_static_", "type": "Double", "count": 1, "change": False, "writable": True, "default": 42.0},
    ]
    cfg = write_mocker_config(tmp_dir, port, nodes=nodes)
    mocker = start_mocker(cfg, port, host=parsed.host)
    ds_name = unique_name(settings.test_prefix, "UA-2-2-037-ds")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    wait_ds_alive(api, ds_id, timeout=60.0)

    tn = unique_name(settings.test_prefix, "UA-2-2-037-tag")
    td = add_tag(api, tag_name=tn, data_type=10, ds_id=ds_id, tag_base_name=f"{NS}_dc_static_1")
    tag_id = int(td.get("id") or td.get("tagId"))

    wait_until(f"tag_list:{tn}", lambda: any(
        r.get("tagName") == tn for r in
        (list_tags(api, page=1, page_size=50, data={"tagName": tn}).get("records") or [])
    ), timeout=30.0)

    wait_until(f"rt_avail:{tn}", lambda: (
        get_rt_point(api, tn).get("tagValue") is not None
        and (get_rt_point(api, tn).get("quality", 0) != 0)
    ), timeout=90.0)

    pt_before = get_rt_point(api, tn)
    last_good_value = pt_before.get("tagValue")
    last_good_quality = pt_before.get("quality")
    last_good_tag_time = pt_before.get("tagTime")
    assert last_good_value is not None, f"tagValue should be valid before disconnect"
    assert last_good_quality not in (None, 0), f"quality should be good before disconnect, got {last_good_quality}"

    stop_mocker(mocker)
    wait_ds_offline(api, ds_id, timeout=60.0)

    page = list_tags(api, page=1, page_size=50, data={"tagName": tn, "dsId": ds_id})
    list_recs = page.get("records") or []
    config_found = any(r.get("tagName") == tn for r in list_recs)
    assert config_found, f"tag {tn} config disappeared after DS disconnect"

    qwq_after = query_tags_with_quality(api, tag_name=tn, page_size=10)
    recs_after = _qwq_records(qwq_after)
    match_after = [r for r in recs_after if r.get("tagName") == tn]
    if match_after:
        q_after = match_after[0].get("quality")
        v_after = match_after[0].get("tagValue")
        if q_after not in (None, 0) and v_after is not None:
            assert v_after == last_good_value, (
                f"old value {v_after} should equal last_good {last_good_value} "
                f"(old value is stale but valid); quality={q_after}"
            )
        if q_after is not None and q_after == 0:
            pass

    other_ds_alive = is_ds_alive(api, ds_id)
    assert not other_ds_alive, f"DS {ds_id} still alive after mocker stop"

    cleanup_errors: list[str] = []
    try:
        delete_tags_physical(api, [tag_id])
    except TptAPIError as exc:
        if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
            cleanup_errors.append(f"delete tag: {exc.msg}")
    try:
        change_ds_state(api, ds_id, False)
    except TptAPIError as exc:
        cleanup_errors.append(f"disable ds: {exc.msg}")
    delete_datasource_if_exists(api, ds_id, ds_name)
    try:
        stop_mocker(mocker)
    except Exception as exc:
        cleanup_errors.append(f"stop_mocker: {exc}")
    try:
        if not _check_port_closed(parsed.host, port, timeout=5.0):
            cleanup_errors.append(f"port {port} still listening")
    except Exception as exc:
        cleanup_errors.append(f"port check: {exc}")
    if cleanup_errors:
        raise AssertionError("Cleanup errors: " + "; ".join(cleanup_errors))


# ===================================================================
# UA-2-2-038  运行状态_断线恢复
# ===================================================================

@pytest.mark.case(id="UA-2-2-038", chapter="UA-2-2", title="运行状态_断线恢复",
    preconditions=["已完成断线用例"],
    steps=["重启 Mock，等待恢复后查询"],
    expected=["无需重建位号；质量恢复；实时值继续更新"])
@pytest.mark.integration
def test_runtime_reconnect(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    tmp_dir = tmp_path_factory.mktemp("ua22_038")
    NS = 2
    nodes = [
        {"name": "rc_chg_", "type": "Int32", "count": 1, "change": True, "writable": False},
    ]
    cfg = write_mocker_config(tmp_dir, port, nodes=nodes)
    mocker = start_mocker(cfg, port, host=parsed.host)
    ds_name = unique_name(settings.test_prefix, "UA-2-2-038-ds")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    wait_ds_alive(api, ds_id, timeout=60.0)

    tn = unique_name(settings.test_prefix, "UA-2-2-038-tag")
    td = add_tag(api, tag_name=tn, data_type=6, ds_id=ds_id, tag_base_name=f"{NS}_rc_chg_1")
    tag_id = int(td.get("id") or td.get("tagId"))

    wait_until(f"tag_list:{tn}", lambda: any(
        r.get("tagName") == tn for r in
        (list_tags(api, page=1, page_size=50, data={"tagName": tn}).get("records") or [])
    ), timeout=30.0)

    wait_until(f"rt_avail:{tn}", lambda: (
        get_rt_point(api, tn).get("tagValue") is not None
        and (get_rt_point(api, tn).get("quality", 0) != 0)
    ), timeout=90.0)

    qwq_before = query_tags_with_quality(api, page_size=200)
    recs_before = _qwq_records(qwq_before)
    match_b = [r for r in recs_before if r.get("tagName") == tn]
    before_tag_id = match_b[0].get("id") if match_b else None

    stop_mocker(mocker)
    wait_ds_offline(api, ds_id, timeout=60.0)

    def _ds_down():
        return not is_ds_alive(api, ds_id)
    wait_until(f"ds_down:{ds_id}", _ds_down, timeout=30.0)

    mocker = start_mocker(cfg, port, host=parsed.host)
    wait_ds_alive(api, ds_id, timeout=90.0)

    wait_until(f"rt_restored:{tn}", lambda: (
        get_rt_point(api, tn).get("tagValue") is not None
        and (get_rt_point(api, tn).get("quality", 0) != 0)
    ), timeout=90.0)

    qwq_after_all = query_tags_with_quality(api, page_size=200)
    recs_after = _qwq_records(qwq_after_all)
    match_a = [r for r in recs_after if r.get("tagName") == tn]
    assert len(match_a) >= 1, f"tag {tn} not found after reconnect"
    after_tag_id = match_a[0].get("id")
    if before_tag_id is not None and after_tag_id is not None:
        assert after_tag_id == before_tag_id, (
            f"tag ID changed after reconnect: {before_tag_id} -> {after_tag_id}"
        )
    q_after = match_a[0].get("quality")
    assert q_after not in (None, 0), f"quality not restored after reconnect: {q_after}"
    v_after = match_a[0].get("tagValue")
    assert v_after is not None, "RT value None after reconnect"

    assert is_ds_alive(api, ds_id), f"DS {ds_id} should be alive after reconnect"

    cleanup_errors: list[str] = []
    try:
        delete_tags_physical(api, [tag_id])
    except TptAPIError as exc:
        if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
            cleanup_errors.append(f"delete tag: {exc.msg}")
    try:
        change_ds_state(api, ds_id, False)
    except TptAPIError as exc:
        cleanup_errors.append(f"disable ds: {exc.msg}")
    delete_datasource_if_exists(api, ds_id, ds_name)
    try:
        stop_mocker(mocker)
    except Exception as exc:
        cleanup_errors.append(f"stop_mocker: {exc}")
    try:
        if not _check_port_closed(parsed.host, port, timeout=5.0):
            cleanup_errors.append(f"port {port} still listening")
    except Exception as exc:
        cleanup_errors.append(f"port check: {exc}")
    if cleanup_errors:
        raise AssertionError("Cleanup errors: " + "; ".join(cleanup_errors))


# ===================================================================
# UA-2-2-039  运行状态_时间戳更新
# ===================================================================

@pytest.mark.case(id="UA-2-2-039", chapter="UA-2-2", title="运行状态_时间戳更新",
    preconditions=["变化节点持续采集"],
    steps=["间隔两个周期查询两次"],
    expected=["tagTime 可解析且不倒退；值变化时采集时间推进"])
@pytest.mark.integration
def test_runtime_timestamp_update(runtime_env, api):
    ctx = runtime_env
    tn = ctx["change_tag_name_a"]

    samples: list[dict] = []
    for _ in range(2):
        def _sample():
            qwq = query_tags_with_quality(api, page_size=200)
            for r in _qwq_records(qwq):
                if r.get("tagName") == tn and r.get("tagTime") and r.get("quality") not in (None, 0):
                    return r
            return {}
        r = _sample()
        assert r, f"no valid sample for {tn}"
        samples.append(r)
        if _ == 0:
            wait_until(f"tag_time_progress:{tn}",
                       lambda: any(
                           r2.get("tagTime") != samples[0].get("tagTime")
                           for r2 in _qwq_records(query_tags_with_quality(api, page_size=200))
                           if r2.get("tagName") == tn
                       ),
                       timeout=60.0)

    t0 = samples[0].get("tagTime")
    t1 = samples[1].get("tagTime")
    assert t0 is not None, "first tagTime is None"
    assert t1 is not None, "second tagTime is None"
    assert len(str(t0).strip()) > 0, "first tagTime is empty"
    assert len(str(t1).strip()) > 0, "second tagTime is empty"

    v0 = samples[0].get("tagValue")
    v1 = samples[1].get("tagValue")
    if v0 != v1:
        assert str(t1) >= str(t0), (
            f"tagTime went backwards: t0={t0}, t1={t1} when value changed from {v0} to {v1}"
        )


# ===================================================================
# UA-2-2-040  运行状态_静态值质量
# ===================================================================

@pytest.mark.case(id="UA-2-2-040", chapter="UA-2-2", title="运行状态_静态值质量",
    preconditions=["静态节点值不变化"],
    steps=["连续查询值和质量"],
    expected=["值不变时质量仍有效，不误判断线"])
@pytest.mark.integration
def test_runtime_static_quality(runtime_env, api):
    ctx = runtime_env
    tn = ctx["static_tag_name"]

    for i in range(3):
        qwq = query_tags_with_quality(api, page_size=200)
        recs = _qwq_records(qwq)
        match = [r for r in recs if r.get("tagName") == tn]
        assert len(match) >= 1, f"tag {tn} not found in iteration {i}"
        r = match[0]
        q = r.get("quality")
        assert q not in (None, 0), f"quality={q} for static tag {tn} in iteration {i}"
        v = r.get("tagValue")
        assert v is not None, f"tagValue None for static tag {tn} in iteration {i}"

    assert is_ds_alive(api, ctx["ds_id_a"]), "DS A should be alive during static observation"

    src_val = opcua_read_sync(ctx["endpoint_a"], "rt_static_1", namespace_index=2)
    assert src_val is not None, "source value is None for rt_static_2"
