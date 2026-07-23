"""UA-2 shared baseline provisioning unit tests (no real API calls).

All tpt_api.datahub functions and ua_test_harness.clients.tpt_client.get_api
are monkeypatched. The alive-polling helper (_wait_ds_alive) is monkeypatched
to return True so tests never sleep. Tests assert on CALLS and STATE, never on
source text.
"""
import pytest
from unittest.mock import MagicMock

from ua_test_harness.context import RunContext
from ua_test_harness.config import RunConfig
from ua_test_harness.provisioning.ua2_baseline import (
    BaselineError,
    ensure_ua2_baseline,
    require_shared_datasource,
    teardown_ua2_baseline,
    SHARED_TYPES_DS_NAME,
    SHARED_EMPTY_DS_NAME,
)


def _ctx():
    cfg = RunConfig()
    cfg.run_id = "t"
    cfg.local_ip = "127.0.0.1"
    cfg.mock.endpoints.functional = "opc.tcp://127.0.0.1:18965/ua_mocker/"
    return RunContext(
        config=cfg,
        emitter=MagicMock(),
        evidence_root=None,
        log_path=None,
        cancellation_token=None,
    )


TYPES_EP = "opc.tcp://127.0.0.1:18965/ua_mocker/"
EMPTY_EP = "opc.tcp://127.0.0.1:18967/ua_mocker/"


def _patch_datahub(monkeypatch, *, ds_rows=None, add_raises=None, recycle_rows=None, tag_rows_by_ds=None):
    import tpt_api.datahub as dh
    calls = {"add": [], "change_state": [], "delete": []}

    def fake_list_ds(api, page=1, page_size=10, sort="-createTime", data=None):
        rec = ds_rows or []
        if data and "dsName" in data:
            rec = [r for r in rec if r.get("dsName") == data["dsName"]]
        return {"records": rec, "total": len(rec)}
    monkeypatch.setattr(dh, "list_ds_info", fake_list_ds)

    def fake_add(api, ds_name, ds_type=1, ds_sub_type=4, ds_tar_url="", **kw):
        calls["add"].append(ds_name)
        if add_raises:
            raise add_raises
        return {"id": 999, "dsName": ds_name, "dsTarUrl": ds_tar_url, "alive": False, "dsStatus": 1}
    monkeypatch.setattr(dh, "add_ds_info", fake_add)

    def fake_change(api, ds_id, enabled):
        calls["change_state"].append((ds_id, enabled))
        return {}
    monkeypatch.setattr(dh, "change_ds_state", fake_change)

    def fake_delete(api, ids):
        calls["delete"].append(ids)
        return {}
    monkeypatch.setattr(dh, "delete_ds_info", fake_delete)

    def fake_qtq(api, ds_id=None, group_id="0", tag_name="", tag_base_name="",
                 page=1, page_size=100, sort="-createTime"):
        if ds_id is not None and tag_rows_by_ds is not None:
            return {"tagInfoList": {"records": tag_rows_by_ds.get(int(ds_id), []), "total": 0}}
        return {"tagInfoList": {"records": [], "total": 0}}
    monkeypatch.setattr(dh, "query_tags_with_quality", fake_qtq)

    def fake_list_recycle(api, page=1, page_size=100, group_id="1", tag_type=1, sort="-createTime"):
        return {"tagInfoList": {"records": recycle_rows or [], "total": len(recycle_rows or [])}}
    monkeypatch.setattr(dh, "list_recycle_tags", fake_list_recycle)

    return calls


def _patch_get_api(monkeypatch, api=None):
    import ua_test_harness.clients.tpt_client as tc
    monkeypatch.setattr(tc, "get_api", lambda ctx: api or MagicMock())


def _patch_wait_alive(monkeypatch, value=True):
    import ua_test_harness.provisioning.ua2_baseline as bl
    monkeypatch.setattr(bl, "_wait_ds_alive", lambda ctx, ds_id, timeout: value, raising=False)


def _types_row(id_=11, alive=True, ep=TYPES_EP):
    return {"id": id_, "dsName": SHARED_TYPES_DS_NAME, "dsTarUrl": ep, "alive": alive, "dsStatus": 1}


def _empty_row(id_=22, alive=True, ep=EMPTY_EP):
    return {"id": id_, "dsName": SHARED_EMPTY_DS_NAME, "dsTarUrl": ep, "alive": alive, "dsStatus": 1}


