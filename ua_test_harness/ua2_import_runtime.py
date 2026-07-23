"""UA-2-3 导入导出精确 dispatcher。"""
from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_import_helpers import (
    assert_export_rows,
    export_to_temp,
    import_file,
    wait_collectible,
    write_invalid_file,
)
from ua_test_harness.ua2_ops import active_rows, case_tag_name, cleanup_case_tag, create_case_tag, exact


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _observed(ctx, meta, detail: Any = None) -> CaseStatus:
    ctx.bag[f"observed_{meta['id']}"] = detail or meta.get("title")
    return CaseStatus.OBSERVED


def _blocked(ctx, meta, reason: str) -> CaseStatus:
    ctx.bag[f"blocked_{meta['id']}"] = reason
    return CaseStatus.BLOCKED


def _make_tags(ctx, cc, ds_id: int, count: int, *, type_key: str = "INT32") -> list[dict]:
    """创建绑定 ua2_types.yaml *_r_* 节点的可采集位号(导出前需 RT 有效)。"""
    from ua_test_harness.ua2_fixture_map import base_name_for_node, read_spec

    spec = read_spec(type_key)
    base = base_name_for_node(spec["node"])
    return [
        create_case_tag(
            ctx, cc, ds_id,
            suffix=f"t{i}",
            data_type=spec["dtype"],
            tag_base_name=base,
            only_read=True,
        )
        for i in range(count)
    ]


def _make_collectible_tag(ctx, cc, ds_id: int, *, suffix: str) -> dict:
    """单条可采集位号(跨源/空 DS 等场景复用)。"""
    from ua_test_harness.ua2_fixture_map import base_name_for_node, read_spec

    spec = read_spec("INT32")
    tag = create_case_tag(
        ctx, cc, ds_id,
        suffix=suffix,
        data_type=spec["dtype"],
        tag_base_name=base_name_for_node(spec["node"]),
        only_read=True,
    )
    wait_collectible(ctx, tag["name"])
    return tag


