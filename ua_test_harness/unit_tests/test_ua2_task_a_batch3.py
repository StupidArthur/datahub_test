"""任务 A 第三批: 探索写入拒绝不变 + needPush/可用性 单测。"""
from __future__ import annotations

from unittest.mock import MagicMock

import ua_test_harness.ua2_precise as precise
from ua_test_harness.config import RunConfig
from ua_test_harness.context import CaseContext, RunContext
from ua_test_harness.models import CaseStatus
from ua_test_harness.resources import ResourceRegistry


def _ctx() -> RunContext:
    cfg = RunConfig()
    cfg.run_id = "ua2_a_batch3"
    return RunContext(config=cfg, emitter=MagicMock(), evidence_root=None, log_path=None, cancellation_token=None)


def _cc(case_id: str) -> CaseContext:
    return CaseContext(case_id=case_id, title="t", registry=ResourceRegistry())


def test_write_explore_reject_unchanged(monkeypatch):
    monkeypatch.setattr(precise, "types_context", lambda ctx: {"id": 100, "endpoint": "opc.tcp://127.0.0.1:18965/ua_mocker/"})
    monkeypatch.setattr(precise, "create_case_tag", lambda *a, **k: {"id": 1, "name": "tag_w"})
    monkeypatch.setattr(precise, "cleanup_case_tag", lambda *a, **k: None)
    monkeypatch.setattr(precise, "opcua_read", lambda *a, **k: 1.0)
    monkeypatch.setattr(
        "ua_test_harness.fixtures.tag.read_rt",
        lambda *a, **k: {"tagValue": 1.0},
    )

    def fail_write(*a, **k):
        raise RuntimeError("rejected")

    monkeypatch.setattr("ua_test_harness.fixtures.tag.write_tag", fail_write)

    status = precise.precise_write_explore(
        _ctx(), _cc("UA-2-1-043"), {"id": "UA-2-1-043"},
        suffix="43", type_key="SBYTE", probe_values=[-129],
    )
    assert status == CaseStatus.PASS


def test_need_push_099_passes(monkeypatch):
    monkeypatch.setattr(precise, "types_context", lambda ctx: {"id": 100, "endpoint": "opc.tcp://127.0.0.1:18965/ua_mocker/"})
    monkeypatch.setattr(precise, "create_case_tag", lambda *a, **k: {"id": 2, "name": "tag_np"})
    monkeypatch.setattr(precise, "cleanup_case_tag", lambda *a, **k: None)
    monkeypatch.setattr(precise, "config_page_row", lambda *a, **k: {"id": 2, "tagName": "tag_np", "dataType": 6, "needPush": False})
    monkeypatch.setattr("tpt_api.datahub.update_tag", lambda *a, **k: {})
    monkeypatch.setattr(precise, "_api", lambda ctx: object())

    status = precise.precise_need_push(_ctx(), _cc("UA-2-1-099"), {"id": "UA-2-1-099"})
    assert status == CaseStatus.PASS