# --- 1. ensure reuses existing types DS ---
def test_ensure_reuses_existing_types_ds(monkeypatch):
    ctx = _ctx()
    calls = _patch_datahub(monkeypatch, ds_rows=[_types_row(), _empty_row()], tag_rows_by_ds={})
    _patch_get_api(monkeypatch)
    _patch_wait_alive(monkeypatch, True)

    bl = ensure_ua2_baseline(ctx)

    assert calls["add"] == []                      # no creation
    assert calls["delete"] == []                   # never deletes
    assert bl.types_ds_id == 11                    # reused existing id
    assert bl.types_endpoint == TYPES_EP
    assert bl.empty_ds_id == 22
    assert bl.empty_endpoint == EMPTY_EP


# --- 2. ensure creates when missing ---
def test_ensure_creates_when_missing(monkeypatch):
    ctx = _ctx()
    # types DS missing; empty DS present + alive + no tags
    calls = _patch_datahub(monkeypatch, ds_rows=[_empty_row()], tag_rows_by_ds={})
    _patch_get_api(monkeypatch)
    _patch_wait_alive(monkeypatch, True)

    bl = ensure_ua2_baseline(ctx)

    assert calls["add"] == [SHARED_TYPES_DS_NAME]  # created exactly once
    assert (999, True) in calls["change_state"]    # newly created was enabled
    assert bl.types_ds_id == 999                   # new id from add_ds_info


# --- 3. ensure raises BaselineError on endpoint mismatch ---
def test_ensure_raises_on_config_mismatch(monkeypatch):
    ctx = _ctx()
    wrong_types = _types_row(ep="opc.tcp://WRONG:18965/ua_mocker/")
    calls = _patch_datahub(monkeypatch, ds_rows=[wrong_types, _empty_row()], tag_rows_by_ds={})
    _patch_get_api(monkeypatch)
    _patch_wait_alive(monkeypatch, True)

    with pytest.raises(BaselineError):
        ensure_ua2_baseline(ctx)

    assert calls["delete"] == []                   # NEVER auto-delete on mismatch


# --- 4. ensure empty DS blocked when active tags present ---
def test_ensure_empty_ds_blocked_when_has_active_tags(monkeypatch):
    ctx = _ctx()
    calls = _patch_datahub(
        monkeypatch,
        ds_rows=[_types_row(), _empty_row()],
        tag_rows_by_ds={22: [{"id": 1, "tagName": "leftover", "dsId": 22}]},
    )
    _patch_get_api(monkeypatch)
    _patch_wait_alive(monkeypatch, True)

    with pytest.raises(BaselineError):
        ensure_ua2_baseline(ctx)

    assert calls["delete"] == []                   # no auto-clear / no delete


# --- 5. ensure empty DS blocked when recycle has matching dsId (2 pages) ---
def test_ensure_empty_ds_blocked_when_has_recycle_tags(monkeypatch):
    ctx = _ctx()
    calls = _patch_datahub(monkeypatch, ds_rows=[_types_row(), _empty_row()], tag_rows_by_ds={})
    _patch_get_api(monkeypatch)
    _patch_wait_alive(monkeypatch, True)

    # Stateful 2-page recycle fake: page 1 full (200 non-matching), page 2 one match.
    import tpt_api.datahub as dh
    page1 = [{"id": 100 + i, "dsId": 999} for i in range(200)]   # none match dsId=22
    page2 = [{"id": 999, "dsId": 22}]                            # matches empty DS

    def fake_recycle(api, page=1, page_size=100, group_id="1", tag_type=1, sort="-createTime"):
        if page == 1:
            return {"tagInfoList": {"records": page1, "total": 201}}
        if page == 2:
            return {"tagInfoList": {"records": page2, "total": 201}}
        return {"tagInfoList": {"records": [], "total": 201}}
    monkeypatch.setattr(dh, "list_recycle_tags", fake_recycle)

    with pytest.raises(BaselineError):
        ensure_ua2_baseline(ctx)

    assert calls["delete"] == []                   # no auto-clear / no delete


# --- 6. require_shared_datasource("types") returns dict when present+alive ---
def test_require_shared_datasource_types(monkeypatch):
    ctx = _ctx()
    calls = _patch_datahub(monkeypatch, ds_rows=[_types_row()], tag_rows_by_ds={})
    _patch_get_api(monkeypatch)
    _patch_wait_alive(monkeypatch, True)

    ds = require_shared_datasource(ctx, "types")

    assert ds["id"] == 11
    assert ds["name"] == SHARED_TYPES_DS_NAME
    assert ds["endpoint"] == TYPES_EP
    assert ds["alive"] is True
    assert calls["add"] == []                      # never creates
    assert calls["delete"] == []                   # never deletes


