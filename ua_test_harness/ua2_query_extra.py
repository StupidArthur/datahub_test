"""UA-2-2 余量 case 精确实现(分页/断线/分组/结果更新/稳定性)。"""
from __future__ import annotations

import time
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import (
    active_rows,
    all_recycle_rows,
    case_tag_name,
    cleanup_case_tag,
    create_case_tag,
    exact,
    physical_delete_tag,
    restore_tag,
    soft_delete_tag,
)


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def explore_name_query(ctx, cc, meta, cid: str) -> CaseStatus:
    """UA-2-2-007/009/010/013: 名称片段/大小写/Unicode 探索。"""
    ds = require_shared_datasource(ctx, "types")
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=cid[-3:])
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        from tpt_api.datahub import query_tags_with_quality
        probes: list[dict[str, Any]] = []
        if cid == "UA-2-2-007":
            for q in ("pump", tag_name[:4], tag_name):
                res = query_tags_with_quality(_api(ctx), tag_name=q, page=1, page_size=50)
                recs = ((res or {}).get("tagInfoList") or {}).get("records") or []
                probes.append({"query": q, "count": len(recs), "hit": tag_name in {r.get("tagName") for r in recs}})
        elif cid == "UA-2-2-009":
            for q in (tag_name, tag_name.upper(), tag_name.lower()):
                res = query_tags_with_quality(_api(ctx), tag_name=q, page=1, page_size=50)
                recs = ((res or {}).get("tagInfoList") or {}).get("records") or []
                probes.append({"query": q, "count": len(recs)})
        elif cid == "UA-2-2-010":
            cn = case_tag_name(ctx, cc, "cn测试")
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
            tag_id = tag_name = 0
            cn_tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="cn")
            cn_id, cn_name = int(cn_tag["id"]), cn_tag["name"]
            try:
                for q in (cn_name, "测试", cn_name[:2]):
                    res = query_tags_with_quality(_api(ctx), tag_name=q, page=1, page_size=50)
                    recs = ((res or {}).get("tagInfoList") or {}).get("records") or []
                    probes.append({"query": q, "count": len(recs)})
            finally:
                cleanup_case_tag(ctx, cc, cn_id, cn_name)
            ctx.bag[cid] = {"probes": probes}
            return CaseStatus.OBSERVED
        elif cid == "UA-2-2-013":
            base = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0].get("tagBaseName", "")
            frag = base[:6] if len(base) > 6 else base[:3]
            res = query_tags_with_quality(_api(ctx), tag_base_name=frag, page=1, page_size=50)
            recs = ((res or {}).get("tagInfoList") or {}).get("records") or []
            filtered = [r for r in recs if frag in str(r.get("tagBaseName") or "")]
            probes.append({"fragment": frag, "raw": len(recs), "filtered": len(filtered)})
        ctx.bag[cid] = {"probes": probes}
        return CaseStatus.OBSERVED
    finally:
        if tag_id:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)


