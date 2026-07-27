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
    change_ds_state,
    delete_tags,
    delete_tags_physical,
    get_all_tags,
    get_not_used_tags,
    get_rt_value,
    list_ds_info,
    list_favorite_tags,
    list_recycle_tags,
    list_tags,
    query_tags_with_quality,
    remove_tag_group_relation,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DsSubTypes, DsTypes

from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists
from tests.support.endpoints import parse_mocker_endpoint
from tests.support.mocker_process import find_free_port, start_mocker, stop_mocker, write_mocker_config
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import is_ds_alive, wait_ds_alive, wait_ds_offline


# ---------------------------------------------------------------------------
# Module-level fixture: creates two datasources + groups + tags
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ua22_env(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port_a = find_free_port()
    endpoint_a = f"opc.tcp://{parsed.host}:{port_a}/ua_mocker/"
    port_b = find_free_port()
    endpoint_b = f"opc.tcp://{parsed.host}:{port_b}/ua_mocker/"

    tmp_dir = tmp_path_factory.mktemp("ua22")

    nodes_a = [
        {"name": "1_static_1", "type": "Double", "count": 1, "change": False, "writable": True, "default": 12.5},
        {"name": "1_change_1", "type": "Int32", "count": 1, "change": True, "writable": False},
        {"name": "1_static_N", "type": "Double", "count": 22, "change": False, "writable": True, "default": 0.0},
    ]
    cfg_dir_a = tmp_dir / "a"
    cfg_dir_a.mkdir(exist_ok=True)
    cfg_a = write_mocker_config(cfg_dir_a, port_a, nodes=nodes_a)
    mocker_a = start_mocker(cfg_a, port_a, host=parsed.host)

    nodes_b = [
        {"name": "1_static_1", "type": "Double", "count": 1, "change": False, "writable": True, "default": 42.0},
        {"name": "1_change_1", "type": "Int32", "count": 1, "change": True, "writable": False},
        {"name": "1_static_2", "type": "Double", "count": 1, "change": False, "writable": True, "default": 99.0},
    ]
    cfg_dir_b = tmp_dir / "b"
    cfg_dir_b.mkdir(exist_ok=True)
    cfg_b = write_mocker_config(cfg_dir_b, port_b, nodes=nodes_b)
    mocker_b = start_mocker(cfg_b, port_b, host=parsed.host)

    ds_name_a = unique_name(settings.test_prefix, "UA-2-2-dsA")
    data_a = add_ds_info(
        api, ds_name=ds_name_a,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint_a,
    )
    ds_id_a = int(data_a.get("id") or data_a.get("dsId"))
    wait_ds_alive(api, ds_id_a)

    ds_name_b = unique_name(settings.test_prefix, "UA-2-2-dsB")
    data_b = add_ds_info(
        api, ds_name=ds_name_b,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint_b,
    )
    ds_id_b = int(data_b.get("id") or data_b.get("dsId"))
    wait_ds_alive(api, ds_id_b)

    group_1_data = add_tag_group(api, f"UA22_Group1_{uuid.uuid4().hex[:4]}")
    group_id_1 = int(group_1_data.get("id") or group_1_data.get("groupId"))
    group_2_data = add_tag_group(api, f"UA22_Empty_{uuid.uuid4().hex[:4]}")
    group_id_2 = int(group_2_data.get("id") or group_2_data.get("groupId"))

    tags_a_ids: list[int] = []
    tags_a_names: list[str] = []
    for i in range(12):
        tn = unique_name(settings.test_prefix, f"UA-2-2-tagA{i:02d}")
        base = "1_static_1" if i < 2 else f"1_static_{i + 2}"
        gid = str(group_id_1) if i < 8 else "0"
        td = add_tag(api, tag_name=tn, data_type=10, ds_id=ds_id_a, tag_base_name=base, group_id=gid)
        tags_a_ids.append(int(td.get("id") or td.get("tagId")))
        tags_a_names.append(tn)

    tags_b_ids: list[int] = []
    tags_b_names: list[str] = []
    for i in range(3):
        tn = unique_name(settings.test_prefix, f"UA-2-2-tagB{i:02d}")
        base = "1_static_1" if i == 0 else f"1_static_{i + 1}"
        td = add_tag(api, tag_name=tn, data_type=10, ds_id=ds_id_b, tag_base_name=base, group_id="0")
        tags_b_ids.append(int(td.get("id") or td.get("tagId")))
        tags_b_names.append(tn)

    change_tn = unique_name(settings.test_prefix, "UA-2-2-chgA")
    td = add_tag(api, tag_name=change_tn, data_type=6, ds_id=ds_id_a, tag_base_name="1_change_1", group_id="0")
    change_id_a = int(td.get("id") or td.get("tagId"))

    change_tn_b = unique_name(settings.test_prefix, "UA-2-2-chgB")
    td = add_tag(api, tag_name=change_tn_b, data_type=6, ds_id=ds_id_b, tag_base_name="1_change_1", group_id="0")
    change_id_b = int(td.get("id") or td.get("tagId"))

    del_tn = unique_name(settings.test_prefix, "UA-2-2-del")
    td = add_tag(api, tag_name=del_tn, data_type=10, ds_id=ds_id_a, tag_base_name="1_static_3", group_id="0")
    del_id = int(td.get("id") or td.get("tagId"))
    delete_tags(api, del_id)

    fav_tn = tags_a_names[0]
    fav_id = tags_a_ids[0]
    add_tag_group_relation(api, 2, [fav_id])

    # Wait for all infrastructure to stabilize — replace fixed sleep with state checks
    wait_until(
        f"tags_in_list",
        lambda: len((list_tags(api, page=1, page_size=200).get("records") or [])) >= 15,
        timeout=30.0,
    )
    wait_until(
        f"rt_static:{tags_a_names[0]}",
        lambda: (get_rt_point(api, tags_a_names[0]).get("tagValue") is not None
                 and (get_rt_point(api, tags_a_names[0]).get("quality", 0) != 0)),
        timeout=30.0,
    )
    wait_until(
        f"chg_quality:{change_tn}",
        lambda: any(
            r.get("tagName") == change_tn and r.get("quality") not in (None, 0) and r.get("tagTime")
            for r in _qwq_records(query_tags_with_quality(api, tag_name=change_tn, page_size=10))
        ),
        timeout=60.0,
    )

    ctx = {
        "ds_id_a": ds_id_a, "ds_name_a": ds_name_a,
        "ds_id_b": ds_id_b, "ds_name_b": ds_name_b,
        "tags_a_ids": tags_a_ids, "tags_a_names": tags_a_names,
        "tags_b_ids": tags_b_ids, "tags_b_names": tags_b_names,
        "change_tag_name_a": change_tn, "change_tag_id_a": change_id_a,
        "change_tag_name_b": change_tn_b, "change_tag_id_b": change_id_b,
        "del_tag_name": del_tn, "del_tag_id": del_id,
        "fav_tag_name": fav_tn, "fav_tag_id": fav_id,
        "group_id_1": group_id_1, "group_id_2": group_id_2,
        "mocker_a": mocker_a, "mocker_b": mocker_b,
        "port_a": port_a, "port_b": port_b,
        "endpoint_a": endpoint_a, "endpoint_b": endpoint_b,
    }
    yield ctx

    cleanup_errors: list[str] = []
    all_tag_ids = tags_a_ids + tags_b_ids + [change_id_a, change_id_b, del_id]
    for tid in all_tag_ids:
        try:
            delete_tags_physical(api, [tid])
        except TptAPIError as exc:
            if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                cleanup_errors.append(f"delete tag id={tid}: {exc.msg}")
    try:
        r_page = list_recycle_tags(api, page=1, page_size=999)
        for t in (r_page.get("tagInfoList") or {}).get("records") or []:
            if t.get("tagName") in [del_tn]:
                try:
                    delete_tags_physical(api, [int(t["id"])])
                except TptAPIError as exc:
                    cleanup_errors.append(f"delete recycle tag {t.get('tagName')}: {exc.msg}")
    except Exception as exc:
        cleanup_errors.append(f"list_recycle_tags: {exc}")
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
            cleanup_errors.append(f"port {host}:{port} still listening after cleanup")
        except (OSError, socket.error):
            pass
        except Exception as exc:
            cleanup_errors.append(f"port check {host}:{port}: {exc}")
    if cleanup_errors:
        raise AssertionError("Cleanup errors: " + "; ".join(cleanup_errors))


# ---------------------------------------------------------------------------
# Helper: extract records from query_tags_with_quality response
# ---------------------------------------------------------------------------

def _qwq_records(resp: dict) -> list[dict]:
    return (resp.get("tagInfoList") or {}).get("records") or []


def _qwq_total(resp: dict) -> int:
    return ((resp.get("tagInfoList") or {}).get("total") or 0)


# ===================================================================
# UA-2-2-001 ~ UA-2-2-005  已注册位号列表
# ===================================================================

@pytest.mark.case(id="UA-2-2-001", chapter="UA-2-2", title="列表_默认范围",
    preconditions=["系统存在已注册位号"],
    steps=["调用 tag-info/page(page=1,size=10,data={})", "调用 queryWithQuality(groupId='0')"],
    expected=["请求成功；分页结构可解析；记录 ID 唯一；数量不超过页大小"])
@pytest.mark.integration
def test_list_default_scope(ua22_env, api):
    ctx = ua22_env
    page = list_tags(api, page=1, page_size=10, data={})
    records = page.get("records") or []
    assert len(records) <= 10
    ids = [r["id"] for r in records if r.get("id")]
    assert len(ids) == len(set(ids)), "duplicate IDs in list_tags"

    qwq = query_tags_with_quality(api, group_id="0", page_size=10)
    qwq_recs = _qwq_records(qwq)
    assert len(qwq_recs) <= 10
    qwq_ids = [r["id"] for r in qwq_recs if r.get("id")]
    assert len(qwq_ids) == len(set(qwq_ids)), "duplicate IDs in queryWithQuality"


@pytest.mark.case(id="UA-2-2-002", chapter="UA-2-2", title="列表_空范围",
    preconditions=["存在无位号分组 G0"],
    steps=["调用 queryWithQuality(groupId=G2)"],
    expected=["成功返回空记录且 total=0；不混入其他分组"])
@pytest.mark.integration
def test_list_empty_scope(ua22_env, api):
    g2 = str(ua22_env["group_id_2"])
    qwq = query_tags_with_quality(api, group_id=g2, page_size=50)
    recs = _qwq_records(qwq)
    assert len(recs) == 0, f"expected empty group, got {len(recs)} records"
    assert _qwq_total(qwq) == 0


@pytest.mark.case(id="UA-2-2-003", chapter="UA-2-2", title="列表_多数据源集合",
    preconditions=["A、B 均有位号"],
    steps=["分别查询 A、B，并查询不限定数据源的范围"],
    expected=["各数据源集合归属正确；相同底层名按 dsId 区分；无重复 ID"])
@pytest.mark.integration
def test_list_multi_ds(ua22_env, api):
    ctx = ua22_env
    qwq_all = query_tags_with_quality(api, group_id="0", page_size=200)
    all_recs = _qwq_records(qwq_all)
    all_ds_ids = {r["dsId"] for r in all_recs if r.get("dsId")}

    qwq_a = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], group_id="0", page_size=100)
    recs_a = _qwq_records(qwq_a)
    for r in recs_a:
        assert r["dsId"] == ctx["ds_id_a"]

    qwq_b = query_tags_with_quality(api, ds_id=ctx["ds_id_b"], group_id="0", page_size=100)
    recs_b = _qwq_records(qwq_b)
    for r in recs_b:
        assert r["dsId"] == ctx["ds_id_b"]

    names_a = {r["tagName"] for r in recs_a}
    names_b = {r["tagName"] for r in recs_b}
    assert not (names_a & names_b), "tagName overlap across ds"

    all_ids = [r["id"] for r in all_recs if r.get("id")]
    assert len(all_ids) == len(set(all_ids))


