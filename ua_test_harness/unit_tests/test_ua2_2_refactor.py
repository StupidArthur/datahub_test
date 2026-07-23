"""UA-2-2 refactor tests: shared DS + filters pushed to API + fixed closures.

Verifies the 8 handlers (004/005/008/011/015/016/019/033) drop
prepare_datasource, use require_shared_datasource("types") (or "empty" for 019),
push tagName/dsId filters to list_tags, fix the closure late-binding in 011,
and use paginated all_active_rows for 016.

All tpt_api and provisioning calls are monkeypatched; no real TPT traffic.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import ua_test_harness.ua2_common as ua2_common
import ua_test_harness.ua2_query_runtime as rt
from ua_test_harness.config import RunConfig
from ua_test_harness.context import CaseContext, RunContext
from ua_test_harness.models import CaseStatus
from ua_test_harness.resources import ResourceRegistry


TYPES_DS = {
    "id": 100,
    "name": "ua_shared_ua2_types_ds",
    "endpoint": "opc.tcp://127.0.0.1:18965/ua_mocker/",
    "alive": True,
}
EMPTY_DS = {
    "id": 200,
    "name": "ua_shared_ua2_empty_ds",
    "endpoint": "opc.tcp://127.0.0.1:18967/ua_mocker/",
    "alive": True,
}


def _ctx() -> RunContext:
    cfg = RunConfig()
    cfg.run_id = "ua2_2_refactor_run"
    cfg.local_ip = "127.0.0.1"
    cfg.mock.endpoints.functional = "opc.tcp://127.0.0.1:18965/ua_mocker/"
    return RunContext(
        config=cfg,
        emitter=MagicMock(),
        evidence_root=None,
        log_path=None,
        cancellation_token=None,
    )


def _cc(case_id: str = "UA-2-2-004") -> CaseContext:
    return CaseContext(case_id=case_id, title="t", registry=ResourceRegistry())


class _Calls:
    """Track cross-layer calls."""
    def __init__(self):
        self.require_shared: list[str] = []
        self.create_case_tag: list[tuple[str, int]] = []   # (suffix, ds_id)
        self.cleanup_case_tag: list[tuple[int, str]] = []
        self.physical_delete_tag: list[int] = []
        self.active_rows: list[dict] = []
        self.all_active_rows: list[dict] = []
        self.create_tag_raw: list[str] = []
        self.prepare_datasource: list = []


def _patch_env(monkeypatch, calls: _Calls, *,
               shared_ds: dict = TYPES_DS,
               active_rows_records_for: callable | None = None,
               all_active_pages: list[list[dict]] | None = None):
    """Common mocks: route ops through call tracker.

    active_rows_records_for(**filters) -> list[dict]: returns what active_rows() should yield
    all_active_pages: list of pages returned by list_tags (for paginated cases like 016)
    """
    monkeypatch.setattr(rt, "ensure_mock_ready", lambda ctx, key="functional": None)
    monkeypatch.setattr(rt, "ensure_logged_in", lambda ctx: None)

    def fake_require(ctx, name):
        calls.require_shared.append(name)
        if name == "empty":
            return dict(EMPTY_DS)
        return dict(shared_ds) if shared_ds is not TYPES_DS else dict(TYPES_DS)
    monkeypatch.setattr(rt, "require_shared_datasource", fake_require)

    def fake_create_case_tag(ctx, cc, ds_id, *, suffix="tag", **kw):
        calls.create_case_tag.append((suffix, ds_id))
        n = f"ua_case_ua2_{cc.case_id}_{suffix}_ns001"
        tag_id = 800 if int(ds_id) == int(TYPES_DS["id"]) else 801
        cc.registry.register(
            f"tag:{n}", "tag",
            lambda tid=tag_id: calls.physical_delete_tag.append(tid),
            payload={"id": tag_id, "name": n},
        )
        return {"id": tag_id, "name": n}
    monkeypatch.setattr(rt, "create_case_tag", fake_create_case_tag)

    def fake_cleanup_case_tag(ctx, cc, tag_id, tag_name):
        calls.cleanup_case_tag.append((tag_id, tag_name))
        calls.physical_delete_tag.append(tag_id)
        cc.registry.pop(f"tag:{tag_name}")
    monkeypatch.setattr(rt, "cleanup_case_tag", fake_cleanup_case_tag)

    def fake_active_rows(ctx, **kw):
        calls.active_rows.append(kw)
        if active_rows_records_for is not None:
            return active_rows_records_for(**kw)
        return []
    monkeypatch.setattr(rt, "active_rows", fake_active_rows)

    def fake_all_active_rows(ctx, **kw):
        calls.all_active_rows.append(kw)
        if all_active_pages is None:
            return []
        out: list[dict] = []
        for page in all_active_pages:
            out.extend(page)
        return out
    monkeypatch.setattr(rt, "all_active_rows", fake_all_active_rows)

    monkeypatch.setattr(rt, "exact", lambda rows, field, value: [r for r in rows if r.get(field) == value])

    return calls


# --- 1. UA-2-2-019: uses empty DS, dsId filter, no tag ---

def test_019_uses_empty_shared_ds_with_ds_id_filter(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-2-019")
    calls = _Calls()

    def ar(**kw):
        # Only return [] when dsId filter is used (the server-side scope)
        if "dsId" in kw:
            return []
        # If called without dsId, that would mean global fetch -- flag as wrong
        return [{"id": 999, "tagName": "leaked"}]
    _patch_env(monkeypatch, calls, active_rows_records_for=ar)

    status = rt.query_empty_datasource(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["empty"]            # uses EMPTY shared DS
    assert calls.create_case_tag == []                  # NO tag created
    assert calls.cleanup_case_tag == []                 # NO cleanup needed
    # All active_rows calls must push dsId down to the API
    assert all("dsId" in kw for kw in calls.active_rows), \
        f"active_rows was called without dsId: {calls.active_rows}"


# --- 2. UA-2-2-004: shared types DS, case tag created + cleaned ---

def test_004_uses_types_ds_and_cleans_tag(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-2-004")
    calls = _Calls()

    tag_name_used: list[str] = []

    def ar(**kw):
        calls.active_rows.append(kw)
        if not tag_name_used:
            return []
        # Server-side tagName filter: return the matching record
        if kw.get("tagName") == tag_name_used[0]:
            return [{
                "id": 800, "dsId": 100, "tagName": tag_name_used[0],
                "tagBaseName": "2_" + tag_name_used[0], "tagType": 1,
                "dataType": 6, "unit": "", "frequency": 1,
                "onlyRead": False, "needPush": True, "tagDesc": "ua-2-2 precise batch",
            }]
        return []

    def cct(ctx, cc, ds_id, *, suffix="tag", **kw):
        calls.create_case_tag.append((suffix, ds_id))
        n = f"ua_case_ua2_{cc.case_id}_{suffix}_ns001"
        tag_name_used.append(n)
        cc.registry.register(
            f"tag:{n}", "tag",
            lambda: calls.physical_delete_tag.append(800),
            payload={"id": 800, "name": n},
        )
        return {"id": 800, "name": n}

    _patch_env(monkeypatch, calls, active_rows_records_for=ar)
    monkeypatch.setattr(rt, "create_case_tag", cct)

    status = rt.query_config_fields(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]
    assert calls.create_case_tag and calls.create_case_tag[0][0] == "cfg"
    assert calls.cleanup_case_tag                       # cleanup ran
    assert cc.registry.size() == 0
    # The query filter must push tagName down to the API
    assert any(kw.get("tagName") == tag_name_used[0] for kw in calls.active_rows)


# --- 3. UA-2-2-011: no closure bug -- two tags both cleaned, registry empty ---

def test_011_no_closure_bug_both_tags_cleaned(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-2-011")
    calls = _Calls()

    created: list[tuple[int, str]] = []

    def cct(ctx, cc, ds_id, *, suffix="tag", **kw):
        calls.create_case_tag.append((suffix, ds_id))
        n = f"ua_case_ua2_{cc.case_id}_{suffix}_ns001"
        rid = 800 + len(created)
        created.append((rid, n))
        cc.registry.register(
            f"tag:{n}", "tag",
            lambda rid=rid: calls.physical_delete_tag.append(rid),
            payload={"id": rid, "name": n},
        )
        return {"id": rid, "name": n}

    def ar(**kw):
        calls.active_rows.append(kw)
        # broad scope (dsId) returns both our tags + maybe others
        if "dsId" in kw:
            return [{"id": rid, "dsId": 100, "tagName": n} for rid, n in created] + \
                   [{"id": 999, "tagName": "other"}]
        # targeted tagName filter
        if "tagName" in kw:
            target = kw["tagName"]
            return [{"id": rid, "dsId": 100, "tagName": n} for rid, n in created if n == target]
        return []

    _patch_env(monkeypatch, calls, active_rows_records_for=ar)
    monkeypatch.setattr(rt, "create_case_tag", cct)

    status = rt.query_clear_name_filter(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]
    # both case tags created (suffixes differ)
    assert len(calls.create_case_tag) == 2
    # both case tags cleaned (NOT shared-variable lambda bug)
    assert len(calls.cleanup_case_tag) == 2, calls.cleanup_case_tag
    cleaned_ids = sorted(tid for tid, _ in calls.cleanup_case_tag)
    expected_ids = sorted(rid for rid, _ in created)
    assert cleaned_ids == expected_ids
    # registry must be empty (no leftover fallback)
    assert cc.registry.size() == 0
    # broad query pushed dsId down to API (not fetch-all)
    assert any(kw.get("dsId") == 100 for kw in calls.active_rows)


# --- 4. UA-2-2-016: paginated fetch via all_active_rows ---

def test_016_uses_all_active_rows_paginated(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-2-016")
    calls = _Calls()

    # Provide 2 pages of records (none matches the impossible base name).
    page_a = [{"id": i, "tagBaseName": f"base_{i}"} for i in range(500)]
    page_b = [{"id": i, "tagBaseName": f"base_{i}"} for i in range(500, 1000)]
    _patch_env(monkeypatch, calls, all_active_pages=[page_a, page_b])

    status = rt.query_missing_base_name(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]
    assert calls.create_case_tag == []                  # no tag created
    assert calls.active_rows == []                      # active_rows NOT used
    assert len(calls.all_active_rows) >= 1              # all_active_rows used
    # active_rows(used for filter queries) should NOT have been called for 016


# --- 5. None of the 8 handlers call prepare_datasource ---

def test_no_prepare_datasource(monkeypatch):
    prep_calls = []

    def exploding_prepare(*args, **kwargs):
        prep_calls.append((args, kwargs))
        raise RuntimeError("prepare_datasource must NOT be called in the new UA-2-2 path")

    monkeypatch.setattr(ua2_common, "prepare_datasource", exploding_prepare)

    # Helper: capture the tag_name passed to create_case_tag, and have
    # active_rows echo it back so handlers can satisfy their assertions.
    tag_capture: list[tuple[str, str]] = []   # (suffix, tag_name)

    def make_cct():
        def fake_cct(ctx, cc, ds_id, *, suffix="tag", tag_base_name=None, **kw):
            n = f"ua_case_ua2_{cc.case_id}_{suffix}_ns001"
            tag_capture.append((suffix, n))
            cc.registry.register(
                f"tag:{n}", "tag",
                lambda: None,
                payload={"id": 800, "name": n},
            )
            return {"id": 800, "name": n}
        return fake_cct

    def make_ar(tag_capture_list):
        def ar(**kw):
            if "tagName" in kw:
                target = kw["tagName"]
                return [{
                    "id": 800, "dsId": 100, "tagName": target,
                    "tagBaseName": "2_" + target, "tagType": 1,
                    "dataType": 6, "unit": "", "frequency": 1,
                    "onlyRead": False, "needPush": True, "tagDesc": "ua-2-2 precise batch",
                }]
            return []
        return ar

    # 004
    tag_capture.clear()
    calls_004 = _Calls()
    _patch_env(monkeypatch, calls_004, active_rows_records_for=make_ar(tag_capture))
    monkeypatch.setattr(rt, "create_case_tag", make_cct())
    rt.query_config_fields(_ctx(), _cc("UA-2-2-004"))

    # 005
    tag_capture.clear()
    calls_005 = _Calls()
    _patch_env(monkeypatch, calls_005, active_rows_records_for=make_ar(tag_capture))
    monkeypatch.setattr(rt, "create_case_tag", make_cct())
    rt.query_repeat_stable(_ctx(), _cc("UA-2-2-005"))

    # 008 query_missing_name
    calls_008 = _Calls()
    _patch_env(monkeypatch, calls_008, active_rows_records_for=lambda **kw: [])
    rt.query_missing_name(_ctx(), _cc("UA-2-2-008"))

    # 011 query_clear_name_filter
    tag_capture.clear()
    def ar_011(**kw):
        if "tagName" in kw:
            return [{"id": 800 + i, "dsId": 100, "tagName": kw["tagName"]}
                    for i, (_, n) in enumerate(tag_capture) if n == kw["tagName"]]
        if "dsId" in kw:
            return [{"id": 800 + i, "dsId": 100, "tagName": n}
                    for i, (_, n) in enumerate(tag_capture)] + \
                   [{"id": 999, "tagName": "other"}]
        return []
    calls_011 = _Calls()
    _patch_env(monkeypatch, calls_011, active_rows_records_for=ar_011)
    monkeypatch.setattr(rt, "create_case_tag", make_cct())
    rt.query_clear_name_filter(_ctx(), _cc("UA-2-2-011"))

    # 015 query_base_name_exact (needs the record to exist for assertions).
    # The handler uses tag_base_name="2_" + "ua_b15_<ns>"; the fake echoes
    # tagName but supplies a predictable tagBaseName matching whatever the
    # case set. We don't know the suffix, so we just always return the same
    # tagBaseName -- this is enough to exercise "passed without AssertionError".
    captured_b15_base: list[str] = []

    def fake_cct_015(ctx, cc, ds_id, *, suffix="tag", tag_base_name=None, **kw):
        calls_015_local = _Calls()  # noqa: F841 - just used for create
        n = f"ua_case_ua2_{cc.case_id}_{suffix}_ns001"
        cc.registry.register(
            f"tag:{n}", "tag",
            lambda: None,
            payload={"id": 800, "name": n},
        )
        if tag_base_name:
            captured_b15_base.append(tag_base_name)
        return {"id": 800, "name": n}

    def ar_015(**kw):
        if "tagName" in kw:
            base = captured_b15_base[0] if captured_b15_base else "2_x"
            return [{
                "id": 800, "dsId": 100, "tagName": kw["tagName"],
                "tagBaseName": base,
            }]
        return []
    calls_015 = _Calls()
    _patch_env(monkeypatch, calls_015, active_rows_records_for=ar_015)
    monkeypatch.setattr(rt, "create_case_tag", fake_cct_015)
    rt.query_base_name_exact(_ctx(), _cc("UA-2-2-015"))

    # 016 query_missing_base_name
    calls_016 = _Calls()
    _patch_env(monkeypatch, calls_016, all_active_pages=[[]])
    rt.query_missing_base_name(_ctx(), _cc("UA-2-2-016"))

    # 019 query_empty_datasource
    calls_019 = _Calls()
    _patch_env(monkeypatch, calls_019, active_rows_records_for=lambda **kw: [])
    rt.query_empty_datasource(_ctx(), _cc("UA-2-2-019"))

    # 033 shares query_config_fields
    tag_capture.clear()
    calls_033 = _Calls()
    _patch_env(monkeypatch, calls_033, active_rows_records_for=make_ar(tag_capture))
    monkeypatch.setattr(rt, "create_case_tag", make_cct())
    rt.query_config_fields(_ctx(), _cc("UA-2-2-033"))

    assert prep_calls == [], f"prepare_datasource was called: {prep_calls}"


# --- batch 2: UA-2-2-001 / 003 / 006 / 017 / 030 ---

def test_001_list_default_range_no_tag_lifecycle(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-2-001")
    calls = _Calls()
    _patch_env(monkeypatch, calls)

    list_calls: list[dict] = []
    qtq_calls: list[dict] = []

    def fake_list_tags(api, page=1, page_size=10, data=None, sort="-createTime"):
        list_calls.append({"page": page, "page_size": page_size, "data": data})
        return {"records": [{"id": 1}, {"id": 2}], "total": 2}

    def fake_qtq(api, ds_id=None, group_id="0", tag_name="", tag_base_name="",
                 tag_type=1, page=1, page_size=100, sort="-createTime"):
        qtq_calls.append({"group_id": group_id, "page": page, "page_size": page_size})
        return {"tagInfoList": {"records": [{"id": 3}, {"id": 4}]}}

    monkeypatch.setattr("tpt_api.datahub.list_tags", fake_list_tags)
    monkeypatch.setattr("tpt_api.datahub.query_tags_with_quality", fake_qtq)
    monkeypatch.setattr("ua_test_harness.clients.tpt_client.get_api", lambda ctx: object())

    status = rt.query_list_default_range(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]
    assert calls.create_case_tag == []
    assert list_calls and list_calls[0]["page_size"] == 10
    assert qtq_calls and qtq_calls[0]["group_id"] == "0"


def test_003_multi_ds_scoped_queries(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-2-003")
    calls = _Calls()
    tag_t = "ua_case_ua2_UA-2-2-003_mds_t_ns001"
    tag_e = "ua_case_ua2_UA-2-2-003_mds_e_ns001"

    def ar(**kw):
        if kw.get("dsId") == 100:
            return [{"id": 800, "dsId": 100, "tagName": tag_t}]
        if kw.get("dsId") == 200:
            return [{"id": 801, "dsId": 200, "tagName": tag_e}]
        return [{"id": 800, "dsId": 100, "tagName": tag_t}, {"id": 801, "dsId": 200, "tagName": tag_e}]

    _patch_env(monkeypatch, calls, active_rows_records_for=ar)

    qtq_calls: list[dict] = []

    def fake_qtq(api, ds_id=None, **kw):
        qtq_calls.append({"ds_id": ds_id})
        if ds_id == 100:
            return {"tagInfoList": {"records": [{"id": 800, "dsId": 100, "tagName": tag_t}]}}
        if ds_id == 200:
            return {"tagInfoList": {"records": [{"id": 801, "dsId": 200, "tagName": tag_e}]}}
        return {"tagInfoList": {"records": []}}

    monkeypatch.setattr("tpt_api.datahub.query_tags_with_quality", fake_qtq)
    monkeypatch.setattr("ua_test_harness.clients.tpt_client.get_api", lambda ctx: object())

    status = rt.query_multi_datasource_set(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types", "empty"]
    assert ("mds_t", 100) in calls.create_case_tag
    assert ("mds_e", 200) in calls.create_case_tag
    assert (800, tag_t) in calls.cleanup_case_tag
    assert (801, tag_e) in calls.cleanup_case_tag
    assert {c["ds_id"] for c in qtq_calls} == {100, 200}


def test_006_full_tag_name_exact_hit(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-2-006")
    calls = _Calls()
    tag_name = "ua_case_ua2_UA-2-2-006_fn_ns001"

    def ar(**kw):
        if kw.get("tagName") == tag_name:
            return [{"id": 800, "dsId": 100, "tagName": tag_name}]
        return []

    _patch_env(monkeypatch, calls, active_rows_records_for=ar)
    status = rt.query_full_tag_name(ctx, cc)

    assert status == CaseStatus.PASS
    assert any(kw.get("tagName") == tag_name for kw in calls.active_rows)


def test_017_single_ds_scope(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-2-017")
    calls = _Calls()
    tag_name = "ua_case_ua2_UA-2-2-017_sd_ns001"

    def ar(**kw):
        if kw.get("dsId") == 100:
            return [
                {"id": 800, "dsId": 100, "tagName": tag_name},
                {"id": 801, "dsId": 100, "tagName": "other"},
            ]
        return []

    _patch_env(monkeypatch, calls, active_rows_records_for=ar)
    status = rt.query_single_datasource(ctx, cc)

    assert status == CaseStatus.PASS
    assert all(kw.get("dsId") == 100 for kw in calls.active_rows if "dsId" in kw)


def test_030_contradictory_filters_empty_on_wrong_ds(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-2-030")
    calls = _Calls()
    tag_name = "ua_case_ua2_UA-2-2-030_ct_ns001"

    def ar(**kw):
        if kw.get("dsId") == 200 and kw.get("tagName") == tag_name:
            return []
        if kw.get("dsId") == 100 and kw.get("tagName") == tag_name:
            return [{"id": 800, "dsId": 100, "tagName": tag_name}]
        return []

    _patch_env(monkeypatch, calls, active_rows_records_for=ar)
    status = rt.query_contradictory_filters(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types", "empty"]