# --- 7. require raises BaselineError when missing ---
def test_require_shared_datasource_missing_raises(monkeypatch):
    ctx = _ctx()
    calls = _patch_datahub(monkeypatch, ds_rows=[], tag_rows_by_ds={})
    _patch_get_api(monkeypatch)
    _patch_wait_alive(monkeypatch, True)

    with pytest.raises(BaselineError):
        require_shared_datasource(ctx, "types")

    assert calls["add"] == []
    assert calls["delete"] == []


# --- 8. require raises when alive=False ---
def test_require_shared_datasource_not_alive_raises(monkeypatch):
    ctx = _ctx()
    calls = _patch_datahub(monkeypatch, ds_rows=[_types_row(alive=False)], tag_rows_by_ds={})
    _patch_get_api(monkeypatch)
    _patch_wait_alive(monkeypatch, True)

    with pytest.raises(BaselineError):
        require_shared_datasource(ctx, "types")

    assert calls["add"] == []                      # require never creates/enables
    assert calls["delete"] == []


# --- 9. require raises when endpoint mismatch ---
def test_require_shared_datasource_wrong_endpoint_raises(monkeypatch):
    ctx = _ctx()
    calls = _patch_datahub(
        monkeypatch,
        ds_rows=[_types_row(ep="opc.tcp://WRONG:18965/ua_mocker/")],
        tag_rows_by_ds={},
    )
    _patch_get_api(monkeypatch)
    _patch_wait_alive(monkeypatch, True)

    with pytest.raises(BaselineError):
        require_shared_datasource(ctx, "types")

    assert calls["delete"] == []


# --- 10. teardown raises unless confirm=True; with confirm disables+deletes both ---
def test_teardown_requires_confirm(monkeypatch):
    ctx = _ctx()
    calls = _patch_datahub(monkeypatch, ds_rows=[_types_row(), _empty_row()], tag_rows_by_ds={})
    _patch_get_api(monkeypatch)

    # confirm=False -> raises, nothing deleted
    with pytest.raises(BaselineError):
        teardown_ua2_baseline(ctx, confirm=False)
    assert calls["delete"] == []

    # confirm=True -> disables + deletes both
    result = teardown_ua2_baseline(ctx, confirm=True)

    assert (11, False) in calls["change_state"]
    assert (22, False) in calls["change_state"]
    assert [11] in calls["delete"]
    assert [22] in calls["delete"]
    deleted_ids = sorted(d["id"] for d in result["deleted"])
    assert deleted_ids == [11, 22]


# --- 11. Step 1 (Part 3): _ensure_one alive-wait decoupled from ds_connect_sec ---
def test_ensure_one_uses_dedicated_alive_wait_not_ds_connect_sec(monkeypatch):
    """Both alive-wait call sites in _ensure_one must pass BASELINE_ALIVE_WAIT_SEC,
    not read ctx.config.timeouts.ds_connect_sec."""
    import ua_test_harness.provisioning.ua2_baseline as bl
    captured: list[float] = []

    def fake_wait_alive(ctx, ds_id, timeout):
        captured.append(timeout)
        return True

    monkeypatch.setattr(bl, "_wait_ds_alive", fake_wait_alive)
    # alive=False so _ensure_one takes the re-enable branch and calls _wait_ds_alive.
    _patch_datahub(
        monkeypatch,
        ds_rows=[_types_row(alive=False), _empty_row(alive=False)],
        tag_rows_by_ds={},
    )
    _patch_get_api(monkeypatch)

    # Use a config whose ds_connect_sec is intentionally different from BASELINE_ALIVE_WAIT_SEC.
    # If _ensure_one were still reading ds_connect_sec, the captured timeout would be 5, not 120.
    ctx = _ctx()
    ctx.config.timeouts.ds_connect_sec = 5  # sentinel

    from ua_test_harness.provisioning.ua2_baseline import ensure_ua2_baseline
    ensure_ua2_baseline(ctx)

    # Both alive-wait calls (types + empty, re-enable branch) must use the dedicated 120s.
    assert captured, "expected _wait_ds_alive to be called"
    for t in captured:
        assert t == bl.BASELINE_ALIVE_WAIT_SEC == 120, (
            f"alive-wait must use BASELINE_ALIVE_WAIT_SEC (120s), got {t!r}; "
            "still reading ds_connect_sec?"
        )
