"""OPC UA 类型名和底层位号名到 TPT 表示的统一映射。"""
from __future__ import annotations

import re
from collections.abc import Mapping


OPCUA_TO_TPT_DATA_TYPE: dict[str, str] = {
    "BOOLEAN": "BOOLEAN",
    "SBYTE": "S_BYTE",
    "BYTE": "BYTE",
    "INT16": "SHORT",
    "UINT16": "U_SHORT",
    "INT32": "INT",
    "UINT32": "U_INT",
    "INT64": "LONG",
    "UINT64": "U_LONG",
    "FLOAT": "FLOAT",
    "DOUBLE": "DOUBLE",
    "STRING": "STRING",
    "DATETIME": "DATE_TIME",
}


def normalize_opcua_type_name(type_name: str) -> str:
    """把 Int32、int_32、DATE-TIME 等写法归一化为映射键。"""
    normalized = re.sub(r"[^A-Za-z0-9]", "", str(type_name)).upper()
    if not normalized:
        raise ValueError("unsupported OPC UA type: empty")
    return normalized


def tpt_data_type_key(opcua_type: str) -> str:
    normalized = normalize_opcua_type_name(opcua_type)
    try:
        return OPCUA_TO_TPT_DATA_TYPE[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported OPC UA type: {opcua_type}") from exc


def tpt_data_type_value(opcua_type: str, data_types: Mapping[str, int]) -> int:
    """按 OPC UA 类型名从平台 DataTypes 映射中取整数值。"""
    platform_key = tpt_data_type_key(opcua_type)
    try:
        return data_types[platform_key]
    except KeyError as exc:
        raise KeyError(f"TPT DataTypes missing key {platform_key!r} for {opcua_type!r}") from exc


def tpt_tag_base_name(namespace_index: int, node_name: str) -> str:
    """生成 TPT OPC UA 一次位号要求的 ``<namespace>_<node>`` 底层名。"""
    try:
        namespace = int(namespace_index)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid OPC UA namespace index: {namespace_index!r}") from exc
    node = str(node_name).strip()
    if namespace < 0:
        raise ValueError(f"invalid OPC UA namespace index: {namespace}")
    if not node:
        raise ValueError("OPC UA node name is empty")
    prefix = f"{namespace}_"
    return node if node.startswith(prefix) else prefix + node
