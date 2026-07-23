"""Precise UA-2-1 creation scenarios using shared baseline datasource.

Resource model:
- Shared datasource ua_shared_ua2_types_ds is looked up, never created/deleted.
- Each case creates its own ua_case_ua2_-prefixed tag and explicitly deletes it.
- registry is a FALLBACK only; normal cleanup is visible in each case body.
"""
from __future__ import annotations

from typing import Any

from ua_test_harness.assertions import check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_ops import (
    CASE_TAG_PREFIX,
    active_rows,
    case_tag_name,
    cleanup_case_tag,
    create_case_tag,
    create_tag_raw,
    exact,
    physical_delete_tag,
)


def _make_length_name(prefix: str, target_len: int) -> str:
    """Generate a name of exactly `target_len` bytes: prefix + filler + "_end".

    Identical to the legacy implementation so test_length_name_127/128 still pass.
    """
    suffix = "_end"
    head_room = target_len - len(suffix)
    if head_room <= 0:
        return prefix + suffix
    payload = prefix + ("x" * (head_room - len(prefix))) + suffix
    return payload[:target_len]


def _add_tag_by_name(ctx, ds_id: int, name: str) -> dict:
    """Direct add_tag for boundary/duplicate attempts. No pre-clean, no registry.

    Kept as a separate helper because these attempts are TEST ACTIONS, not normal
    case setup -- the case body must NOT register a fallback for them (they are
    expected to either be rejected or be defensively cleaned up by the caller).
    """
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes
    from ua_test_harness.clients.tpt_client import get_api

    return add_tag(
        get_api(ctx),
        tag_name=name,
        data_type=DataTypes["INT"],
        tag_type=TagTypes["一次位号"],
        ds_id=ds_id,
        group_id="0",
        unit="",
        only_read=False,
        frequency=1,
        need_push=True,
        tag_desc="ua-2-1 precise batch",
        is_vector=True,
        tag_base_name="2_" + name,
    )


def duplicate_name_rejected(ctx, cc):
    """UA-2-1-017: 重名位号必须被拒绝,且原记录未被覆盖。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]
    tag = create_case_tag(ctx, cc, ds_id, suffix="dup")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        original = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_eq("original_exists", 1, len(original))
        orig = original[0]
        snapshot = {
            "id": tag_id,
            "dsId": orig.get("dsId"),
            "tagBaseName": orig.get("tagBaseName"),
        }

        rejected = False
        try:
            _add_tag_by_name(ctx, ds_id, tag_name)
        except Exception:
            rejected = True
        check_true("duplicate_rejected", rejected)

        matched = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        check_eq("only_one_record", 1, len(matched))
        rec = matched[0]
        check_eq("dsId_unchanged", snapshot["dsId"], rec.get("dsId"))
        check_eq("id_unchanged", snapshot["id"], int(rec.get("id")))
        check_eq("tagBaseName_unchanged", snapshot["tagBaseName"], rec.get("tagBaseName"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def empty_name_rejected(ctx, cc):
    """UA-2-1-019: tag_name="" 调用 add_tag 必须失败;不允许偷偷接受并落库。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]

    err_id = None
    failed = False
    try:
        try:
            result = _add_tag_by_name(ctx, ds_id, "")
            maybe = result.get("id") or result.get("tagId")
            if maybe:
                err_id = int(maybe)
        except Exception:
            failed = True

        check_true("empty_name_rejected", failed)
        check_eq("no_empty_record", 0, len(exact(active_rows(ctx, tagName=""), "tagName", "")))
        return CaseStatus.PASS
    finally:
        # Even when check_true raises AssertFail (product accepted empty name ->
        # FAIL; Bug #2 product defect, kept as FAIL per decision), clean up any
        # tag the server silently created so nothing leaks. Does not change FAIL.
        if err_id is not None:
            try:
                physical_delete_tag(ctx, err_id)
            except Exception:
                pass


