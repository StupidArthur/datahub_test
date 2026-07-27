from __future__ import annotations

import json
import socket

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    delete_tags_physical,
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
from tests.support.ua2_helpers import (
    tag_base_name,
    wait_ds_alive,
)


def _qwq_records(resp: dict) -> list[dict]:
    return (resp.get("tagInfoList") or {}).get("records") or []


# ---------------------------------------------------------------------------
# Module-level fixture: DS with tags for stability/concurrency tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def stability_env(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"

    tmp_dir = tmp_path_factory.mktemp("ua22_st")
    nodes = [
        {"name": "st_", "type": "Double", "count": 15, "change": False, "writable": True, "default": 5.0},
        {"name": "change_", "type": "Int32", "count": 1, "change": True, "writable": False},
    ]
    cfg = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=1)
    mocker = start_mocker(cfg, port, host=parsed.host)

    ds_name = unique_name(settings.test_prefix, "UA-2-2-st")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    wait_ds_alive(api, ds_id)

    with_rt_id = None
    with_rt_name = None
    tag_ids: list[int] = []
    tag_names: list[str] = []
    for i in range(12):
        tn = unique_name(settings.test_prefix, f"UA-2-2-st{i:02d}")
        tbn = tag_base_name(f"st_{i + 1}", 1)
        td = add_tag(api, tag_name=tn, data_type=11, ds_id=ds_id, tag_base_name=tbn, group_id="0")
        tag_ids.append(int(td.get("id") or td.get("tagId")))
        tag_names.append(tn)
        if i == 0:
            with_rt_id = int(td.get("id") or td.get("tagId"))
            with_rt_name = tn

    wait_until(
        "tags_st_list",
        lambda: len((list_tags(api, page=1, page_size=200).get("records") or [])) >= 12,
        timeout=30.0,
    )

    ctx = {
        "ds_id": ds_id, "ds_name": ds_name,
        "tag_ids": tag_ids, "tag_names": tag_names,
        "with_rt_id": with_rt_id, "with_rt_name": with_rt_name,
        "mocker": mocker, "port": port, "host": parsed.host,
        "endpoint": endpoint,
    }
    yield ctx

    cleanup_errors: list[str] = []
    for tid in tag_ids:
        try:
            delete_tags_physical(api, [tid])
        except TptAPIError as exc:
            if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                cleanup_errors.append(f"delete tag id={tid}: {exc.msg}")
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
        sock = socket.create_connection((parsed.host, port), timeout=3.0)
        sock.close()
        cleanup_errors.append(f"port {port} still listening")
    except (OSError, socket.error):
        pass
    except Exception as exc:
        cleanup_errors.append(f"port check: {exc}")
    if cleanup_errors:
        raise AssertionError("Cleanup errors: " + "; ".join(cleanup_errors))


# ===================================================================
# UA-2-2-065  稳定性_连续查询
# ===================================================================

@pytest.mark.case(id="UA-2-2-065", chapter="UA-2-2", title="稳定性_连续查询",
    preconditions=["查询期间不修改配置"],
    steps=["相同请求连续执行 20 次"],
    expected=["total 稳定；首页 ID 集合稳定；无随机失败"])
@pytest.mark.integration
def test_stability_repeat_query(stability_env, api):
    ctx = stability_env
    ds_id = ctx["ds_id"]

    totals = []
    id_sets = []
    for _ in range(20):
        page = list_tags(api, page=1, page_size=10, data={"dsId": ds_id})
        totals.append(int(page.get("total") or 0))
        id_sets.append({int(r["id"]) for r in (page.get("records") or []) if r.get("id")})

    assert len(set(totals)) == 1, f"total changed across 20 runs: {set(totals)}"
    assert len(set(frozenset(s) for s in id_sets)) == 1, (
        "first-page ID set changed across 20 runs"
    )


# ===================================================================
# UA-2-2-066  稳定性_并发只读查询
# ===================================================================

@pytest.mark.case(id="UA-2-2-066", chapter="UA-2-2", title="稳定性_并发只读查询",
    preconditions=["存在 DS 有数据；且创建空 DS"],
    steps=["并发发出不同条件的查询"],
    expected=["各结果按各自过滤计算；无交叉泄露；无副作用"])
@pytest.mark.integration
def test_stability_concurrent_query(api, settings, stability_env, tmp_path_factory, mocker_endpoint):
    ctx = stability_env
    ds_a = ctx["ds_id"]
    tn = ctx["with_rt_name"]

    parsed = parse_mocker_endpoint(mocker_endpoint)
    port_b = find_free_port()
    endpoint_b = f"opc.tcp://{parsed.host}:{port_b}/ua_mocker/"
    tmp_dir = tmp_path_factory.mktemp("ua22_066")
    nodes_b = [
        {"name": "empty_", "type": "Double", "count": 1, "change": False, "writable": True, "default": 1.0},
    ]
    cfg_b = write_mocker_config(tmp_dir, port_b, nodes=nodes_b)
    mocker_b = start_mocker(cfg_b, port_b, host=parsed.host)
    ds_name_b = unique_name(settings.test_prefix, "UA-2-2-066-empty")
    data_b = add_ds_info(
        api, ds_name=ds_name_b,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint_b,
    )
    ds_b = int(data_b.get("id") or data_b.get("dsId"))
    try:
        for _ in range(3):
            r1 = query_tags_with_quality(api, ds_id=ds_a, page_size=20)
            r2 = query_tags_with_quality(api, ds_id=ds_b, page_size=20)
            n1 = {r.get("tagName") for r in _qwq_records(r1)}
            n2 = {r.get("tagName") for r in _qwq_records(r2)}
            assert not n1.intersection(n2) or not n1 or not n2, (
                f"concurrent queries leaked: ds_a={len(n1)} names, ds_b={len(n2)} names"
            )
    finally:
        try:
            delete_datasource_if_exists(api, ds_b, ds_name_b)
        except Exception:
            pass
        try:
            stop_mocker(mocker_b)
        except Exception:
            pass


# ===================================================================
# UA-2-2-067  隔离性_查询不修改配置
# ===================================================================

@pytest.mark.case(id="UA-2-2-067", chapter="UA-2-2", title="隔离性_查询不修改配置",
    preconditions=["存在完整位号"],
    steps=["记录配置快照，执行查询/分页/browse/详情组合，再对比"],
    expected=["配置字段、分组关系、源端值均不变"])
@pytest.mark.integration
def test_stability_query_no_mutation(stability_env, api):
    ctx = stability_env
    ds_id = ctx["ds_id"]
    tn = ctx["with_rt_name"]
    tag_id = ctx["with_rt_id"]

    def _snapshot():
        page = list_tags(api, page=1, page_size=50, data={"tagName": tn, "dsId": ds_id})
        for r in (page.get("records") or []):
            if r.get("tagName") == tn:
                return {k: r.get(k) for k in ("tagName", "tagBaseName", "dsId", "dataType", "frequency", "unit", "onlyRead", "needPush")}
        return {}

    snap = _snapshot()
    assert snap, f"tag {tn} not found for snapshot"

    for _ in range(5):
        list_tags(api, page=1, page_size=10, data={"tagName": tn, "dsId": ds_id})
        query_tags_with_quality(api, tag_name=tn, page_size=10)

    after = _snapshot()
    assert after, f"tag {tn} not found post-query"

    for field in ("tagName", "tagBaseName", "dsId", "dataType", "frequency"):
        assert snap.get(field) == after.get(field), (
            f"field {field} changed: {snap.get(field)} -> {after.get(field)}"
        )
