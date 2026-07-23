"""ua2_query_extra 单测。"""
from __future__ import annotations

from ua_test_harness.ua2_import_helpers import EXPECTED_EXPORT_COLUMNS


def test_export_column_count():
    assert EXPECTED_EXPORT_COLUMNS == 21
