"""任务 A 第二批: UA-2-3 导出断言 helper 单测。"""
from __future__ import annotations

import pytest

import ua_test_harness.ua2_import_helpers as ih
from ua_test_harness.assertions import AssertFail


def test_export_identity_matches_config():
    rows = [
        ih.EXPECTED_HEADER_ROW,
        ["tag_a", "base_a", "1", "types_ds", "kW", "INT", "", "1", "5", "100", "90", "80", "-100", "-90", "-80", "desc", "0", "1", "0", "0", "100"],
    ]
    cfg = {"tagBaseName": "base_a", "unit": "kW", "frequency": 5, "tagDesc": "desc", "onlyRead": 0, "needPush": 1}
    ih.assert_export_identity(rows, "tag_a", ds_name="types_ds", cfg=cfg)
    ih.assert_export_config_fields(rows, "tag_a", cfg)
    ih.assert_export_limits(rows, "tag_a", {
        "limitUp": 100, "limitUpUp": 90, "limitUpUpUp": 80,
        "limitDown": -100, "limitDownDown": -90, "limitDownDownDown": -80,
    })


def test_find_export_row_missing_raises():
    with pytest.raises(AssertFail):
        ih.find_export_row([ih.EXPECTED_HEADER_ROW], "missing")
