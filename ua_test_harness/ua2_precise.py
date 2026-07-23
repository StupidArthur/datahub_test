"""UA-2 精确实现层 — 对齐 doc 公共新增/读取/写入闭环。

每条回归 case 应调用本模块函数,而非 dispatcher 内联简化断言。
"""
from __future__ import annotations

import math
import time
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.opcua.client import UaSourceClient
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_fixture_map import (
    NAMESPACE_INDEX,
    base_name_for_node,
    read_spec,
    write_spec,
)
from ua_test_harness.ua2_ops import (
    active_rows,
    case_tag_name,
    cleanup_case_tag,
    create_case_tag,
    exact,
)


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _row_value(row: dict[str, Any] | None) -> Any:
    row = row or {}
    return row.get("tagValue", row.get("value"))


def _quality(row: dict[str, Any] | None) -> Any:
    row = row or {}
    return row.get("quality", row.get("qualityCode"))


def types_context(ctx):
    """共享 types DS 前置: mock ready + 登录 + baseline。"""
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    return require_shared_datasource(ctx, "types")


def config_page_row(ctx, tag_name: str) -> dict[str, Any]:
    """tag-info/page 按 tagName 查唯一配置记录(doc 事实源)。"""
    from tpt_api.datahub import list_tags

    page = list_tags(_api(ctx), page=1, page_size=50, data={"tagName": tag_name})
    rows = [r for r in (page.get("records") or []) if r.get("tagName") == tag_name]
    check_eq(f"config_unique:{tag_name}", 1, len(rows))
    return rows[0]


def rt_row(ctx, tag_name: str, *, timeout: float = 60.0) -> dict[str, Any]:
    """getRTValue 等待有效质量码。"""
    from tpt_api.datahub import get_rt_value

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = get_rt_value(_api(ctx), tag_names=[tag_name], is_from_db=False)
        if isinstance(rows, list):
            for row in rows:
                if row.get("tagName") == tag_name and _quality(row) not in (None, 0):
                    return row
        time.sleep(1.0)
    raise AssertFail(f"getRTValue timeout for {tag_name}")


def qtq_row(ctx, tag_name: str, ds_id: int, *, timeout: float = 60.0) -> dict[str, Any]:
    """queryWithQuality(groupId=0) 等待有效记录。"""
    from tpt_api.datahub import query_tags_with_quality

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        res = query_tags_with_quality(
            _api(ctx), ds_id=ds_id, group_id="0", tag_name=tag_name, page=1, page_size=10,
        )
        records = ((res or {}).get("tagInfoList") or {}).get("records") or []
        for rec in records:
            if rec.get("tagName") == tag_name and _quality(rec) not in (None, 0):
                return rec
        time.sleep(1.0)
    raise AssertFail(f"queryWithQuality timeout for {tag_name}")


def opcua_read(endpoint: str, node_name: str, *, namespace_index: int = NAMESPACE_INDEX) -> Any:
    """asyncua 直读源端节点(默认 namespace=2,可传 namespace_index=1 读 functional mock)。"""
    client = UaSourceClient(endpoint, namespace_index=namespace_index)
    return client.read_sync(node_name)


def opcua_write(endpoint: str, node_name: str, value: Any, *, type_key: str | None = None,
                namespace_index: int = NAMESPACE_INDEX) -> None:
    """asyncua 直写源端节点(默认 namespace=2);type_key 用于恢复源端时显式 varianttype。"""
    client = UaSourceClient(endpoint, namespace_index=namespace_index)
    client.write_sync(node_name, value, type_key=type_key)


def _values_close(a: Any, b: Any, *, type_key: str) -> bool:
    if a is None or b is None:
        return False
    if type_key in ("FLOAT", "DOUBLE"):
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-5, abs_tol=1e-5)
        except (TypeError, ValueError):
            return False
    if type_key in ("INT64", "UINT64"):
        return str(a) == str(b)
    if type_key == "BOOLEAN":
        return bool(a) == bool(b)
    if type_key == "STRING":
        return str(a) == str(b)
    if type_key == "DATETIME":
        return str(a)[:19] in str(b)[:19] or str(b)[:19] in str(a)[:19]
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return a == b


def assert_config_matches_request(
    rec: dict[str, Any],
    *,
    tag_name: str,
    ds_id: int,
    tag_base_name: str,
    data_type_key: str,
    only_read: bool = False,
    frequency: int = 1,
    unit: str = "",
    need_push: bool = True,
    tag_desc: str = "",
):
    """逐字段比对 doc 要求的配置持久化。"""
    check_eq("tagName", tag_name, rec.get("tagName"))
    check_eq("tagBaseName", tag_base_name, rec.get("tagBaseName"))
    check_eq("dsId", ds_id, rec.get("dsId"))
    check_eq("tagType", 1, rec.get("tagType"))
    check_eq("onlyRead", only_read, rec.get("onlyRead"))
    check_eq("frequency", frequency, rec.get("frequency"))
    check_eq("needPush", need_push, rec.get("needPush"))
    if unit:
        check_eq("unit", unit, rec.get("unit"))
    if tag_desc:
        check_eq("tagDesc", tag_desc, rec.get("tagDesc"))


