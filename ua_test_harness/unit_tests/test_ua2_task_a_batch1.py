"""任务 A 第一批: UA-2-2 分组/结果更新 + UA-2-1-014 断言单测。"""
from __future__ import annotations

from unittest.mock import MagicMock

import ua_test_harness.ua2_create_runtime as create_rt
import ua_test_harness.ua2_query_extra as qx
from ua_test_harness.config import RunConfig
from ua_test_harness.context import CaseContext, RunContext
from ua_test_harness.models import CaseStatus
from ua_test_harness.resources import ResourceRegistry


TYPES_DS = {"id": 100, "name": "ua_shared_ua2_types_ds", "endpoint": "opc.tcp://127.0.0.1:18965/ua_mocker/", "alive": True}


def _ctx() -> RunContext:
    cfg = RunConfig()
    cfg.run_id = "ua2_a_batch1"
    cfg.local_ip = "127.0.0.1"
    return RunContext(config=cfg, emitter=MagicMock(), evidence_root=None, log_path=None, cancellation_token=None)


def _cc(case_id: str) -> CaseContext:
    return CaseContext(case_id=case_id, title="t", registry=ResourceRegistry())


def test_022_group_query_passes_assertion(monkeypatch):
    monkeypatch.setattr(qx, "ensure_mock_ready", lambda *a, **k: None)
    monkeypatch.setattr(qx, "ensure_logged_in", lambda *a, **k: None)
    monkeypatch.setattr(qx, "require_shared_datasource", lambda *a, **k: dict(TYPES_DS))
    monkeypatch.setattr(qx, "create_case_tag", lambda *a, **k: {"id": 501, "name": "ua_case_ua2_UA-2-2-022_t22_ns001"})
    monkeypatch.setattr(qx, "cleanup_case_tag", lambda *a, **k: None)
    monkeypatch.setattr("tpt_api.datahub.add_tag_group", lambda api, **kw: {"id": "9001"})
    monkeypatch.setattr("tpt_api.datahub.add_tag_group_relation", lambda *a, **k: None)
    monkeypatch.setattr("tpt_api.datahub.delete_tag_group", lambda *a, **k: None)
    monkeypatch.setattr(
        "tpt_api.datahub.query_tags_with_quality",
        lambda api, **kw: {"tagInfoList": {"records": [{"tagName": "ua_case_ua2_UA-2-2-022_t22_ns001"}]}},
    )
    monkeypatch.setattr(qx, "_api", lambda ctx: object())

    status = qx.query_group_cases(_ctx(), _cc("UA-2-2-022"), {"id": "UA-2-2-022"}, "UA-2-2-022")
    assert status == CaseStatus.PASS


def test_014_empty_base_reject_no_residual(monkeypatch):
    monkeypatch.setattr(create_rt, "ensure_mock_ready", lambda *a, **k: None)
    monkeypatch.setattr(create_rt, "ensure_logged_in", lambda *a, **k: None)
    monkeypatch.setattr(create_rt, "_types_ds", lambda ctx: dict(TYPES_DS))
    monkeypatch.setattr(create_rt, "try_add_tag", lambda *a, **k: (False, "rejected"))
    monkeypatch.setattr(create_rt, "active_rows", lambda ctx, **kw: [])
    monkeypatch.setattr(create_rt, "exact", lambda rows, field, val: rows)
    monkeypatch.setattr(create_rt, "cleanup_case_tag", lambda *a, **k: None)

    status = create_rt.dispatch_ua2_1(_ctx(), _cc("UA-2-1-014"), {"id": "UA-2-1-014"})
    assert status == CaseStatus.PASS


def test_058_update_base_mapping(monkeypatch):
    tag_name = "ua_case_ua2_UA-2-2-058_58_ns001"
    update_calls: list[dict] = []
    base_counter = {"n": 0}

    monkeypatch.setattr(qx, "require_shared_datasource", lambda *a, **k: dict(TYPES_DS))
    monkeypatch.setattr(qx, "create_case_tag", lambda *a, **k: {"id": 601, "name": tag_name})
    monkeypatch.setattr(qx, "cleanup_case_tag", lambda *a, **k: None)
    monkeypatch.setattr(qx, "exact", lambda rows, field, val: rows)
    monkeypatch.setattr("ua_test_harness.ua2_browse.pick_unused_nodes", lambda *a, **k: [{}, {}])

    def node_base(_n):
        v = "2_base_a" if base_counter["n"] == 0 else "2_base_b"
        base_counter["n"] += 1
        return v

    monkeypatch.setattr("ua_test_harness.ua2_browse.node_base_name", node_base)

    def fake_active(ctx, **kw):
        tb = kw.get("tagBaseName")
        tn = kw.get("tagName")
        if tb == "2_base_a":
            return []
        if tb == "2_base_b":
            return [{"id": 601, "tagName": tag_name, "tagBaseName": "2_base_b", "dsId": 100}]
        if tn == tag_name:
            return [{"id": 601, "tagName": tag_name, "tagBaseName": "2_base_a", "dsId": 100, "dataType": 6, "frequency": 10, "unit": ""}]
        return []

    monkeypatch.setattr(qx, "active_rows", fake_active)
    monkeypatch.setattr(
        "tpt_api.datahub.update_tag",
        lambda *a, **k: update_calls.append(dict(k)) or {},
    )
    monkeypatch.setattr("ua_test_harness.ua2_precise.config_page_row", lambda *a, **k: {"tagBaseName": "2_base_b"})
    monkeypatch.setattr("ua_test_harness.ua2_precise.rt_row", lambda *a, **k: {"tagValue": 1})
    monkeypatch.setattr(qx, "_api", lambda ctx: object())

    status = qx.result_update_cases(_ctx(), _cc("UA-2-2-058"), {"id": "UA-2-2-058"}, "UA-2-2-058")
    assert status == CaseStatus.PASS
    assert update_calls and update_calls[0].get("tag_base_name") == "2_base_b"


def test_059_group_move(monkeypatch):
    tag_name = "ua_case_ua2_UA-2-2-059_59_ns001"
    group_counter = {"n": 0}

    monkeypatch.setattr(qx, "require_shared_datasource", lambda *a, **k: dict(TYPES_DS))
    monkeypatch.setattr(qx, "create_case_tag", lambda *a, **k: {"id": 701, "name": tag_name})
    monkeypatch.setattr(qx, "cleanup_case_tag", lambda *a, **k: None)

    def fake_add_group(api, **kw):
        group_counter["n"] += 1
        return {"id": f"g{group_counter['n']}"}

    monkeypatch.setattr("tpt_api.datahub.add_tag_group", fake_add_group)
    monkeypatch.setattr("tpt_api.datahub.add_tag_group_relation", lambda *a, **k: None)
    monkeypatch.setattr("tpt_api.datahub.batch_update_tags", lambda *a, **k: None)
    monkeypatch.setattr("tpt_api.datahub.delete_tag_group", lambda *a, **k: None)

    def fake_qtwq(api, **kw):
        gid = str(kw.get("group_id") or "")
        if gid == "g1":
            return {"tagInfoList": {"records": []}}
        if gid == "g2":
            return {"tagInfoList": {"records": [{"id": 701, "tagName": tag_name}]}}
        return {"tagInfoList": {"records": []}}

    monkeypatch.setattr("tpt_api.datahub.query_tags_with_quality", fake_qtwq)
    monkeypatch.setattr(qx, "_api", lambda ctx: object())

    status = qx.result_update_cases(_ctx(), _cc("UA-2-2-059"), {"id": "UA-2-2-059"}, "UA-2-2-059")
    assert status == CaseStatus.PASS
