# -*- coding: utf-8 -*-
"""
OPC UA 类型映射：将组态中的类型名字符串映射到 asyncua 的 VariantType 及 Python 默认值。
"""

from datetime import datetime
from typing import Any

from asyncua import ua

# 组态 type 字符串 -> (ua.VariantType, 默认 Python 值)
TYPE_MAP = {
    "Boolean": (ua.VariantType.Boolean, False),
    "SByte": (ua.VariantType.SByte, 0),
    "Byte": (ua.VariantType.Byte, 0),
    "Int16": (ua.VariantType.Int16, 0),
    "UInt16": (ua.VariantType.UInt16, 0),
    "Int32": (ua.VariantType.Int32, 0),
    "UInt32": (ua.VariantType.UInt32, 0),
    "Int64": (ua.VariantType.Int64, 0),
    "UInt64": (ua.VariantType.UInt64, 0),
    "Float": (ua.VariantType.Float, 0.0),
    "Double": (ua.VariantType.Double, 0.0),
    "String": (ua.VariantType.String, ""),
    "DateTime": (ua.VariantType.DateTime, datetime(2025, 1, 1, 0, 0, 0)),
}

# 参与周期变化的类型（用于锯齿波 / 字符循环 / bool 翻转）
NUMERIC_VARIANT_TYPES = {
    ua.VariantType.SByte,
    ua.VariantType.Byte,
    ua.VariantType.Int16,
    ua.VariantType.UInt16,
    ua.VariantType.Int32,
    ua.VariantType.UInt32,
    ua.VariantType.Int64,
    ua.VariantType.UInt64,
    ua.VariantType.Float,
    ua.VariantType.Double,
}


def get_variant_type_and_default(type_name: str) -> tuple[ua.VariantType, Any]:
    """
    根据组态类型名返回 OPC UA VariantType 与默认 Python 值。

    :param type_name: 组态中的 type 字符串，如 "Int32", "Float"
    :return: (VariantType, default_value)
    :raises ValueError: 不支持的 type_name
    """
    key = type_name.strip()
    if key not in TYPE_MAP:
        raise ValueError(f"不支持的类型: {type_name}，支持: {list(TYPE_MAP.keys())}")
    return TYPE_MAP[key]


def is_numeric_type(variant_type: ua.VariantType) -> bool:
    """是否为数值类型（用于 0~99 锯齿波）。"""
    return variant_type in NUMERIC_VARIANT_TYPES


# VariantType -> 默认值（用于写回时 None 的兜底）
_DEFAULT_BY_VARIANT: dict[ua.VariantType, Any] = {v: d for _, (v, d) in TYPE_MAP.items()}


def coerce_to_type(value: Any, variant_type: ua.VariantType) -> Any:
    """
    将 Python 值强制为指定 VariantType 对应的类型（用于写回/持久化）。
    """
    if value is None:
        return _DEFAULT_BY_VARIANT.get(variant_type, None)
    if variant_type == ua.VariantType.Boolean:
        return bool(value)
    if variant_type in NUMERIC_VARIANT_TYPES:
        if variant_type in (ua.VariantType.Float, ua.VariantType.Double):
            return float(value)
        return int(value)
    if variant_type == ua.VariantType.String:
        return str(value)
    if variant_type == ua.VariantType.DateTime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    return value