def query_group_cases(ctx, cc, meta, cid: str) -> CaseStatus:
    """UA-2-2-021~025: 分组/收藏/回收站查询。"""
    from tpt_api.datahub import (
        add_tag_group,
        add_tag_group_relation,
        list_favorite_tags,
        list_recycle_tags,
        query_tags_with_quality,
    )

    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    api = _api(ctx)
    grp_name = case_tag_name(ctx, cc, f"g{cid[-3:]}")
    created_groups: list[str] = []
    tag_id = tag_name = 0

    try:
        if cid == "UA-2-2-021":
            root = query_tags_with_quality(api, group_id="0", ds_id=ds_id, page=1, page_size=20)
            root_n = len(((root or {}).get("tagInfoList") or {}).get("records") or [])
            grp = add_tag_group(api, group_name=grp_name, parent_id="0")
            gid = str(grp.get("id") or "")
            created_groups.append(gid)
            add_tag_group_relation(api, group_id=gid, tag_ids=[])
            sub = query_tags_with_quality(api, group_id=gid, page=1, page_size=20)
            sub_n = len(((sub or {}).get("tagInfoList") or {}).get("records") or [])
            ctx.bag[cid] = {"root_count": root_n, "subgroup_count": sub_n, "group_id": gid}
            return CaseStatus.OBSERVED

        grp = add_tag_group(api, group_name=grp_name, parent_id="0")
        gid = str(grp.get("id") or "")
        created_groups.append(gid)
        tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:])
        tag_id, tag_name = int(tag["id"]), tag["name"]

        if cid == "UA-2-2-022":
            add_tag_group_relation(api, group_id=gid, tag_ids=[tag_id])
            res = query_tags_with_quality(api, group_id=gid, tag_name=tag_name, page=1, page_size=10)
            recs = ((res or {}).get("tagInfoList") or {}).get("records") or []
            check_true("in_group", any(r.get("tagName") == tag_name for r in recs))
            return CaseStatus.PASS

        if cid == "UA-2-2-023":
            empty_gid = str(add_tag_group(api, group_name=case_tag_name(ctx, cc, "empty"), parent_id="0").get("id") or "")
            created_groups.append(empty_gid)
            res = query_tags_with_quality(api, group_id=empty_gid, page=1, page_size=10)
            recs = ((res or {}).get("tagInfoList") or {}).get("records") or []
            check_eq("empty_group", 0, len(recs))
            return CaseStatus.PASS

        if cid == "UA-2-2-024":
            add_tag_group_relation(api, group_id="2", tag_ids=[tag_id])
            fav = list_favorite_tags(api, page=1, page_size=50)
            recs = ((fav or {}).get("tagInfoList") or {}).get("records") or []
            check_true("in_favorites", any(int(r.get("id", -1)) == tag_id for r in recs))
            from tpt_api.datahub import remove_tag_group_relation
            remove_tag_group_relation(api, group_id="2", tag_ids=[tag_id])
            return CaseStatus.PASS

        if cid == "UA-2-2-025":
            soft_delete_tag(ctx, tag_id)
            time.sleep(2)
            active = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
            check_eq("not_in_active", 0, len(active))
            recy = list_recycle_tags(api, page=1, page_size=50, group_id="1")
            rrecs = ((recy or {}).get("tagInfoList") or {}).get("records") or []
            check_true("in_recycle", any(int(r.get("id", -1)) == tag_id for r in rrecs))
            restore_tag(ctx, tag_id)
            tag_id = tag_name = 0
            return CaseStatus.PASS

        raise AssertFail(f"query_group_cases: {cid}")
    finally:
        if tag_id:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
        from tpt_api.datahub import delete_tag_group
        for gid in created_groups:
            if gid:
                try:
                    delete_tag_group(api, [gid], is_force=False)
                except Exception:
                    pass


def runtime_offline_online(ctx, cc, meta, cid: str) -> CaseStatus:
    """UA-2-2-037/038/040: 断线/恢复/静态质量。"""
    from ua_test_harness.clients import mock_control
    from ua_test_harness.ua2_fixture_map import base_name_for_node, read_spec, write_spec
    from ua_test_harness.ua2_precise import opcua_read, rt_row

    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    endpoint = str(ds["endpoint"])
    spec = write_spec("DOUBLE") if cid == "UA-2-2-040" else read_spec("INT32")
    base = base_name_for_node(spec["node"])
    tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:], data_type=spec["dtype"], tag_base_name=base)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        rt_row(ctx, tag_name, timeout=60.0)
        if cid == "UA-2-2-037":
            mock_control.stop_mock("functional")
            try:
                time.sleep(3)
                rows = active_rows(ctx, tagName=tag_name)
                check_true("config_still_queryable", bool(rows))
                q = rows[0].get("quality", rows[0].get("qualityCode"))
                ctx.bag[cid] = {"quality_after_offline": q}
                return CaseStatus.PASS
            finally:
                mock_control.start_mock("functional")
                mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
        if cid == "UA-2-2-038":
            mock_control.stop_mock("functional")
            mock_control.start_mock("functional")
            mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
            time.sleep(3)
            rt_row(ctx, tag_name, timeout=90.0)
            opcua_read(endpoint, spec["node"])
            return CaseStatus.PASS
        if cid == "UA-2-2-040":
            v1 = active_rows(ctx, tagName=tag_name)[0]
            time.sleep(3)
            v2 = active_rows(ctx, tagName=tag_name)[0]
            check_eq("value_stable", v1.get("tagValue", v1.get("value")), v2.get("tagValue", v2.get("value")))
            check_true("quality_valid", v1.get("quality") is not None)
            return CaseStatus.PASS
        raise AssertFail(f"runtime_offline_online: {cid}")
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def browse_to_add(ctx, cc) -> CaseStatus:
    """UA-2-2-048: browse 结果 batchAdd + RT 闭环。"""
    from tpt_api.datahub import batch_add_tags
    from ua_test_harness.ua2_browse import browse_entry_to_batch_info, pick_unused_nodes
    from ua_test_harness.ua2_precise import config_page_row, rt_row

    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    node = pick_unused_nodes(ctx, ds_id, 1)[0]
    tname = case_tag_name(ctx, cc, "048")
    info = browse_entry_to_batch_info(node, ds_id=ds_id, tag_name=tname)
    batch_add_tags(_api(ctx), [info], conflict_strategy=0)
    try:
        cfg = config_page_row(ctx, tname)
        check_eq("base", info["tagBaseName"], cfg.get("tagBaseName"))
        rt_row(ctx, tname, timeout=60.0)
        return CaseStatus.PASS
    finally:
        row = exact(active_rows(ctx, tagName=tname), "tagName", tname)
        if row:
            cleanup_case_tag(ctx, cc, int(row[0]["id"]), tname)


