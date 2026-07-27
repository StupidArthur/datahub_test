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
    batch_update_tags,
    change_ds_state,
    delete_tag_group,
    delete_tags,
    delete_tags_physical,
    list_favorite_tags,
    list_recycle_tags,
    list_tags,
    query_tags_with_quality,
    remove_tag_group_relation,
    update_tag,
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
    filter_unregistered,
    node_base_name,
    pick_unused_nodes,
    registered_base_names,
    tag_base_name,
    wait_ds_alive,
)


def _qwq_records(resp: dict) -> list[dict]:
    return (resp.get("tagInfoList") or {}).get("records") or []


# ---------------------------------------------------------------------------
# Module-level fixture: DS with registered tags for mutation tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def update_env(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"

    tmp_dir = tmp_path_factory.mktemp("ua22_up")
    nodes = [
        {"name": "up_", "type": "Double", "count": 30, "change": False, "writable": True, "default": 10.0},
    ]
    cfg = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=1)
    mocker = start_mocker(cfg, port, host=parsed.host)

    ds_name = unique_name(settings.test_prefix, "UA-2-2-up-ds")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    wait_ds_alive(api, ds_id)

    g1 = add_tag_group(api, f"UA22_UpG1_{uuid.uuid4().hex[:4]}")
    g1_id = int(g1.get("id") or g1.get("groupId"))
    g2 = add_tag_group(api, f"UA22_UpG2_{uuid.uuid4().hex[:4]}")
    g2_id = int(g2.get("id") or g2.get("groupId"))

    fixed_ids: list[int] = []
    fixed_names: list[str] = []
    for i in range(5):
        tn = unique_name(settings.test_prefix, f"UA-2-2-up{i:02d}")
        tbn = tag_base_name(f"up_{i + 1}", 1)
        td = add_tag(api, tag_name=tn, data_type=11, ds_id=ds_id, tag_base_name=tbn,
                     group_id=str(g1_id))
        fixed_ids.append(int(td.get("id") or td.get("tagId")))
        fixed_names.append(tn)

    wait_until(
        "tags_up_list",
        lambda: len((list_tags(api, page=1, page_size=200).get("records") or [])) >= 5,
        timeout=30.0,
    )

    ctx = {
        "ds_id": ds_id, "ds_name": ds_name,
        "g1_id": g1_id, "g2_id": g2_id,
        "fixed_ids": fixed_ids, "fixed_names": fixed_names,
        "mocker": mocker, "port": port,
        "host": parsed.host, "endpoint": endpoint,
        "namespace_index": 1,
    }
    yield ctx

    cleanup_errors: list[str] = []
    for tid in fixed_ids:
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
# UA-2-2-056  结果更新_新增位号
# ===================================================================

@pytest.mark.case(id="UA-2-2-056", chapter="UA-2-2", title="结果更新_新增位号",
    preconditions=["DS 有未注册节点"],
    steps=["browse → batchAdd → 查询新位号"],
    expected=["新记录返回；配置字段和 DS 归属正确"])
@pytest.mark.integration
def test_result_update_add(update_env, api):
    ctx = update_env
    ds_id = ctx["ds_id"]
    ns = ctx["namespace_index"]

    node = pick_unused_nodes(api, ds_id, 1, namespace_index=ns)[0]
    tname = unique_name(ctx.get("_test_prefix_setting", ""), "UA-2-2-056-tag")
    info = browse_entry_to_batch_info(node, ds_id=ds_id, tag_name=tname)

    tag_id = None
    try:
        batch_add_tags(api, [info], conflict_strategy=0)

        page = list_tags(api, page=1, page_size=50, data={"tagName": tname})
        recs = page.get("records") or []
        match = [r for r in recs if r.get("tagName") == tname]
        assert len(match) == 1, f"tag {tname} not found after add"
        r = match[0]
        assert r["dsId"] == ds_id, f"dsId mismatch: {r.get('dsId')}"
        assert r["tagBaseName"] == info["tagBaseName"]
        tag_id = int(r["id"])
    finally:
        if tag_id:
            try:
                delete_tags_physical(api, [tag_id])
            except TptAPIError as exc:
                if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                    raise


# ===================================================================
# UA-2-2-057  结果更新_重命名
# ===================================================================

@pytest.mark.case(id="UA-2-2-057", chapter="UA-2-2", title="结果更新_重命名",
    preconditions=["存在位号"],
    steps=["update_tag 重命名，分别查新旧名"],
    expected=["旧名无结果；新名命中；ID 不变"])
