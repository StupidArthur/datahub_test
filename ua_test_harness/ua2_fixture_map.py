"""UA-2 mock 节点与数据类型映射(ua2_types.yaml, namespace_index=2)。"""
from __future__ import annotations

from ua_test_harness.type_mapping import tpt_tag_base_name

NAMESPACE_INDEX = 2

# 读取节点: change=true, writable=false
READ_NODES: dict[str, dict[str, str]] = {
    "BOOLEAN": {"node": "ua2_boolean_r_1", "dtype": "BOOLEAN"},
    "SBYTE": {"node": "ua2_sbyte_r_1", "dtype": "S_BYTE"},
    "BYTE": {"node": "ua2_byte_r_1", "dtype": "BYTE"},
    "INT16": {"node": "ua2_int16_r_1", "dtype": "SHORT"},
    "UINT16": {"node": "ua2_uint16_r_1", "dtype": "U_SHORT"},
    "INT32": {"node": "ua2_int32_r_1", "dtype": "INT"},
    "UINT32": {"node": "ua2_uint32_r_1", "dtype": "U_INT"},
    "INT64": {"node": "ua2_int64_r_1", "dtype": "LONG"},
    "UINT64": {"node": "ua2_uint64_r_1", "dtype": "U_LONG"},
    "FLOAT": {"node": "ua2_float_r_1", "dtype": "FLOAT"},
    "DOUBLE": {"node": "ua2_double_r_1", "dtype": "DOUBLE"},
    "STRING": {"node": "ua2_string_r_1", "dtype": "STRING"},
    "DATETIME": {"node": "ua2_datetime_r_1", "dtype": "DATE_TIME"},
}

WRITE_NODES: dict[str, dict[str, str]] = {
    "BOOLEAN": {"node": "ua2_boolean_w_1", "dtype": "BOOLEAN"},
    "SBYTE": {"node": "ua2_sbyte_w_1", "dtype": "S_BYTE"},
    "BYTE": {"node": "ua2_byte_w_1", "dtype": "BYTE"},
    "INT16": {"node": "ua2_int16_w_1", "dtype": "SHORT"},
    "UINT16": {"node": "ua2_uint16_w_1", "dtype": "U_SHORT"},
    "INT32": {"node": "ua2_int32_w_1", "dtype": "INT"},
    "UINT32": {"node": "ua2_uint32_w_1", "dtype": "U_INT"},
    "INT64": {"node": "ua2_int64_w_1", "dtype": "LONG"},
    "UINT64": {"node": "ua2_uint64_w_1", "dtype": "U_LONG"},
    "FLOAT": {"node": "ua2_float_w_1", "dtype": "FLOAT"},
    "DOUBLE": {"node": "ua2_double_w_1", "dtype": "DOUBLE"},
    "STRING": {"node": "ua2_string_w_1", "dtype": "STRING"},
    "DATETIME": {"node": "ua2_datetime_w_1", "dtype": "DATE_TIME"},
}

# UA-2-1-026..038 case_id -> type key
CASE_READ_TYPE: dict[str, str] = {
    f"UA-2-1-{n:03d}": key
    for n, key in zip(
        range(26, 39),
        ["BOOLEAN", "SBYTE", "BYTE", "INT16", "UINT16", "INT32", "UINT32",
         "INT64", "UINT64", "FLOAT", "DOUBLE", "STRING", "DATETIME"],
    )
}

CASE_WRITE_TYPE: dict[str, str] = {
    "UA-2-1-039": "BOOLEAN", "UA-2-1-040": "BOOLEAN", "UA-2-1-041": "BOOLEAN",
    "UA-2-1-042": "SBYTE", "UA-2-1-043": "SBYTE",
    "UA-2-1-044": "BYTE", "UA-2-1-045": "BYTE",
    "UA-2-1-046": "INT16", "UA-2-1-047": "INT16",
    "UA-2-1-048": "UINT16", "UA-2-1-049": "UINT16",
    "UA-2-1-050": "INT32", "UA-2-1-051": "INT32",
    "UA-2-1-052": "UINT32", "UA-2-1-053": "UINT32",
    "UA-2-1-054": "INT64", "UA-2-1-055": "INT64", "UA-2-1-056": "INT64",
    "UA-2-1-057": "UINT64", "UA-2-1-058": "UINT64", "UA-2-1-059": "UINT64",
    "UA-2-1-060": "FLOAT", "UA-2-1-061": "FLOAT", "UA-2-1-062": "FLOAT",
    "UA-2-1-063": "DOUBLE", "UA-2-1-064": "DOUBLE", "UA-2-1-065": "DOUBLE",
    "UA-2-1-066": "STRING", "UA-2-1-067": "STRING", "UA-2-1-068": "STRING",
    "UA-2-1-069": "STRING", "UA-2-1-070": "STRING",
    "UA-2-1-071": "DATETIME", "UA-2-1-072": "DATETIME", "UA-2-1-073": "DATETIME",
    "UA-2-1-074": "DATETIME", "UA-2-1-075": "DATETIME",
}


def base_name_for_node(node_name: str) -> str:
    return tpt_tag_base_name(NAMESPACE_INDEX, node_name)


def read_spec(type_key: str) -> dict[str, str]:
    return READ_NODES[type_key]


def write_spec(type_key: str) -> dict[str, str]:
    return WRITE_NODES[type_key]