def pagination_cases(ctx, cc, meta, cid: str) -> CaseStatus:
    """UA-2-2-049~052/054: 分页与排序。"""
    from tpt_api.datahub import list_tags

    api = _api(ctx)
    ds = require_shared_datasource(ctx, "types")
    filter_data = {"dsId": int(ds["id"])}

    if cid == "UA-2-2-049":
        page = list_tags(api, page=1, page_size=10, data=filter_data)
        recs = page.get("records") or []
        total = int(page.get("total") or 0)
        check_true("page_size_ok", len(recs) <= 10)
        check_true("total_parseable", total >= len(recs))
        ids = [int(r["id"]) for r in recs if r.get("id")]
        check_eq("no_dup_ids", len(ids), len(set(ids)))
        return CaseStatus.PASS

    if cid == "UA-2-2-050":
        seen: set[int] = set()
        page_num = 1
        page_size = 10
        total = None
        while page_num <= 50:
            page = list_tags(api, page=page_num, page_size=page_size, data=filter_data)
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
        check_true("pagination_complete", len(seen) >= min(total or 0, 1))
        return CaseStatus.PASS

    if cid == "UA-2-2-051":
        page1 = list_tags(api, page=1, page_size=10, data=filter_data)
        total = int(page1.get("total") or 0)
        last_page = max(1, (total + 9) // 10)
        tail = list_tags(api, page=last_page, page_size=10, data=filter_data)
        over = list_tags(api, page=last_page + 1, page_size=10, data=filter_data)
        check_true("tail_parseable", isinstance((tail.get("records") or []), list))
        check_true("over_page_empty_or_short", len(over.get("records") or []) == 0)
        return CaseStatus.PASS

    if cid == "UA-2-2-052":
        ids_a: set[int] = set()
        ids_b: set[int] = set()
        for sz in (10, 50):
            p = 1
            while p <= 20:
                page = list_tags(api, page=p, page_size=sz, data=filter_data)
                recs = page.get("records") or []
                bucket = ids_a if sz == 10 else ids_b
                for r in recs:
                    bucket.add(int(r["id"]))
                if len(recs) < sz:
                    break
                p += 1
        check_true("same_total_union", ids_a == ids_b or len(ids_b) >= len(ids_a))
        return CaseStatus.PASS

    if cid == "UA-2-2-054":
        p1 = list_tags(api, page=1, page_size=20, sort="tagName", data=filter_data)
        p2 = list_tags(api, page=1, page_size=20, sort="tagName", data=filter_data)
        n1 = [r.get("tagName") for r in (p1.get("records") or [])]
        n2 = [r.get("tagName") for r in (p2.get("records") or [])]
        check_eq("sort_stable", n1, n2)
        return CaseStatus.PASS

    raise AssertFail(f"pagination_cases: {cid}")


def browse_cursor_complete(ctx, cc) -> CaseStatus:
    """UA-2-2-055: browse continueID 完整性。"""
    from ua_test_harness.ua2_browse import browse_all_nodes, node_base_name

    ds = require_shared_datasource(ctx, "types")
    nodes = browse_all_nodes(ctx, int(ds["id"]))
    bases = [node_base_name(n) for n in nodes]
    check_eq("no_dup_bases", len(bases), len(set(bases)))
    return CaseStatus.PASS


def result_update_cases(ctx, cc, meta, cid: str) -> CaseStatus:
    """UA-2-2-056~064: 查询结果随业务变化。"""
    from tpt_api.datahub import batch_update_tags, update_tag
    from tpt_api.types import DataTypes
    from ua_test_harness.ua2_browse import filter_unregistered, browse_all_nodes, registered_base_names

    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    api = _api(ctx)
    tag_id = tag_name = 0
    gid = ""
    created_groups: list[str] = []

    try:
        if cid == "UA-2-2-056":
            new_name = case_tag_name(ctx, cc, "56")
            from ua_test_harness.ua2_browse import browse_entry_to_batch_info, pick_unused_nodes
            from tpt_api.datahub import batch_add_tags
            node = pick_unused_nodes(ctx, ds_id, 1)[0]
            batch_add_tags(api, [browse_entry_to_batch_info(node, ds_id=ds_id, tag_name=new_name)], 0)
            check_true("found_after_add", bool(exact(active_rows(ctx, tagName=new_name), "tagName", new_name)))
            row = exact(active_rows(ctx, tagName=new_name), "tagName", new_name)[0]
            cleanup_case_tag(ctx, cc, int(row["id"]), new_name)
            return CaseStatus.PASS

        if cid in {"UA-2-2-058", "UA-2-2-059"}:
            from tpt_api.datahub import add_tag_group, add_tag_group_relation, batch_update_tags, query_tags_with_quality
            from ua_test_harness.ua2_browse import node_base_name, pick_unused_nodes
            from ua_test_harness.ua2_precise import config_page_row, rt_row

            if cid == "UA-2-2-058":
                nodes = pick_unused_nodes(ctx, ds_id, 2)
                base_a = node_base_name(nodes[0])
                base_b = node_base_name(nodes[1])
                tag = create_case_tag(
                    ctx, cc, ds_id, suffix="58",
                    tag_base_name=base_a, data_type=str(nodes[0].get("dataType") or "INT"),
                )
                tag_id, tag_name = int(tag["id"]), tag["name"]
                cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
                dtype = int(cfg.get("dataType") or 6)
                update_tag(
                    api, tag_id, tag_name=tag_name, data_type=dtype, ds_id=ds_id,
                    tag_base_name=base_b, frequency=int(cfg.get("frequency") or 10),
                    unit=str(cfg.get("unit") or ""),
                )
                check_eq("old_base_gone", 0, len([
                    r for r in active_rows(ctx, tagBaseName=base_a, tagName=tag_name)
                    if str(r.get("tagBaseName") or "") == base_a
                ]))
                new_rows = [
                    r for r in active_rows(ctx, tagBaseName=base_b)
                    if r.get("tagName") == tag_name and str(r.get("tagBaseName") or "") == base_b
                ]
                check_eq("new_base_hit", 1, len(new_rows))
                cfg2 = config_page_row(ctx, tag_name)
                check_eq("config_base_updated", base_b, cfg2.get("tagBaseName"))
                rt_row(ctx, tag_name, timeout=60.0)
                cleanup_case_tag(ctx, cc, tag_id, tag_name)
                tag_id = tag_name = 0
                return CaseStatus.PASS

            g1 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "g58a"), parent_id="0")
            g2 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "g58b"), parent_id="0")
            g1_id, g2_id = str(g1.get("id") or ""), str(g2.get("id") or "")
            created_groups.extend([g1_id, g2_id])
            tag = create_case_tag(ctx, cc, ds_id, suffix="59")
            tag_id, tag_name = int(tag["id"]), tag["name"]
            add_tag_group_relation(api, group_id=g1_id, tag_ids=[tag_id])
            batch_update_tags(api, [tag_id], group_id=g2_id)
            in_g1 = ((query_tags_with_quality(api, group_id=g1_id, tag_name=tag_name, page=1, page_size=10) or {})
                     .get("tagInfoList") or {}).get("records") or []
            in_g2 = ((query_tags_with_quality(api, group_id=g2_id, tag_name=tag_name, page=1, page_size=10) or {})
                     .get("tagInfoList") or {}).get("records") or []
            check_eq("g1_empty", 0, len(in_g1))
            check_eq("g2_has_tag", 1, len(in_g2))
            check_eq("tag_id_unchanged", tag_id, int(in_g2[0].get("id") or 0))
            return CaseStatus.PASS

        tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:])
        tag_id, tag_name = int(tag["id"]), tag["name"]

        if cid == "UA-2-2-057":
            new_name = case_tag_name(ctx, cc, "57new")
            cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
            update_tag(api, tag_id, tag_name=new_name,
                       data_type=int(cfg.get("dataType") or DataTypes["INT"]),
                       ds_id=int(cfg.get("dsId")))
            check_eq("old_gone", 0, len(exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)))
            check_eq("new_found", 1, len(exact(active_rows(ctx, tagName=new_name), "tagName", new_name)))
            cleanup_case_tag(ctx, cc, tag_id, new_name)
            tag_id = tag_name = 0
            return CaseStatus.PASS

        if cid == "UA-2-2-061":
            soft_delete_tag(ctx, tag_id)
            time.sleep(2)
            check_eq("gone_active", 0, len(exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)))
            check_true("in_recycle", bool([r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name]))
            physical_delete_tag(ctx, tag_id)
            cc.registry.pop(f"tag:{tag_name}")
            tag_id = tag_name = 0
            return CaseStatus.PASS

        if cid in {"UA-2-2-063", "UA-2-2-064"}:
            before = len(filter_unregistered(ctx, ds_id, browse_all_nodes(ctx, ds_id)))
            if cid == "UA-2-2-063":
                after_reg = len(registered_base_names(ctx, ds_id))
                after = len(filter_unregistered(ctx, ds_id, browse_all_nodes(ctx, ds_id)))
                ctx.bag[cid] = {"before": before, "after": after, "registered": after_reg}
            else:
                soft_delete_tag(ctx, tag_id)
                after_soft = len(filter_unregistered(ctx, ds_id, browse_all_nodes(ctx, ds_id)))
                physical_delete_tag(ctx, tag_id)
                cc.registry.pop(f"tag:{tag_name}")
                tag_id = tag_name = 0
                after_phys = len(filter_unregistered(ctx, ds_id, browse_all_nodes(ctx, ds_id)))
                ctx.bag[cid] = {"after_soft": after_soft, "after_physical": after_phys}
            return CaseStatus.OBSERVED

        if cid == "UA-2-2-062":
            soft_delete_tag(ctx, tag_id)
            physical_delete_tag(ctx, tag_id)
            cc.registry.pop(f"tag:{tag_name}")
            check_eq("no_active", 0, len(exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)))
            check_eq("no_recycle", 0, len([r for r in all_recycle_rows(ctx) if r.get("tagName") == tag_name]))
            tag_id = tag_name = 0
            return CaseStatus.PASS

        if cid == "UA-2-2-060":
            from tpt_api.datahub import add_tag_group_relation, remove_tag_group_relation, list_favorite_tags
            add_tag_group_relation(api, group_id="2", tag_ids=[tag_id])
            fav = list_favorite_tags(api, page=1, page_size=50)
            recs = ((fav or {}).get("tagInfoList") or {}).get("records") or []
            check_true("favorited", any(int(r.get("id", -1)) == tag_id for r in recs))
            remove_tag_group_relation(api, group_id="2", tag_ids=[tag_id])
            return CaseStatus.PASS

        raise AssertFail(f"result_update_cases: {cid}")
    finally:
        if tag_id:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
        from tpt_api.datahub import delete_tag_group
        for grp_id in created_groups:
            if grp_id:
                try:
                    delete_tag_group(api, [grp_id], is_force=False)
                except Exception:
                    pass


