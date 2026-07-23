"""UA-2-3 导入导出 helper。"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from ua_test_harness.assertions import AssertFail, check_eq, check_true

EXPECTED_EXPORT_COLUMNS = 21
EXPECTED_HEADER_ROW = [
    "Tag Name", "Base Tag Name", "Tag Type", "Datasource Name", "Unit", "Data Type",
    "Expression", "Tag Value", "Frequency", "High Limit", "HH Limit", "HHH Limit",
    "Low Limit", "LL Limit", "LLL Limit", "Description", "Group Name",
    "Real-time Push", "Readonly", "Lo EU", "Hi EU",
]

_COL_TAG = 0
_COL_BASE = 1
_COL_DS = 3
_COL_UNIT = 4
_COL_DTYPE = 5
_COL_FREQ = 8
_COL_HI = 9
_COL_HH = 10
_COL_HHH = 11
_COL_LO = 12
_COL_LL = 13
_COL_LLL = 14
_COL_DESC = 15
_COL_GROUP = 16
_COL_PUSH = 17
_COL_RO = 18


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def _str_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _bool_cell(value: Any) -> str:
    if value in (True, 1, "1", "true", "True"):
        return "1"
    if value in (False, 0, "0", "false", "False"):
        return "0"
    return _str_cell(value)


def find_export_row(rows: list[list[Any]], tag_name: str) -> list[Any]:
    """在导出矩阵中定位目标位号行。"""
    for row in rows[1:]:
        if row and _str_cell(row[_COL_TAG]) == tag_name:
            return list(row)
    raise AssertFail(f"export missing row for {tag_name}")


def assert_export_identity(rows: list[list[Any]], tag_name: str, *, ds_name: str, cfg: dict) -> None:
    """UA-2-3-007: 系统名、底层名、数据源、分组归属。"""
    row = find_export_row(rows, tag_name)
    check_eq("export_tag_name", tag_name, _str_cell(row[_COL_TAG]))
    check_eq("export_base_name", _str_cell(cfg.get("tagBaseName")), _str_cell(row[_COL_BASE]))
    check_eq("export_ds_name", ds_name, _str_cell(row[_COL_DS]))
    check_true("export_dtype_present", _str_cell(row[_COL_DTYPE]) != "")


def assert_export_config_fields(rows: list[list[Any]], tag_name: str, cfg: dict) -> None:
    """UA-2-3-008: 类型/单位/频率/只读/推送/描述。"""
    row = find_export_row(rows, tag_name)
    check_eq("export_unit", _str_cell(cfg.get("unit")), _str_cell(row[_COL_UNIT]))
    check_eq("export_frequency", _str_cell(cfg.get("frequency")), _str_cell(row[_COL_FREQ]))
    check_eq("export_desc", _str_cell(cfg.get("tagDesc") or cfg.get("description")), _str_cell(row[_COL_DESC]))
    check_eq("export_readonly", _bool_cell(cfg.get("onlyRead")), _bool_cell(row[_COL_RO]))
    check_eq("export_need_push", _bool_cell(cfg.get("needPush")), _bool_cell(row[_COL_PUSH]))


def assert_export_limits(rows: list[list[Any]], tag_name: str, cfg: dict) -> None:
    """UA-2-3-009: 量程及六档限值。"""
    row = find_export_row(rows, tag_name)
    pairs = [
        ("limitUp", _COL_HI),
        ("limitUpUp", _COL_HH),
        ("limitUpUpUp", _COL_HHH),
        ("limitDown", _COL_LO),
        ("limitDownDown", _COL_LL),
        ("limitDownDownDown", _COL_LLL),
    ]
    for field, col in pairs:
        check_eq(f"export_{field}", _str_cell(cfg.get(field)), _str_cell(row[col]))


def wait_collectible(ctx, tag_name: str, timeout: float = 60.0) -> None:
    """导出前等待 RT 有效(服务端要求有采集数据)。"""
    from ua_test_harness.ua2_precise import rt_row
    rt_row(ctx, tag_name, timeout=timeout)


def export_to_temp(ctx, tag_ids: list[int], *, suffix: str = "export") -> tuple[str, list[list[Any]]]:
    from tpt_api.datahub import export_tags

    tmp = tempfile.mkdtemp(prefix="ua23_")
    path = os.path.join(tmp, f"{suffix}.xlsx")
    rows = export_tags(_api(ctx), tag_ids, save_path=path, parse=True)
    return path, rows


def assert_export_rows(rows: list[list[Any]], *, min_rows: int = 2, tag_names: set[str] | None = None) -> None:
    check_true("has_header", len(rows) >= 1)
    check_eq("column_count", EXPECTED_EXPORT_COLUMNS, len(rows[0]))
    check_true("enough_rows", len(rows) >= min_rows)
    if tag_names:
        exported = {str(r[0]) for r in rows[1:] if r and r[0]}
        check_true("names_subset", tag_names.issubset(exported) or exported.issubset(tag_names))


def import_file(ctx, path: str, *, conflict_strategy: int = 1) -> dict[str, Any]:
    from tpt_api.datahub import import_tags_from_file
    return import_tags_from_file(_api(ctx), path, conflict_strategy=conflict_strategy)


def write_invalid_file(path: str, content: bytes) -> None:
    with open(path, "wb") as f:
        f.write(content)
