"""UA-2-5 分组树精确 dispatcher。"""
from __future__ import annotations

from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import active_rows, case_tag_name, cleanup_case_tag, create_case_tag, exact


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _observed(ctx, meta, detail: Any = None) -> CaseStatus:
    ctx.bag[f"observed_{meta['id']}"] = detail or meta.get("title")
    return CaseStatus.OBSERVED


def _flatten_tree(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for n in nodes or []:
        out.append(n)
        out.extend(_flatten_tree(n.get("tagGroupList") or []))
    return out


def _tree_nodes(api) -> list[dict]:
    from tpt_api.datahub import get_tag_group_tree
    tree = get_tag_group_tree(api)
    if isinstance(tree, list):
        return _flatten_tree(tree)
    return _flatten_tree([tree] if tree else [])


def _delete_group(api, gid: str) -> None:
    from tpt_api.datahub import delete_tag_group
    if gid and gid not in ("0", "1", "2"):
        try:
            delete_tag_group(api, [gid], is_force=False)
        except Exception:
            pass


def dispatch_ua2_5(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    cid = meta["id"]
    num = int(cid.split("-")[-1])
    api = _api(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    created: list[str] = []
    tag_id = tag_name = 0

    try:
        from tpt_api.datahub import (
            add_tag_group,
            add_tag_group_relation,
            batch_update_tags,
            delete_tag_group,
            get_tag_group_tree,
            list_favorite_tags,
            remove_tag_group_relation,
            update_tag_group,
        )

        if num == 1:
            nodes = _tree_nodes(api)
            check_true("has_root", any(str(n.get("id")) == "0" or n.get("groupName") == "Root" for n in nodes))
            ids = [str(n.get("id")) for n in nodes if n.get("id") is not None]
            check_eq("unique_ids", len(ids), len(set(ids)))
            return CaseStatus.PASS

        if num == 2:
            snaps = [_tree_nodes(api) for _ in range(3)]
            check_eq("stable", snaps[0], snaps[1])
            check_eq("stable2", snaps[1], snaps[2])
            return CaseStatus.PASS

        if num == 3:
            g1 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "g1"), parent_id="0")
            g1_id = str(g1.get("id") or "")
            created.append(g1_id)
            g2 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "g2"), parent_id=g1_id)
            g2_id = str(g2.get("id") or "")
            created.append(g2_id)
            g3 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "g3"), parent_id=g2_id)
            g3_id = str(g3.get("id") or "")
            created.append(g3_id)
            nodes = {str(n.get("id")): n for n in _tree_nodes(api)}
            check_eq("g2_parent", g1_id, str(nodes.get(g2_id, {}).get("parentId")))
            check_eq("g3_parent", g2_id, str(nodes.get(g3_id, {}).get("parentId")))
            return CaseStatus.PASS

        if num == 4:
            g = add_tag_group(api, group_name=case_tag_name(ctx, cc, "r4"), parent_id="0")
            gid = str(g.get("id") or "")
            created.append(gid)
            nodes = _tree_nodes(api)
            check_true("under_root", any(str(n.get("id")) == gid for n in nodes))
            return CaseStatus.PASS

        if num == 5:
            g1 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "p5"), parent_id="0")
            g1_id = str(g1.get("id") or "")
            created.append(g1_id)
            g2 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "c5"), parent_id=g1_id)
            g2_id = str(g2.get("id") or "")
            created.append(g2_id)
            nodes = {str(n.get("id")): n for n in _tree_nodes(api)}
            check_eq("child_parent", g1_id, str(nodes.get(g2_id, {}).get("parentId")))
            return CaseStatus.PASS

        if num == 6:
            g1 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "dup"), parent_id="0")
            gid1 = str(g1.get("id") or "")
            created.append(gid1)
            try:
                g2 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "dup"), parent_id="0")
                created.append(str(g2.get("id") or ""))
                ctx.bag[cid] = {"duplicate_allowed": True}
            except Exception as exc:
                ctx.bag[cid] = {"duplicate_allowed": False, "error": str(exc)}
            return CaseStatus.OBSERVED

        if num == 7:
            try:
                add_tag_group(api, group_name="", parent_id="0")
                ctx.bag[cid] = {"accepted": True}
            except Exception as exc:
                ctx.bag[cid] = {"accepted": False, "error": str(exc)}
            return CaseStatus.OBSERVED

        if num == 8:
            try:
                add_tag_group(api, group_name=case_tag_name(ctx, cc, "bad"), parent_id="999999")
                ctx.bag[cid] = {"accepted": True}
            except Exception as exc:
                ctx.bag[cid] = {"accepted": False, "error": str(exc)}
            return CaseStatus.OBSERVED

        if num == 9:
            g = add_tag_group(api, group_name=case_tag_name(ctx, cc, "old"), parent_id="0")
            gid = str(g.get("id") or "")
            created.append(gid)
            new_name = case_tag_name(ctx, cc, "new")
            update_tag_group(api, gid, group_name=new_name, parent_id="0")
            nodes = {str(n.get("id")): n for n in _tree_nodes(api)}
            check_eq("renamed", new_name, nodes.get(gid, {}).get("groupName"))
            return CaseStatus.PASS

        if num == 10:
            g1 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "m1"), parent_id="0")
            g2 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "m2"), parent_id="0")
            g3 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "m3"), parent_id="0")
            ids = [str(g1.get("id")), str(g2.get("id")), str(g3.get("id"))]
            created.extend(ids)
            update_tag_group(api, ids[1], group_name=case_tag_name(ctx, cc, "m2m"), parent_id=ids[2])
            nodes = {str(n.get("id")): n for n in _tree_nodes(api)}
            check_eq("moved_parent", ids[2], str(nodes.get(ids[1], {}).get("parentId")))
            return CaseStatus.PASS

        if num == 11:
            g = add_tag_group(api, group_name=case_tag_name(ctx, cc, "both"), parent_id="0")
            gid = str(g.get("id") or "")
            created.append(gid)
            g2 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "tgt"), parent_id="0")
            tgt = str(g2.get("id") or "")
            created.append(tgt)
            new_name = case_tag_name(ctx, cc, "both2")
            update_tag_group(api, gid, group_name=new_name, parent_id=tgt)
            nodes = {str(n.get("id")): n for n in _tree_nodes(api)}
            check_eq("name", new_name, nodes.get(gid, {}).get("groupName"))
            check_eq("parent", tgt, str(nodes.get(gid, {}).get("parentId")))
            return CaseStatus.PASS

        if num == 12:
            try:
                update_tag_group(api, "999999", group_name="x", parent_id="0")
                ctx.bag[cid] = {"accepted": True}
            except Exception as exc:
                ctx.bag[cid] = {"accepted": False, "error": str(exc)}
            return CaseStatus.OBSERVED

        if num == 13:
            g1 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "p13"), parent_id="0")
            g2 = add_tag_group(api, group_name=case_tag_name(ctx, cc, "c13"), parent_id=str(g1.get("id")))
            ids = [str(g1.get("id")), str(g2.get("id"))]
            created.extend(ids)
            try:
                update_tag_group(api, ids[0], group_name=case_tag_name(ctx, cc, "p13"), parent_id=ids[1])
                ctx.bag[cid] = {"cycle_allowed": True}
            except Exception as exc:
                ctx.bag[cid] = {"cycle_allowed": False, "error": str(exc)}
            return CaseStatus.OBSERVED

        if num in {14, 15, 16, 17}:
            g = add_tag_group(api, group_name=case_tag_name(ctx, cc, f"tg{num}"), parent_id="0")
            gid = str(g.get("id") or "")
            created.append(gid)
            tags = [create_case_tag(ctx, cc, ds_id, suffix=f"{num}{i}") for i in range(1 if num == 14 else min(3, 10))]
            try:
                tids = [int(t["id"]) for t in tags]
                add_tag_group_relation(api, group_id=gid, tag_ids=tids)
                batch_update_tags(api, tids, group_id=gid if num != 16 else "0")
                for t in tags:
                    check_true("still_active", bool(exact(active_rows(ctx, tagName=t["name"]), "tagName", t["name"])))
                if num == 17:
                    try:
                        batch_update_tags(api, tids, group_id="999999")
                        ctx.bag[cid] = {"accepted": True}
                    except Exception as exc:
                        ctx.bag[cid] = {"accepted": False, "error": str(exc)}
                    return CaseStatus.OBSERVED
                return CaseStatus.PASS
            finally:
                for t in tags:
                    cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])

        if num == 18:
            g = add_tag_group(api, group_name=case_tag_name(ctx, cc, "del18"), parent_id="0")
            gid = str(g.get("id") or "")
            delete_tag_group(api, [gid], is_force=False)
            nodes = _tree_nodes(api)
            check_true("gone", gid not in {str(n.get("id")) for n in nodes})
            return CaseStatus.PASS

        if num in {19, 20, 21}:
            g = add_tag_group(api, group_name=case_tag_name(ctx, cc, f"nf{num}"), parent_id="0")
            gid = str(g.get("id") or "")
            created.append(gid)
            tag = create_case_tag(ctx, cc, ds_id, suffix=str(num))
            tag_id, tag_name = int(tag["id"]), tag["name"]
            try:
                add_tag_group_relation(api, group_id=gid, tag_ids=[tag_id])
                force = num == 20
                try:
                    delete_tag_group(api, [gid], is_force=force)
                    ctx.bag[cid] = {"deleted": True, "force": force}
                except Exception as exc:
                    ctx.bag[cid] = {"deleted": False, "error": str(exc)}
                return CaseStatus.OBSERVED
            finally:
                cleanup_case_tag(ctx, cc, tag_id, tag_name)
                _delete_group(api, gid)

        if num == 22:
            gs = [add_tag_group(api, group_name=case_tag_name(ctx, cc, f"b{i}"), parent_id="0") for i in range(3)]
            ids = [str(g.get("id") or "") for g in gs]
            delete_tag_group(api, ids, is_force=False)
            nodes = {str(n.get("id")) for n in _tree_nodes(api)}
            check_true("all_gone", all(i not in nodes for i in ids))
            return CaseStatus.PASS

        if num in {23, 24, 25, 26, 27}:
            if num == 24:
                tags = [create_case_tag(ctx, cc, ds_id, suffix=f"24{i}") for i in range(3)]
            else:
                tags = [create_case_tag(ctx, cc, ds_id, suffix=str(num))]
            tids = [int(t["id"]) for t in tags]
            try:
                if num == 25:
                    add_tag_group_relation(api, group_id="2", tag_ids=[tids[0]])
                    add_tag_group_relation(api, group_id="2", tag_ids=[tids[0]])
                    ctx.bag[cid] = {"duplicate_fav": True}
                    return CaseStatus.OBSERVED
                if num == 27:
                    add_tag_group_relation(api, group_id="2", tag_ids=[tids[0]])
                    result = remove_tag_group_relation(api, group_id="2", tag_ids=[tids[0]])
                    fav = list_favorite_tags(api, page=1, page_size=50)
                    recs = ((fav or {}).get("tagInfoList") or {}).get("records") or []
                    gone = not any(int(r.get("id", -1)) == tids[0] for r in recs)
                    check_true("removed_even_if_false_return", gone)
                    ctx.bag[cid] = {"api_result": result}
                    return CaseStatus.PASS
                add_tag_group_relation(api, group_id="2", tag_ids=tids)
                fav = list_favorite_tags(api, page=1, page_size=50)
                recs = ((fav or {}).get("tagInfoList") or {}).get("records") or []
                for tid in tids:
                    check_true(f"fav_{tid}", any(int(r.get("id", -1)) == tid for r in recs))
                if num == 26:
                    remove_tag_group_relation(api, group_id="2", tag_ids=tids)
                    fav2 = list_favorite_tags(api, page=1, page_size=50)
                    recs2 = ((fav2 or {}).get("tagInfoList") or {}).get("records") or []
                    for tid in tids:
                        check_true(f"removed_{tid}", not any(int(r.get("id", -1)) == tid for r in recs2))
                return CaseStatus.PASS
            finally:
                try:
                    remove_tag_group_relation(api, group_id="2", tag_ids=tids)
                except Exception:
                    pass
                for t in tags:
                    cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])

        return _observed(ctx, meta, f"residual {cid}")
    finally:
        for gid in created:
            _delete_group(api, gid)
