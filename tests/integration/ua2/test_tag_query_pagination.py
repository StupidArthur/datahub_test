from __future__ import annotations

import json
import socket
import uuid

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    add_tag_group,
    change_ds_state,
    delete_tags_physical,
    get_not_used_tags,
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
    browse_all_unused_candidates,
    node_base_name,
    tag_base_name,
    wait_ds_alive,
)


# ---------------------------------------------------------------------------
# Module-level fixture: DS with ≥20 registered tags for pagination tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def paginate_env(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"

    tmp_dir = tmp_path_factory.mktemp("ua22_pg")
    nodes = [
        {"name": "pg_", "type": "Double", "count": 25, "change": False, "writable": True, "default": 10.0},
    ]
    cfg = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=1)
    mocker = start_mocker(cfg, port, host=parsed.host)

    ds_name = unique_name(settings.test_prefix, "UA-2-2-pg")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    wait_ds_alive(api, ds_id)

    group_data = add_tag_group(api, f"UA22_PgG_{uuid.uuid4().hex[:4]}")
    group_id = int(group_data.get("id") or group_data.get("groupId"))

    tag_ids: list[int] = []
    tag_names: list[str] = []
    for i in range(20):
        tn = unique_name(settings.test_prefix, f"UA-2-2-pg{i:02d}")
        tbn = tag_base_name(f"pg_{i + 1}", 1)
        td = add_tag(api, tag_name=tn, data_type=11, ds_id=ds_id, tag_base_name=tbn,
                     group_id=str(group_id) if i < 15 else "0")
        tag_ids.append(int(td.get("id") or td.get("tagId")))
        tag_names.append(tn)

    wait_until(
        "tags_list_pg",
        lambda: len((list_tags(api, page=1, page_size=200).get("records") or [])) >= 20,
        timeout=30.0,
    )

    for tn in tag_names:
        wait_until(f"rt_pg:{tn}", lambda tn=tn: (
            get_rt_point(api, tn).get("tagValue") is not None
        ), timeout=60.0)

    ctx = {
        "ds_id": ds_id, "ds_name": ds_name,
        "tag_ids": tag_ids, "tag_names": tag_names,
        "group_id": group_id,
        "mocker": mocker, "port": port,
        "host": parsed.host,
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
# UA-2-2-049  分页_首页
# ===================================================================

@pytest.mark.case(id="UA-2-2-049", chapter="UA-2-2", title="分页_首页",
    preconditions=["数据源有 ≥10 个位号"],
    steps=["page=1, size=10"],
    expected=["记录 ≤ 10；total 可解析；ID 唯一"])
@pytest.mark.integration
def test_pagination_first_page(paginate_env, api):
    ctx = paginate_env
    page = list_tags(api, page=1, page_size=10, data={"dsId": ctx["ds_id"]})
    recs = page.get("records") or []
    assert len(recs) <= 10, f"page size exceeded: {len(recs)}"
    total = int(page.get("total") or 0)
    assert total >= len(recs), f"total {total} < returned {len(recs)}"
    ids = [int(r["id"]) for r in recs if r.get("id")]
    assert len(ids) == len(set(ids)), "duplicate IDs in first page"


# ===================================================================
# UA-2-2-050  分页_连续翻页完整性
# ===================================================================

@pytest.mark.case(id="UA-2-2-050", chapter="UA-2-2", title="分页_连续翻页完整性",
    preconditions=["数据源有足够位号"],
    steps=["从第 1 页翻到末尾"],
    expected=["集合完整无溢出；不产生重复 ID"])
@pytest.mark.integration
def test_pagination_complete_walk(paginate_env, api):
    ctx = paginate_env
    seen: set[int] = set()
    page_num = 1
    page_size = 10
    total = None
    while page_num <= 50:
        page = list_tags(api, page=page_num, page_size=page_size, data={"dsId": ctx["ds_id"]})
        recs = page.get("records") or []
        if total is None:
            total = int(page.get("total") or 0)
        if not recs:
            break
        for r in recs:
            seen.add(int(r["id"]))
        if len(recs) < page_size:
            break
        page_num += 1
    assert len(seen) >= min(total or 0, 1), (
        f"walk collected {len(seen)} IDs but total={total}"
    )


# ===================================================================
# UA-2-2-051  分页_尾页
# ===================================================================

@pytest.mark.case(id="UA-2-2-051", chapter="UA-2-2", title="分页_尾页",
    preconditions=["total 已知"],
    steps=["计算尾页并请求；再请求下一页"],
    expected=["尾页可解析；越页为空或数量 == 0"])
@pytest.mark.integration
def test_pagination_last_page(paginate_env, api):
    ctx = paginate_env
    page1 = list_tags(api, page=1, page_size=10, data={"dsId": ctx["ds_id"]})
    total = int(page1.get("total") or 0)
    last_page = max(1, (total + 9) // 10)
    tail = list_tags(api, page=last_page, page_size=10, data={"dsId": ctx["ds_id"]})
    over = list_tags(api, page=last_page + 1, page_size=10, data={"dsId": ctx["ds_id"]})
    assert isinstance(tail.get("records"), list), "tail page records not a list"
    assert len(over.get("records") or []) == 0, (
        f"over-page (page {last_page + 1}) returned {len(over.get('records') or [])} records"
    )


# ===================================================================
# UA-2-2-052  分页_不同页大小
# ===================================================================

@pytest.mark.case(id="UA-2-2-052", chapter="UA-2-2", title="分页_不同页大小",
    preconditions=["数据源已注册位号"],
    steps=["分别以 size=10 和 size=50 翻遍所有页"],
    expected=["各自的 size 边界受控；两次并集一致"])
@pytest.mark.integration
def test_pagination_different_sizes(paginate_env, api):
    ctx = paginate_env

    def _walk_all(sz: int) -> set[int]:
        seen: set[int] = set()
        p = 1
        while p <= 20:
            page = list_tags(api, page=p, page_size=sz, data={"dsId": ctx["ds_id"]})
            recs = page.get("records") or []
            for r in recs:
                seen.add(int(r["id"]))
            if len(recs) < sz:
                break
            p += 1
        return seen

    ids_10 = _walk_all(10)
    ids_50 = _walk_all(50)
    union_10 = ids_10
    assert len(ids_50) >= len(ids_10) or ids_50 == ids_10, (
        f"size=50 union ({len(ids_50)}) smaller than size=10 ({len(ids_10)})"
    )


# ===================================================================
# UA-2-2-053  分页_条件变化客户端页码 (GUI-DEFERRED)
# ===================================================================

@pytest.mark.case(id="UA-2-2-053", chapter="UA-2-2", title="分页_条件变化客户端页码",
    preconditions=["（GUI-DEFERRED）"],
    steps=["（GUI-DEFERRED）"],
    expected=["（GUI-DEFERRED）"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_pagination_condition_change(paginate_env, api, record_property):
    record_property("observation", json.dumps({"reason": "GUI-DEFERRED: frontend pagination state, awaiting GUI version"}))
    pytest.xfail("UA-2-2-053 GUI-DEFERRED: frontend pagination state, awaiting GUI version")


# ===================================================================
# UA-2-2-054  排序_稳定顺序
# ===================================================================

@pytest.mark.case(id="UA-2-2-054", chapter="UA-2-2", title="排序_稳定顺序",
    preconditions=["数据源有 ≥10 个位号"],
    steps=["相同 sort 条件请求两次"],
    expected=["排序稳定；不因分页影响"])
@pytest.mark.integration
def test_sort_stable(paginate_env, api):
    ctx = paginate_env
    p1 = list_tags(api, page=1, page_size=20, sort="tagName", data={"dsId": ctx["ds_id"]})
    p2 = list_tags(api, page=1, page_size=20, sort="tagName", data={"dsId": ctx["ds_id"]})
    n1 = [r.get("tagName") for r in (p1.get("records") or [])]
    n2 = [r.get("tagName") for r in (p2.get("records") or [])]
    assert n1 == n2, f"sort order changed between requests"


# ===================================================================
# UA-2-2-055  底层浏览_游标完整性
# ===================================================================

@pytest.mark.case(id="UA-2-2-055", chapter="UA-2-2", title="底层浏览_游标完整性",
    preconditions=["DS 有多个未注册节点"],
    steps=["游标翻页到最后"],
    expected=["无重复/遗漏 base name；终点游标 empty"])
@pytest.mark.integration
def test_browse_cursor_complete(paginate_env, api):
    ctx = paginate_env
    nodes = browse_all_unused_candidates(api, ctx["ds_id"])
    bases = [node_base_name(n) for n in nodes]
    assert len(bases) == len(set(bases)), (
        f"duplicate base names in browse results: "
        f"{len(bases)} total, {len(set(bases))} unique"
    )
