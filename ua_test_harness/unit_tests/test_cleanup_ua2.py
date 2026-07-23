"""Unit tests for scripts/cleanup_ua2_resources.py.

All external API calls are replaced with fakes via monkeypatch (no real API).
We load the standalone script via importlib, drive its main() through sys.argv
with a temp --result path, and assert on the recorded calls + result JSON.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


# ---------- module loading ----------

@pytest.fixture(scope="module")
def mod():
    """Load scripts/cleanup_ua2_resources.py as an isolated module."""
    path = Path(__file__).resolve().parent.parent.parent / "scripts" / "cleanup_ua2_resources.py"
    spec = importlib.util.spec_from_file_location("cleanup_ua2_resources_under_test", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------- fake installation ----------

def _install_fakes(monkeypatch, *, active_pages=None, recycle_pages=None, ds_rows_seq=None):
    """Monkeypatch tpt_api.datahub + tpt_api.client.AlgAPI with queue-based fakes.

    active_pages / recycle_pages / ds_rows_seq are queues (lists of pages); each
    call pops the front page, returning an empty page once exhausted. This lets a
    single fake serve both the pre-delete collect and the post-delete re-check.
    Returns a `calls` dict recording every invocation.
    """
    import tpt_api.client as client
    import tpt_api.datahub as dh

    calls = {
        "query_tags_with_quality": [],
        "list_recycle_tags": [],
        "list_ds_info": [],
        "delete_tags_physical": [],
        "change_ds_state": [],
        "delete_ds_info": [],
        "login": [],
        "AlgAPI_init": [],
    }
    active_q = list(active_pages or [])
    recycle_q = list(recycle_pages or [])
    ds_q = list(ds_rows_seq or [])

    def fake_qtq(api, ds_id=None, group_id="0", tag_name="", tag_base_name="",
                 page=1, page_size=100, sort="-createTime"):
        calls["query_tags_with_quality"].append({
            "page": page, "page_size": page_size, "ds_id": ds_id,
            "group_id": group_id, "tag_name": tag_name,
        })
        recs = active_q.pop(0) if active_q else []
        return {"tagInfoList": {"records": recs, "total": len(recs)}}

    def fake_list_recycle_tags(api, page=1, page_size=100, group_id="1", tag_type=1, sort="-createTime"):
        calls["list_recycle_tags"].append({"page": page, "page_size": page_size, "group_id": group_id})
        recs = recycle_q.pop(0) if recycle_q else []
        return {"tagInfoList": {"records": recs, "total": len(recs)}}

    def fake_list_ds_info(api, page=1, page_size=10, sort="-createTime", data=None):
        calls["list_ds_info"].append({"page": page, "page_size": page_size, "data": data})
        recs = ds_q.pop(0) if ds_q else []
        return {"records": recs, "total": len(recs)}

    def fake_delete_tags_physical(api, ids):
        calls["delete_tags_physical"].append(list(ids))
        return {}

    def fake_change_ds_state(api, ds_id, enabled):
        calls["change_ds_state"].append((ds_id, enabled))
        return {}

    def fake_delete_ds_info(api, ids):
        calls["delete_ds_info"].append(list(ids))
        return {}

    monkeypatch.setattr(dh, "query_tags_with_quality", fake_qtq)
    monkeypatch.setattr(dh, "list_recycle_tags", fake_list_recycle_tags)
    monkeypatch.setattr(dh, "list_ds_info", fake_list_ds_info)
    monkeypatch.setattr(dh, "delete_tags_physical", fake_delete_tags_physical)
    monkeypatch.setattr(dh, "change_ds_state", fake_change_ds_state)
    monkeypatch.setattr(dh, "delete_ds_info", fake_delete_ds_info)

    class FakeApi:
        def __init__(self, *a, **kw):
            calls["AlgAPI_init"].append((a, kw))

        def login(self, username, password, tenant_id=""):
            calls["login"].append((username, password, tenant_id))
            return {"ok": True}

    monkeypatch.setattr(client, "AlgAPI", FakeApi)
    return calls


def _run(mod, monkeypatch, tmp_path, argv_extra, *, active_pages=None,
         recycle_pages=None, ds_rows_seq=None, password="secret"):
    """Run mod.main() with fakes installed and a temp --result path.

    Returns (return_code, parsed_log_or_None, calls).
    """
    calls = _install_fakes(
        monkeypatch,
        active_pages=active_pages,
        recycle_pages=recycle_pages,
        ds_rows_seq=ds_rows_seq,
    )
    result_path = tmp_path / "cleanup_result.json"
    argv = ["cleanup", "--result", str(result_path)] + list(argv_extra)
    monkeypatch.setattr(sys, "argv", argv)
    # Patch load_env_json to return a fake env (cleanup script reads from env.json).
    import ua_test_harness.env_config as env_cfg_mod
    fake_env = {
        "baseUrl": "http://x",
        "username": "u",
        "password": password,
        "tenantId": "",
        "localIp": "127.0.0.1",
    }
    monkeypatch.setattr(env_cfg_mod, "load_env_json", lambda: fake_env)
    monkeypatch.setattr(mod, "load_env_json", lambda: fake_env)
    rc = mod.main()
    log = None
    if result_path.exists():
        log = json.loads(result_path.read_text(encoding="utf-8"))
    return rc, log, calls


# ---------- tests ----------

def test_cleanup_default_prefix_is_case(mod):
    """req 1: module PREFIX == 'ua_case_ua2_'."""
    assert mod.PREFIX == "ua_case_ua2_"


def test_cleanup_refuses_shared_prefix(mod, monkeypatch, tmp_path):
    """req 2: --prefix ua_shared_ua2_ -> returns 2, NO delete calls, no collect."""
    rc, log, calls = _run(mod, monkeypatch, tmp_path, ["--prefix", "ua_shared_ua2_"])
    assert rc == 2
    assert calls["delete_tags_physical"] == []
    assert calls["delete_ds_info"] == []
    assert calls["change_ds_state"] == []
    # Refused before login / collect, so no API queries happened at all.
    assert calls["query_tags_with_quality"] == []
    assert calls["list_ds_info"] == []
    assert calls["AlgAPI_init"] == []


def test_cleanup_does_not_delete_shared_resources(mod, monkeypatch, tmp_path):
    """req 3: a shared datasource (ua_shared_ua2_types_ds) survives every run.

    Run with --include-case-datasources; the fake ds listing returns both a
    case DS and the shared DS. The shared DS id must never be disabled or
    deleted (client-side CASE_DS_PREFIX filter excludes it).
    """
    case_ds = {"id": 700, "dsName": "ua_case_ua2_ds_1", "dsTarUrl": "opc.tcp://x"}
    shared_ds = {"id": 555, "dsName": "ua_shared_ua2_types_ds", "dsTarUrl": "opc.tcp://y"}
    # collect -> [case_ds, shared_ds]; recheck -> [shared_ds] (case deleted)
    rc, log, calls = _run(
        mod, monkeypatch, tmp_path, ["--include-case-datasources"],
        ds_rows_seq=[[case_ds, shared_ds], [shared_ds]],
    )
    # shared DS never disabled nor deleted
    for ds_id, _ in calls["change_ds_state"]:
        assert ds_id != 555
    for ids in calls["delete_ds_info"]:
        assert 555 not in ids
    # case DS was disabled + deleted
    assert (700, False) in calls["change_ds_state"]
    assert [700] in calls["delete_ds_info"]
    # shared excluded by recheck filter -> no residual -> exit 0
    assert rc == 0
    assert log["residualCaseDatasources"] == 0


def test_cleanup_paginates_active_tags(mod, monkeypatch, tmp_path):
    """req 4: fake list_tags returns 3 pages (500+500+1=1001); all collected + deleted."""
    page1 = [{"id": i, "tagName": f"ua_case_ua2_a{i}"} for i in range(1, 501)]
    page2 = [{"id": i, "tagName": f"ua_case_ua2_b{i}"} for i in range(501, 1001)]
    page3 = [{"id": 1001, "tagName": "ua_case_ua2_c"}]
    rc, log, calls = _run(
        mod, monkeypatch, tmp_path, [],
        active_pages=[page1, page2, page3],
    )
    assert calls["delete_tags_physical"], "expected a physical delete call"
    deleted = calls["delete_tags_physical"][0]
    assert len(deleted) == 1001
    assert set(deleted) == set(range(1, 1002))
    # pagination used page_size 500
    assert all(c["page_size"] == 500 for c in calls["query_tags_with_quality"])
    # recheck exhausted the queue -> clean
    assert rc == 0
    assert log["residualActive"] == 0


def test_cleanup_paginates_recycle(mod, monkeypatch, tmp_path):
    """req 5: fake list_recycle_tags returns 2 full pages (200+200=400); all collected + deleted."""
    rpage1 = [{"id": i, "tagName": f"ua_case_ua2_r{i}"} for i in range(1, 201)]
    rpage2 = [{"id": i, "tagName": f"ua_case_ua2_r{i}"} for i in range(201, 401)]
    rc, log, calls = _run(
        mod, monkeypatch, tmp_path, [],
        recycle_pages=[rpage1, rpage2],
    )
    assert calls["delete_tags_physical"]
    deleted = calls["delete_tags_physical"][0]
    assert len(deleted) == 400
    assert set(deleted) == set(range(1, 401))
    # recycle pagination used page_size 200
    assert all(c["page_size"] == 200 for c in calls["list_recycle_tags"])
    assert rc == 0
    assert log["residualRecycle"] == 0


def test_cleanup_no_datasource_delete_by_default(mod, monkeypatch, tmp_path):
    """req 6: without --include-case-datasources, delete_ds_info is never called
    even when a case DS is present in the listing."""
    case_ds = {"id": 700, "dsName": "ua_case_ua2_ds_1"}
    rc, log, calls = _run(
        mod, monkeypatch, tmp_path, [],
        ds_rows_seq=[[case_ds]],  # present, but never queried without the flag
    )
    assert calls["delete_ds_info"] == []
    assert calls["change_ds_state"] == []
    # _collect_case_ds_ids is not even invoked without the flag
    assert calls["list_ds_info"] == []
    assert rc == 0


def test_cleanup_recheck_exit_1_on_residual(mod, monkeypatch, tmp_path):
    """req 7: residual present after delete -> exit 1."""
    rec = {"id": 42, "tagName": "ua_case_ua2_x"}
    # active returns the rec on collect AND on recheck (delete did not clear it)
    rc, log, calls = _run(
        mod, monkeypatch, tmp_path, [],
        active_pages=[[rec], [rec]],
    )
    assert rc == 1
    assert log["residualActive"] == 1
    assert log["exitCode"] == 1
    # delete was attempted
    assert [42] in calls["delete_tags_physical"]


def test_cleanup_recheck_exit_0_on_clean(mod, monkeypatch, tmp_path):
    """req 7: clean after delete -> exit 0."""
    rec = {"id": 42, "tagName": "ua_case_ua2_x"}
    # active returns rec on collect; queue exhausted -> empty on recheck
    rc, log, calls = _run(
        mod, monkeypatch, tmp_path, [],
        active_pages=[[rec]],
    )
    assert rc == 0
    assert log["residualActive"] == 0
    assert log["exitCode"] == 0
    assert [42] in calls["delete_tags_physical"]
