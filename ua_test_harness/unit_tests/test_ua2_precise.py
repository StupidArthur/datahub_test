"""ua2_precise 模块单测: 值比较、写入映射、dispatcher 委托路径。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ua_test_harness.ua2_precise import (
    CASE_WRITE_VALUES,
    _values_close,
    assert_config_matches_request,
    precise_write_explore,
    public_write_closed_loop,
)
from ua_test_harness.assertions import AssertFail
from ua_test_harness.config import RunConfig
from ua_test_harness.context import CaseContext, RunContext
from ua_test_harness.models import CaseStatus
from ua_test_harness.resources import ResourceRegistry


def test_values_close_float_tolerance():
    assert _values_close(1.25, 1.2500001, type_key="FLOAT")
    assert not _values_close(1.25, 1.3, type_key="FLOAT")


def test_values_close_int64_as_string():
    assert _values_close("9999999999", 9999999999, type_key="INT64")
    assert _values_close(9999999999, "9999999999", type_key="INT64")


def test_assert_config_matches_request_ok():
    rec = {
        "tagName": "t1", "tagBaseName": "2_node", "dsId": 100,
        "tagType": 1, "onlyRead": False, "frequency": 1, "needPush": True,
    }
    assert_config_matches_request(
        rec, tag_name="t1", ds_id=100, tag_base_name="2_node", data_type_key="INT",
        only_read=False,
    )


def test_assert_config_mismatch_raises():
    with pytest.raises(AssertFail):
        assert_config_matches_request(
            {"tagName": "a"}, tag_name="b", ds_id=1, tag_base_name="x", data_type_key="INT",
        )


def test_case_write_values_cover_regression_ids():
    """回归写入 case 应全部在 CASE_WRITE_VALUES 中。"""
    expected = {
        "UA-2-1-039", "UA-2-1-040", "UA-2-1-042", "UA-2-1-044", "UA-2-1-046",
        "UA-2-1-048", "UA-2-1-050", "UA-2-1-052", "UA-2-1-054", "UA-2-1-055",
        "UA-2-1-057", "UA-2-1-058", "UA-2-1-060", "UA-2-1-061", "UA-2-1-063",
        "UA-2-1-064", "UA-2-1-066", "UA-2-1-067", "UA-2-1-068",
        "UA-2-1-071", "UA-2-1-072", "UA-2-1-074",
    }
    assert expected.issubset(set(CASE_WRITE_VALUES))


def test_precise_write_explore_records_probe(monkeypatch):
    import ua_test_harness.ua2_precise as precise

    ctx = RunContext(
        config=RunConfig(),
        emitter=MagicMock(),
        evidence_root=None,
        log_path=None,
        cancellation_token=None,
    )
    cc = CaseContext(case_id="UA-2-1-041", title="t", registry=ResourceRegistry())
    meta = {"id": "UA-2-1-041"}

    monkeypatch.setattr(precise, "types_context", lambda c: {"id": 1, "endpoint": "opc.tcp://x"})
    monkeypatch.setattr(precise, "create_case_tag", lambda *a, **k: {"id": 9, "name": "tag9"})
    monkeypatch.setattr(precise, "cleanup_case_tag", lambda *a, **k: None)
    monkeypatch.setattr(precise, "opcua_read", lambda *a, **k: 0)

    def fake_write(ctx, name, val):
        if val == "bad":
            raise RuntimeError("rejected")

    monkeypatch.setattr("ua_test_harness.fixtures.tag.write_tag", fake_write)
    monkeypatch.setattr("ua_test_harness.fixtures.tag.read_rt", lambda ctx, n: {"tagValue": 0, "quality": 192})

    status = precise_write_explore(
        ctx, cc, meta, suffix="041", type_key="BOOLEAN", probe_values=[True, "bad"],
    )
    assert status == CaseStatus.PASS
    assert len(ctx.bag["UA-2-1-041"]["probe_writes"]) == 2
    assert ctx.bag["UA-2-1-041"]["probe_writes"][1]["accepted"] is False


def test_public_write_closed_loop_delegates_cleanup(monkeypatch):
    import ua_test_harness.ua2_precise as precise

    calls: list[str] = []
    monkeypatch.setattr(precise, "types_context", lambda c: {"id": 1, "endpoint": "opc.tcp://x"})
    monkeypatch.setattr(precise, "create_case_tag", lambda *a, **k: {"id": 7, "name": "tag7"})
    monkeypatch.setattr(precise, "config_page_row", lambda ctx, n: {
        "tagName": n, "tagBaseName": "2_ua2_boolean_w_1", "dsId": 1, "tagType": 1,
        "onlyRead": False, "frequency": 1, "needPush": True, "tagDesc": "d",
    })
    monkeypatch.setattr(precise, "opcua_read", lambda *a, **k: False)
    monkeypatch.setattr(precise, "opcua_write", lambda *a, **k: calls.append("opcua_write"))
    monkeypatch.setattr(precise, "write_value_closed_loop", lambda *a, **k: {"tagValue": True, "quality": 192})
    monkeypatch.setattr("ua_test_harness.fixtures.tag.write_tag", lambda *a, **k: calls.append("restore"))

    ctx = RunContext(
        config=RunConfig(),
        emitter=MagicMock(),
        evidence_root=None,
        log_path=None,
        cancellation_token=None,
    )
    cc = CaseContext(case_id="UA-2-1-039", title="t", registry=ResourceRegistry())

    status, tag_id, tag_name = public_write_closed_loop(
        ctx, cc, suffix="039", type_key="BOOLEAN", values=[True],
    )
    assert status == CaseStatus.PASS
    assert tag_id == 7
    assert "restore" in calls
