"""ua2_browse 单测。"""
from __future__ import annotations

from unittest.mock import MagicMock

from ua_test_harness.ua2_browse import (
    filter_unregistered,
    node_base_name,
    browse_entry_to_batch_info,
)
from ua_test_harness.config import RunConfig
from ua_test_harness.context import RunContext


def _ctx():
    return RunContext(
        config=RunConfig(),
        emitter=MagicMock(),
        evidence_root=None,
        log_path=None,
        cancellation_token=None,
    )


def test_node_base_name():
    assert node_base_name({"name": "ua2_int32_r_1"}) == "2_ua2_int32_r_1"


def test_filter_unregistered(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr(
        "ua_test_harness.ua2_browse.registered_base_names",
        lambda c, d: {"2_ua2_int32_r_1"},
    )
    nodes = [
        {"name": "ua2_int32_r_1"},
        {"name": "ua2_boolean_r_1"},
    ]
    out = filter_unregistered(ctx, 1, nodes)
    assert len(out) == 1
    assert out[0]["tagBaseName"] == "2_ua2_boolean_r_1"


def test_browse_entry_to_batch_info():
    entry = {"name": "ua2_int32_r_1", "readOnly": True, "tagDataType": "Int32", "tagBaseName": "2_ua2_int32_r_1"}
    info = browse_entry_to_batch_info(entry, ds_id=100, tag_name="t1")
    assert info["tagName"] == "t1"
    assert info["dsId"] == 100
    assert info["onlyRead"] is True