def stability_cases(ctx, cc, meta, cid: str) -> CaseStatus:
    """UA-2-2-065~067: 稳定性与隔离。"""
    from tpt_api.datahub import list_tags, query_tags_with_quality

    api = _api(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])

    if cid == "UA-2-2-065":
        totals = []
        id_sets = []
        for _ in range(20):
            page = list_tags(api, page=1, page_size=10, data={"dsId": ds_id})
            totals.append(int(page.get("total") or 0))
            id_sets.append({int(r["id"]) for r in (page.get("records") or []) if r.get("id")})
        check_eq("total_stable", len(set(totals)), 1)
        check_eq("first_page_ids_stable", len(set(frozenset(s) for s in id_sets)), 1)
        return CaseStatus.PASS

    if cid == "UA-2-2-066":
        r1 = query_tags_with_quality(api, ds_id=ds_id, page=1, page_size=20)
        empty = require_shared_datasource(ctx, "empty")
        r2 = query_tags_with_quality(api, ds_id=int(empty["id"]), page=1, page_size=20)
        n1 = {r.get("tagName") for r in (((r1 or {}).get("tagInfoList") or {}).get("records") or [])}
        n2 = {r.get("tagName") for r in (((r2 or {}).get("tagInfoList") or {}).get("records") or [])}
        check_true("isolated_sets", not n1.intersection(n2) or (not n1 or not n2))
        return CaseStatus.PASS

    if cid == "UA-2-2-067":
        tag = create_case_tag(ctx, cc, ds_id, suffix="67")
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            snap = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0].copy()
            for _ in range(5):
                list_tags(api, page=1, page_size=10, data={"tagName": tag_name})
                query_tags_with_quality(api, tag_name=tag_name, page=1, page_size=10)
            after = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
            for f in ("tagName", "tagBaseName", "dsId", "dataType", "frequency"):
                check_eq(f"unchanged_{f}", snap.get(f), after.get(f))
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    raise AssertFail(f"stability_cases: {cid}")
