"""UA-2 共享 helper: 在共享 baseline DS 上执行公共新增/读取/写入闭环。"""
from __future__ import annotations

import time
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true
from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import require_shared_datasource
from ua_test_harness.ua2_fixture_map import base_name_for_node, read_spec, write_spec
from ua_test_harness.ua2_ops import (
    active_rows,
    cleanup_case_tag,
    create_case_tag,
    create_tag_raw,
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


def _wait_rt(ctx, name: str, timeout: float = 60.0) -> dict[str, Any]:
    from ua_test_harness.fixtures.tag import read_rt

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = read_rt(ctx, name)
        if row and _quality(row) is not None:
            return row
        time.sleep(1.0)
    raise AssertFail(f"rt timeout for {name}")


def _wait_changed(ctx, name: str, first: Any, timeout: float = 30.0) -> dict[str, Any]:
    from ua_test_harness.fixtures.tag import read_rt

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = read_rt(ctx, name)
        if row and _row_value(row) != first:
            return row
        time.sleep(1.0)
    raise AssertFail(f"rt change timeout for {name}")


def _qtq_row(ctx, *, tag_name: str = "", ds_id: int | None = None) -> dict[str, Any] | None:
    from tpt_api.datahub import query_tags_with_quality

    res = query_tags_with_quality(
        _api(ctx), ds_id=ds_id, group_id="0", tag_name=tag_name, page=1, page_size=10,
    )
    records = ((res or {}).get("tagInfoList") or {}).get("records") or []
    for rec in records:
        if not tag_name or rec.get("tagName") == tag_name:
            return rec
    return None


def _types_ds(ctx) -> dict[str, Any]:
    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    return require_shared_datasource(ctx, "types")


def _observe(ctx, case_id: str, key: str, value: Any) -> CaseStatus:
    ctx.bag[f"observed_{case_id}_{key}"] = value
    return CaseStatus.OBSERVED


def verify_config_row(rec: dict, *, tag_name: str, ds_id: int, data_type_key: str,
                      tag_base_name: str, only_read: bool = False, unit: str = "",
                      frequency: int = 1, need_push: bool = True, tag_desc: str = ""):
    check_eq("tagName", tag_name, rec.get("tagName"))
    check_eq("tagBaseName", tag_base_name, rec.get("tagBaseName"))
    check_eq("dsId", ds_id, rec.get("dsId"))
    check_eq("tagType", 1, rec.get("tagType"))
    if tag_desc:
        check_eq("tagDesc", tag_desc, rec.get("tagDesc"))
    check_eq("unit", unit, rec.get("unit"))
    check_eq("frequency", frequency, rec.get("frequency"))
    check_eq("onlyRead", only_read, rec.get("onlyRead"))
    check_eq("needPush", need_push, rec.get("needPush"))


def standard_read_closed_loop(ctx, cc, *, suffix: str, type_key: str) -> CaseStatus:
    """公共读取闭环 — 委托 ua2_precise.public_create_read_loop。"""
    from ua_test_harness.ua2_precise import public_create_read_loop

    status, tag_id, tag_name = public_create_read_loop(ctx, cc, suffix=suffix, type_key=type_key)
    cleanup_case_tag(ctx, cc, tag_id, tag_name)
    return status


def standard_write_closed_loop(
    ctx, cc, *, suffix: str, type_key: str, values: list[Any], tag_desc: str = "",
) -> CaseStatus:
    """公共写入闭环 — 委托 ua2_precise.public_write_closed_loop。"""
    from ua_test_harness.ua2_precise import public_write_closed_loop

    status, tag_id, tag_name = public_write_closed_loop(
        ctx, cc, suffix=suffix, type_key=type_key, values=values, tag_desc=tag_desc,
    )
    cleanup_case_tag(ctx, cc, tag_id, tag_name)
    return status


def try_add_tag(ctx, ds_id: int, *, tag_name: str, data_type: str = "INT",
                tag_base_name: str | None = None) -> tuple[bool, Any]:
    """尝试 add_tag; 返回 (成功?, 结果或异常信息)。"""
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes

    try:
        result = add_tag(
            _api(ctx),
            tag_name=tag_name,
            data_type=DataTypes[data_type],
            tag_type=TagTypes["一次位号"],
            ds_id=ds_id,
            group_id="0",
            unit="",
            only_read=False,
            frequency=1,
            need_push=True,
            tag_desc="ua2 try add",
            is_vector=True,
            tag_base_name=tag_base_name or f"2_{tag_name}",
        )
        return True, result
    except Exception as exc:
        return False, str(exc)


def write_and_verify(ctx, tag_name: str, value: Any, *, timeout: float = 30.0) -> dict:
    from ua_test_harness.fixtures.tag import read_rt, write_tag

    write_tag(ctx, tag_name, value)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = read_rt(ctx, tag_name)
        if row and _row_value(row) == value:
            return row
        time.sleep(1.0)
    raise AssertFail(f"write not visible for {tag_name} value={value!r}")
