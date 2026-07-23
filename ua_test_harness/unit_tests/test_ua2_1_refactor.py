"""UA-2-1 refactor tests: shared DS + explicit case-private tag lifecycle.

Verifies the 4 handlers (017/019/021/022) drop prepare_datasource, use
require_shared_datasource("types") + create_case_tag/cleanup_case_tag, and
clean up case tags in finally. No real TPT traffic: all tpt_api calls and
provisioning calls are monkeypatched.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import ua_test_harness.ua2_common as ua2_common
import ua_test_harness.ua2_create_runtime as rt
from ua_test_harness.assertions import AssertFail
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


def _ctx() -> RunContext:
    cfg = RunConfig()
    cfg.run_id = "ua2_1_refactor_run"
    cfg.local_ip = "127.0.0.1"
    cfg.mock.endpoints.functional = "opc.tcp://127.0.0.1:18965/ua_mocker/"
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


class _Calls:
    """Track cross-layer calls in a single object."""
    def __init__(self):
        self.require_shared: list[str] = []
        self.create_case_tag: list[str] = []
        self.cleanup_case_tag: list[tuple[int, str]] = []
        self.physical_delete_tag: list[int] = []
        self.create_tag_raw: list[str] = []
        self.active_rows: list[dict] = []
        self.add_tag_by_name: list[str] = []
        self.prepare_datasource: list = []


def _patch_env(monkeypatch, calls: _Calls, *,
               create_case_tag_id: int = 500,
               require_returns: dict | None = None,
               add_tag_raises_for: callable | None = None,
               create_tag_raw_id: int | None = None,
               create_tag_raw_raises: bool = False):
    """Common mocks: skip ensure_*; route ops through call tracker.

    create_case_tag: returns a deterministic record + registers a fallback on cc.registry
    create_tag_raw: optionally raises (boundary rejected) or returns id
    _add_tag_by_name: raises for matching name (used by duplicate test)
    """
    monkeypatch.setattr(rt, "ensure_mock_ready", lambda ctx, key="functional": None)
    monkeypatch.setattr(rt, "ensure_logged_in", lambda ctx: None)

    def fake_require(ctx, name):
        calls.require_shared.append(name)
        return require_returns if require_returns is not None else dict(TYPES_DS)
    monkeypatch.setattr(rt, "require_shared_datasource", fake_require)

    def fake_create_case_tag(ctx, cc, ds_id, *, suffix="tag", **kw):
        calls.create_case_tag.append(suffix)
        n = f"ua_case_ua2_{cc.case_id}_{suffix}_ns001"
        # register a real fallback so cleanup_case_tag can pop it
        cc.registry.register(
            f"tag:{n}", "tag",
            lambda: calls.physical_delete_tag.append(create_case_tag_id),
            payload={"id": create_case_tag_id, "name": n},
        )
        return {"id": create_case_tag_id, "name": n}
    monkeypatch.setattr(rt, "create_case_tag", fake_create_case_tag)

    def fake_cleanup_case_tag(ctx, cc, tag_id, tag_name):
        calls.cleanup_case_tag.append((tag_id, tag_name))
        # mimic the real cleanup: delete + pop (pop here means registry entry removed)
        calls.physical_delete_tag.append(tag_id)
        cc.registry.pop(f"tag:{tag_name}")
    monkeypatch.setattr(rt, "cleanup_case_tag", fake_cleanup_case_tag)

    def fake_create_tag_raw(ctx, name, ds_id, **kw):
        calls.create_tag_raw.append(name)
        if create_tag_raw_raises:
            raise Exception("boundary name rejected by server")
        rid = create_tag_raw_id if create_tag_raw_id is not None else 600
        return {"id": rid, "name": name}
    monkeypatch.setattr(rt, "create_tag_raw", fake_create_tag_raw)

    def fake_physical_delete_tag(ctx, tag_id):
        calls.physical_delete_tag.append(tag_id)
    monkeypatch.setattr(rt, "physical_delete_tag", fake_physical_delete_tag)

    def fake_active_rows(ctx, **kw):
        calls.active_rows.append(kw)
        return []
    monkeypatch.setattr(rt, "active_rows", fake_active_rows)

    monkeypatch.setattr(rt, "exact", lambda rows, field, value: [r for r in rows if r.get(field) == value])

    def fake_add_tag_by_name(ctx, ds_id, name):
        calls.add_tag_by_name.append(name)
        if add_tag_raises_for is not None and add_tag_raises_for(name):
            raise Exception(f"server rejected name {name!r}")
        return {"id": 999, "tagName": name}
    monkeypatch.setattr(rt, "_add_tag_by_name", fake_add_tag_by_name)

    return calls


# --- 1. 017 happy path: duplicate rejected, original unchanged, cleanup runs ---

def test_017_uses_shared_ds_and_cleans_tag(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-1-017")
    calls = _Calls()

    # active_rows returns the original record so duplicate_rejected check fires
    def fake_active_rows(ctx, **kw):
        calls.active_rows.append(kw)
        return [{"id": 500, "dsId": 100, "tagName": "ua_case_ua2_UA-2-1-017_dup_ns001",
                 "tagBaseName": "2_ua_case_ua2_UA-2-1-017_dup_ns001"}]
    _patch_env(monkeypatch, calls, add_tag_raises_for=lambda n: True)
    monkeypatch.setattr(rt, "active_rows", fake_active_rows)

    status = rt.duplicate_name_rejected(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]           # require_shared_datasource("types") called once
    assert calls.create_case_tag == ["dup"]            # case tag created with suffix="dup"
    assert len(calls.add_tag_by_name) == 1            # duplicate attempt made
    assert calls.cleanup_case_tag                     # cleanup_case_tag called in finally
    assert calls.cleanup_case_tag[0][0] == 500
    assert cc.registry.size() == 0                    # tag was popped from registry


# --- 2. 017 fail path: duplicate NOT rejected -> handler raises AssertFail; cleanup still runs ---

def test_017_assert_fail_kept_and_cleanup_runs(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-1-017")
    calls = _Calls()

    # _add_tag_by_name returns id (not raise) -> rejected stays False -> check_true raises AssertFail
    def fake_active_rows(ctx, **kw):
        calls.active_rows.append(kw)
        return [{"id": 500, "dsId": 100, "tagName": "ua_case_ua2_UA-2-1-017_dup_ns001",
                 "tagBaseName": "2_ua_case_ua2_UA-2-1-017_dup_ns001"}]
    _patch_env(monkeypatch, calls, add_tag_raises_for=lambda n: False)
    monkeypatch.setattr(rt, "active_rows", fake_active_rows)

    with pytest.raises(AssertFail):
        rt.duplicate_name_rejected(ctx, cc)

    # Even though the handler raised, finally must have run:
    assert calls.cleanup_case_tag                      # cleanup_case_tag ran
    assert calls.cleanup_case_tag[0][0] == 500
    assert cc.registry.size() == 0                     # registry popped


# --- 3. 019 empty name rejected -> PASS, no case tag created ---

def test_019_no_tag_created_passes(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-1-019")
    calls = _Calls()

    # _add_tag_by_name("") raises; active_rows("") returns []
    _patch_env(monkeypatch, calls, add_tag_raises_for=lambda n: n == "")
    # default fake_active_rows already returns []

    status = rt.empty_name_rejected(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]           # shared DS looked up
    assert calls.create_case_tag == []                 # NO case tag created (empty name path)
    assert calls.add_tag_by_name == [""]               # empty add_tag attempted
    assert cc.registry.size() == 0                     # no fallback registered


# --- 4. 021 length=127 accepted: tag created, byte-equal, cleanup ---

def test_021_length_127_cleans_tag(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-1-021")
    calls = _Calls()

    # active_rows returns the boundary tag record (accepted)
    created_name: list[str] = []
    def fake_create_tag_raw_recorded(ctx, name, ds_id, **kw):
        calls.create_tag_raw.append(name)
        created_name.append(name)
        return {"id": 700, "name": name}
    _patch_env(monkeypatch, calls, create_tag_raw_id=700, create_tag_raw_raises=False)
    monkeypatch.setattr(rt, "create_tag_raw", fake_create_tag_raw_recorded)

    def fake_active_rows_recorded(ctx, **kw):
        calls.active_rows.append(kw)
        if not created_name:
            return []
        return [{"id": 700, "dsId": 100, "tagName": created_name[0],
                 "tagBaseName": "2_" + created_name[0]}]
    monkeypatch.setattr(rt, "active_rows", fake_active_rows_recorded)

    status = rt.name_length_127(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]           # shared DS looked up
    assert len(calls.create_tag_raw) == 1              # boundary tag created
    assert len(created_name) == 1
    assert len(created_name[0]) == 127                 # name is exactly 127 bytes
    assert created_name[0].startswith("ua_case_ua2_")  # case-private prefix
    assert "127" in created_name[0]                    # contains length marker
    assert cc.registry.size() == 0                     # cleanup_case_tag popped the fallback


# --- 5. 022 length=128 rejected: server rejects, no partial record, PASS ---

def test_022_length_128_rejected_no_leak(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-1-022")
    calls = _Calls()

    # create_tag_raw raises (server rejected 128-byte name); active_rows returns []
    _patch_env(monkeypatch, calls, create_tag_raw_raises=True)

    status = rt.name_length_128(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]           # shared DS looked up
    assert len(calls.create_tag_raw) == 1              # attempted boundary tag
    assert cc.registry.size() == 0                     # no fallback registered (create_tag_raw raised before register)


# --- 6. None of the 4 handlers call prepare_datasource ---

def test_no_prepare_datasource(monkeypatch):
    """None of the 4 handlers should ever call ua2_common.prepare_datasource.

    Strategy: monkeypatch ua2_common.prepare_datasource to raise on call,
    set up enough mocks to run each handler end-to-end, then assert none triggered it.
    """
    prep_calls = []

    def exploding_prepare(*args, **kwargs):
        prep_calls.append((args, kwargs))
        raise RuntimeError("prepare_datasource must NOT be called in the new UA-2-1 path")

    monkeypatch.setattr(ua2_common, "prepare_datasource", exploding_prepare)

    # ---------- 017 happy path ----------
    calls017 = _Calls()
    def ar017(ctx, **kw):
        calls017.active_rows.append(kw)
        return [{"id": 500, "dsId": 100,
                 "tagName": "ua_case_ua2_UA-2-1-017_dup_ns001",
                 "tagBaseName": "2_ua_case_ua2_UA-2-1-017_dup_ns001"}]
    _patch_env(monkeypatch, calls017, add_tag_raises_for=lambda n: True)
    monkeypatch.setattr(rt, "active_rows", ar017)
    rt.duplicate_name_rejected(_ctx(), _cc("UA-2-1-017"))

    # ---------- 019 empty ----------
    calls019 = _Calls()
    _patch_env(monkeypatch, calls019, add_tag_raises_for=lambda n: n == "")
    rt.empty_name_rejected(_ctx(), _cc("UA-2-1-019"))

    # ---------- 021 accepted ----------
    calls021 = _Calls()
    n127: list[str] = []
    def ctr021(ctx, name, ds_id, **kw):
        calls021.create_tag_raw.append(name)
        n127.append(name)
        return {"id": 700, "name": name}
    _patch_env(monkeypatch, calls021, create_tag_raw_id=700)
    monkeypatch.setattr(rt, "create_tag_raw", ctr021)
    def ar021(ctx, **kw):
        calls021.active_rows.append(kw)
        if not n127:
            return []
        return [{"id": 700, "dsId": 100, "tagName": n127[0], "tagBaseName": "2_" + n127[0]}]
    monkeypatch.setattr(rt, "active_rows", ar021)
    rt.name_length_127(_ctx(), _cc("UA-2-1-021"))

    # ---------- 022 rejected ----------
    calls022 = _Calls()
    _patch_env(monkeypatch, calls022, create_tag_raw_raises=True)
    rt.name_length_128(_ctx(), _cc("UA-2-1-022"))

    assert prep_calls == [], f"prepare_datasource was called: {prep_calls}"


# --- 7. 019 leak fix: platform accepts empty name -> FAIL, but no tag leaks ---

def test_019_leak_cleaned_up_when_platform_accepts_empty_name(monkeypatch):
    """Bug #2 decision A: platform accepts empty name -> case FAIL (AssertFail),
    but the silently-created tag MUST be cleaned up by the finally block (no leak)."""
    ctx = _ctx()
    cc = _cc("UA-2-1-019")
    calls = _Calls()
    # platform ACCEPTS empty name (add_tag_raises_for=None -> returns id 999, no raise)
    _patch_env(monkeypatch, calls)

    with pytest.raises(AssertFail):
        rt.empty_name_rejected(ctx, cc)

    # The leaked tag (id 999) was physically deleted by the finally cleanup.
    assert 999 in calls.physical_delete_tag, calls.physical_delete_tag