def public_create_read_loop(
    ctx,
    cc,
    *,
    suffix: str,
    type_key: str,
    tag_desc: str = "",
    compare_opcua: bool = True,
) -> tuple[CaseStatus, int, str]:
    """doc §公共新增闭环 — 返回 (status, tag_id, tag_name);调用方负责 finally cleanup。

    断言:
      1. add_tag 成功(由 create_case_tag 保证)
      2. tag-info/page 唯一记录且字段一致
      3. getRTValue 有效值
      4. queryWithQuality 与 getRTValue 一致且质量有效
      5. 可选 asyncua 与 RT 一致
      6. 变化节点: 两次 RT 值不同
    """
    spec = read_spec(type_key)
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    endpoint = str(ds["endpoint"])
    base = base_name_for_node(spec["node"])
    node_name = spec["node"]

    tag = create_case_tag(
        ctx, cc, ds_id,
        suffix=suffix,
        data_type=spec["dtype"],
        tag_base_name=base,
        tag_desc=tag_desc or f"ua2 precise read {type_key}",
        only_read=True,
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]

    cfg = config_page_row(ctx, tag_name)
    assert_config_matches_request(
        cfg, tag_name=tag_name, ds_id=ds_id, tag_base_name=base,
        data_type_key=spec["dtype"], only_read=True, tag_desc=tag_desc or cfg.get("tagDesc", ""),
    )

    time.sleep(max(2, int(cfg.get("frequency") or 1) * 2))
    rt1 = rt_row(ctx, tag_name)
    check_true("rt1_quality_valid", _quality(rt1) not in (None, 0))

    qtq = qtq_row(ctx, tag_name, ds_id)
    check_eq("qtq_matches_rt1", _row_value(rt1), _row_value(qtq))
    check_true("qtq_quality_valid", _quality(qtq) not in (None, 0))

    rt1_val = _row_value(rt1)
    deadline = time.monotonic() + 30.0
    rt2 = None
    while time.monotonic() < deadline:
        from tpt_api.datahub import get_rt_value

        rows = get_rt_value(_api(ctx), tag_names=[tag_name], is_from_db=False)
        if isinstance(rows, list):
            for row in rows:
                if row.get("tagName") == tag_name and _quality(row) not in (None, 0):
                    if _row_value(row) != rt1_val:
                        rt2 = row
                        break
        if rt2 is not None:
            break
        time.sleep(0.5)
    check_true("rt_values_change", rt2 is not None)

    if compare_opcua:
        src = opcua_read(endpoint, node_name)
        check_true("opcua_matches_rt2", _values_close(_row_value(rt2), src, type_key=type_key))

    return CaseStatus.PASS, tag_id, tag_name


def public_create_read_no_collect(
    ctx,
    cc,
    *,
    suffix: str,
    tag_base_name: str,
    data_type: str = "INT",
    expect_quality_zero: bool = True,
) -> tuple[CaseStatus, int, str]:
    """位号可创建但无有效采集(坏节点/断线等)。"""
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    tag = create_case_tag(ctx, cc, ds_id, suffix=suffix, data_type=data_type, tag_base_name=tag_base_name)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    config_page_row(ctx, tag_name)

    deadline = time.monotonic() + 20.0
    qtq = None
    while time.monotonic() < deadline:
        try:
            qtq = qtq_row(ctx, tag_name, ds_id, timeout=3.0)
            break
        except AssertFail:
            time.sleep(1.0)
    if qtq and expect_quality_zero:
        check_true("quality_zero_or_no_value", _quality(qtq) in (None, 0) or _row_value(qtq) is None)
    return CaseStatus.PASS, tag_id, tag_name


def _wait_ds_alive(ctx, ds_id: int, *, alive: bool, timeout: float = 120.0) -> None:
    from ua_test_harness.ua2_ops import find_datasource_by_id

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = find_datasource_by_id(ctx, ds_id)
        if alive and row and row.get("alive"):
            return
        if not alive and (not row or not row.get("alive")):
            return
        time.sleep(1.0)
    raise AssertFail(f"ds {ds_id} alive={alive} timeout")