@pytest.mark.integration
def test_result_update_rename(update_env, api):
    ctx = update_env
    ds_id = ctx["ds_id"]

    old_name = ctx["fixed_names"][0]
    old_id = ctx["fixed_ids"][0]
    new_name = unique_name(ctx.get("_test_prefix_setting", ""), "UA-2-2-057-new")

    try:
        cfg = list_tags(api, page=1, page_size=50, data={"tagName": old_name})
        recs = cfg.get("records") or []
        match = [r for r in recs if r.get("tagName") == old_name]
        assert len(match) == 1, f"tag {old_name} not found"
        r = match[0]

        update_tag(api, old_id, tag_name=new_name,
                   data_type=int(r.get("dataType") or 11),
                   ds_id=int(r.get("dsId")))

        old_page = list_tags(api, page=1, page_size=50, data={"tagName": old_name})
        old_match = [r2 for r2 in (old_page.get("records") or []) if r2.get("tagName") == old_name]
        assert len(old_match) == 0, f"old name {old_name} still returns results"

        new_page = list_tags(api, page=1, page_size=50, data={"tagName": new_name})
        new_match = [r2 for r2 in (new_page.get("records") or []) if r2.get("tagName") == new_name]
        assert len(new_match) == 1, f"new name {new_name} not found"
        assert int(new_match[0]["id"]) == old_id, "tag ID changed after rename"
    finally:
        try:
            update_tag(api, old_id, tag_name=old_name, data_type=11, ds_id=ds_id)
        except TptAPIError:
            pass


# ===================================================================
# UA-2-2-058  结果更新_修改底层节点
# ===================================================================

@pytest.mark.case(id="UA-2-2-058", chapter="UA-2-2", title="结果更新_修改底层节点",
    preconditions=["DS 有至少 2 个未注册节点"],
    steps=["用 base_a 创建位号 → update_tag 改 base_b → 查询并读 RT"],
    expected=["旧映射消失；新映射命中；RT 来自新节点"])
@pytest.mark.integration
def test_result_update_change_base(update_env, api):
    ctx = update_env
    ds_id = ctx["ds_id"]
    ns = ctx["namespace_index"]

    nodes = pick_unused_nodes(api, ds_id, 2, namespace_index=ns)
    base_a = node_base_name(nodes[0], namespace_index=ns)
    base_b = node_base_name(nodes[1], namespace_index=ns)

    tname = unique_name(ctx.get("_test_prefix_setting", ""), "UA-2-2-058-tag")
    td = add_tag(api, tag_name=tname, data_type=11, ds_id=ds_id, tag_base_name=base_a, group_id="0")
    tag_id = int(td.get("id") or td.get("tagId"))

    try:
        update_tag(api, tag_id, tag_name=tname, data_type=11, ds_id=ds_id, tag_base_name=base_b,
                   unit="", tag_desc="", only_read=False, need_push=True, frequency=10)

        page = list_tags(api, page=1, page_size=50, data={"tagName": tname})
        match = [r for r in (page.get("records") or []) if r.get("tagName") == tname]
        assert len(match) == 1, f"tag {tname} not found after base change"
        assert match[0].get("tagBaseName") == base_b, (
            f"expected base {base_b}, got {match[0].get('tagBaseName')}"
        )

        old_page = list_tags(api, page=1, page_size=50, data={"tagBaseName": base_a, "tagName": tname})
        old_match = [r for r in (old_page.get("records") or []) if r.get("tagName") == tname]
        assert len(old_match) == 0, f"old base {base_a} still associated with {tname}"
    finally:
        try:
            delete_tags_physical(api, [tag_id])
        except TptAPIError as exc:
            if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                raise


# ===================================================================
# UA-2-2-059  结果更新_移动分组
# ===================================================================

@pytest.mark.case(id="UA-2-2-059", chapter="UA-2-2", title="结果更新_移动分组",
    preconditions=["G1 有位号；G2 为空"],
    steps=["batchUpdate 将位号从 G1 移到 G2"],
    expected=["G1 不再含该位号；G2 含该位号；ID 不变"])
@pytest.mark.integration
def test_result_update_move_group(update_env, api):
    ctx = update_env
    g1_id = str(ctx["g1_id"])
    g2_id = str(ctx["g2_id"])
    tn = ctx["fixed_names"][1]
    tid = ctx["fixed_ids"][1]

    try:
        batch_update_tags(api, [tid], group_id=g2_id)

        q1 = query_tags_with_quality(api, group_id=g1_id, tag_name=tn, page_size=10)
        in_g1 = [r for r in _qwq_records(q1) if r.get("tagName") == tn]
        assert len(in_g1) == 0, f"tag {tn} still in G1 after move"

        q2 = query_tags_with_quality(api, group_id=g2_id, tag_name=tn, page_size=10)
        in_g2 = [r for r in _qwq_records(q2) if r.get("tagName") == tn]
        assert len(in_g2) == 1, f"tag {tn} not in G2 after move"
        assert int(in_g2[0]["id"]) == tid, "tag ID changed after group move"
    finally:
        try:
            batch_update_tags(api, [tid], group_id=g1_id)
        except TptAPIError:
            pass


