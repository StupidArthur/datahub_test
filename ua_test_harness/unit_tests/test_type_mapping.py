from __future__ import annotations

import pytest

from ua_test_harness.type_mapping import (
    normalize_opcua_type_name,
    tpt_data_type_key,
    tpt_data_type_value,
    tpt_tag_base_name,
)


def test_all_opcua_types_map_to_tpt_keys() -> None:
    expected = {
        "Boolean": "BOOLEAN",
        "SByte": "S_BYTE",
        "Byte": "BYTE",
        "Int16": "SHORT",
        "UInt16": "U_SHORT",
        "Int32": "INT",
        "UInt32": "U_INT",
        "Int64": "LONG",
        "UInt64": "U_LONG",
        "Float": "FLOAT",
        "Double": "DOUBLE",
        "String": "STRING",
        "DateTime": "DATE_TIME",
    }
    assert {name: tpt_data_type_key(name) for name in expected} == expected


def test_normalize_and_value_lookup() -> None:
    assert normalize_opcua_type_name(" date-time ") == "DATETIME"
    assert tpt_data_type_value("Int32", {"INT": 6}) == 6


def test_tag_base_name_contains_namespace_and_is_idempotent() -> None:
    assert tpt_tag_base_name(2, "smoke_change_1") == "2_smoke_change_1"
    assert tpt_tag_base_name(2, "2_smoke_change_1") == "2_smoke_change_1"


def test_invalid_tag_base_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="namespace"):
        tpt_tag_base_name(-1, "node")
    with pytest.raises(ValueError, match="node name"):
        tpt_tag_base_name(2, "  ")


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported OPC UA type"):
        tpt_data_type_key("Guid")