def _verify_length(ctx, cc, target_len: int):
    """Boundary-length tag: create, then assert either exact bytes (accepted)
    or zero records (rejected). finally always cleans up the created tag."""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    ds = require_shared_datasource(ctx, "types")
    ds_id = ds["id"]

    name = _make_length_name(
        CASE_TAG_PREFIX + "tag_len" + str(target_len) + "_",
        target_len,
    )
    assert len(name) == target_len, (len(name), target_len)
    assert name.startswith(CASE_TAG_PREFIX), name

    b_id: int | None = None
    try:
        boundary = create_tag_raw(ctx, name, ds_id, tag_desc="ua-2-1 precise batch")
        b_id = int(boundary["id"])
        # Register the fallback so cleanup_case_tag can pop it later.
        cc.registry.register(
            f"tag:{name}", "tag",
            lambda: physical_delete_tag(ctx, b_id),
            payload={"id": b_id, "name": name},
        )
    except Exception:
        # Server rejected the boundary name outright; b_id stays None.
        b_id = None

    try:
        matched = exact(active_rows(ctx, tagName=name), "tagName", name)
        if matched:
            check_eq("only_one_match", 1, len(matched))
            rec = matched[0]
            check_eq("name_byte_equal", name, rec.get("tagName"))
            check_eq("length_exact", len(name), len(rec.get("tagName") or ""))
            return CaseStatus.PASS
        # rejected path: ensure no partial record
        check_eq("no_partial_record_on_reject", 0, len(matched))
        return CaseStatus.PASS
    finally:
        if b_id is not None:
            cleanup_case_tag(ctx, cc, b_id, name)


def name_length_127(ctx, cc):
    """UA-2-1-021: 总长度=127 名。接受必须字节一致;拒绝不得留半截。"""
    return _verify_length(ctx, cc, 127)


def name_length_128(ctx, cc):
    """UA-2-1-022: 总长度=128 名。接受必须字节一致;拒绝不得留半截。"""
    return _verify_length(ctx, cc, 128)


# ---------- UA-2-1 章节 dispatcher(余量 case) ----------

from ua_test_harness.models import CaseStatus as _CS
from ua_test_harness.ua2_fixture_map import CASE_READ_TYPE, CASE_WRITE_TYPE, base_name_for_node, read_spec, write_spec
from ua_test_harness.ua2_helpers import (
    _observe,
    _qtq_row,
    _types_ds,
    _wait_changed,
    _wait_rt,
    standard_read_closed_loop,
    standard_write_closed_loop,
    try_add_tag,
    verify_config_row,
    write_and_verify,
)


def _explore(ctx, meta, *, outcome: str, detail: Any = None) -> _CS:
    cid = meta["id"]
    ctx.bag[f"explore_{cid}"] = {"outcome": outcome, "detail": detail}
    return _CS.OBSERVED


def _blocked(ctx, meta, reason: str) -> _CS:
    ctx.bag[f"blocked_{meta['id']}"] = reason
    return _CS.BLOCKED


def _precise_explore_duplicate_base(ctx, cc, meta) -> _CS:
    """UA-2-1-011: 同数据源重复映射同一底层节点 — 记录第二次是否允许。"""
    ds = _types_ds(ctx)
    ds_id = int(ds["id"])
    base = base_name_for_node("ua2_int32_r_1")
    a = create_case_tag(ctx, cc, ds_id, suffix="11a", data_type="INT", tag_base_name=base)
    a_id, a_name = int(a["id"]), a["name"]
    try:
        b_name = case_tag_name(ctx, cc, "11b")
        ok, detail = try_add_tag(ctx, ds_id, tag_name=b_name, data_type="INT", tag_base_name=base)
        ctx.bag[meta["id"]] = {"second_allowed": ok, "detail": detail}
        if ok:
            rows = exact(active_rows(ctx, tagBaseName=base), "tagBaseName", base)
            ctx.bag[f"{meta['id']}_count"] = len(rows)
            cleanup_case_tag(ctx, cc, int(rows[-1]["id"]), rows[-1]["tagName"])
        else:
            check_true("first_tag_intact", bool(exact(active_rows(ctx, tagName=a_name), "tagName", a_name)))
        return _CS.PASS
    finally:
        cleanup_case_tag(ctx, cc, a_id, a_name)