@pytest.mark.case(id="UA-2-2-004", chapter="UA-2-2", title="列表_配置字段",
    preconditions=["已知完整配置位号"],
    steps=["按 tagName 定位记录"],
    expected=["tagName/tagBaseName/tagType/dsId/dataType/unit/frequency/onlyRead/needPush/tagDesc 与创建请求一致"])
@pytest.mark.integration
def test_list_config_fields(ua22_env, api):
    ctx = ua22_env
    tn = ctx["tags_a_names"][0]
    tag_id = ctx["tags_a_ids"][0]
    page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
    records = page.get("records") or []
    match = [r for r in records if r.get("tagName") == tn]
    assert len(match) == 1, f"expected single match, got {len(match)}"
    r = match[0]
    assert r["tagName"] == tn
    assert r["dsId"] == ctx["ds_id_a"]
    assert r["dataType"] == 10  # Double
    assert r["tagType"] == 1  # 一次位号
    assert "tagBaseName" in r
    assert "unit" in r
    assert "frequency" in r or "collectInterval" in r
    assert "onlyRead" in r


@pytest.mark.case(id="UA-2-2-005", chapter="UA-2-2", title="列表_重复查询稳定性",
    preconditions=["查询期间不修改配置"],
    steps=["相同请求连续执行 3 次"],
    expected=["total 和 ID 顺序稳定；配置字段不漂移"])
