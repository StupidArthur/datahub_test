"""UA-2-4 refactor tests: shared DS + explicit tag lifecycle (soft/restore/physical).

Verifies the 4 handlers (001/013/020/024) drop prepare_datasource, use
require_shared_datasource("types") + create_case_tag/cleanup_case_tag, and
follow the explicit lifecycle:
  - 001: soft-delete -> assert active empty + recycle contains same id; cleanup deletes
  - 013: soft-delete -> restore -> assert active contains same id + recycle empty; cleanup deletes
  - 020: soft-delete -> physical-delete (test action) -> pop registry; cleanup is safe no-op
  - 024: soft-delete -> physical-delete -> attempt restore (must run assertions, not silent)

All tpt_api and provisioning calls are monkeypatched; no real TPT traffic.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import ua_test_harness.ua2_common as ua2_common
import ua_test_harness.ua2_recycle_runtime as rt
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
    cfg.run_id = "ua2_4_refactor_run"
    cfg.local_ip = "127.0.0.1"
    cfg.mock.endpoints.functional = "opc.tcp://127.0.0.1:18965/ua_mocker/"
    return RunContext(
        config=cfg,
        emitter=MagicMock(),
        evidence_root=None,
        log_path=None,
        cancellation_token=None,
    )


def _cc(case_id: str = "UA-2-4-001") -> CaseContext:
    return CaseContext(case_id=case_id, title="t", registry=ResourceRegistry())


class _Calls:
    """Track cross-layer calls."""
    def __init__(self):
        self.require_shared: list[str] = []
        self.create_case_tag: list[tuple[str, int]] = []
        self.cleanup_case_tag: list[tuple[int, str]] = []
        self.physical_delete_tag: list[int] = []
        self.soft_delete_tag: list[int] = []
        self.restore_tag: list[int] = []
        self.active_rows: list[dict] = []
        self.all_recycle_rows: list[dict] = []
        self.registry_pop: list[str] = []
        self.registry_register: list[str] = []
        self.prepare_datasource: list = []


def _patch_env(monkeypatch, calls: _Calls):
    """Common mocks. State (active/recycle rows) is mutated by tests through state vars."""
    state = {
        "active": [],          # list[dict]
        "recycle": [],         # list[dict]
        "tag_names": [],       # list[str] -- in order of creation
    }

    monkeypatch.setattr(rt, "ensure_mock_ready", lambda ctx, key="functional": None)
    monkeypatch.setattr(rt, "ensure_logged_in", lambda ctx: None)

    def fake_require(ctx, name):
        calls.require_shared.append(name)
        return dict(TYPES_DS)
    monkeypatch.setattr(rt, "require_shared_datasource", fake_require)

    def fake_create_case_tag(ctx, cc, ds_id, *, suffix="tag", **kw):
        calls.create_case_tag.append((suffix, ds_id))
        n = f"ua_case_ua2_{cc.case_id}_{suffix}_ns001"
        state["tag_names"].append(n)
        rid = 800 + len(state["tag_names"]) - 1
        # add to active immediately to mimic server-side persistence
        state["active"].append({"id": rid, "dsId": ds_id, "tagName": n})
        # register fallback (real ResourceRegistry)
        captured = {"rid": rid, "name": n}
        def _cleanup_fn():
            calls.physical_delete_tag.append(captured["rid"])
        cc.registry.register(
            f"tag:{n}", "tag",
            _cleanup_fn,
            payload={"id": captured["rid"], "name": captured["name"]},
        )
        calls.registry_register.append(n)
        return {"id": captured["rid"], "name": captured["name"]}
    monkeypatch.setattr(rt, "create_case_tag", fake_create_case_tag)

    def fake_cleanup_case_tag(ctx, cc, tag_id, tag_name):
        calls.cleanup_case_tag.append((tag_id, tag_name))
        calls.physical_delete_tag.append(tag_id)
        # remove from active and recycle
        state["active"] = [r for r in state["active"] if r.get("tagName") != tag_name]
        state["recycle"] = [r for r in state["recycle"] if r.get("tagName") != tag_name]
        # pop registry entry
        cc.registry.pop(f"tag:{tag_name}")
        calls.registry_pop.append(tag_name)
    monkeypatch.setattr(rt, "cleanup_case_tag", fake_cleanup_case_tag)

    def fake_soft_delete_tag(ctx, tag_id):
        calls.soft_delete_tag.append(tag_id)
        # move tag from active to recycle
        for r in state["active"]:
            if int(r.get("id")) == int(tag_id):
                state["recycle"].append(dict(r))
                break
        state["active"] = [r for r in state["active"] if int(r.get("id")) != int(tag_id)]
    monkeypatch.setattr(rt, "soft_delete_tag", fake_soft_delete_tag)

    def fake_restore_tag(ctx, tag_id):
        calls.restore_tag.append(tag_id)
        # try to move from recycle back to active; if not in recycle, raise
        for r in state["recycle"]:
            if int(r.get("id")) == int(tag_id):
                state["active"].append(dict(r))
                break
        else:
            raise RuntimeError("cannot restore: tag not in recycle")
        state["recycle"] = [r for r in state["recycle"] if int(r.get("id")) != int(tag_id)]
    monkeypatch.setattr(rt, "restore_tag", fake_restore_tag)

    def fake_physical_delete_tag(ctx, tag_id):
        calls.physical_delete_tag.append(tag_id)
        state["active"] = [r for r in state["active"] if int(r.get("id")) != int(tag_id)]
        state["recycle"] = [r for r in state["recycle"] if int(r.get("id")) != int(tag_id)]
    monkeypatch.setattr(rt, "physical_delete_tag", fake_physical_delete_tag)

    def fake_active_rows(ctx, **kw):
        calls.active_rows.append(kw)
        if "tagName" in kw:
            target = kw["tagName"]
            return [dict(r) for r in state["active"] if r.get("tagName") == target]
        return [dict(r) for r in state["active"]]
    monkeypatch.setattr(rt, "active_rows", fake_active_rows)

    def fake_all_recycle_rows(ctx):
        calls.all_recycle_rows.append({})
        return [dict(r) for r in state["recycle"]]
    monkeypatch.setattr(rt, "all_recycle_rows", fake_all_recycle_rows)

    monkeypatch.setattr(rt, "exact",
                        lambda rows, field, value: [r for r in rows if r.get(field) == value])

    return state


# --- 1. UA-2-4-001: soft-delete -> active empty + recycle contains same id; cleanup deletes ---

def test_001_soft_delete_uses_shared_ds(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-4-001")
    calls = _Calls()
    state = _patch_env(monkeypatch, calls)

    status = rt.soft_delete_one(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]            # shared DS looked up
    assert len(calls.create_case_tag) == 1
    # soft_delete_tag was called with the tag_id
    assert calls.soft_delete_tag == [800]
    # The handler verified recycle contains the tag (we can't easily inspect
    # mid-flight state because finally cleanup wipes it; the PASS itself
    # implies check_true("recycle_contains") passed).
    assert calls.all_recycle_rows                       # all_recycle_rows was queried
    # cleanup_case_tag ran in finally (registry popped, physical delete invoked)
    assert calls.cleanup_case_tag == [(800, state["tag_names"][0])]
    assert cc.registry.size() == 0
    # After finally: nothing left in either list
    assert state["active"] == []
    assert state["recycle"] == []


# --- 2. UA-2-4-013: create -> soft -> restore -> active; cleanup deletes ---

def test_013_restore_roundtrip(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-4-013")
    calls = _Calls()
    state = _patch_env(monkeypatch, calls)

    status = rt.restore_one(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]
    assert calls.soft_delete_tag == [800]
    assert calls.restore_tag == [800]
    # Mid-flight: after restore_tag, the tag was in active (handler's PASS
    # implies check_eq("restored_id_matches") passed; finally cleanup wipes it).
    # cleanup_case_tag ran
    assert calls.cleanup_case_tag == [(800, state["tag_names"][0])]
    assert cc.registry.size() == 0
    # After finally: nothing left
    assert state["active"] == []
    assert state["recycle"] == []


# --- 3. UA-2-4-020: physical delete pops registry; finally cleanup safe no-op ---

def test_020_physical_delete_pops_registry(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-4-020")
    calls = _Calls()
    state = _patch_env(monkeypatch, calls)

    status = rt.physical_delete_one(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]
    assert calls.soft_delete_tag == [800]
    # physical_delete_tag called at least once for the test action (the finally cleanup
    # is a no-op because registry was popped, but the case body still calls it).
    assert 800 in calls.physical_delete_tag
    # After physical_delete, tag is gone from active + recycle
    assert not any(int(r.get("id")) == 800 for r in state["active"])
    assert not any(int(r.get("id")) == 800 for r in state["recycle"])
    # Registry was popped by the case body (test action) — registry empty afterwards
    assert cc.registry.size() == 0
    # registry_pop was called with the tag name (in the case body, not just finally)
    assert state["tag_names"][0] in calls.registry_pop


# --- 4. UA-2-4-024: restore attempt captured; asserts run; FAIL not masked ---

def test_024_irreversible_asserts_no_recreate(monkeypatch):
    ctx = _ctx()
    cc = _cc("UA-2-4-024")
    calls = _Calls()
    state = _patch_env(monkeypatch, calls)

    status = rt.physical_delete_irreversible(ctx, cc)

    assert status == CaseStatus.PASS
    assert calls.require_shared == ["types"]
    assert calls.soft_delete_tag == [800]
    # The restore attempt was made (test action). It raised because tag already gone.
    assert calls.restore_tag == [800]
    # active and recycle both have no record for this tag_id
    assert not any(int(r.get("id")) == 800 for r in state["active"])
    assert not any(int(r.get("id")) == 800 for r in state["recycle"])
    # cleanup_case_tag ran (idempotent — already gone)
    assert calls.cleanup_case_tag == [(800, state["tag_names"][0])]


def test_024_assert_fail_is_not_swallowed_by_restore_catch(monkeypatch):
    """If restore raises an UNEXPECTED error inside the try/except, the final
    assertions MUST still run and propagate AssertFail (not be silently swallowed)."""
    ctx = _ctx()
    cc = _cc("UA-2-4-024")
    calls = _Calls()
    state = _patch_env(monkeypatch, calls)

    # Force the next active_rows call (which the final assertion makes) to raise AssertFail
    # via a non-matching tagName (i.e. the tag was leaked into active unexpectedly).
    def fake_active_rows_leaked(ctx, **kw):
        calls.active_rows.append(kw)
        # Simulate: somehow the tag leaked back into active with the same id
        if "tagName" in kw:
            target = kw["tagName"]
            return [{"id": 800, "dsId": 100, "tagName": target}]
        return []
    monkeypatch.setattr(rt, "active_rows", fake_active_rows_leaked)

    # Now the final assertion `check_eq("no_surreptitious_recreate_active", 0, len(rows_a))`
    # must raise AssertFail. The try/except for restore_tag must NOT swallow it.
    with pytest.raises(AssertFail):
        rt.physical_delete_irreversible(ctx, cc)


# --- 5. None of the 4 handlers call prepare_datasource ---

def test_no_prepare_datasource(monkeypatch):
    prep_calls = []

    def exploding_prepare(*args, **kwargs):
        prep_calls.append((args, kwargs))
        raise RuntimeError("prepare_datasource must NOT be called in the new UA-2-4 path")

    monkeypatch.setattr(ua2_common, "prepare_datasource", exploding_prepare)

    # 001
    calls_001 = _Calls()
    _patch_env(monkeypatch, calls_001)
    rt.soft_delete_one(_ctx(), _cc("UA-2-4-001"))

    # 013
    calls_013 = _Calls()
    _patch_env(monkeypatch, calls_013)
    rt.restore_one(_ctx(), _cc("UA-2-4-013"))

    # 020
    calls_020 = _Calls()
    _patch_env(monkeypatch, calls_020)
    rt.physical_delete_one(_ctx(), _cc("UA-2-4-020"))

    # 024
    calls_024 = _Calls()
    _patch_env(monkeypatch, calls_024)
    rt.physical_delete_irreversible(_ctx(), _cc("UA-2-4-024"))

    assert prep_calls == [], f"prepare_datasource was called: {prep_calls}"