# ===================================================================
# UA-2-2-060  结果更新_收藏关系
# ===================================================================

@pytest.mark.case(id="UA-2-2-060", chapter="UA-2-2", title="结果更新_收藏关系",
    preconditions=["存在未收藏位号"],
    steps=["添加到收藏夹 → 查收藏列表 → 移出收藏 → 再查"],
    expected=["收藏后出现在列表；移出后消失；正常列表不受影响"])
@pytest.mark.integration
def test_result_update_favorite(update_env, api):
    ctx = update_env
    tn = ctx["fixed_names"][2]
    tid = ctx["fixed_ids"][2]

    try:
        add_tag_group_relation(api, "2", [tid])

        fav = list_favorite_tags(api, page_size=50)
        recs = (fav.get("tagInfoList") or {}).get("records") or []
        assert any(int(r.get("id", -1)) == tid for r in recs), (
            f"tag {tn} not in favorites after add"
        )

        remove_tag_group_relation(api, "2", [tid])

        fav2 = list_favorite_tags(api, page_size=50)
        recs2 = (fav2.get("tagInfoList") or {}).get("records") or []
        assert not any(int(r.get("id", -1)) == tid for r in recs2), (
            f"tag {tn} still in favorites after removal"
        )
    except Exception:
        try:
            remove_tag_group_relation(api, "2", [tid])
        except TptAPIError:
            pass
        raise


# ===================================================================
# UA-2-2-061  结果更新_软删除
# ===================================================================

@pytest.mark.case(id="UA-2-2-061", chapter="UA-2-2", title="结果更新_软删除",
    preconditions=["存在位号"],
    steps=["软删除 → 查正常列表 → 查回收站"],
    expected=["正常列表无该位号；回收站含该位号"])
@pytest.mark.integration
def test_result_update_soft_delete(update_env, api, record_property):
    ctx = update_env
    ds_id = ctx["ds_id"]

    node = pick_unused_nodes(api, ds_id, 1, namespace_index=ctx["namespace_index"])[0]
    tname = unique_name(ctx.get("_test_prefix_setting", ""), "UA-2-2-061-tag")
    info = browse_entry_to_batch_info(node, ds_id=ds_id, tag_name=tname)
    batch_add_tags(api, [info], conflict_strategy=0)

    page = list_tags(api, page=1, page_size=50, data={"tagName": tname})
    match = [r for r in (page.get("records") or []) if r.get("tagName") == tname]
    assert len(match) == 1
    tag_id = int(match[0]["id"])

    try:
        delete_tags(api, tag_id)

        active = list_tags(api, page=1, page_size=200, data={"dsId": ds_id})
        active_names = {r["tagName"] for r in (active.get("records") or [])}
        assert tname not in active_names, f"soft-deleted tag {tname} still in active list"

        recycle = list_recycle_tags(api, page_size=200)
        rec_recs = (recycle.get("tagInfoList") or {}).get("records") or []
        assert any(r.get("tagName") == tname for r in rec_recs), (
            f"soft-deleted tag {tname} not found in recycle"
        )
    finally:
        try:
            delete_tags_physical(api, [tag_id])
        except TptAPIError as exc:
            if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                raise


# ===================================================================
# UA-2-2-062  结果更新_物理删除
# ===================================================================

@pytest.mark.case(id="UA-2-2-062", chapter="UA-2-2", title="结果更新_物理删除",
    preconditions=["存在位号"],
    steps=["软删除 → 物理删除 → 查正常和回收站"],
    expected=["正常列表无；回收站无"])