@pytest.mark.integration
def test_list_stability(ua22_env, api):
    results = []
    for _ in range(3):
        qwq = query_tags_with_quality(api, group_id="0", page_size=50)
        recs = _qwq_records(qwq)
        total = _qwq_total(qwq)
        ids = [r["id"] for r in recs if r.get("id")]
        results.append((total, tuple(ids)))
    totals = [r[0] for r in results]
    assert len(set(totals)) == 1, f"total changed across runs: {totals}"
    id_sets = [set(r[1]) for r in results]
    for i in range(1, len(id_sets)):
        assert id_sets[i] == id_sets[0], f"ID set changed in run {i}"


# ===================================================================
# UA-2-2-006 ~ UA-2-2-011  按系统位号名查找
# ===================================================================

@pytest.mark.case(id="UA-2-2-006", chapter="UA-2-2", title="系统名_完整名称",
    preconditions=["存在唯一目标位号"],
    steps=["使用完整 tagName 查询"],
    expected=["返回目标记录且不返回无关记录"])
@pytest.mark.integration
def test_sysname_exact(ua22_env, api):
    ctx = ua22_env
    tn = ctx["tags_a_names"][0]
    tag_id = ctx["tags_a_ids"][0]
    qwq = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], tag_name=tn, page_size=50)
    recs = _qwq_records(qwq)
    assert len(recs) == 1, f"expected 1 result, got {len(recs)}"
    r = recs[0]
    assert r["tagName"] == tn
    assert r["id"] == tag_id


