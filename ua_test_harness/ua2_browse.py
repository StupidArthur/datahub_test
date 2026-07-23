"""UA-2 browse 执行器 — getNotUsedBaseTagInfoContinue + 已注册二次过滤。

doc 要求: API 可能返回已导入节点,工具侧必须用 dsId+tagBaseName 与 tag-info 做差集。
"""
from __future__ import annotations

from typing import Any

from ua_test_harness.assertions import AssertFail
from ua_test_harness.type_mapping import tpt_data_type_key, tpt_tag_base_name
from ua_test_harness.ua2_fixture_map import NAMESPACE_INDEX


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def registered_base_names(ctx, ds_id: int) -> set[str]:
    """已注册 active 位号的 tagBaseName 集合(单 DS)。"""
    from ua_test_harness.ua2_ops import all_active_rows

    return {
        str(r.get("tagBaseName"))
        for r in all_active_rows(ctx, ds_id=ds_id)
        if r.get("tagBaseName")
    }


def browse_page(
    ctx,
    ds_id: int,
    *,
    tag_name: str = "",
    continue_id: str = "",
    page_size: int = 500,
) -> dict[str, Any]:
    from tpt_api.datahub import get_not_used_tags

    return get_not_used_tags(
        _api(ctx), ds_id=ds_id, tag_name=tag_name,
        continue_id=continue_id, page_size=page_size,
    )


def browse_all_nodes(
    ctx,
    ds_id: int,
    *,
    tag_name_filter: str = "",
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    """游标分页拉取 browse 全部 successes 条目。"""
    nodes: list[dict[str, Any]] = []
    continue_id = ""
    for _ in range(max_pages):
        page = browse_page(ctx, ds_id, tag_name=tag_name_filter, continue_id=continue_id)
        batch = list(page.get("successes") or [])
        nodes.extend(batch)
        continue_id = str(page.get("continueID") or "")
        if not continue_id or not batch:
            break
    return nodes


def node_base_name(entry: dict[str, Any]) -> str:
    raw = entry.get("name") or entry.get("browseName") or ""
    return tpt_tag_base_name(NAMESPACE_INDEX, str(raw))


def filter_unregistered(
    ctx,
    ds_id: int,
    nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """排除已在 tag-info 注册的 tagBaseName。"""
    reg = registered_base_names(ctx, ds_id)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in nodes:
        base = node_base_name(entry)
        if base in reg or base in seen:
            continue
        seen.add(base)
        out.append({**entry, "tagBaseName": base})
    return out


def pick_unused_nodes(
    ctx,
    ds_id: int,
    count: int,
    *,
    tag_name_filter: str = "",
) -> list[dict[str, Any]]:
    """Browse + 二次过滤,取 count 个未注册底层节点。"""
    raw = browse_all_nodes(ctx, ds_id, tag_name_filter=tag_name_filter)
    avail = filter_unregistered(ctx, ds_id, raw)
    if len(avail) < count:
        raise AssertFail(
            f"browse: need {count} unregistered nodes on ds={ds_id}, got {len(avail)}",
        )
    return avail[:count]


def _data_type_for_entry(entry: dict[str, Any]) -> str:
    """从 browse 条目解析 TPT DataTypes 键名。"""
    from tpt_api.types import DataTypes

    hub = entry.get("hubDataType")
    if hub is not None:
        for key, val in DataTypes.items():
            if int(val) == int(hub):
                return key
    raw_type = entry.get("tagDataType") or entry.get("tagDataTypeName") or "Int32"
    return tpt_data_type_key(str(raw_type))


def browse_entry_to_batch_info(
    entry: dict[str, Any],
    *,
    ds_id: int,
    tag_name: str,
    only_read: bool | None = None,
    unit: str = "",
    tag_desc: str = "",
) -> dict[str, Any]:
    """将 browse successes 条目转为 batchAdd tagInfos 元素。"""
    from tpt_api.types import DataTypes, TagTypes

    dtype_key = _data_type_for_entry(entry)
    base = entry.get("tagBaseName") or node_base_name(entry)
    read_only = bool(entry.get("readOnly", True)) if only_read is None else only_read
    info: dict[str, Any] = {
        "tagName": tag_name,
        "tagBaseName": base,
        "dataType": DataTypes[dtype_key],
        "tagType": TagTypes["一次位号"],
        "dsId": ds_id,
        "groupId": "0",
        "frequency": 1,
        "onlyRead": read_only,
        "needPush": True,
        "isVector": True,
    }
    if unit:
        info["unit"] = unit
    if tag_desc:
        info["tagDesc"] = tag_desc
    return info