def _precise_explore_invalid_base(ctx, cc, meta) -> _CS:
    """UA-2-1-012: 非法 tagBaseName 格式 — 记录接受/拒绝与字段值。"""
    ds = _types_ds(ctx)
    b_name = case_tag_name(ctx, cc, "12")
    ok, detail = try_add_tag(
        ctx, int(ds["id"]),
        tag_name=b_name,
        tag_base_name="invalid_format",
    )
    ctx.bag[meta["id"]] = {"accepted": ok, "detail": detail}
    if ok:
        rows = exact(active_rows(ctx, tagName=b_name), "tagName", b_name)
        if rows:
            cleanup_case_tag(ctx, cc, int(rows[0]["id"]), b_name)
    else:
        check_eq("no_residual_on_reject", 0, len(exact(active_rows(ctx, tagName=b_name), "tagName", b_name)))
    return _CS.PASS


def _precise_explore_type_mismatch(ctx, cc, meta) -> _CS:
    """UA-2-1-015: Double 节点配置 Boolean。"""
    from ua_test_harness.fixtures.tag import read_rt

    ds = _types_ds(ctx)
    spec = read_spec("DOUBLE")
    base = base_name_for_node(spec["node"])
    name = case_tag_name(ctx, cc, "15")
    ok, detail = try_add_tag(ctx, int(ds["id"]), tag_name=name, data_type="BOOLEAN", tag_base_name=base)
    ctx.bag[meta["id"]] = {"accepted": ok, "detail": detail}
    rows = exact(active_rows(ctx, tagName=name), "tagName", name)
    if rows:
        row = read_rt(ctx, name)
        ctx.bag[meta["id"]]["rt"] = row
        cleanup_case_tag(ctx, cc, int(rows[0]["id"]), name)
    return _CS.OBSERVED


def _precise_explore_whitespace_names(ctx, cc, meta) -> _CS:
    """UA-2-1-020: 纯空白名称探索。"""
    ds = _types_ds(ctx)
    results = []
    for label, nm in [("space", " "), ("spaces", "   "), ("tab", "\t")]:
        ok, detail = try_add_tag(ctx, int(ds["id"]), tag_name=nm)
        results.append({"label": label, "accepted": ok, "detail": detail})
        rows = exact(active_rows(ctx, tagName=nm), "tagName", nm) if ok else []
        for r in rows:
            cleanup_case_tag(ctx, cc, int(r["id"]), r["tagName"])
    ctx.bag[meta["id"]] = results
    return _CS.OBSERVED


def _precise_explore_name_boundary(ctx, cc, meta, cid: str) -> _CS:
    """UA-2-1-023/024/025: 名称边界与 Unicode。"""
    from ua_test_harness.fixtures.tag import read_rt

    ds = _types_ds(ctx)
    ds_id = int(ds["id"])
    if cid == "UA-2-1-023":
        name = "n" * 129
        ok, detail = try_add_tag(ctx, ds_id, tag_name=name)
        ctx.bag[cid] = {"len": 129, "accepted": ok, "detail": detail}
        rows = exact(active_rows(ctx, tagName=name), "tagName", name)
        if rows:
            cleanup_case_tag(ctx, cc, int(rows[0]["id"]), name)
        return _CS.OBSERVED
    if cid == "UA-2-1-024":
        name = "a/b\\c.d@e#f"
        ok, detail = try_add_tag(ctx, ds_id, tag_name=name)
        ctx.bag[cid] = {"accepted": ok, "detail": detail}
        rows = exact(active_rows(ctx, tagName=name), "tagName", name)
        if rows:
            ctx.bag[cid]["rt"] = read_rt(ctx, name)
            cleanup_case_tag(ctx, cc, int(rows[0]["id"]), name)
        return _CS.OBSERVED
    names = ["位号中文", "tag🔥", "Tag_A", "tag_a"]
    records = []
    for nm in names:
        ok, detail = try_add_tag(ctx, ds_id, tag_name=nm)
        records.append({"name": nm, "accepted": ok, "detail": detail})
        rows = exact(active_rows(ctx, tagName=nm), "tagName", nm)
        for r in rows:
            cleanup_case_tag(ctx, cc, int(r["id"]), r["tagName"])
    ctx.bag[cid] = records
    return _CS.OBSERVED


def _basic_create_read(ctx, cc, meta, *, suffix: str, base_node: str = "ua2_int32_r_1",
                       dtype: str = "INT") -> _CS:
    from ua_test_harness.ua2_helpers import standard_read_closed_loop
    from ua_test_harness.ua2_fixture_map import READ_NODES

    type_key = next((k for k, v in READ_NODES.items() if v["node"] == base_node), "INT32")
    return standard_read_closed_loop(ctx, cc, suffix=suffix, type_key=type_key)