@pytest.mark.case(id="UA-2-2-007", chapter="UA-2-2", title="系统名_部分名称",
    preconditions=["存在 tagA00/tagA01/tagA02"],
    steps=["使用公共前缀查询"],
    expected=["记录包含、前缀或精确匹配规则；不得返回明显无关项"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_sysname_partial(ua22_env, api, record_property):
    ctx = ua22_env
    prefix = ctx["tags_a_names"][0][:-2]
    qwq = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], tag_name=prefix, page_size=100)
    recs = _qwq_records(qwq)
    observations = {
        "prefix": prefix,
        "returned_count": len(recs),
        "returned_names": [r["tagName"] for r in recs],
    }
    record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    pytest.xfail(f"UA-2-2-007 partial name match semantics not specified; observed={observations}")


@pytest.mark.case(id="UA-2-2-008", chapter="UA-2-2", title="系统名_不存在",
    preconditions=["目标名称不存在"],
    steps=["使用不存在名称查询"],
    expected=["成功返回空集合，不产生服务器错误"])
@pytest.mark.integration
def test_sysname_not_found(ua22_env, api):
    qwq = query_tags_with_quality(api, tag_name="__nonexistent_ua22__", page_size=10)
    recs = _qwq_records(qwq)
    assert len(recs) == 0


@pytest.mark.case(id="UA-2-2-009", chapter="UA-2-2", title="系统名_大小写",
    preconditions=["存在大小写可区分名称"],
    steps=["分别使用原大小写和变体查询"],
    expected=["记录大小写规则，结果稳定可复现"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_sysname_case(ua22_env, api, record_property):
    ctx = ua22_env
    tn = ctx["tags_a_names"][0]
    tn_upper = tn.upper()
    tn_lower = tn.lower()
    qwq_orig = query_tags_with_quality(api, tag_name=tn, page_size=50)
    qwq_upper = query_tags_with_quality(api, tag_name=tn_upper, page_size=50)
    qwq_lower = query_tags_with_quality(api, tag_name=tn_lower, page_size=50)
    observations = {
        "original_count": len(_qwq_records(qwq_orig)),
        "upper_count": len(_qwq_records(qwq_upper)),
        "lower_count": len(_qwq_records(qwq_lower)),
    }
    record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    pytest.xfail(f"UA-2-2-009 case sensitivity semantics not specified; observed={observations}")


@pytest.mark.case(id="UA-2-2-010", chapter="UA-2-2", title="系统名_Unicode与特殊字符",
    preconditions=["存在中文或允许特殊字符名称"],
    steps=["使用完整名和片段查询"],
    expected=["参数传输正确；无转义错误；记录匹配规则"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_sysname_unicode(api, settings, ua22_env, record_property):
    ctx = ua22_env
    tn = unique_name(settings.test_prefix, "UA-2-2-unicode_测试")
    td = add_tag(api, tag_name=tn, data_type=12, ds_id=ctx["ds_id_a"], tag_base_name="1_static_4", group_id="0")
    tag_id = int(td.get("id") or td.get("tagId"))
    try:
        qwq = query_tags_with_quality(api, tag_name=tn, page_size=10)
        recs = _qwq_records(qwq)
        obs = {"tag_name": tn, "returned_count": len(recs), "match": len(recs) == 1 and recs[0]["tagName"] == tn}
        record_property("observation", json.dumps(obs, ensure_ascii=False, default=str))
        pytest.xfail(f"UA-2-2-010 unicode query semantics not specified; observed={obs}")
    finally:
        try:
            delete_tags_physical(api, [tag_id])
        except TptAPIError as exc:
            if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                raise


@pytest.mark.case(id="UA-2-2-011", chapter="UA-2-2", title="系统名_空条件",
    preconditions=["已完成一次名称过滤"],
    steps=["改用空字符串或不传 tagName 查询"],
    expected=["名称过滤不再生效，恢复同一 dsId/groupId 范围集合"])
@pytest.mark.integration
def test_sysname_empty_condition(ua22_env, api):
    ctx = ua22_env
    qwq_empty = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], tag_name="", page_size=200)
    recs_empty = _qwq_records(qwq_empty)
    qwq_none = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], page_size=200)
    recs_none = _qwq_records(qwq_none)
    assert len(recs_empty) > 0, "empty tag_name should return all tags"
    assert len(recs_empty) == len(recs_none), "empty vs. omitted tag_name should match"


