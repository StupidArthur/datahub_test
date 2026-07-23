# -*- coding: utf-8 -*-
"""
变更引擎：根据 OPC UA 类型与当前值，计算下一周期的值。
规则：bool 翻转；数值 0~99 锯齿波步长 1；字符串单字符 a~z 循环；DateTime 每周期 +1 秒。
"""

from datetime import datetime
from typing import Any

from asyncua import ua

from type_mapping import is_numeric_type

# 锯齿波范围
SAWTOOTH_MIN = 0
SAWTOOTH_MAX = 99
SAWTOOTH_STEP = 1

# 单字符循环：a-z
CHARS = "abcdefghijklmnopqrstuvwxyz"


def next_value(variant_type: ua.VariantType, current: Any) -> Any:
    """
    根据类型与当前值计算下一周期值。
    首次调用时 current 可为 None，返回该类型的起始值。

    :param variant_type: OPC UA VariantType
    :param current: 当前值
    :return: 下一周期值
    """
    if variant_type == ua.VariantType.Boolean:
        return not bool(current) if current is not None else False
    if is_numeric_type(variant_type):
        return _next_numeric(current, variant_type)
    if variant_type == ua.VariantType.String:
        return _next_string(current)
    if variant_type == ua.VariantType.DateTime:
        return _next_datetime(current)
    return current


def _next_numeric(current: Any, variant_type: ua.VariantType) -> Any:
    """0~99 锯齿波，步长 1。"""
    if current is None:
        n = SAWTOOTH_MIN
    else:
        try:
            n = int(current) + SAWTOOTH_STEP
        except (TypeError, ValueError):
            n = SAWTOOTH_MIN
    if n > SAWTOOTH_MAX:
        n = SAWTOOTH_MIN
    if n < SAWTOOTH_MIN:
        n = SAWTOOTH_MIN
    if variant_type in (ua.VariantType.Float, ua.VariantType.Double):
        return float(n)
    return n


def _next_string(current: Any) -> str:
    """单字符 a~z 循环。"""
    if not current or not isinstance(current, str):
        return CHARS[0]
    c = current.strip() or CHARS[0]
    if len(c) > 1:
        c = c[0]
    try:
        idx = CHARS.index(c.lower())
    except ValueError:
        return CHARS[0]
    idx = (idx + 1) % len(CHARS)
    return CHARS[idx]


def _next_datetime(current: Any) -> datetime:
    """每周期 +1 秒。"""
    if current is None:
        return datetime(2025, 1, 1, 0, 0, 0)
    if isinstance(current, datetime):
        from datetime import timedelta
        return current + timedelta(seconds=1)
    if isinstance(current, str):
        dt = datetime.fromisoformat(current.replace("Z", "+00:00"))
        from datetime import timedelta
        return dt + timedelta(seconds=1)
    return datetime(2025, 1, 1, 0, 0, 0)
