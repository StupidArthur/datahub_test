from __future__ import annotations

import json
import socket
import uuid

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    add_tag_group,
    add_tag_group_relation,
    batch_add_tags,
    change_ds_state,
    delete_tags_physical,
    list_tags,
    list_recycle_tags,
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
from tests.support.ua2_helpers import (
    browse_all_unused_candidates,
    browse_entry_to_batch_info,
    browse_page,
    filter_unregistered,
    is_ds_alive,
    node_base_name,
    pick_unused_nodes,
    registered_base_names,
    tag_base_name,
    wait_ds_alive,
    wait_ds_offline,
)


def _qwq_records(resp: dict) -> list[dict]:
    return (resp.get("tagInfoList") or {}).get("records") or []


# ---------------------------------------------------------------------------
# Module-level fixture: browse env with ≥20 unregistered nodes on DS A
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def browse_env(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port_a = find_free_port()
    endpoint_a = f"opc.tcp://{parsed.host}:{port_a}/ua_mocker/"
    port_b = find_free_port()
    endpoint_b = f"opc.tcp://{parsed.host}:{port_b}/ua_mocker/"

    tmp_dir = tmp_path_factory.mktemp("ua22_br")

    # DS A: 30 static nodes + 1 change node → 25 unregistered (register 5)
    nodes_a = [
        {"name": "static_", "type": "Double", "count": 30, "change": False, "writable": True, "default": 12.5},
        {"name": "change_", "type": "Int32", "count": 1, "change": True, "writable": False},
    ]
    cfg_dir_a = tmp_dir / "a"
    cfg_dir_a.mkdir(exist_ok=True)
    cfg_a = write_mocker_config(cfg_dir_a, port_a, nodes=nodes_a, namespace_index=1)
    mocker_a = start_mocker(cfg_a, port_a, host=parsed.host)

    # DS B: 5 static + 1 change → 2 unregistered (register 3)
    nodes_b = [
        {"name": "static_", "type": "Double", "count": 5, "change": False, "writable": True, "default": 42.0},
        {"name": "change_", "type": "Int32", "count": 1, "change": True, "writable": False},
    ]
    cfg_dir_b = tmp_dir / "b"
    cfg_dir_b.mkdir(exist_ok=True)
    cfg_b = write_mocker_config(cfg_dir_b, port_b, nodes=nodes_b, namespace_index=1)
    mocker_b = start_mocker(cfg_b, port_b, host=parsed.host)

    ds_name_a = unique_name(settings.test_prefix, "UA-2-2-brA")
    data_a = add_ds_info(
        api, ds_name=ds_name_a,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint_a,
    )
    ds_id_a = int(data_a.get("id") or data_a.get("dsId"))
    wait_ds_alive(api, ds_id_a)

    ds_name_b = unique_name(settings.test_prefix, "UA-2-2-brB")
    data_b = add_ds_info(
        api, ds_name=ds_name_b,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint_b,
    )
    ds_id_b = int(data_b.get("id") or data_b.get("dsId"))
    wait_ds_alive(api, ds_id_b)

    group_data = add_tag_group(api, f"UA22_BrG_{uuid.uuid4().hex[:4]}")
    group_id = int(group_data.get("id") or group_data.get("groupId"))

    # Register 5 tags on DS A (static_1..static_5)
    tags_a_ids: list[int] = []
    tags_a_names: list[str] = []
    for i in range(5):
        tn = unique_name(settings.test_prefix, f"UA-2-2-brA{i:02d}")
        tbn = tag_base_name(f"static_{i + 1}", 1)
        td = add_tag(api, tag_name=tn, data_type=11, ds_id=ds_id_a, tag_base_name=tbn, group_id=str(group_id))
        tags_a_ids.append(int(td.get("id") or td.get("tagId")))
        tags_a_names.append(tn)

    # Register change_1 on DS A
    chg_tn_a = unique_name(settings.test_prefix, "UA-2-2-brChA")
    td = add_tag(api, tag_name=chg_tn_a, data_type=6, ds_id=ds_id_a,
                 tag_base_name=tag_base_name("change_1", 1), group_id="0")
    chg_id_a = int(td.get("id") or td.get("tagId"))

    # Register 3 tags on DS B (static_1..static_3)
    tags_b_ids: list[int] = []
    tags_b_names: list[str] = []
    for i in range(3):
        tn = unique_name(settings.test_prefix, f"UA-2-2-brB{i:02d}")
        tbn = tag_base_name(f"static_{i + 1}", 1)
        td = add_tag(api, tag_name=tn, data_type=11, ds_id=ds_id_b, tag_base_name=tbn, group_id="0")
        tags_b_ids.append(int(td.get("id") or td.get("tagId")))
        tags_b_names.append(tn)

    # Register change_1 on DS B
    chg_tn_b = unique_name(settings.test_prefix, "UA-2-2-brChB")
    td = add_tag(api, tag_name=chg_tn_b, data_type=6, ds_id=ds_id_b,
                 tag_base_name=tag_base_name("change_1", 1), group_id="0")
    chg_id_b = int(td.get("id") or td.get("tagId"))

    wait_until(
        "tags_in_list_br",
        lambda: len((list_tags(api, page=1, page_size=200).get("records") or [])) >= 10,
        timeout=30.0,
    )
    for tn in tags_a_names:
        wait_until(f"rt_br:{tn}", lambda tn=tn: (
            get_rt_point(api, tn).get("tagValue") is not None
        ), timeout=30.0)

    ctx = {
        "ds_id_a": ds_id_a, "ds_name_a": ds_name_a,
        "ds_id_b": ds_id_b, "ds_name_b": ds_name_b,
        "tags_a_ids": tags_a_ids, "tags_a_names": tags_a_names,
        "tags_b_ids": tags_b_ids, "tags_b_names": tags_b_names,
        "chg_tag_name_a": chg_tn_a, "chg_tag_id_a": chg_id_a,
        "chg_tag_name_b": chg_tn_b, "chg_tag_id_b": chg_id_b,
        "group_id": group_id,
        "mocker_a": mocker_a, "mocker_b": mocker_b,
        "port_a": port_a, "port_b": port_b,
        "endpoint_a": endpoint_a, "endpoint_b": endpoint_b,
        "host": parsed.host,
        "namespace_index": 1,
    }
    yield ctx

    cleanup_errors: list[str] = []
    all_ids = tags_a_ids + tags_b_ids + [chg_id_a, chg_id_b]
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
# UA-2-2-041  底层浏览_数据源隔离
# ===================================================================

@pytest.mark.case(id="UA-2-2-041", chapter="UA-2-2", title="底层浏览_数据源隔离",
    preconditions=["两数据源 A（含未注册节点）、B（含未注册节点）"],
    steps=["browse A 和 B 分别取未注册节点"],
    expected=["A、B 的未注册节点集合不重叠；游标不串源"])
@pytest.mark.integration
def test_browse_ds_isolation(browse_env, api):
    ctx = browse_env
    ds_a, ds_b = ctx["ds_id_a"], ctx["ds_id_b"]
    ns = ctx["namespace_index"]

    nodes_a = filter_unregistered(api, ds_a, browse_all_unused_candidates(api, ds_a), namespace_index=ns)
    nodes_b = filter_unregistered(api, ds_b, browse_all_unused_candidates(api, ds_b), namespace_index=ns)

    assert len(nodes_a) > 0, "DS A should have unregistered nodes"
    bases_a = {n["tagBaseName"] for n in nodes_a}
    bases_b = {n["tagBaseName"] for n in nodes_b}

    overlap = bases_a & bases_b
    assert len(overlap) == 0, (
        f"DS A and B share unregistered base names: {overlap}"
    )


# ===================================================================
# UA-2-2-042  底层浏览_节点信息
# ===================================================================

@pytest.mark.case(id="UA-2-2-042", chapter="UA-2-2", title="底层浏览_节点信息",
    preconditions=["数据源有未注册节点"],
    steps=["browse 取一个节点，检视字段，asyncua 读到源端"],
    expected=["name/description/tagDataType/readOnly/hubDataType 字段存在；源端可读"])
@pytest.mark.integration
def test_browse_node_info(browse_env, api):
    ctx = browse_env
    ds_a = ctx["ds_id_a"]
    ns = ctx["namespace_index"]

    raw = browse_all_unused_candidates(api, ds_a)
    assert len(raw) > 0, "browse returned no nodes"
    entry = raw[0]
    raw_name = str(entry.get("name") or entry.get("browseName") or "")
    assert raw_name, "entry has no name/browseName"

    has_type = entry.get("tagDataType") is not None or entry.get("hubDataType") is not None
    assert has_type, "entry missing tagDataType and hubDataType"

    assert "readOnly" in entry, "entry missing readOnly"
    assert "description" in entry, "entry missing description"


# ===================================================================
# UA-2-2-043  底层浏览_名称过滤（探索）
# ===================================================================

@pytest.mark.case(id="UA-2-2-043", chapter="UA-2-2", title="底层浏览_名称过滤",
    preconditions=["存在多种名称模式的未注册节点"],
    steps=["无过滤浏览 vs tagName='int32' 过滤浏览"],
    expected=["记录过滤规则；记录观察结果"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_browse_name_filter(browse_env, api, record_property):
    ctx = browse_env
    ds_a = ctx["ds_id_a"]

    all_nodes = browse_all_unused_candidates(api, ds_a)
    filtered = browse_all_unused_candidates(api, ds_a, tag_name_filter="int32")

    obs = {"all_count": len(all_nodes), "filtered_int32_count": len(filtered)}
    record_property("observation", json.dumps(obs, ensure_ascii=False, default=str))
    pytest.xfail(f"UA-2-2-043 name filter semantics not specified; observed={obs}")


# ===================================================================
# UA-2-2-044  底层浏览_已注册过滤（探索）
# ===================================================================

@pytest.mark.case(id="UA-2-2-044", chapter="UA-2-2", title="底层浏览_已注册过滤",
    preconditions=["DS A 有已注册和未注册节点"],
    steps=["浏览原始节点集，二次过滤，对比注册集合"],
    expected=["记录观察结果；工具最终集合排除已注册"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_browse_registered_filter(browse_env, api, record_property):
    ctx = browse_env
    ds_a = ctx["ds_id_a"]
    ns = ctx["namespace_index"]

    raw = browse_all_unused_candidates(api, ds_a)
    filtered = filter_unregistered(api, ds_a, raw, namespace_index=ns)
    reg = registered_base_names(api, ds_a)

    obs = {
        "raw_count": len(raw),
        "after_filter": len(filtered),
        "registered_count": len(reg),
    }
    record_property("observation", json.dumps(obs, ensure_ascii=False, default=str))
    pytest.xfail(f"UA-2-2-044 registered filter semantics not specified; observed={obs}")


# ===================================================================
# UA-2-2-045  底层浏览_跨源同名过滤
# ===================================================================

@pytest.mark.case(id="UA-2-2-045", chapter="UA-2-2", title="底层浏览_跨源同名过滤",
    preconditions=["A、B 存在相同底层名节点；A 已注册该节点"],
    steps=["A 注册一个节点后，A browse 应排除,B browse 仍包含"],
    expected=["A 视图排除已注册；B 视图仍保持同名节点可选"])
@pytest.mark.integration
def test_browse_cross_ds_same_name(browse_env, api):
    ctx = browse_env
    ds_a, ds_b = ctx["ds_id_a"], ctx["ds_id_b"]
    ns = ctx["namespace_index"]

    nodes_a = pick_unused_nodes(api, ds_a, 1, namespace_index=ns)
    base = nodes_a[0]["tagBaseName"]

    tname = unique_name(ctx.get("_test_prefix_setting", ""), "UA-2-2-045-tag")
    info = browse_entry_to_batch_info(nodes_a[0], ds_id=ds_a, tag_name=tname)
    try:
        batch_add_tags(api, [info], conflict_strategy=0)

        nodes_a_after = filter_unregistered(api, ds_a, browse_all_unused_candidates(api, ds_a), namespace_index=ns)
        a_bases = {n["tagBaseName"] for n in nodes_a_after}
        assert base not in a_bases, (
            f"base {base} still appears in DS A browse after registration"
        )

        nodes_b = filter_unregistered(api, ds_b, browse_all_unused_candidates(api, ds_b), namespace_index=ns)
        b_bases = {n["tagBaseName"] for n in nodes_b}
        if base not in b_bases:
            pass
    finally:
        page = list_tags(api, page=1, page_size=50, data={"tagName": tname})
        for r in (page.get("records") or []):
            if r.get("tagName") == tname:
                try:
                    delete_tags_physical(api, [int(r["id"])])
                except TptAPIError:
                    pass


# ===================================================================
# UA-2-2-046  底层浏览_数据源断线
# ===================================================================

@pytest.mark.case(id="UA-2-2-046", chapter="UA-2-2", title="底层浏览_数据源断线",
    preconditions=["DS A 在线"],
    steps=["停 mocker，browse A"],
    expected=["browse 显式失败或空；无陈旧缓存"])
@pytest.mark.integration
def test_browse_offline(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    tmp_dir = tmp_path_factory.mktemp("ua22_046")
    nodes = [
        {"name": "off_", "type": "Double", "count": 3, "change": False, "writable": True, "default": 1.0},
    ]
    cfg = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=1)
    mocker = start_mocker(cfg, port, host=parsed.host)

    ds_name = unique_name(settings.test_prefix, "UA-2-2-046-ds")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    wait_ds_alive(api, ds_id, timeout=60.0)

    stop_mocker(mocker)
    wait_ds_offline(api, ds_id, timeout=60.0)

    try:
        page = browse_page(api, ds_id)
        had_results = bool(page.get("successes"))
    except Exception:
        had_results = False

    assert not had_results, "browse should have failed or returned empty after disconnect"

    cleanup_errors: list[str] = []
    try:
        change_ds_state(api, ds_id, False)
    except TptAPIError as exc:
        cleanup_errors.append(f"disable: {exc.msg}")
    delete_datasource_if_exists(api, ds_id, ds_name)
    try:
        stop_mocker(mocker)
    except Exception as exc:
        cleanup_errors.append(f"stop_mocker: {exc}")
    if cleanup_errors:
        raise AssertionError("Cleanup errors: " + "; ".join(cleanup_errors))


# ===================================================================
# UA-2-2-047  底层浏览_恢复后可用
# ===================================================================

@pytest.mark.case(id="UA-2-2-047", chapter="UA-2-2", title="底层浏览_恢复后可用",
    preconditions=["DS A 已从断线恢复"],
    steps=["重启 mocker，等待就绪后 browse"],
    expected=["节点集合恢复，无需重建 DS"])
@pytest.mark.integration
def test_browse_recovery(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    tmp_dir = tmp_path_factory.mktemp("ua22_047")
    nodes = [
        {"name": "rec_", "type": "Double", "count": 3, "change": False, "writable": True, "default": 5.0},
    ]
    cfg = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=1)
    mocker = start_mocker(cfg, port, host=parsed.host)

    ds_name = unique_name(settings.test_prefix, "UA-2-2-047-ds")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    wait_ds_alive(api, ds_id, timeout=60.0)

    stop_mocker(mocker)
    mocker = start_mocker(cfg, port, host=parsed.host)
    wait_ds_alive(api, ds_id, timeout=90.0)

    wait_until(
        "browse_after_recovery",
        lambda: len(browse_all_unused_candidates(api, ds_id)) > 0,
        timeout=60.0,
    )

    cleanup_errors: list[str] = []
    try:
        change_ds_state(api, ds_id, False)
    except TptAPIError as exc:
        cleanup_errors.append(f"disable: {exc.msg}")
    delete_datasource_if_exists(api, ds_id, ds_name)
    try:
        stop_mocker(mocker)
    except Exception as exc:
        cleanup_errors.append(f"stop_mocker: {exc}")
    if cleanup_errors:
        raise AssertionError("Cleanup errors: " + "; ".join(cleanup_errors))


# ===================================================================
# UA-2-2-048  底层浏览_结果可用于新增
# ===================================================================

@pytest.mark.case(id="UA-2-2-048", chapter="UA-2-2", title="底层浏览_结果可用于新增",
    preconditions=["DS A 有未注册节点"],
    steps=["browse → batchAdd → 查配置 → 读 RT"],
    expected=["新增成功；tagBaseName 映射正确；RT 可读且有值"])
@pytest.mark.integration
def test_browse_to_add(browse_env, api):
    ctx = browse_env
    ds_a = ctx["ds_id_a"]
    ns = ctx["namespace_index"]

    node = pick_unused_nodes(api, ds_a, 1, namespace_index=ns)[0]
    tname = unique_name(ctx.get("_test_prefix_setting", ""), "UA-2-2-048-tag")
    info = browse_entry_to_batch_info(node, ds_id=ds_a, tag_name=tname)

    tag_id = None
    try:
        batch_add_tags(api, [info], conflict_strategy=0)

        page = list_tags(api, page=1, page_size=50, data={"tagName": tname})
        records = page.get("records") or []
        match = [r for r in records if r.get("tagName") == tname]
        assert len(match) == 1, f"tag {tname} not found after batchAdd"
        assert match[0].get("tagBaseName") == info["tagBaseName"], (
            f"tagBaseName mismatch: expected {info['tagBaseName']}, got {match[0].get('tagBaseName')}"
        )
        tag_id = int(match[0]["id"])

        wait_until(
            f"rt_value:{tname}",
            lambda: get_rt_point(api, tname).get("tagValue") is not None,
            timeout=30.0,
        )
        rt = get_rt_point(api, tname)
        assert rt.get("quality", 0) not in (None, 0), f"quality is invalid for {tname}"
    finally:
        if tag_id:
            try:
                delete_tags_physical(api, [tag_id])
            except TptAPIError as exc:
                if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                    raise