# ===================================================================
# UA-2-2-012 ~ UA-2-2-016  按底层位号名查找
# ===================================================================

@pytest.mark.case(id="UA-2-2-012", chapter="UA-2-2", title="底层名_完整名称",
    preconditions=["系统名与底层名不同"],
    steps=["使用完整 tagBaseName 查询"],
    expected=["定位绑定该节点的位号；系统名与底层名映射正确"])
@pytest.mark.integration
def test_basename_exact(ua22_env, api):
    ctx = ua22_env
    tn = ctx["tags_a_names"][0]
    base = "1_static_1"
    qwq = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], tag_base_name=base, page_size=200)
    recs = _qwq_records(qwq)
    tag_names_found = [r["tagName"] for r in recs]
    assert tn in tag_names_found, f"expected {tn} in results"
    for r in recs:
        assert r["dsId"] == ctx["ds_id_a"], f"unexpected dsId for {r['tagName']}"
        assert base in r["tagBaseName"], f"baseName {r['tagBaseName']} does not contain {base}"


@pytest.mark.case(id="UA-2-2-013", chapter="UA-2-2", title="底层名_部分名称",
    preconditions=["多个底层名共享前缀"],
    steps=["使用公共片段查询"],
    expected=["记录匹配规则；结果仅含符合规则的节点"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_basename_partial(ua22_env, api, record_property):
    qwq = query_tags_with_quality(api, tag_base_name="static", page_size=200)
    recs = _qwq_records(qwq)
    obs = {"returned_count": len(recs), "bases": list({r["tagBaseName"] for r in recs})}
    record_property("observation", json.dumps(obs, ensure_ascii=False, default=str))
    pytest.xfail(f"UA-2-2-013 partial baseName semantics not specified; observed={obs}")


@pytest.mark.case(id="UA-2-2-014", chapter="UA-2-2", title="底层名_跨数据源同名",
    preconditions=["A、B 有相同 tagBaseName"],
    steps=["不限定 dsId 查询，再分别限定 A、B"],
    expected=["记录按 dsId 区分；限定数据源后只返回对应记录"])
@pytest.mark.integration
def test_basename_cross_ds(ua22_env, api):
    ctx = ua22_env
    base = "1_static_1"
    qwq_all = query_tags_with_quality(api, tag_base_name=base, page_size=200)
    recs_all = _qwq_records(qwq_all)
    ds_ids = {r["dsId"] for r in recs_all}
    assert ctx["ds_id_a"] in ds_ids
    assert ctx["ds_id_b"] in ds_ids

    qwq_a = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], tag_base_name=base, page_size=50)
    for r in _qwq_records(qwq_a):
        assert r["dsId"] == ctx["ds_id_a"]

    qwq_b = query_tags_with_quality(api, ds_id=ctx["ds_id_b"], tag_base_name=base, page_size=50)
    for r in _qwq_records(qwq_b):
        assert r["dsId"] == ctx["ds_id_b"]


@pytest.mark.case(id="UA-2-2-015", chapter="UA-2-2", title="底层名_namespace格式",
    preconditions=['存在 "1_static_1"'],
    steps=["使用完整值查询"],
    expected=["完整匹配目标；下划线和 namespace 部分未被截断"])
@pytest.mark.integration
def test_basename_namespace(ua22_env, api):
    base = "1_change_1"
    qwq = query_tags_with_quality(api, tag_base_name=base, page_size=100)
    recs = _qwq_records(qwq)
    assert len(recs) >= 1
    for r in recs:
        assert r["tagBaseName"] == base, f"expected {base}, got {r['tagBaseName']}"


@pytest.mark.case(id="UA-2-2-016", chapter="UA-2-2", title="底层名_不存在",
    preconditions=["目标不存在"],
    steps=["查询不存在 tagBaseName"],
    expected=["成功返回空集合"])
@pytest.mark.integration
def test_basename_not_found(ua22_env, api):
    qwq = query_tags_with_quality(api, tag_base_name="__nonexistent_base__", page_size=10)
    recs = _qwq_records(qwq)
    assert len(recs) == 0


# ===================================================================
# UA-2-2-017 ~ UA-2-2-020  按数据源筛选
# ===================================================================

@pytest.mark.case(id="UA-2-2-017", chapter="UA-2-2", title="数据源_单个数据源",
    preconditions=["A、B 均有位号"],
    steps=["传 dsId=A 查询"],
    expected=["所有记录 dsId=A，集合与已知记录一致"])
