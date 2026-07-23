"""Unit tests for ua_test_harness.ua2_ops (thin single-action ops layer).

All tests monkeypatch tpt_api.datahub and ua_test_harness.clients.tpt_client.get_api;
no real API is ever called. cc.registry is a REAL ResourceRegistry so registry
state (register/pop/size/snapshot) is exercised end-to-end.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import tpt_api.datahub as dh
import ua_test_harness.clients.tpt_client as tc
import ua_test_harness.ua2_ops as ops
from ua_test_harness.config import RunConfig
from ua_test_harness.context import CaseContext, RunContext
from ua_test_harness.resources import ResourceRegistry
from ua_test_harness.ua2_ops import (
    CASE_TAG_PREFIX,
    all_active_rows,
    all_recycle_rows,
    case_tag_name,
    cleanup_case_tag,
    create_case_tag,
    create_datasource_raw,
    create_tag_raw,
    wait_tag_absent,
)


def _ctx() -> RunContext:
    cfg = RunConfig()
    cfg.run_id = "ua2_ops_test_run"
    cfg.local_ip = "127.0.0.1"
    return RunContext(
        config=cfg,
        emitter=MagicMock(),
        evidence_root=None,
        log_path=None,
        cancellation_token=None,
    )


def _cc(case_id: str = "UA-2-1-017") -> CaseContext:
    # Real ResourceRegistry so register/pop/size/snapshot are exercised.
    return CaseContext(case_id=case_id, title="t", registry=ResourceRegistry())


def _patch_get_api(monkeypatch, api=None):
    monkeypatch.setattr(tc, "get_api", lambda ctx: api or MagicMock())


# 1. create_tag_raw calls add_tag exactly once; NEVER calls delete_tags_physical.
def test_create_tag_raw_does_not_predelete(monkeypatch):
    calls = {"add_tag": 0, "delete_physical": 0}

    def fake_add_tag(api, **kw):
        calls["add_tag"] += 1
        return {"id": 101}

    def fake_del_phys(api, ids):
        calls["delete_physical"] += 1
        return {}

    monkeypatch.setattr(dh, "add_tag", fake_add_tag)
    monkeypatch.setattr(dh, "delete_tags_physical", fake_del_phys)
    _patch_get_api(monkeypatch)

    ctx = _ctx()
    res = create_tag_raw(ctx, "ua_case_ua2_x", 7)

    assert calls["add_tag"] == 1
    assert calls["delete_physical"] == 0
    assert res["id"] == 101
    assert res["name"] == "ua_case_ua2_x"


# 2. create_datasource_raw calls add_ds_info once; NEVER change_ds_state.
def test_create_datasource_raw_does_not_auto_enable(monkeypatch):
    calls = {"add_ds": 0, "change_state": 0}

    def fake_add_ds(api, **kw):
        calls["add_ds"] += 1
        return {"id": 9}

    def fake_change(api, ds_id, enabled):
        calls["change_state"] += 1
        return {}

    monkeypatch.setattr(dh, "add_ds_info", fake_add_ds)
    monkeypatch.setattr(dh, "change_ds_state", fake_change)
    _patch_get_api(monkeypatch)

    ctx = _ctx()
    res = create_datasource_raw(ctx, "ua_case_ua2_ds_x", "opc.tcp://127.0.0.1:18965/ua_mocker/")

    assert calls["add_ds"] == 1
    assert calls["change_state"] == 0
    assert res["id"] == 9
    assert res["name"] == "ua_case_ua2_ds_x"
    assert res["endpoint"] == "opc.tcp://127.0.0.1:18965/ua_mocker/"


# 3. case_tag_name starts with prefix and contains the case_id.
def test_case_tag_name_uses_prefix(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-1-017")
    name = case_tag_name(ctx, cc, "dup")
    assert name.startswith(CASE_TAG_PREFIX)
    # case_id with '-' replaced by '_' is embedded in the name
    assert "UA_2_1_017" in name
    assert "dup" in name


# 4. create_case_tag registers a "tag:{name}" fallback on cc.registry.
def test_create_case_tag_registers_fallback(monkeypatch):
    monkeypatch.setattr(dh, "add_tag", lambda api, **kw: {"id": 55})
    _patch_get_api(monkeypatch)

    ctx = _ctx()
    cc = _cc("UA-2-1-017")
    tag = create_case_tag(ctx, cc, 7, suffix="tag")
    name = tag["name"]

    assert cc.registry.size() == 1
    snap = cc.registry.snapshot()
    assert snap[0]["name"] == f"tag:{name}"
    assert snap[0]["kind"] == "tag"
    assert tag["id"] == 55


# 5. cleanup_case_tag: physical_delete_tag called, wait_tag_absent True, registry popped.
def test_cleanup_case_tag_deletes_and_pops(monkeypatch):
    calls = {"delete_physical": 0}

    monkeypatch.setattr(dh, "add_tag", lambda api, **kw: {"id": 77})

    def fake_del_phys(api, ids):
        calls["delete_physical"] += 1
        return {}

    monkeypatch.setattr(dh, "delete_tags_physical", fake_del_phys)
    # find_tag_by_name -> query_tags_with_quality empty -> wait_tag_absent returns True (no sleep)
    monkeypatch.setattr(dh, "query_tags_with_quality", lambda api, **kw: {"tagInfoList": {"records": []}})
    _patch_get_api(monkeypatch)

    ctx = _ctx()
    cc = _cc("UA-2-1-017")
    tag = create_case_tag(ctx, cc, 7, suffix="tag")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    assert cc.registry.size() == 1

    cleanup_case_tag(ctx, cc, tag_id, tag_name)

    assert calls["delete_physical"] == 1
    assert cc.registry.size() == 0  # popped
    # explicit: under the fake (empty records) wait_tag_absent returns True
    assert wait_tag_absent(ctx, tag_name) is True


# 6. cleanup_case_tag SWALLOWS: physical_delete_tag raises -> no raise, entry remains.
def test_cleanup_case_tag_swallows_error(monkeypatch):
    monkeypatch.setattr(dh, "add_tag", lambda api, **kw: {"id": 88})

    def raising_physical_delete(ctx, tag_id):
        raise RuntimeError("boom")

    monkeypatch.setattr(ops, "physical_delete_tag", raising_physical_delete)
    _patch_get_api(monkeypatch)

    ctx = _ctx()
    cc = _cc("UA-2-1-017")
    tag = create_case_tag(ctx, cc, 7, suffix="tag")
    tag_id, tag_name = int(tag["id"]), tag["name"]
    assert cc.registry.size() == 1

    # must NOT raise
    cleanup_case_tag(ctx, cc, tag_id, tag_name)

    # registry entry REMAINS (pop never reached because physical_delete_tag raised)
    assert cc.registry.size() == 1
    snap = cc.registry.snapshot()
    assert snap[0]["name"] == f"tag:{tag_name}"


# 7. create_case_tag does NOT pre-delete even if a same-name tag exists.
def test_create_case_tag_no_predelete(monkeypatch):
    calls = {"delete_physical": 0}

    monkeypatch.setattr(dh, "add_tag", lambda api, **kw: {"id": 99})

    def fake_del_phys(api, ids):
        calls["delete_physical"] += 1
        return {}

    monkeypatch.setattr(dh, "delete_tags_physical", fake_del_phys)
    # simulate a same-name tag already existing; create_case_tag must not consult/delete it
    monkeypatch.setattr(dh, "query_tags_with_quality", lambda api, **kw: {
        "tagInfoList": {"records": [{"id": 999, "tagName": "preexisting"}]}
    })
    _patch_get_api(monkeypatch)

    ctx = _ctx()
    cc = _cc("UA-2-1-017")
    tag = create_case_tag(ctx, cc, 7, suffix="tag")

    assert calls["delete_physical"] == 0  # no implicit pre-clean
    assert cc.registry.size() == 1
    assert tag["id"] == 99


# 8. all_active_rows PAGINATES: 2 full pages (500 each) then empty -> 1000.
def test_all_active_rows_paginates(monkeypatch):
    pages: list[int] = []

    def fake_qtq(api, ds_id=None, group_id="0", tag_name="", tag_base_name="",
                 page=1, page_size=100, sort="-createTime"):
        pages.append(page)
        if page == 1:
            return {"tagInfoList": {"records": [{"id": i} for i in range(500)]}}
        if page == 2:
            return {"tagInfoList": {"records": [{"id": i} for i in range(500, 1000)]}}
        return {"tagInfoList": {"records": []}}

    monkeypatch.setattr(dh, "query_tags_with_quality", fake_qtq)
    _patch_get_api(monkeypatch)

    ctx = _ctx()
    rows = all_active_rows(ctx)

    assert len(rows) == 1000
    assert pages == [1, 2, 3]  # 3rd call returns empty -> stop


# 9. all_recycle_rows PAGINATES: 2 pages -> collects all.
def test_all_recycle_rows_paginates(monkeypatch):
    pages: list[int] = []

    def fake_list_recycle(api, page=1, page_size=200, group_id="1", tag_type=1, sort="-createTime"):
        pages.append(page)
        if page == 1:
            return {"tagInfoList": {"records": [{"id": i} for i in range(200)]}}
        if page == 2:
            return {"tagInfoList": {"records": [{"id": i} for i in range(200, 400)]}}
        return {"tagInfoList": {"records": []}}

    monkeypatch.setattr(dh, "list_recycle_tags", fake_list_recycle)
    _patch_get_api(monkeypatch)

    ctx = _ctx()
    rows = all_recycle_rows(ctx)

    assert len(rows) == 400
    assert pages == [1, 2, 3]  # 3rd call returns empty -> stop