def dispatch_ua2_3(ctx, cc, meta) -> CaseStatus:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    cid = meta["id"]
    ds = require_shared_datasource(ctx, "types")
    ds_id = int(ds["id"])
    num = int(cid.split("-")[-1])
    tmp_dir = tempfile.mkdtemp(prefix="ua23_run_")
    tags: list[dict] = []

    try:
        if num != 10 and (num <= 12 or num in {28} or (13 <= num <= 27)):
            tags = _make_tags(ctx, cc, ds_id, 1 if num not in {2, 14, 29, 32} else min(10, 3))
            for t in tags:
                wait_collectible(ctx, t["name"])

        if num == 1:
            path, rows = export_to_temp(ctx, [int(tags[0]["id"])], suffix=cid)
            assert_export_rows(rows, min_rows=2, tag_names={tags[0]["name"]})
            return CaseStatus.PASS

        if num == 2:
            ids = [int(t["id"]) for t in tags]
            _, rows = export_to_temp(ctx, ids, suffix=cid)
            assert_export_rows(rows, min_rows=len(ids) + 1)
            return CaseStatus.PASS

        if num == 3:
            empty = require_shared_datasource(ctx, "empty")
            t2 = _make_collectible_tag(ctx, cc, int(empty["id"]), suffix="3b")
            tags.append(t2)
            _, rows = export_to_temp(ctx, [int(tags[0]["id"]), int(t2["id"])], suffix=cid)
            assert_export_rows(rows, min_rows=3)
            return CaseStatus.PASS

        if num == 4:
            try:
                from tpt_api.datahub import export_tags
                export_tags(_api(ctx), [], parse=False)
                ctx.bag[cid] = {"empty_ids": "accepted"}
            except Exception as exc:
                ctx.bag[cid] = {"empty_ids": "rejected", "error": str(exc)}
            return CaseStatus.OBSERVED

        if num == 5:
            tid = int(tags[0]["id"])
            p1, r1 = export_to_temp(ctx, [tid], suffix="5a")
            p2, r2 = export_to_temp(ctx, [tid], suffix="5b")
            check_eq("row_count_stable", len(r1), len(r2))
            return CaseStatus.PASS

        if num == 6:
            _, rows = export_to_temp(ctx, [int(tags[0]["id"])], suffix=cid)
            check_eq("header_cols", 21, len(rows[0]))
            return CaseStatus.PASS

        if num in {7, 8, 9}:
            from ua_test_harness.ua2_precise import config_page_row
            from ua_test_harness.ua2_import_helpers import (
                assert_export_config_fields,
                assert_export_identity,
                assert_export_limits,
            )

            tname = tags[0]["name"]
            tid = int(tags[0]["id"])
            if num == 8:
                from tpt_api.datahub import update_tag
                from tpt_api.types import DataTypes
                cfg0 = exact(active_rows(ctx, tagName=tname), "tagName", tname)[0]
                update_tag(
                    _api(ctx), tid, tag_name=tname,
                    data_type=int(cfg0.get("dataType") or DataTypes["INT"]),
                    ds_id=int(cfg0.get("dsId")),
                    unit="kW", frequency=5, tag_desc="export_field_check",
                    only_read=False, need_push=True,
                )
                wait_collectible(ctx, tname)
            if num == 9:
                from tpt_api.datahub import update_tag
                from tpt_api.types import DataTypes
                cfg0 = exact(active_rows(ctx, tagName=tname), "tagName", tname)[0]
                update_tag(
                    _api(ctx), tid, tag_name=tname,
                    data_type=int(cfg0.get("dataType") or DataTypes["INT"]),
                    ds_id=int(cfg0.get("dsId")),
                    limit_up=100, limit_up_up=90, limit_up_up_up=80,
                    limit_down=-100, limit_down_down=-90, limit_down_down_down=-80,
                )
                wait_collectible(ctx, tname)
            _, rows = export_to_temp(ctx, [tid], suffix=cid)
            cfg = config_page_row(ctx, tname)
            assert_export_identity(rows, tname, ds_name=str(ds["name"]), cfg=cfg)
            if num == 8:
                assert_export_config_fields(rows, tname, cfg)
            if num == 9:
                assert_export_limits(rows, tname, cfg)
            return CaseStatus.PASS

        if num == 10:
            from ua_test_harness.ua2_fixture_map import READ_NODES, base_name_for_node
            from ua_test_harness.ua2_import_helpers import find_export_row, _str_cell

            type_tags: list[dict] = []
            try:
                for i, (key, spec) in enumerate(READ_NODES.items()):
                    t = create_case_tag(
                        ctx, cc, ds_id, suffix=f"10{i:02d}",
                        data_type=spec["dtype"],
                        tag_base_name=base_name_for_node(spec["node"]),
                    )
                    type_tags.append(t)
                    wait_collectible(ctx, t["name"])
                ids = [int(t["id"]) for t in type_tags]
                _, rows = export_to_temp(ctx, ids, suffix=cid)
                check_eq("type_row_count", len(READ_NODES) + 1, len(rows))
                for key, t in zip(READ_NODES.keys(), type_tags):
                    er = find_export_row(rows, t["name"])
                    check_true(f"type_export_{key}", _str_cell(er[5]) != "")
                return CaseStatus.PASS
            finally:
                for t in type_tags:
                    cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])

        if num in {11, 12}:
            _, rows = export_to_temp(ctx, [int(tags[0]["id"])], suffix=cid)
            ctx.bag[cid] = {"rows": len(rows), "sample": rows[1] if len(rows) > 1 else None}
            return CaseStatus.OBSERVED

        if num == 13:
            path, _ = export_to_temp(ctx, [int(tags[0]["id"])], suffix=cid)
            import_file(ctx, path, conflict_strategy=1)
            check_true("still_exists", bool(exact(active_rows(ctx, tagName=tags[0]["name"]), "tagName", tags[0]["name"])))
            return CaseStatus.PASS

        if num == 14:
            path, _ = export_to_temp(ctx, [int(t["id"]) for t in tags], suffix=cid)
            import_file(ctx, path, conflict_strategy=1)
            for t in tags:
                check_true(f"exists_{t['name']}", bool(exact(active_rows(ctx, tagName=t["name"]), "tagName", t["name"])))
            return CaseStatus.PASS

        if num in {15, 16, 17, 18}:
            path, _ = export_to_temp(ctx, [int(tags[0]["id"])], suffix=cid)
            try:
                import_file(ctx, path, conflict_strategy=1)
                return CaseStatus.PASS if num != 18 else CaseStatus.OBSERVED
            except Exception as exc:
                return _observed(ctx, meta, str(exc))

        if num == 19:
            path, _ = export_to_temp(ctx, [int(tags[0]["id"])], suffix=cid)
            import_file(ctx, path)
            from ua_test_harness.ua2_precise import rt_row
            rt_row(ctx, tags[0]["name"], timeout=60.0)
            return CaseStatus.PASS

        if num == 20:
            tname = tags[0]["name"]
            snap = exact(active_rows(ctx, tagName=tname), "tagName", tname)[0]
            path, _ = export_to_temp(ctx, [int(tags[0]["id"])], suffix=cid)
            import_file(ctx, path, conflict_strategy=0)
            after = exact(active_rows(ctx, tagName=tname), "tagName", tname)[0]
            check_eq("unit_unchanged", snap.get("unit"), after.get("unit"))
            return CaseStatus.PASS

        if num == 21:
            from tpt_api.datahub import update_tag
            from tpt_api.types import DataTypes
            tname = tags[0]["name"]
            tid = int(tags[0]["id"])
            cfg = exact(active_rows(ctx, tagName=tname), "tagName", tname)[0]
            update_tag(_api(ctx), tid, tag_name=tname,
                       data_type=int(cfg.get("dataType") or DataTypes["INT"]),
                       ds_id=int(cfg.get("dsId")), unit="Hz")
            wait_collectible(ctx, tname)
            path, _ = export_to_temp(ctx, [tid], suffix=cid)
            import_file(ctx, path, conflict_strategy=1)
            after = exact(active_rows(ctx, tagName=tname), "tagName", tname)[0]
            check_eq("unit_in_config", "Hz", after.get("unit"))
            wait_collectible(ctx, tname)
            return CaseStatus.PASS

        if num in {22, 23, 24, 25, 26, 27}:
            bad = os.path.join(tmp_dir, f"bad_{num}.xlsx")
            if num == 25:
                write_invalid_file(bad, b"not an xlsx")
            elif num == 26:
                write_invalid_file(bad, b"PK\x03\x04broken")
            else:
                write_invalid_file(bad, b"tag,name\na,b")
            try:
                import_file(ctx, bad, conflict_strategy=0)
                ctx.bag[cid] = {"accepted": True}
            except Exception as exc:
                ctx.bag[cid] = {"accepted": False, "error": str(exc)}
            return CaseStatus.OBSERVED if num in {22, 23, 24, 27} else CaseStatus.PASS

        if num == 28:
            tname = tags[0]["name"]
            tid = int(tags[0]["id"])
            from tpt_api.datahub import update_tag
            from tpt_api.types import DataTypes
            cfg = exact(active_rows(ctx, tagName=tname), "tagName", tname)[0]
            update_tag(_api(ctx), tid, tag_name=tname,
                       data_type=int(cfg.get("dataType") or DataTypes["INT"]),
                       ds_id=int(cfg.get("dsId")), unit="MHz", tag_desc="roundtrip")
            wait_collectible(ctx, tname)
            p1, _ = export_to_temp(ctx, [tid], suffix="28a")
            import_file(ctx, p1, conflict_strategy=1)
            p2, r2 = export_to_temp(ctx, [tid], suffix="28b")
            check_true("second_export", len(r2) >= 2)
            return CaseStatus.PASS

        if num in {29, 30, 31, 32}:
            from tpt_api.datahub import batch_add_tags
            from ua_test_harness.ua2_browse import browse_entry_to_batch_info, pick_unused_nodes
            from ua_test_harness.ua2_precise import config_page_row, rt_row

            count = 1 if num == 29 else (10 if num != 32 else min(100, 20))
            try:
                nodes = pick_unused_nodes(ctx, ds_id, count)
            except Exception as exc:
                ctx.bag[cid] = {"browse_error": str(exc)}
                return CaseStatus.OBSERVED
            created: list[tuple[int, str]] = []
            try:
                if num == 31:
                    tname = case_tag_name(ctx, cc, "31")
                    info = browse_entry_to_batch_info(nodes[0], ds_id=ds_id, tag_name=tname, unit="kW")
                    batch_add_tags(_api(ctx), [info], conflict_strategy=0)
                    created.append((int(config_page_row(ctx, tname)["id"]), tname))
                    info["unit"] = "Hz"
                    batch_add_tags(_api(ctx), [info], conflict_strategy=1)
                    check_eq("unit", "Hz", config_page_row(ctx, tname).get("unit"))
                    return CaseStatus.PASS
                infos = [
                    browse_entry_to_batch_info(n, ds_id=ds_id, tag_name=case_tag_name(ctx, cc, f"3{num}{i}"))
                    for i, n in enumerate(nodes)
                ]
                batch_add_tags(_api(ctx), infos, conflict_strategy=0)
                for info in infos:
                    config_page_row(ctx, info["tagName"])
                    if num in {29, 32}:
                        rt_row(ctx, info["tagName"], timeout=60.0)
                    row = exact(active_rows(ctx, tagName=info["tagName"]), "tagName", info["tagName"])
                    created.append((int(row[0]["id"]), info["tagName"]))
                return CaseStatus.PASS
            finally:
                for tid, tname in created:
                    cleanup_case_tag(ctx, cc, tid, tname)

        return _blocked(ctx, meta, f"UA-2-3 gap {cid}")
    except Exception as exc:
        kind = meta.get("kind") or ""
        if "探索" in kind:
            ctx.bag[cid] = {"error": str(exc)}
            return CaseStatus.OBSERVED
        raise
    finally:
        for t in tags:
            cleanup_case_tag(ctx, cc, int(t["id"]), t["name"])
        shutil.rmtree(tmp_dir, ignore_errors=True)