@pytest.mark.integration
def test_ds_filter_single(ua22_env, api):
    ctx = ua22_env
    qwq = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], page_size=200)
    recs = _qwq_records(qwq)
    assert len(recs) > 0, "expected tags in ds A"
    for r in recs:
        assert r["dsId"] == ctx["ds_id_a"], f"record dsId={r['dsId']} != {ctx['ds_id_a']}"


@pytest.mark.case(id="UA-2-2-018", chapter="UA-2-2", title="数据源_切换条件",
    preconditions=["A、B 均有位号"],
    steps=["先传 A，再传 B 执行两次请求"],
    expected=["第二次只返回 B；请求之间不串条件"])
@pytest.mark.integration
def test_ds_filter_switch(ua22_env, api):
    ctx = ua22_env
    qwq_a = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], page_size=200)
    recs_a = _qwq_records(qwq_a)
    ids_a = {r["id"] for r in recs_a}

    qwq_b = query_tags_with_quality(api, ds_id=ctx["ds_id_b"], page_size=200)
    recs_b = _qwq_records(qwq_b)
    ids_b = {r["id"] for r in recs_b}

    assert not (ids_a & ids_b), "tags from A leaked into B query"
    for r in recs_b:
        assert r["dsId"] == ctx["ds_id_b"]


@pytest.mark.case(id="UA-2-2-019", chapter="UA-2-2", title="数据源_无位号",
    preconditions=["C 已创建但无位号"],
    steps=["传 dsId=C 查询"],
    expected=["成功返回空集合"])
@pytest.mark.integration
def test_ds_filter_empty(api, settings, ua22_env):
    ctx = ua22_env
    ds_c_name = unique_name(settings.test_prefix, "UA-2-2-C")
    fake_url = f"opc.tcp://10.255.255.1:{find_free_port()}/ua_mocker/"
    data_c = add_ds_info(
        api, ds_name=ds_c_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=fake_url,
    )
    ds_id_c = int(data_c.get("id") or data_c.get("dsId"))
    try:
        qwq = query_tags_with_quality(api, ds_id=ds_id_c, page_size=50)
        recs = _qwq_records(qwq)
        assert len(recs) == 0, f"expected empty DS C, got {len(recs)} tags"
    finally:
        delete_datasource_if_exists(api, ds_id_c, ds_c_name)


@pytest.mark.case(id="UA-2-2-020", chapter="UA-2-2", title="数据源_不传条件",
    preconditions=["已知 A、B 集合"],
    steps=["不传 dsId 查询"],
    expected=["返回接口默认范围；A、B 作子集包含在结果中"])
@pytest.mark.integration
def test_ds_filter_no_param(ua22_env, api):
    ctx = ua22_env
    qwq_all = query_tags_with_quality(api, page_size=200)
    recs_all = _qwq_records(qwq_all)
    all_ids = {r["id"] for r in recs_all}

    qwq_a = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], page_size=200)
    qwq_b = query_tags_with_quality(api, ds_id=ctx["ds_id_b"], page_size=200)
    ids_a = {r["id"] for r in _qwq_records(qwq_a)}
    ids_b = {r["id"] for r in _qwq_records(qwq_b)}

    assert ids_a.issubset(all_ids), "DS A tags missing from unfiltered result"
    assert ids_b.issubset(all_ids), "DS B tags missing from unfiltered result"


# ===================================================================
# UA-2-2-021 ~ UA-2-2-025  按分组筛选
# ===================================================================