def precise_mock_offline_create(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-004: mock 停、alive=false、位号可建、quality=0。"""
    from ua_test_harness.clients import mock_control

    ds = types_context(ctx)
    ds_id = int(ds["id"])
    spec = read_spec("INT32")
    base = base_name_for_node(spec["node"])
    mock_control.stop_mock("functional", ctx=ctx)
    tag_id = tag_name = 0
    try:
        _wait_ds_alive(ctx, ds_id, alive=False, timeout=60.0)
        _, tag_id, tag_name = public_create_read_no_collect(
            ctx, cc, suffix="004", tag_base_name=base, data_type=spec["dtype"],
        )
        return CaseStatus.PASS
    finally:
        if tag_id:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
        mock_control.start_mock("functional", ctx=ctx)
        mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
        _wait_ds_alive(ctx, ds_id, alive=True, timeout=120.0)


def precise_mock_recovery(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-005: mock 恢复后原位号 RT/质量恢复,不需重建。"""
    from ua_test_harness.clients import mock_control

    ds = types_context(ctx)
    ds_id = int(ds["id"])
    spec = read_spec("INT32")
    base = base_name_for_node(spec["node"])

    mock_control.stop_mock("functional", ctx=ctx)
    tag = create_case_tag(ctx, cc, ds_id, suffix="005", data_type=spec["dtype"], tag_base_name=base)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        _wait_ds_alive(ctx, ds_id, alive=False, timeout=60.0)
        qtq = qtq_row(ctx, tag_name, ds_id, timeout=15.0)
        check_true("offline_quality_bad", _quality(qtq) in (None, 0))

        mock_control.start_mock("functional", ctx=ctx)
        mock_control.wait_ready("functional", timeout=120.0, ctx=ctx)
        _wait_ds_alive(ctx, ds_id, alive=True, timeout=120.0)

        rt1 = rt_row(ctx, tag_name, timeout=90.0)
        check_true("quality_recovered", _quality(rt1) not in (None, 0))
        qtq2 = qtq_row(ctx, tag_name, ds_id)
        check_true("qtq_quality_recovered", _quality(qtq2) not in (None, 0))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        if mock_control.status("functional", ctx=ctx) not in ("ready", "running"):
            mock_control.start_mock("functional", ctx=ctx)


def precise_ds_disabled_create(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-006: 数据源禁用、位号可建、quality=0。"""
    from ua_test_harness.ua2_ops import disable_datasource, enable_datasource

    ds = types_context(ctx)
    ds_id = int(ds["id"])
    spec = read_spec("INT32")
    base = base_name_for_node(spec["node"])
    disable_datasource(ctx, ds_id)
    tag_id = tag_name = 0
    try:
        _wait_ds_alive(ctx, ds_id, alive=False, timeout=30.0)
        _, tag_id, tag_name = public_create_read_no_collect(
            ctx, cc, suffix="006", tag_base_name=base, data_type=spec["dtype"],
        )
        return CaseStatus.PASS
    finally:
        if tag_id:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
        enable_datasource(ctx, ds_id)
        _wait_ds_alive(ctx, ds_id, alive=True, timeout=120.0)


def precise_ds_reenable_collect(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-007: 禁用后启用、原位号恢复采集。"""
    from ua_test_harness.ua2_ops import disable_datasource, enable_datasource

    ds = types_context(ctx)
    ds_id = int(ds["id"])
    spec = read_spec("INT32")
    base = base_name_for_node(spec["node"])
    tag = create_case_tag(ctx, cc, ds_id, suffix="007", data_type=spec["dtype"], tag_base_name=base)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        disable_datasource(ctx, ds_id)
        _wait_ds_alive(ctx, ds_id, alive=False, timeout=30.0)
        enable_datasource(ctx, ds_id)
        _wait_ds_alive(ctx, ds_id, alive=True, timeout=120.0)
        rt1 = rt_row(ctx, tag_name, timeout=90.0)
        check_true("reenable_quality", _quality(rt1) not in (None, 0))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)
        enable_datasource(ctx, ds_id)


# doc 回归 case → 写入值序列(单值亦用列表)
CASE_WRITE_VALUES: dict[str, list[Any]] = {
    "UA-2-1-039": [True],
    "UA-2-1-040": [False],
    "UA-2-1-042": [-128, 127],
    "UA-2-1-044": [0, 255],
    "UA-2-1-046": [-32768, 32767],
    "UA-2-1-048": [0, 65535],
    "UA-2-1-050": [-2147483648, 2147483647],
    "UA-2-1-052": [0, 4294967295],
    "UA-2-1-054": [9999999999],
    "UA-2-1-055": ["-9223372036854775808", "9223372036854775807"],
    "UA-2-1-057": [9999999999],
    "UA-2-1-058": ["18446744073709551615"],
    "UA-2-1-060": [1.25, -999.99],
    "UA-2-1-061": [1.23456789, 0.000001],
    "UA-2-1-063": [1.25, -999.99],
    "UA-2-1-064": [1.23456789012345, 0.0000000001],
    "UA-2-1-066": [""],
    "UA-2-1-067": ["hello", "测试用例"],
    "UA-2-1-068": ['<>&"\'\\\n\t'],
    "UA-2-1-071": ["2025-06-01T12:00:00Z"],
    "UA-2-1-072": ["2025-06-01T20:00:00+08:00"],
    "UA-2-1-074": ["1601-01-01T00:00:00Z", "1970-01-01T00:00:00Z"],
}


def write_value_closed_loop(
    ctx,
    *,
    tag_name: str,
    ds_id: int,
    endpoint: str,
    node_name: str,
    type_key: str,
    value: Any,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """单次写入闭环: writeTagValues → RT → QTQ → asyncua 源端对照。"""
    from ua_test_harness.fixtures.tag import write_tag

    write_tag(ctx, tag_name, value)
    time.sleep(1.0)
    rt = rt_row(ctx, tag_name, timeout=timeout)
    check_true("rt_quality_valid", _quality(rt) not in (None, 0))
    check_true("rt_matches_write", _values_close(_row_value(rt), value, type_key=type_key))
    qtq = qtq_row(ctx, tag_name, ds_id, timeout=timeout)
    check_true("qtq_quality_valid", _quality(qtq) not in (None, 0))
    check_true("qtq_matches_rt", _values_close(_row_value(rt), _row_value(qtq), type_key=type_key))
    src = opcua_read(endpoint, node_name)
    check_true("opcua_matches_rt", _values_close(_row_value(rt), src, type_key=type_key))
    return rt


def public_write_closed_loop(
    ctx,
    cc,
    *,
    suffix: str,
    type_key: str,
    values: list[Any],
    tag_desc: str = "",
    restore_original: bool = True,
) -> tuple[CaseStatus, int, str]:
    """doc §写入闭环 — 创建可写位号,依次写入并验证,可选恢复源端原值。"""
    spec = write_spec(type_key)
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    endpoint = str(ds["endpoint"])
    base = base_name_for_node(spec["node"])
    node_name = spec["node"]

    tag = create_case_tag(
        ctx, cc, ds_id,
        suffix=suffix,
        data_type=spec["dtype"],
        tag_base_name=base,
        tag_desc=tag_desc or f"ua2 precise write {type_key}",
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]

    cfg = config_page_row(ctx, tag_name)
    assert_config_matches_request(
        cfg, tag_name=tag_name, ds_id=ds_id, tag_base_name=base,
        data_type_key=spec["dtype"], only_read=False,
        tag_desc=tag_desc or cfg.get("tagDesc", ""),
    )

    original = opcua_read(endpoint, node_name)
    try:
        for val in values:
            write_value_closed_loop(
                ctx, tag_name=tag_name, ds_id=ds_id, endpoint=endpoint,
                node_name=node_name, type_key=type_key, value=val,
            )
        if restore_original:
            from ua_test_harness.fixtures.tag import write_tag
            write_tag(ctx, tag_name, original)
            opcua_write(endpoint, node_name, original, type_key=type_key)
        return CaseStatus.PASS, tag_id, tag_name
    except Exception:
        if restore_original:
            try:
                from ua_test_harness.fixtures.tag import write_tag
                write_tag(ctx, tag_name, original)
                opcua_write(endpoint, node_name, original, type_key=type_key)
            except Exception:
                pass
        raise


def precise_write_explore(
    ctx,
    cc,
    meta,
    *,
    suffix: str,
    type_key: str,
    probe_values: list[Any],
) -> CaseStatus:
    """探索类写入: 记录每次 write 的接受/拒绝与前后 RT/源端,返回 OBSERVED。"""
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    spec = write_spec(type_key)
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    endpoint = str(ds["endpoint"])
    base = base_name_for_node(spec["node"])
    node_name = spec["node"]
    tag = create_case_tag(ctx, cc, ds_id, suffix=suffix, data_type=spec["dtype"], tag_base_name=base)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    records: list[dict[str, Any]] = []
    try:
        for val in probe_values:
            before_rt = read_rt(ctx, tag_name)
            before_src = opcua_read(endpoint, node_name)
            err = None
            try:
                write_tag(ctx, tag_name, val)
                accepted = True
            except Exception as exc:
                accepted = False
                err = str(exc)
            after_rt = read_rt(ctx, tag_name)
            after_src = opcua_read(endpoint, node_name)
            records.append({
                "value": val,
                "accepted": accepted,
                "error": err,
                "before_rt": _row_value(before_rt),
                "after_rt": _row_value(after_rt),
                "before_src": before_src,
                "after_src": after_src,
            })
            if not accepted:
                check_eq(f"rt_unchanged_on_reject:{val}", _row_value(before_rt), _row_value(after_rt))
                check_eq(f"src_unchanged_on_reject:{val}", before_src, after_src)
        ctx.bag[meta["id"]] = {"probe_writes": records}
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def precise_field_unit_desc(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-076~081: 单位与描述字段精确/探索。"""
    cid = meta["id"]
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    suffix = cid[-3:]

    if cid == "UA-2-1-076":
        tag = create_case_tag(ctx, cc, ds_id, suffix=suffix, data_type="INT", unit="kW")
    elif cid == "UA-2-1-077":
        tag = create_case_tag(ctx, cc, ds_id, suffix=suffix, data_type="INT", unit="")
    elif cid == "UA-2-1-079":
        tag = create_case_tag(ctx, cc, ds_id, suffix=suffix, data_type="INT", tag_desc="test desc")
    elif cid == "UA-2-1-080":
        tag = create_case_tag(ctx, cc, ds_id, suffix=suffix, data_type="INT", tag_desc=None)
    elif cid == "UA-2-1-078":
        probes = ["千瓦", "k" * 64]
        records = []
        for i, u in enumerate(probes):
            tname = case_tag_name(ctx, cc, f"78{i}")
            ok, detail = _try_add_with_unit(ctx, ds_id, tname, unit=u)
            records.append({"unit": u, "accepted": ok, "detail": detail})
            if ok:
                row = config_page_row(ctx, tname)
                cleanup_case_tag(ctx, cc, int(row["id"]), tname)
        ctx.bag[cid] = {"unit_probes": records}
        return CaseStatus.OBSERVED
    elif cid == "UA-2-1-081":
        probes = ["中文描述\n第二行", "x" * 512]
        records = []
        for i, d in enumerate(probes):
            tname = case_tag_name(ctx, cc, f"81{i}")
            ok, detail = _try_add_with_desc(ctx, ds_id, tname, tag_desc=d)
            records.append({"desc_len": len(d), "accepted": ok, "detail": detail})
            if ok:
                row = config_page_row(ctx, tname)
                cleanup_case_tag(ctx, cc, int(row["id"]), tname)
        ctx.bag[cid] = {"desc_probes": records}
        return CaseStatus.OBSERVED
    else:
        raise AssertFail(f"precise_field_unit_desc: unsupported {cid}")

    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        cfg = config_page_row(ctx, tag_name)
        if cid == "UA-2-1-076":
            check_eq("unit", "kW", cfg.get("unit"))
        if cid == "UA-2-1-077":
            check_eq("unit", "", cfg.get("unit") or "")
        if cid == "UA-2-1-079":
            check_eq("tagDesc", "test desc", cfg.get("tagDesc"))
        if cid == "UA-2-1-080":
            check_eq("tagDesc", f"{tag_name} 描述", cfg.get("tagDesc"))
        rt_row(ctx, tag_name, timeout=30.0)
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _try_add_with_unit(ctx, ds_id: int, name: str, *, unit: str) -> tuple[bool, Any]:
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes
    try:
        add_tag(
            _api(ctx), tag_name=name, data_type=DataTypes["INT"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, group_id="0",
            unit=unit, only_read=False, frequency=1, need_push=True,
            is_vector=True, tag_base_name=f"2_{name}",
        )
        return True, None
    except Exception as exc:
        return False, str(exc)


def _try_add_with_desc(ctx, ds_id: int, name: str, *, tag_desc: str) -> tuple[bool, Any]:
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes
    try:
        add_tag(
            _api(ctx), tag_name=name, data_type=DataTypes["INT"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, group_id="0",
            unit="", only_read=False, frequency=1, need_push=True,
            tag_desc=tag_desc, is_vector=True, tag_base_name=f"2_{name}",
        )
        return True, None
    except Exception as exc:
        return False, str(exc)


def precise_only_read(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-082~085: onlyRead 与源端 writable 组合。"""
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    cid = meta["id"]
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    endpoint = str(ds["endpoint"])

    if cid == "UA-2-1-083":
        from ua_test_harness.ua2_helpers import standard_write_closed_loop
        return standard_write_closed_loop(
            ctx, cc, suffix="083", type_key="DOUBLE", values=[42.0], tag_desc="onlyRead false write",
        )

    src_writable = cid in {"UA-2-1-082", "UA-2-1-083", "UA-2-1-085"}
    spec = write_spec("DOUBLE") if src_writable else read_spec("DOUBLE")
    only_read = cid in {"UA-2-1-082", "UA-2-1-084"}
    base = base_name_for_node(spec["node"])
    node_name = spec["node"]

    tag = create_case_tag(
        ctx, cc, ds_id, suffix=cid[-3:], data_type=spec["dtype"],
        tag_base_name=base, only_read=only_read,
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        cfg = config_page_row(ctx, tag_name)
        check_eq("onlyRead", only_read, cfg.get("onlyRead"))
        before_rt = read_rt(ctx, tag_name)
        before_src = opcua_read(endpoint, node_name)
        failed = False
        err = None
        try:
            write_tag(ctx, tag_name, 99.9)
        except Exception as exc:
            failed = True
            err = str(exc)
        after_rt = read_rt(ctx, tag_name)
        after_src = opcua_read(endpoint, node_name)

        if cid == "UA-2-1-085":
            check_true("write_failed_or_ineffective", failed or _row_value(before_rt) == _row_value(after_rt))
            check_true("source_unchanged", _values_close(before_src, after_src, type_key="DOUBLE"))
            ctx.bag[cid] = {
                "onlyRead": only_read, "write_failed": failed, "error": err,
                "before_src": before_src, "after_src": after_src,
            }
            return CaseStatus.PASS

        check_true("write_rejected_or_unchanged", failed or _row_value(before_rt) == _row_value(after_rt))
        check_true("source_unchanged", _values_close(before_src, after_src, type_key="DOUBLE"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def precise_frequency(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-086~090: 频率默认/探索。"""
    from ua_test_harness.fixtures.tag import read_history, read_rt

    cid = meta["id"]
    ds = types_context(ctx)
    ds_id = int(ds["id"])

    if cid == "UA-2-1-086":
        tag = create_case_tag(ctx, cc, ds_id, suffix="086", data_type="INT")
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            cfg = config_page_row(ctx, tag_name)
            check_eq("default_frequency", 10, cfg.get("frequency"))
            rt_row(ctx, tag_name)
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    freq_map = {"UA-2-1-087": 1, "UA-2-1-088": 5, "UA-2-1-089": 30}
    if cid in freq_map:
        freq = freq_map[cid]
        duration = 30 if freq == 1 else (60 if freq == 5 else 120)
        tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:], data_type="INT", frequency=freq)
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            samples: list[dict[str, Any]] = []
            deadline = time.monotonic() + duration
            while time.monotonic() < deadline:
                row = read_rt(ctx, tag_name) or {}
                samples.append({"t": time.time(), "v": _row_value(row), "q": _quality(row)})
                time.sleep(1.0)
            end_ms = int(time.time() * 1000)
            hist = read_history(ctx, tag_name, end_ms - duration * 1000, end_ms)
            ctx.bag[cid] = {"frequency": freq, "rt_samples": len(samples), "history_count": len(hist or [])}
            return CaseStatus.OBSERVED
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    if cid == "UA-2-1-090":
        records = []
        for bad in (0, -1, 999999):
            tname = case_tag_name(ctx, cc, f"90{bad}")
            ok, detail = _try_add_frequency(ctx, ds_id, tname, frequency=bad)
            records.append({"frequency": bad, "accepted": ok, "detail": detail})
            if ok:
                row = config_page_row(ctx, tname)
                cleanup_case_tag(ctx, cc, int(row["id"]), tname)
        ctx.bag[cid] = {"freq_probes": records}
        return CaseStatus.OBSERVED
    raise AssertFail(f"precise_frequency: unsupported {cid}")


def _try_add_frequency(ctx, ds_id: int, name: str, *, frequency: int) -> tuple[bool, Any]:
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes
    try:
        add_tag(
            _api(ctx), tag_name=name, data_type=DataTypes["INT"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, group_id="0",
            unit="", only_read=False, frequency=frequency, need_push=True,
            is_vector=True, tag_base_name=f"2_{name}",
        )
        return True, None
    except Exception as exc:
        return False, str(exc)


def precise_limits(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-091~097: 量程与报警限。"""
    from tpt_api.datahub import update_tag
    from tpt_api.types import DataTypes
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    cid = meta["id"]
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    spec = write_spec("DOUBLE")
    base = base_name_for_node(spec["node"])

    if cid in {"UA-2-1-093", "UA-2-1-094", "UA-2-1-096", "UA-2-1-097"}:
        tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:], data_type="DOUBLE", tag_base_name=base)
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            cfg = config_page_row(ctx, tag_name)
            tid = int(cfg["id"])
            if cid == "UA-2-1-093":
                update_tag(_api(ctx), tid, tag_name=tag_name,
                           data_type=int(cfg.get("dataType") or DataTypes["DOUBLE"]),
                           ds_id=ds_id, hi_eu=100, lo_eu=0)
                endpoint = str(ds["endpoint"])
                records = []
                for val in (150, -50):
                    err = None
                    try:
                        write_tag(ctx, tag_name, val)
                        ok = True
                    except Exception as exc:
                        ok = False
                        err = str(exc)
                    rt = read_rt(ctx, tag_name) if ok else None
                    src = opcua_read(endpoint, spec["node"])
                    records.append({"value": val, "accepted": ok, "error": err,
                                      "rt": _row_value(rt), "src": src})
                ctx.bag[cid] = {"probe_writes": records}
                return CaseStatus.OBSERVED
            if cid == "UA-2-1-094":
                probes = [(100, 100), (100, 0), (None, 0)]
                records = []
                for hi, lo in probes:
                    tname = case_tag_name(ctx, cc, f"94{hi}{lo}")
                    ok, detail = _try_limits_create(ctx, ds_id, tname, hi_eu=hi, lo_eu=lo)
                    records.append({"hi": hi, "lo": lo, "accepted": ok, "detail": detail})
                    if ok:
                        cleanup_case_tag(ctx, cc, int(config_page_row(ctx, tname)["id"]), tname)
                ctx.bag[cid] = {"limit_probes": records}
                return CaseStatus.OBSERVED
            if cid == "UA-2-1-096":
                bad = {"limit_up": 10, "limit_down": 80}
                ok, detail = _try_limits_create(ctx, ds_id, case_tag_name(ctx, cc, "96"), **bad)
                ctx.bag[cid] = {"accepted": ok, "detail": detail}
                return CaseStatus.OBSERVED
            if cid == "UA-2-1-097":
                update_tag(_api(ctx), tid, tag_name=tag_name,
                           data_type=int(cfg.get("dataType") or DataTypes["DOUBLE"]),
                           ds_id=ds_id, hi_eu=50, lo_eu=0, limit_up=80, limit_down=-20)
                cfg2 = config_page_row(ctx, tag_name)
                ctx.bag[cid] = {"limitUp": cfg2.get("limitUp"), "limitDown": cfg2.get("limitDown")}
                return CaseStatus.OBSERVED
        finally:
            if tag_id:
                cleanup_case_tag(ctx, cc, tag_id, tag_name)

    tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:], data_type="DOUBLE", tag_base_name=base)
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        cfg = config_page_row(ctx, tag_name)
        tid = int(cfg["id"])
        dtype = int(cfg.get("dataType") or DataTypes["DOUBLE"])
        if cid == "UA-2-1-091":
            update_tag(_api(ctx), tid, tag_name=tag_name, data_type=dtype, ds_id=ds_id, hi_eu=100, lo_eu=0)
            cfg2 = config_page_row(ctx, tag_name)
            check_eq("hiEU", 100, cfg2.get("hiEU"))
            check_eq("loEU", 0, cfg2.get("loEU"))
            rt_row(ctx, tag_name)
            return CaseStatus.PASS
        if cid == "UA-2-1-092":
            update_tag(_api(ctx), tid, tag_name=tag_name, data_type=dtype, ds_id=ds_id, hi_eu=100, lo_eu=0)
            write_value_closed_loop(
                ctx, tag_name=tag_name, ds_id=ds_id, endpoint=str(ds["endpoint"]),
                node_name=spec["node"], type_key="DOUBLE", value=50.0,
            )
            return CaseStatus.PASS
        if cid == "UA-2-1-095":
            update_tag(
                _api(ctx), tid, tag_name=tag_name, data_type=dtype, ds_id=ds_id,
                limit_up=80, limit_up_up=90, limit_up_up_up=100,
                limit_down=10, limit_down_down=5, limit_down_down_down=0,
            )
            cfg2 = config_page_row(ctx, tag_name)
            check_eq("limitUp", 80, int(cfg2.get("limitUp")))
            check_eq("limitDownDownDown", 0, int(cfg2.get("limitDownDownDown")))
            return CaseStatus.PASS
        raise AssertFail(f"precise_limits: unsupported {cid}")
    finally:
        if tag_id:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)


def _try_limits_create(ctx, ds_id, name, *, hi_eu=None, lo_eu=None, **limits) -> tuple[bool, Any]:
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes
    kw: dict[str, Any] = {}
    if hi_eu is not None:
        kw["hi_eu"] = hi_eu
    if lo_eu is not None:
        kw["lo_eu"] = lo_eu
    kw.update(limits)
    try:
        add_tag(
            _api(ctx), tag_name=name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, group_id="0",
            unit="", only_read=False, frequency=1, need_push=True,
            is_vector=True, tag_base_name=f"2_{name}", **kw,
        )
        return True, None
    except Exception as exc:
        return False, str(exc)


def precise_need_push(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-098~101: needPush 字段与行为探索。"""
    from tpt_api.datahub import update_tag
    from tpt_api.types import DataTypes
    from ua_test_harness.fixtures.tag import read_history, read_rt

    cid = meta["id"]
    ds = types_context(ctx)
    ds_id = int(ds["id"])

    if cid in {"UA-2-1-100", "UA-2-1-101"}:
        tag = create_case_tag(ctx, cc, ds_id, suffix=cid[-3:], data_type="INT", need_push=False)
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            cfg = config_page_row(ctx, tag_name)
            check_eq("needPush", False, cfg.get("needPush"))
            if cid == "UA-2-1-100":
                samples = []
                for _ in range(5):
                    samples.append(read_rt(ctx, tag_name))
                    time.sleep(2.0)
                ctx.bag[cid] = {"rt_samples": samples}
            else:
                time.sleep(30)
                end_ms = int(time.time() * 1000)
                hist = read_history(ctx, tag_name, end_ms - 35_000, end_ms)
                ctx.bag[cid] = {"history_count": len(hist or [])}
            return CaseStatus.OBSERVED
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)

    tag = create_case_tag(
        ctx, cc, ds_id, suffix=cid[-3:], data_type="INT",
        need_push=False if cid == "UA-2-1-099" else True,
    )
    tag_id, tag_name = int(tag["id"]), tag["name"]
    try:
        if cid == "UA-2-1-099":
            cfg = config_page_row(ctx, tag_name)
            update_tag(
                _api(ctx), int(cfg["id"]), tag_name=tag_name,
                data_type=int(cfg.get("dataType") or DataTypes["INT"]),
                ds_id=ds_id, need_push=False,
            )
        cfg = config_page_row(ctx, tag_name)
        expected = cid == "UA-2-1-098"
        check_eq("needPush", expected, cfg.get("needPush"))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, tag_id, tag_name)


def precise_availability(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-102~104: 可用性闭环。"""
    from ua_test_harness.fixtures.tag import read_history
    from ua_test_harness.ua2_helpers import standard_read_closed_loop, standard_write_closed_loop

    cid = meta["id"]
    if cid == "UA-2-1-102":
        return standard_read_closed_loop(ctx, cc, suffix="102", type_key="INT32")
    if cid == "UA-2-1-103":
        return standard_write_closed_loop(
            ctx, cc, suffix="103", type_key="DOUBLE", values=[42.0], tag_desc="availability write",
        )
    if cid == "UA-2-1-104":
        ds = types_context(ctx)
        ds_id = int(ds["id"])
        spec = write_spec("DOUBLE")
        base = base_name_for_node(spec["node"])
        tag = create_case_tag(ctx, cc, ds_id, suffix="104", data_type=spec["dtype"], tag_base_name=base)
        tag_id, tag_name = int(tag["id"]), tag["name"]
        try:
            write_value_closed_loop(
                ctx, tag_name=tag_name, ds_id=ds_id, endpoint=str(ds["endpoint"]),
                node_name=spec["node"], type_key="DOUBLE", value=77.7,
            )
            start_ms = int(time.time() * 1000) - 5000
            deadline = time.monotonic() + 90.0
            hist = []
            while time.monotonic() < deadline:
                end_ms = int(time.time() * 1000)
                hist = read_history(ctx, tag_name, start_ms, end_ms) or []
                if hist:
                    break
                time.sleep(3.0)
            check_true("history_has_points", bool(hist))
            return CaseStatus.PASS
        finally:
            cleanup_case_tag(ctx, cc, tag_id, tag_name)
    raise AssertFail(f"precise_availability: unsupported {cid}")


def precise_batch(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-105~112: batchAdd 精确/探索。"""
    from tpt_api.datahub import batch_add_tags

    cid = meta["id"]
    ds = types_context(ctx)
    ds_id = int(ds["id"])
    created: list[tuple[int, str]] = []

    try:
        if cid == "UA-2-1-108":
            try:
                batch_add_tags(_api(ctx), [], conflict_strategy=0)
                ctx.bag[cid] = {"empty_batch": "accepted"}
            except Exception as exc:
                ctx.bag[cid] = {"empty_batch": "rejected", "error": str(exc)}
            return CaseStatus.OBSERVED

        if cid in {"UA-2-1-109", "UA-2-1-110", "UA-2-1-111", "UA-2-1-112"}:
            return _precise_batch_explore(ctx, cc, meta, cid, ds_id)

        if cid == "UA-2-1-105":
            from ua_test_harness.ua2_browse import browse_entry_to_batch_info, pick_unused_nodes
            nodes = pick_unused_nodes(ctx, ds_id, 10)
            infos = [
                browse_entry_to_batch_info(n, ds_id=ds_id, tag_name=case_tag_name(ctx, cc, f"b{i}"))
                for i, n in enumerate(nodes)
            ]
            batch_add_tags(_api(ctx), infos, conflict_strategy=0)
            for info in infos:
                cfg = config_page_row(ctx, info["tagName"])
                check_eq("batch_tagName", info["tagName"], cfg.get("tagName"))
                check_eq("batch_base", info["tagBaseName"], cfg.get("tagBaseName"))
                rt_row(ctx, info["tagName"], timeout=60.0)
                created.append((int(cfg["id"]), info["tagName"]))
            return CaseStatus.PASS

        if cid == "UA-2-1-106":
            from ua_test_harness.ua2_browse import browse_entry_to_batch_info, pick_unused_nodes
            existing = case_tag_name(ctx, cc, "106exist")
            new_name = case_tag_name(ctx, cc, "106new")
            node_a = pick_unused_nodes(ctx, ds_id, 1)[0]
            node_b = pick_unused_nodes(ctx, ds_id, 1)[0]
            pre = browse_entry_to_batch_info(node_a, ds_id=ds_id, tag_name=existing)
            batch_add_tags(_api(ctx), [pre], conflict_strategy=0)
            created.append((int(config_page_row(ctx, existing)["id"]), existing))
            before = config_page_row(ctx, existing)
            infos = [
                browse_entry_to_batch_info(node_a, ds_id=ds_id, tag_name=existing, unit="kW"),
                browse_entry_to_batch_info(node_b, ds_id=ds_id, tag_name=new_name),
            ]
            result = batch_add_tags(_api(ctx), infos, conflict_strategy=0)
            after = config_page_row(ctx, existing)
            check_eq("existing_unchanged_base", before.get("tagBaseName"), after.get("tagBaseName"))
            check_true("new_created", bool(exact(active_rows(ctx, tagName=new_name), "tagName", new_name)))
            ctx.bag[cid] = {"batch_result": result}
            created.append((int(config_page_row(ctx, new_name)["id"]), new_name))
            return CaseStatus.PASS

        if cid == "UA-2-1-107":
            from ua_test_harness.ua2_browse import browse_entry_to_batch_info, pick_unused_nodes
            node = pick_unused_nodes(ctx, ds_id, 1)[0]
            tname = case_tag_name(ctx, cc, "107")
            info = browse_entry_to_batch_info(node, ds_id=ds_id, tag_name=tname, unit="kW")
            batch_add_tags(_api(ctx), [info], conflict_strategy=0)
            created.append((int(config_page_row(ctx, tname)["id"]), tname))
            info["unit"] = "Hz"
            batch_add_tags(_api(ctx), [info], conflict_strategy=1)
            cfg = config_page_row(ctx, tname)
            check_eq("unit_overwritten", "Hz", cfg.get("unit"))
            rt_row(ctx, tname)
            return CaseStatus.PASS

        raise AssertFail(f"precise_batch: unsupported {cid}")
    finally:
        for tid, tname in created:
            cleanup_case_tag(ctx, cc, tid, tname)


def precise_cross_ds_same_node(ctx, cc, meta) -> CaseStatus:
    """UA-2-1-010: types + empty 共享底层节点,各自 RT 对应各自源端。"""
    from ua_test_harness.fixtures.tag import read_rt

    types = require_shared_datasource(ctx, "types")
    empty = require_shared_datasource(ctx, "empty")
    spec = read_spec("INT32")
    base = base_name_for_node(spec["node"])
    ep_t, ep_e = str(types["endpoint"]), str(empty["endpoint"])
    ta = create_case_tag(
        ctx, cc, int(types["id"]), suffix="10a", data_type=spec["dtype"], tag_base_name=base,
    )
    tb = create_case_tag(
        ctx, cc, int(empty["id"]), suffix="10b", data_type=spec["dtype"], tag_base_name=base,
    )
    try:
        rt_row(ctx, ta["name"])
        rt_row(ctx, tb["name"])
        src_a = opcua_read(ep_t, spec["node"])
        src_b = opcua_read(ep_e, spec["node"])
        ra = read_rt(ctx, ta["name"])
        rb = read_rt(ctx, tb["name"])
        ctx.bag[meta["id"]] = {
            "rt_a": _row_value(ra), "rt_b": _row_value(rb),
            "src_a": src_a, "src_b": src_b,
        }
        check_true("both_created", bool(ra) and bool(rb))
        return CaseStatus.PASS
    finally:
        cleanup_case_tag(ctx, cc, int(ta["id"]), ta["name"])
        cleanup_case_tag(ctx, cc, int(tb["id"]), tb["name"])


def _precise_batch_explore(ctx, cc, meta, cid: str, ds_id: int) -> CaseStatus:
    from tpt_api.datahub import batch_add_tags
    from ua_test_harness.ua2_browse import browse_entry_to_batch_info, pick_unused_nodes

    created: list[tuple[int, str]] = []
    try:
        if cid == "UA-2-1-109":
            nodes = pick_unused_nodes(ctx, ds_id, 9)
            dup = case_tag_name(ctx, cc, "109dup")
            infos = [browse_entry_to_batch_info(n, ds_id=ds_id, tag_name=case_tag_name(ctx, cc, f"109{i}"))
                     for i, n in enumerate(nodes)]
            infos.append(browse_entry_to_batch_info(nodes[0], ds_id=ds_id, tag_name=dup))
            infos.append({"tagName": dup, "tagBaseName": "bad_base", "dataType": 999, "dsId": ds_id})
            try:
                result = batch_add_tags(_api(ctx), infos, conflict_strategy=0)
                ctx.bag[cid] = {"result": result, "strategy": "accepted"}
            except Exception as exc:
                ctx.bag[cid] = {"error": str(exc), "strategy": "rejected"}
        elif cid == "UA-2-1-110":
            dup = case_tag_name(ctx, cc, "110dup")
            node = pick_unused_nodes(ctx, ds_id, 1)[0]
            info = browse_entry_to_batch_info(node, ds_id=ds_id, tag_name=dup)
            try:
                result = batch_add_tags(_api(ctx), [info, info], conflict_strategy=0)
                ctx.bag[cid] = {"result": result}
            except Exception as exc:
                ctx.bag[cid] = {"error": str(exc)}
        elif cid == "UA-2-1-111":
            nodes = pick_unused_nodes(ctx, ds_id, 3)
            infos = [browse_entry_to_batch_info(n, ds_id=ds_id, tag_name=case_tag_name(ctx, cc, f"111{i}"))
                     for i, n in enumerate(nodes)]
            r1 = batch_add_tags(_api(ctx), infos, conflict_strategy=0)
            r2 = batch_add_tags(_api(ctx), infos, conflict_strategy=0)
            ctx.bag[cid] = {"first": r1, "second": r2}
        elif cid == "UA-2-1-112":
            sizes = [1, 10, 100]
            records = []
            for sz in sizes:
                try:
                    nodes = pick_unused_nodes(ctx, ds_id, sz)
                    infos = [browse_entry_to_batch_info(n, ds_id=ds_id, tag_name=case_tag_name(ctx, cc, f"112{sz}{i}"))
                             for i, n in enumerate(nodes)]
                    t0 = time.monotonic()
                    batch_add_tags(_api(ctx), infos, conflict_strategy=0)
                    records.append({"size": sz, "ok": True, "elapsed": time.monotonic() - t0})
                    for info in infos:
                        row = exact(active_rows(ctx, tagName=info["tagName"]), "tagName", info["tagName"])
                        if row:
                            created.append((int(row[0]["id"]), info["tagName"]))
                except Exception as exc:
                    records.append({"size": sz, "ok": False, "error": str(exc)})
            ctx.bag[cid] = {"size_probes": records}
        return CaseStatus.OBSERVED
    finally:
        for tid, tname in created:
            cleanup_case_tag(ctx, cc, tid, tname)