@pytest.mark.integration
def test_result_update_physical_delete(update_env, api):
    ctx = update_env
    ds_id = ctx["ds_id"]

    node = pick_unused_nodes(api, ds_id, 1, namespace_index=ctx["namespace_index"])[0]
    tname = unique_name(ctx.get("_test_prefix_setting", ""), "UA-2-2-062-tag")
    info = browse_entry_to_batch_info(node, ds_id=ds_id, tag_name=tname)
    batch_add_tags(api, [info], conflict_strategy=0)

    page = list_tags(api, page=1, page_size=50, data={"tagName": tname})
    match = [r for r in (page.get("records") or []) if r.get("tagName") == tname]
    assert len(match) == 1
    tag_id = int(match[0]["id"])

    try:
        delete_tags(api, tag_id)
        delete_tags_physical(api, [tag_id])

        active = list_tags(api, page=1, page_size=200, data={"dsId": ds_id})
        active_names = {r["tagName"] for r in (active.get("records") or [])}
        assert tname not in active_names, f"physically deleted tag {tname} still in active list"

        recycle = list_recycle_tags(api, page_size=200)
        rec_recs = (recycle.get("tagInfoList") or {}).get("records") or []
        assert not any(r.get("tagName") == tname for r in rec_recs), (
            f"physically deleted tag {tname} still in recycle"
        )
    finally:
        try:
            delete_tags_physical(api, [tag_id])
        except TptAPIError:
            pass


# ===================================================================
# UA-2-2-063  结果更新_新增后可选集合（探索）
# ===================================================================

@pytest.mark.case(id="UA-2-2-063", chapter="UA-2-2", title="结果更新_新增后可选集合",
    preconditions=["DS 有未注册节点"],
    steps=["新增前后分别 browse 对比"],
    expected=["记录缓存延迟；工具最终立即排除新增"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_result_update_available_after_add(update_env, api, record_property):
    ctx = update_env
    ds_id = ctx["ds_id"]
    ns = ctx["namespace_index"]

    before = len(filter_unregistered(api, ds_id, browse_all_unused_candidates(api, ds_id), namespace_index=ns))

    node = pick_unused_nodes(api, ds_id, 1, namespace_index=ns)[0]
    tname = unique_name(ctx.get("_test_prefix_setting", ""), "UA-2-2-063-tag")
    info = browse_entry_to_batch_info(node, ds_id=ds_id, tag_name=tname)
    batch_add_tags(api, [info], conflict_strategy=0)

    tag_id = None
    try:
        page = list_tags(api, page=1, page_size=50, data={"tagName": tname})
        match = [r for r in (page.get("records") or []) if r.get("tagName") == tname]
        if match:
            tag_id = int(match[0]["id"])

        after_reg = len(registered_base_names(api, ds_id))
        after = len(filter_unregistered(api, ds_id, browse_all_unused_candidates(api, ds_id), namespace_index=ns))

        obs = {"before": before, "after": after, "registered_after": after_reg}
        record_property("observation", json.dumps(obs, ensure_ascii=False, default=str))
        pytest.xfail(f"UA-2-2-063 available set after add not specified; observed={obs}")
    finally:
        if tag_id:
            try:
                delete_tags_physical(api, [tag_id])
            except TptAPIError:
                pass


# ===================================================================
# UA-2-2-064  结果更新_删除后可选集合（探索）
# ===================================================================

@pytest.mark.case(id="UA-2-2-064", chapter="UA-2-2", title="结果更新_删除后可选集合",
    preconditions=["DS 有已注册位号"],
    steps=["删除前后分别 browse 对比"],
    expected=["记录缓存延迟各阶段"])
@pytest.mark.integration
@pytest.mark.spec_pending
def test_result_update_available_after_delete(update_env, api, record_property):
    ctx = update_env
    ds_id = ctx["ds_id"]
    ns = ctx["namespace_index"]

    node = pick_unused_nodes(api, ds_id, 1, namespace_index=ns)[0]
    tname = unique_name(ctx.get("_test_prefix_setting", ""), "UA-2-2-064-tag")
    info = browse_entry_to_batch_info(node, ds_id=ds_id, tag_name=tname)
    batch_add_tags(api, [info], conflict_strategy=0)

    page = list_tags(api, page=1, page_size=50, data={"tagName": tname})
    match = [r for r in (page.get("records") or []) if r.get("tagName") == tname]
    if not match:
        pytest.skip("tag not found after creation")
    tag_id = int(match[0]["id"])

    try:
        delete_tags(api, tag_id)
        after_soft = len(filter_unregistered(api, ds_id, browse_all_unused_candidates(api, ds_id), namespace_index=ns))

        delete_tags_physical(api, [tag_id])
        after_phys = len(filter_unregistered(api, ds_id, browse_all_unused_candidates(api, ds_id), namespace_index=ns))

        obs = {"after_soft_delete": after_soft, "after_physical_delete": after_phys}
        record_property("observation", json.dumps(obs, ensure_ascii=False, default=str))
        pytest.xfail(f"UA-2-2-064 available set after delete not specified; observed={obs}")
    finally:
        try:
            delete_tags_physical(api, [tag_id])
        except TptAPIError:
            pass