@pytest.mark.case(id="UA-2-2-021", chapter="UA-2-2", title="分组_Root范围",
    preconditions=["Root 和普通分组均有位号"],
    steps=["查询 groupId=0"],
    expected=["记录 Root 是直属范围还是包含子组；结果可复现"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_group_root_scope(ua22_env, api, record_property):
    ctx = ua22_env
    qwq = query_tags_with_quality(api, group_id="0", page_size=200)
    recs = _qwq_records(qwq)
    total = _qwq_total(qwq)
    names_in_root = {r["tagName"] for r in recs}
    names_in_g1 = set(ctx["tags_a_names"][:8])
    in_root = [n for n in names_in_root if n in names_in_g1]
    obs = {"total": total, "count": len(recs), "custom_group_tags_in_root": len(in_root)}
    record_property("observation", json.dumps(obs, ensure_ascii=False, default=str))
    pytest.xfail(f"UA-2-2-021 root group scope semantics not specified; observed={obs}")


@pytest.mark.case(id="UA-2-2-022", chapter="UA-2-2", title="分组_普通分组",
    preconditions=["G1 有已知位号"],
    steps=["查询 groupId=G1"],
    expected=["仅返回 G1 范围记录；返回记录均属该分组"])
@pytest.mark.integration
def test_group_normal(ua22_env, api):
    ctx = ua22_env
    gid = str(ctx["group_id_1"])
    qwq = query_tags_with_quality(api, group_id=gid, page_size=200)
    recs = _qwq_records(qwq)
    assert len(recs) > 0, "expected at least 1 tag in group"
    g1_names = set(ctx["tags_a_names"][:8])
    found_names = {r["tagName"] for r in recs}
    common = found_names & g1_names
    assert len(common) > 0, f"no expected group tags found in results"
    extra = found_names - g1_names
    assert len(extra) == 0, f"unexpected tags in group: {extra}"


@pytest.mark.case(id="UA-2-2-023", chapter="UA-2-2", title="分组_空分组",
    preconditions=["G2 无位号"],
    steps=["查询 groupId=G2"],
    expected=["成功返回空集合"])
@pytest.mark.integration
def test_group_empty(ua22_env, api):
    gid = str(ua22_env["group_id_2"])
    qwq = query_tags_with_quality(api, group_id=gid, page_size=50)
    recs = _qwq_records(qwq)
    assert len(recs) == 0, f"expected empty group, got {len(recs)}"
    assert _qwq_total(qwq) == 0


@pytest.mark.case(id="UA-2-2-024", chapter="UA-2-2", title="分组_收藏夹",
    preconditions=["存在收藏和未收藏位号"],
    steps=["调用 tag-group/get(groupId='2')"],
    expected=["仅返回收藏关系中的位号；isCollect 与关系一致"])
@pytest.mark.integration
def test_group_favorites(ua22_env, api):
    ctx = ua22_env
    fav = list_favorite_tags(api, page_size=200)
    recs = (fav.get("tagInfoList") or {}).get("records") or []
    fav_names = {r["tagName"] for r in recs}
    assert ctx["fav_tag_name"] in fav_names, f"favorited tag {ctx['fav_tag_name']} not in favorites"
    nf_names = set(ctx["tags_a_names"][1:]) | set(ctx["tags_b_names"])
    nf_in_fav = fav_names & nf_names
    assert len(nf_in_fav) == 0, f"unfavorited tags found in favorites: {nf_in_fav}"
    for r in recs:
        if r["tagName"] == ctx["fav_tag_name"]:
            assert r.get("isCollect") is True or r.get("isCollect") == 1


@pytest.mark.case(id="UA-2-2-025", chapter="UA-2-2", title="分组_回收站隔离",
    preconditions=["存在正常位号和软删除位号"],
    steps=["分别查询 Root 与 groupId=1"],
    expected=["软删除记录只在回收站；正常记录不被误隐藏"])
@pytest.mark.integration
def test_group_recycle_isolation(ua22_env, api):
    ctx = ua22_env
    recycle = list_recycle_tags(api, page_size=200)
    rec_recs = (recycle.get("tagInfoList") or {}).get("records") or []
    recycle_names = {r["tagName"] for r in rec_recs}
    assert ctx["del_tag_name"] in recycle_names, "soft-deleted tag not in recycle"

    qwq = query_tags_with_quality(api, page_size=200)
    active_names = {r["tagName"] for r in _qwq_records(qwq)}
    assert ctx["del_tag_name"] not in active_names, "soft-deleted tag leaked into active list"

    for r in rec_recs:
        if r["tagName"] == ctx["del_tag_name"]:
            assert r["id"] == ctx["del_tag_id"], "del tag id mismatch in recycle"


# ===================================================================
# UA-2-2-026 ~ UA-2-2-032  组合条件查询
# ===================================================================

@pytest.mark.case(id="UA-2-2-026", chapter="UA-2-2", title="组合_数据源与系统名",
    preconditions=["A、B 有相近名称"],
    steps=["传 dsId=A + tagName"],
    expected=["每条记录同时满足两个条件"])
@pytest.mark.integration
def test_combined_ds_and_name(ua22_env, api):
    ctx = ua22_env
    tn = ctx["tags_a_names"][0]
    qwq = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], tag_name=tn, page_size=50)
    recs = _qwq_records(qwq)
    assert len(recs) == 1, f"expected 1 result, got {len(recs)}"
    r = recs[0]
    assert r["tagName"] == tn
    assert r["dsId"] == ctx["ds_id_a"]


@pytest.mark.case(id="UA-2-2-027", chapter="UA-2-2", title="组合_数据源与底层名",
    preconditions=["A、B 有相同底层名"],
    steps=["传 dsId=A + tagBaseName"],
    expected=["只返回 A 中匹配记录"])
@pytest.mark.integration
def test_combined_ds_and_base(ua22_env, api):
    ctx = ua22_env
    base = "1_static_1"
    qwq = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], tag_base_name=base, page_size=200)
    recs = _qwq_records(qwq)
    assert len(recs) >= 1, "expected at least 1 tag in A with base 1_static_1"
    for r in recs:
        assert r["dsId"] == ctx["ds_id_a"], f"dsId mismatch: {r['dsId']}"
        assert base in r.get("tagBaseName", ""), f"base mismatch: {r.get('tagBaseName')}"


