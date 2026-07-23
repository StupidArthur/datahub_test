"""ua_mocker 组态类型 → TPT dataType 映射。

基于 ua_mocker/type_mapping.py 的 13 种类型名。注意:ua_tpt_loop/mocker_yaml.py
误把 Int16/UInt16 写成 Short/UShort,这里用 ua_mocker 真实类型名修正。
String/DateTime 在 TPT DataTypes 无对应,映射 None(注册时跳过)。
"""
from __future__ import annotations

# ua_mocker type 名 → TPT dataType code(对齐 tpt_api DataTypes:BOOLEAN=1..DOUBLE=11)
MOCKER_TYPE_TO_TPT: dict[str, int | None] = {
    "Boolean": 1,
    "SByte": 2,
    "Byte": 3,
    "Int16": 4,
    "UInt16": 5,
    "Int32": 6,
    "UInt32": 7,
    "Int64": 8,
    "UInt64": 9,
    "Float": 10,
    "Double": 11,
    "String": None,
    "DateTime": None,
}

ALL_TYPES = list(MOCKER_TYPE_TO_TPT.keys())
SUPPORTED_TYPES = [t for t, v in MOCKER_TYPE_TO_TPT.items() if v is not None]


def tpt_data_type(mocker_type: str) -> int | None:
    return MOCKER_TYPE_TO_TPT.get((mocker_type or "").strip())


def expand_node_ids(name: str, count: int) -> list[str]:
    """ua_mocker 约定:name + i, i=1..count → name1..nameN。"""
    return [f"{name}{i}" for i in range(1, max(1, count) + 1)]


def default_for(mocker_type: str):
    """change=false 时的默认值(对齐 ua_mocker/type_mapping.py 默认值)。"""
    return {
        "Boolean": False, "SByte": 0, "Byte": 0, "Int16": 0, "UInt16": 0,
        "Int32": 0, "UInt32": 0, "Int64": 0, "UInt64": 0,
        "Float": 0.0, "Double": 0.0, "String": "",
        "DateTime": "2025-01-01T00:00:00Z",
    }.get((mocker_type or "").strip(), 0)