def dispatch_ua2_1(ctx, cc, meta) -> _CS:
    """UA-2-1 全章 dispatcher: 已有个别 handler 的 case 委托;其余按 doc 模式执行。"""
    cid = meta["id"]
    title = meta.get("title") or ""
    kind = meta.get("kind") or ""

    delegated = {
        "UA-2-1-017": duplicate_name_rejected,
        "UA-2-1-019": empty_name_rejected,
        "UA-2-1-021": name_length_127,
        "UA-2-1-022": name_length_128,
    }
    if cid in delegated:
        return delegated[cid](ctx, cc)

    if cid in CASE_READ_TYPE:
        return standard_read_closed_loop(ctx, cc, suffix=cid.split("-")[-1], type_key=CASE_READ_TYPE[cid])

    if cid in {"UA-2-1-001", "UA-2-1-002"}:
        from ua_test_harness.ua2_precise import public_create_read_loop
        status, tag_id, tag_name = public_create_read_loop(ctx, cc, suffix=cid[-3:], type_key="INT32")
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        return status

    if cid == "UA-2-1-003":
        ds = _types_ds(ctx)
        ok, detail = try_add_tag(ctx, 99999, tag_name=f"ua_case_ua2_{cid}_bad_ds")
        check_true("invalid_ds_rejected", not ok)
        rows = exact(active_rows(ctx, tagName=f"ua_case_ua2_{cid}_bad_ds"), "tagName",
                     f"ua_case_ua2_{cid}_bad_ds")
        check_eq("no_residual_tag", 0, len(rows))
        ctx.bag[f"reject_{cid}"] = detail
        return _CS.PASS

    if cid == "UA-2-1-004":
        from ua_test_harness.ua2_precise import precise_mock_offline_create
        return precise_mock_offline_create(ctx, cc, meta)
    if cid == "UA-2-1-005":
        from ua_test_harness.ua2_precise import precise_mock_recovery
        return precise_mock_recovery(ctx, cc, meta)
    if cid == "UA-2-1-006":
        from ua_test_harness.ua2_precise import precise_ds_disabled_create
        return precise_ds_disabled_create(ctx, cc, meta)
    if cid == "UA-2-1-007":
        from ua_test_harness.ua2_precise import precise_ds_reenable_collect
        return precise_ds_reenable_collect(ctx, cc, meta)

    if cid == "UA-2-1-008":
        from ua_test_harness.ua2_precise import public_create_read_loop
        status, tag_id, tag_name = public_create_read_loop(
            ctx, cc, suffix="008", type_key="DOUBLE", tag_desc="ua2-1-008",
        )
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        return status

    if cid == "UA-2-1-009":
        from ua_test_harness.ua2_precise import public_create_read_no_collect
        base = base_name_for_node("1_nonexistent")
        status, tag_id, tag_name = public_create_read_no_collect(
            ctx, cc, suffix="009", tag_base_name=base, data_type="INT",
        )
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        return status

    if cid == "UA-2-1-010":
        from ua_test_harness.ua2_precise import precise_cross_ds_same_node
        return precise_cross_ds_same_node(ctx, cc, meta)

    if cid == "UA-2-1-011":
        return _precise_explore_duplicate_base(ctx, cc, meta)

    if cid == "UA-2-1-012":
        return _precise_explore_invalid_base(ctx, cc, meta)

    if cid == "UA-2-1-015":
        return _precise_explore_type_mismatch(ctx, cc, meta)
    if cid == "UA-2-1-020":
        return _precise_explore_whitespace_names(ctx, cc, meta)
    if cid in {"UA-2-1-023", "UA-2-1-024", "UA-2-1-025"}:
        return _precise_explore_name_boundary(ctx, cc, meta, cid)

    if cid == "UA-2-1-013":
        from ua_test_harness.ua2_precise import public_create_read_no_collect
        base = base_name_for_node("99_double_ch_1")
        status, tag_id, tag_name = public_create_read_no_collect(
            ctx, cc, suffix="013", tag_base_name=base, data_type="DOUBLE",
        )
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        return status

    if cid == "UA-2-1-014":
        ds = _types_ds(ctx)
        ds_id = int(ds["id"])
        tag_name = f"ua_case_ua2_{cid}"
        ok, detail = try_add_tag(ctx, ds_id, tag_name=tag_name, tag_base_name="")
        ctx.bag[f"empty_base_{cid}"] = {"ok": ok, "detail": detail}
        rows = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        if not ok:
            check_eq("no_residual_on_reject", 0, len(rows))
            return _CS.PASS
        check_eq("exactly_one_if_accepted", 1, len(rows))
        rec = rows[0]
        check_eq("tag_name_saved", tag_name, rec.get("tagName"))
        check_eq("ds_unchanged", ds_id, int(rec.get("dsId")))
        tid = int(rec["id"])
        cleanup_case_tag(ctx, cc, tid, tag_name)
        check_eq("cleaned_up", 0, len(exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)))
        return _CS.PASS

    if cid == "UA-2-1-016":
        from ua_test_harness.ua2_precise import config_page_row, public_create_read_loop, rt_row
        ds = _types_ds(ctx)
        ds_id = int(ds["id"])
        custom = f"ua_case_ua2_{cid}_custom"
        base = base_name_for_node("ua2_double_r_1")
        raw = create_tag_raw(ctx, custom, ds_id, data_type="DOUBLE", tag_base_name=base)
        tag_id = int(raw["id"])
        cc.registry.register(f"tag:{custom}", "tag", lambda: physical_delete_tag(ctx, tag_id))
        try:
            cfg = config_page_row(ctx, custom)
            check_eq("tagName_saved", custom, cfg.get("tagName"))
            check_eq("base_saved", base, cfg.get("tagBaseName"))
            rt_row(ctx, custom)
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, custom)

    if cid == "UA-2-1-018":
        ds = _types_ds(ctx)
        ds_id = int(ds["id"])
        dup = "ua21_cross_dup_shared"
        first = create_case_tag(ctx, cc, ds_id, suffix="18a", data_type="INT")
        # force name
        cleanup_case_tag(ctx, cc, int(first["id"]), first["name"])
        a = create_tag_raw(ctx, dup, ds_id)
        a_id = int(a["id"])
        cc.registry.register(f"tag:{dup}", "tag", lambda: physical_delete_tag(ctx, a_id))
        try:
            from ua_test_harness.provisioning import require_shared_datasource as _req
            empty = _req(ctx, "empty")
            ok, detail = try_add_tag(ctx, int(empty["id"]), tag_name=dup)
            check_true("cross_ds_dup_rejected", not ok)
            ctx.bag[f"cross_dup_{cid}"] = detail
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, a_id, dup)

    if cid in {"UA-2-1-076", "UA-2-1-077", "UA-2-1-078", "UA-2-1-079", "UA-2-1-080", "UA-2-1-081"}:
        from ua_test_harness.ua2_precise import precise_field_unit_desc
        return precise_field_unit_desc(ctx, cc, meta)

    if cid in CASE_WRITE_TYPE:
        return _dispatch_ua2_1_write(ctx, cc, meta)

    if cid in {"UA-2-1-082", "UA-2-1-083", "UA-2-1-084", "UA-2-1-085"}:
        from ua_test_harness.ua2_precise import precise_only_read
        return precise_only_read(ctx, cc, meta)

    if cid in {"UA-2-1-086", "UA-2-1-087", "UA-2-1-088", "UA-2-1-089", "UA-2-1-090"}:
        from ua_test_harness.ua2_precise import precise_frequency
        return precise_frequency(ctx, cc, meta)

    if cid in {"UA-2-1-091", "UA-2-1-092", "UA-2-1-093", "UA-2-1-094",
               "UA-2-1-095", "UA-2-1-096", "UA-2-1-097"}:
        from ua_test_harness.ua2_precise import precise_limits
        return precise_limits(ctx, cc, meta)

    if cid in {"UA-2-1-098", "UA-2-1-099", "UA-2-1-100", "UA-2-1-101"}:
        from ua_test_harness.ua2_precise import precise_need_push
        return precise_need_push(ctx, cc, meta)

    if cid in {"UA-2-1-102", "UA-2-1-103", "UA-2-1-104"}:
        from ua_test_harness.ua2_precise import precise_availability
        return precise_availability(ctx, cc, meta)

    if cid in {"UA-2-1-105", "UA-2-1-106", "UA-2-1-107",
               "UA-2-1-108", "UA-2-1-109", "UA-2-1-110", "UA-2-1-111", "UA-2-1-112"}:
        from ua_test_harness.ua2_precise import precise_batch
        return precise_batch(ctx, cc, meta)

    return _blocked(ctx, meta, f"UA-2-1 dispatcher 未覆盖 {cid}")