@pytest.mark.case(id="UA-2-2-028", chapter="UA-2-2", title="组合_分组与系统名",
    preconditions=["多个分组有相近名称"],
    steps=["传 groupId=G1 + 通过 dsId+tagName 验证"],
    expected=["只返回 G1 中匹配记录"])
@pytest.mark.integration
def test_combined_group_and_name(ua22_env, api):
    ctx = ua22_env
    tn = ctx["tags_a_names"][1]
    tag_id = ctx["tags_a_ids"][1]
    gid = str(ctx["group_id_1"])
    qwq = query_tags_with_quality(api, group_id=gid, page_size=200)
    group_recs = _qwq_records(qwq)
    group_names = {r["tagName"] for r in group_recs}
    assert tn in group_names, f"tag {tn} not found in group {gid}"

    qwq_filtered = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], tag_name=tn, page_size=50)
    recs = _qwq_records(qwq_filtered)
    assert len(recs) == 1, f"expected 1 result, got {len(recs)}"
    assert recs[0]["id"] == tag_id


@pytest.mark.case(id="UA-2-2-029", chapter="UA-2-2", title="组合_三条件",
    preconditions=["存在唯一满足条件的目标"],
    steps=["传 dsId + groupId + tagName"],
    expected=["仅目标返回；条件为 AND 语义"])
@pytest.mark.integration
def test_combined_three_conditions(ua22_env, api):
    ctx = ua22_env
    tn = ctx["tags_a_names"][0]
    page = list_tags(api, page=1, page_size=50, data={
        "tagName": tn, "dsId": ctx["ds_id_a"], "groupId": str(ctx["group_id_1"]),
    })
    records = page.get("records") or []
    match = [r for r in records if r.get("tagName") == tn]
    assert len(match) >= 1, f"combined 3-condition filter: expected >=1, got 0"
    r = match[0]
    assert r["dsId"] == ctx["ds_id_a"], f"dsId mismatch: {r.get('dsId')}"
    assert r["id"] == ctx["tags_a_ids"][0], f"id mismatch: {r.get('id')}"


@pytest.mark.case(id="UA-2-2-030", chapter="UA-2-2", title="组合_条件矛盾",
    preconditions=["A 无目标名，B 有"],
    steps=["传 dsId=A + 目标名"],
    expected=["返回空集合，不退化为 OR 或单条件"])
@pytest.mark.integration
def test_combined_contradiction(ua22_env, api):
    ctx = ua22_env
    tn_b = ctx["tags_b_names"][0]
    qwq = query_tags_with_quality(api, ds_id=ctx["ds_id_a"], tag_name=tn_b, page_size=50)
    recs = _qwq_records(qwq)
    assert len(recs) == 0, f"expected empty for contradiction, got {len(recs)}"


@pytest.mark.case(id="UA-2-2-031", chapter="UA-2-2", title="组合_修改单个条件",
    preconditions=["准备两组可区分条件"],
    steps=["仅改变一次请求中的一个过滤字段"],
    expected=["第二次结果按新条件计算，其他参数保持生效"])
@pytest.mark.integration
def test_combined_change_one(ua22_env, api):
    ctx = ua22_env
    tn = ctx["tags_a_names"][0]
    tn_b = ctx["tags_b_names"][0]
    qwq_first = query_tags_with_quality(
        api, ds_id=ctx["ds_id_a"], tag_name=tn, page_size=50,
    )
    assert len(_qwq_records(qwq_first)) == 1

    qwq_second = query_tags_with_quality(
        api, ds_id=ctx["ds_id_a"], tag_name=tn_b, page_size=50,
    )
    assert len(_qwq_records(qwq_second)) == 0, "ds A should not have tags_b names"


@pytest.mark.case(id="UA-2-2-032", chapter="UA-2-2", title="组合_全部空条件",
    preconditions=["已执行组合过滤"],
    steps=["使用空过滤对象或各字段空值请求"],
    expected=["恢复接口默认范围；不残留上次请求条件"])
@pytest.mark.integration
def test_combined_all_empty(ua22_env, api):
    ctx = ua22_env
    qwq_empty = query_tags_with_quality(api, tag_name="", tag_base_name="", page_size=200)
    qwq_default = query_tags_with_quality(api, page_size=200)
    recs_empty = _qwq_records(qwq_empty)
    recs_default = _qwq_records(qwq_default)
    assert len(recs_empty) == len(recs_default), "empty filters should return default scope"
    empty_ids = {r["id"] for r in recs_empty}
    default_ids = {r["id"] for r in recs_default}
    assert empty_ids == default_ids, "ID sets differ between empty and default query"