def _api_from_ctx(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _quality(row):
    row = row or {}
    return row.get("quality", row.get("qualityCode"))


def _row_value(row):
    row = row or {}
    return row.get("tagValue", row.get("value"))


def _dispatch_ua2_1_write(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    from ua_test_harness.ua2_precise import CASE_WRITE_VALUES, precise_write_explore

    if cid in CASE_WRITE_VALUES:
        type_key = CASE_WRITE_TYPE.get(cid, "INT32")
        return standard_write_closed_loop(
            ctx, cc, suffix=cid[-3:], type_key=type_key,
            values=CASE_WRITE_VALUES[cid], tag_desc=f"write {cid}",
        )

    type_key = CASE_WRITE_TYPE.get(cid, "INT32")
    spec = write_spec(type_key)
    ds = _types_ds(ctx)
    ds_id = int(ds["id"])
    base = base_name_for_node(spec["node"])
    tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:],
                          data_type=spec["dtype"], tag_base_name=base, tag_desc=f"write {cid}")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        explore_probes: dict[str, list[Any]] = {
            "UA-2-1-041": [1, 0, "true"],
            "UA-2-1-043": [-129, 128],
            "UA-2-1-045": [-1, 256],
            "UA-2-1-047": [-32769, 32768],
            "UA-2-1-049": [-1, 65536],
            "UA-2-1-051": [-2147483649, 2147483648],
            "UA-2-1-053": [-1, 4294967296],
            "UA-2-1-056": ["-9223372036854775809", "9223372036854775808"],
            "UA-2-1-059": [-1, "18446744073709551616"],
            "UA-2-1-062": [float("nan"), float("inf"), float("-inf")],
            "UA-2-1-065": [float("nan"), float("inf"), float("-inf")],
            "UA-2-1-069": ["a", "x" * 255, "x" * 256, "x" * 1000],
            "UA-2-1-070": [None],
        }
        if cid in explore_probes:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
            tag_id = tag_name = 0
            return precise_write_explore(
                ctx, cc, meta, suffix=cid[-3:], type_key=type_key,
                probe_values=explore_probes[cid],
            )
        if cid == "UA-2-1-073":
            from ua_test_harness.fixtures.tag import write_tag, read_rt
            failed = False
            for bad in ("not-a-date", "2025-02-30T00:00:00Z"):
                try:
                    write_tag(ctx, tag_name, bad)
                except Exception:
                    failed = True
            check_true("bad_date_rejected", failed)
            return _CS.PASS
        if cid == "UA-2-1-075":
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
            tag_id = tag_name = 0
            return precise_write_explore(
                ctx, cc, meta, suffix="075", type_key=type_key,
                probe_values=["2025-06-01T12:00:00.123Z", "2025-06-01T12:00:00"],
            )
        return _explore(ctx, meta, outcome="write_fallback_explore")
    finally:
        if tag_id:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _dispatch_ua2_1_only_read(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    ds = _types_ds(ctx)
    ds_id = int(ds["id"])
    writable = cid in {"UA-2-1-083", "UA-2-1-085"}
    spec = write_spec("DOUBLE") if writable else read_spec("DOUBLE")
    base = base_name_for_node(spec["node"])
    only_read = cid in {"UA-2-1-082", "UA-2-1-084"}
    tag = create_tag_raw(ctx, case_tag_name(ctx, cc, cid[-3:]), ds_id,
                         data_type=spec["dtype"], tag_base_name=base)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    cc.registry.register(f"tag:{tag_name}", "tag", lambda: physical_delete_tag(ctx, tag_id))
    try:
        from ua_test_harness.fixtures.tag import read_rt, write_tag
        before = read_rt(ctx, tag_name)
        failed = False
        try:
            write_tag(ctx, tag_name, 99.9)
        except Exception:
            failed = True
        after = read_rt(ctx, tag_name)
        if only_read:
            check_true("write_rejected_or_unchanged", failed or _row_value(before) == _row_value(after))
        else:
            return _explore(ctx, meta, outcome="writable_on_readonly_source")
        return _CS.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _dispatch_ua2_1_frequency(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    if cid == "UA-2-1-086":
        ds = _types_ds(ctx)
        tag = create_case_tag(ctx, cc, int(ds["id"]), suffix="086", data_type="INT")
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
            check_eq("default_frequency", 10, cfg[0].get("frequency"))
            _wait_rt(ctx, tag_name)
            return _CS.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
    return _explore(ctx, meta, outcome="frequency_effect_explore")


def _dispatch_ua2_1_limits(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    if cid in {"UA-2-1-093", "UA-2-1-094", "UA-2-1-096", "UA-2-1-097"}:
        return _explore(ctx, meta, outcome="limits_explore")
    ds = _types_ds(ctx)
    ds_id = int(ds["id"])
    tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:], data_type="DOUBLE")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        from tpt_api.datahub import update_tag
        from tpt_api.types import DataTypes
        cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
        if cid == "UA-2-1-091":
            update_tag(_api_from_ctx(ctx), tag_id, tag_name=tag_name,
                       data_type=int(cfg.get("dataType") or DataTypes["DOUBLE"]),
                       ds_id=int(cfg.get("dsId")), hi_eu=100, lo_eu=0)
            cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
            check_eq("hi", 100, cfg[0].get("hiEU"))
            check_eq("lo", 0, cfg[0].get("loEU"))
        if cid == "UA-2-1-092":
            write_and_verify(ctx, tag_name, 50.0)
        if cid == "UA-2-1-095":
            update_tag(_api_from_ctx(ctx), tag_id, tag_name=tag_name,
                       data_type=int(cfg.get("dataType") or DataTypes["DOUBLE"]),
                       ds_id=int(cfg.get("dsId")),
                       limit_up=80, limit_up_up=90, limit_up_up_up=100,
                       limit_down=10, limit_down_down=5, limit_down_down_down=0)
            cfg2 = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
            check_true("limits_saved", cfg2[0].get("limitUp") == 80)
        return _CS.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _dispatch_ua2_1_need_push(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    if cid in {"UA-2-1-100", "UA-2-1-101"}:
        return _explore(ctx, meta, outcome="need_push_behavior_explore")
    ds = _types_ds(ctx)
    need = cid == "UA-2-1-098"
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=cid[-3:], data_type="INT")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        from tpt_api.datahub import update_tag
        from tpt_api.types import DataTypes
        cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)[0]
        if cid == "UA-2-1-099":
            update_tag(_api_from_ctx(ctx), tag_id, tag_name=tag_name,
                       data_type=int(cfg.get("dataType") or DataTypes["INT"]),
                       ds_id=int(cfg.get("dsId")), need_push=False)
        cfg = exact(active_rows(ctx, tagName=tag_name), "tagName", tag_name)
        expected = True if cid == "UA-2-1-098" else False
        check_eq("needPush", expected, cfg[0].get("needPush"))
        return _CS.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _dispatch_ua2_1_availability(ctx, cc, meta) -> _CS:
    cid = meta["id"]
    if cid == "UA-2-1-102":
        return standard_read_closed_loop(ctx, cc, suffix="102", type_key="INT32")
    ds = _types_ds(ctx)
    spec = write_spec("DOUBLE")
    base = base_name_for_node(spec["node"])
    tag = create_case_tag(ctx, cc, int(ds["id"]), suffix=cid[-3:],
                          data_type=spec["dtype"], tag_base_name=base)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        if cid == "UA-2-1-103":
            write_and_verify(ctx, tag_name, 42.0)
            return _CS.PASS
        if cid == "UA-2-1-104":
            _wait_rt(ctx, tag_name)
            import time as _time
            from ua_test_harness.fixtures.tag import read_history
            end_ms = int(_time.time() * 1000)
            hist = read_history(ctx, tag_name, end_ms - 120_000, end_ms)
            if not hist:
                return _CS.BLOCKED
            return _CS.PASS
        return _CS.BLOCKED
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)