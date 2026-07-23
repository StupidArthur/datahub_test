"""Unit tests for scripts/teardown_ua2_baseline.py and scripts/diagnose_ua2_datasource.py.

All external API calls are replaced with fakes via monkeypatch (no real API).
Each script is loaded via importlib and driven through main() with sys.argv
override and a temp --result path.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEARDOWN_PATH = REPO_ROOT / "scripts" / "teardown_ua2_baseline.py"
DIAGNOSE_PATH = REPO_ROOT / "scripts" / "diagnose_ua2_datasource.py"


# ---------- module loading ----------

@pytest.fixture(scope="module")
def teardown_mod():
    spec = importlib.util.spec_from_file_location("teardown_ua2_baseline_under_test", TEARDOWN_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def diagnose_mod():
    spec = importlib.util.spec_from_file_location("diagnose_ua2_datasource_under_test", DIAGNOSE_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------- fake installation (shared between scripts) ----------

def _install_fakes(monkeypatch, *,
                   list_tags_pages=None,
                   list_recycle_pages=None,
                   list_ds_info_pages=None):
    """Monkeypatch tpt_api.datahub + tpt_api.client.AlgAPI.

    `list_*_pages` may be a list (queue: each call pops one) or a callable
    `f(page) -> list[dict]` (stateful, allows multiple consumers to see same
    data — needed when the script queries the same endpoint twice, e.g.
    active tags for the initial report AND for the clean-delete check).
    `list_tags_pages` here drives `query_tags_with_quality` (the script was
    refactored to use QTQ groupId="0" instead of list_tags; see bugs.md #1).
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
        "AlgAPI_init": [],
        "login": [],
    }
    lt_q = list_tags_pages
    lr_q = list_recycle_pages
    ds_q = list_ds_info_pages

    def fake_qtq(api, ds_id=None, group_id="0", tag_name="", tag_base_name="",
                 page=1, page_size=100, sort="-createTime"):
        calls["query_tags_with_quality"].append({
            "page": page, "page_size": page_size, "ds_id": ds_id,
            "group_id": group_id, "tag_name": tag_name,
        })
        if callable(lt_q):
            recs = lt_q(page)
        else:
            lt_q_list = lt_q if isinstance(lt_q, list) else []
            recs = lt_q_list.pop(0) if lt_q_list else []
        return {"tagInfoList": {"records": recs, "total": len(recs)}}

    def fake_list_recycle_tags(api, page=1, page_size=200, group_id="1", tag_type=1, sort="-createTime"):
        calls["list_recycle_tags"].append({"page": page, "page_size": page_size, "group_id": group_id})
        if callable(lr_q):
            recs = lr_q(page)
        else:
            lr_q_list = lr_q if isinstance(lr_q, list) else []
            recs = lr_q_list.pop(0) if lr_q_list else []
        return {"tagInfoList": {"records": recs, "total": len(recs)}}

    def fake_list_ds_info(api, page=1, page_size=10, sort="-createTime", data=None):
        calls["list_ds_info"].append({"page": page, "page_size": page_size, "data": data})
        if callable(ds_q):
            recs = ds_q(page)
        else:
            ds_q_list = ds_q if isinstance(ds_q, list) else []
            recs = ds_q_list.pop(0) if ds_q_list else []
        return {"records": recs, "total": len(recs)}

    monkeypatch.setattr(dh, "query_tags_with_quality", fake_qtq)
    monkeypatch.setattr(dh, "list_recycle_tags", fake_list_recycle_tags)
    monkeypatch.setattr(dh, "list_ds_info", fake_list_ds_info)
    monkeypatch.setattr(dh, "change_ds_state", lambda api, ds_id, enabled: calls["change_ds_state"].append((ds_id, enabled)) or {})
    monkeypatch.setattr(dh, "delete_ds_info", lambda api, ids: calls["delete_ds_info"].append(list(ids)) or {})
    monkeypatch.setattr(dh, "delete_tags_physical", lambda api, ids: calls["delete_tags_physical"].append(list(ids)) or {})

    class FakeApi:
        def __init__(self, *a, **kw):
            calls["AlgAPI_init"].append((a, kw))

        def login(self, username, password, tenant_id=""):
            calls["login"].append((username, password, tenant_id))
            return {"ok": True}

    monkeypatch.setattr(client, "AlgAPI", FakeApi)
    return calls


# ---------- teardown tests ----------

def test_teardown_requires_confirm(teardown_mod, monkeypatch, tmp_path):
    """req 7a: no --confirm-delete-shared -> return 2, no delete calls, no login."""
    calls = _install_fakes(monkeypatch)
    result_path = tmp_path / "teardown.json"
    monkeypatch.setattr(sys, "argv", ["teardown", "--result", str(result_path)])
    # Patch load_env_json to return a fake env (teardown script reads from env.json).
    import ua_test_harness.env_config as env_cfg_mod
    fake_env = {"baseUrl": "http://x", "username": "u", "password": "secret",
                "tenantId": "", "localIp": "127.0.0.1"}
    monkeypatch.setattr(env_cfg_mod, "load_env_json", lambda: fake_env)
    monkeypatch.setattr(teardown_mod, "load_env_json", lambda: fake_env)

    rc = teardown_mod.main()

    assert rc == 2
    assert calls["delete_ds_info"] == []
    assert calls["change_ds_state"] == []
    assert calls["AlgAPI_init"] == []  # we never tried to login
    assert not result_path.exists() or result_path.read_text() == ""


def test_teardown_with_confirm_calls_disable_and_delete(teardown_mod, monkeypatch, tmp_path):
    """req 7b: --confirm-delete-shared -> provision delegate called."""
    calls = _install_fakes(monkeypatch)
    # The teardown script delegates to ua_test_harness.provisioning.teardown_ua2_baseline.
    # We monkeypatch the *delegated* function to a recorder instead of running it.
    captured = {}

    def fake_provisioning_teardown(ctx, *, confirm=False):
        captured["ctx_config_local_ip"] = ctx.config.local_ip
        captured["ctx_endpoint"] = ctx.config.mock.endpoints.functional
        captured["confirm"] = confirm
        return {"deleted": [{"id": 11, "name": "ua_shared_ua2_types_ds"},
                            {"id": 22, "name": "ua_shared_ua2_empty_ds"}]}

    # The script does its sys.path.insert before importing. We patch the imported
    # reference inside ua_test_harness.provisioning.
    import ua_test_harness.provisioning as prov_mod
    monkeypatch.setattr(prov_mod, "teardown_ua2_baseline", fake_provisioning_teardown)

    result_path = tmp_path / "teardown.json"
    monkeypatch.setattr(sys, "argv", ["teardown", "--confirm-delete-shared", "--result", str(result_path)])
    # Patch load_env_json (teardown script reads from env.json).
    import ua_test_harness.env_config as env_cfg_mod
    fake_env = {"baseUrl": "http://x", "username": "u", "password": "secret",
                "tenantId": "", "localIp": "127.0.0.1"}
    monkeypatch.setattr(env_cfg_mod, "load_env_json", lambda: fake_env)
    monkeypatch.setattr(teardown_mod, "load_env_json", lambda: fake_env)

    rc = teardown_mod.main()

    assert rc == 0
    assert captured["confirm"] is True
    assert captured["ctx_config_local_ip"] == "127.0.0.1"
    # Result JSON written
    log = json.loads(result_path.read_text(encoding="utf-8"))
    assert log["deleted"]  # at least one entry
    assert len(log["deleted"]) == 2


# ---------- diagnose tests ----------

def _run_diagnose(diagnose_mod, monkeypatch, tmp_path, *, args=None, **fake_kwargs):
    """Helper: drive diagnose_ua2_datasource.main() with fakes."""
    args = list(args or [])
    calls = _install_fakes(monkeypatch, **fake_kwargs)
    result_path = tmp_path / "diagnose.json"
    argv = ["diagnose", "--result", str(result_path)] + args
    monkeypatch.setattr(sys, "argv", argv)
    # Patch load_env_json to return a fake env (diagnose script reads from env.json).
    import ua_test_harness.env_config as env_cfg_mod
    fake_env = {
        "baseUrl": "http://x",
        "username": "u",
        "password": "secret",
        "tenantId": "",
        "localIp": "127.0.0.1",
    }
    monkeypatch.setattr(env_cfg_mod, "load_env_json", lambda: fake_env)
    monkeypatch.setattr(diagnose_mod, "load_env_json", lambda: fake_env)
    rc = diagnose_mod.main()
    log = None
    if result_path.exists():
        log = json.loads(result_path.read_text(encoding="utf-8"))
    return rc, log, calls


def test_diagnose_lists_active_by_ds_id(diagnose_mod, monkeypatch, tmp_path):
    """req 1: fake list_tags(data={"dsId":X}) returns 2 -> activeTagCount==2."""
    rc, log, calls = _run_diagnose(
        diagnose_mod, monkeypatch, tmp_path,
        args=["--ds-id", "100"],
        list_ds_info_pages=[[{"id": 100, "dsName": "ua_shared_ua2_types_ds",
                              "dsTarUrl": "opc.tcp://127.0.0.1:18965/ua_mocker/",
                              "dsStatus": 1, "alive": True}]],
        list_tags_pages=[[
            {"id": 1, "tagName": "ua_case_ua2_a", "dsId": 100},
            {"id": 2, "tagName": "ua_case_ua2_b", "dsId": 100},
        ]],
        list_recycle_pages=[[]],
    )

    assert rc == 0
    assert log["datasource"]["id"] == 100
    assert log["activeTagCount"] == 2
    assert len(log["activeTags"]) == 2
    # dsId filter was pushed to API
    assert any(c["ds_id"] == 100 and c["group_id"] == "0" for c in calls["query_tags_with_quality"])


def test_diagnose_lists_recycle_filtered_by_ds_id(diagnose_mod, monkeypatch, tmp_path):
    """req 2: 2 pages of recycle; only 1 has matching dsId -> recycleTagCount==1."""
    # Make first page full (200) so pagination advances; second page empty.
    page_a = [{"id": 100 + i, "tagName": f"ua_case_ua2_x{i}", "dsId": 999} for i in range(200)]
    page_b = [{"id": 10, "tagName": "ua_case_ua2_match", "dsId": 100}]  # matches dsId 100
    rc, log, calls = _run_diagnose(
        diagnose_mod, monkeypatch, tmp_path,
        args=["--ds-id", "100"],
        list_ds_info_pages=[[{"id": 100, "dsName": "ua_shared_ua2_types_ds",
                              "dsTarUrl": "opc.tcp://x", "dsStatus": 1, "alive": True}]],
        list_tags_pages=[[]],
        list_recycle_pages=[page_a, page_b],
    )

    assert rc == 0
    assert log["recycleTagCount"] == 1
    assert len(log["recycleTags"]) == 1
    assert log["recycleTags"][0]["id"] == 10
    # Pagination was used (page1 full -> page2)
    assert len(calls["list_recycle_tags"]) >= 2


def test_diagnose_readonly_no_delete(diagnose_mod, monkeypatch, tmp_path):
    """req 3: default mode never calls delete/disable."""
    rc, log, calls = _run_diagnose(
        diagnose_mod, monkeypatch, tmp_path,
        args=["--ds-id", "100"],
        list_ds_info_pages=[[{"id": 100, "dsName": "ua_shared_ua2_types_ds",
                              "dsTarUrl": "opc.tcp://x", "dsStatus": 1, "alive": True}]],
        list_tags_pages=[[{"id": 1, "tagName": "ua_case_ua2_x", "dsId": 100}]],
        list_recycle_pages=[[]],
    )

    assert rc == 0
    assert calls["delete_ds_info"] == []
    assert calls["change_ds_state"] == []
    assert "cleanDelete" not in log  # not attempted


def test_diagnose_clean_delete_refuses_non_case_name(diagnose_mod, monkeypatch, tmp_path):
    """req 4: --attempt-clean-delete on ua_shared_ua2_types_ds -> REFUSED, no delete."""
    rc, log, calls = _run_diagnose(
        diagnose_mod, monkeypatch, tmp_path,
        args=["--ds-id", "100", "--attempt-clean-delete"],
        list_ds_info_pages=[[{"id": 100, "dsName": "ua_shared_ua2_types_ds",
                              "dsTarUrl": "opc.tcp://x", "dsStatus": 1, "alive": True}]],
        list_tags_pages=[[]],
        list_recycle_pages=[[]],
    )

    # shared DS is not a case-private name -> refuse
    assert "cleanDelete" in log
    assert "REFUSED" in log["cleanDelete"]
    assert calls["delete_ds_info"] == []
    assert calls["change_ds_state"] == []


def test_diagnose_clean_delete_refuses_with_tags(diagnose_mod, monkeypatch, tmp_path):
    """req 5: case-named DS with active tags -> TAG_DEPENDENCY, no delete."""
    # Use a callable so the same active-tag data is visible to BOTH the initial
    # report AND the clean-delete check (script calls _active_tags_by_ds twice).
    tag_with_active = lambda page: [{"id": 1, "tagName": "ua_case_ua2_a", "dsId": 200}]
    rc, log, calls = _run_diagnose(
        diagnose_mod, monkeypatch, tmp_path,
        args=["--ds-id", "200", "--attempt-clean-delete"],
        list_ds_info_pages=[[{"id": 200, "dsName": "ua_case_ua2_ds_xyz",
                              "dsTarUrl": "opc.tcp://x", "dsStatus": 1, "alive": True}]],
        list_tags_pages=tag_with_active,
        list_recycle_pages=[[]],
    )

    assert "cleanDelete" in log
    assert "TAG_DEPENDENCY" in log["cleanDelete"]
    assert calls["delete_ds_info"] == []
    assert calls["change_ds_state"] == []


def test_diagnose_clean_delete_sequence(diagnose_mod, monkeypatch, tmp_path):
    """req 6: case-named DS, no tags -> disable -> delete -> poll gone -> DELETED."""
    rc, log, calls = _run_diagnose(
        diagnose_mod, monkeypatch, tmp_path,
        args=["--ds-id", "200", "--attempt-clean-delete"],
        list_ds_info_pages=[
            # First find_ds call: returns the DS
            [{"id": 200, "dsName": "ua_case_ua2_ds_xyz",
              "dsTarUrl": "opc.tcp://x", "dsStatus": 1, "alive": True}],
            # Subsequent find_ds in wait_alive_false poll: still alive=False should be detected
            # We return [] (gone) so the loop breaks immediately
            [],
            # find_ds after delete: confirm gone
            [],
        ],
        list_tags_pages=[[]],
        list_recycle_pages=[[]],
    )

    assert "cleanDelete" in log
    assert log["cleanDelete"] == "DELETED"
    assert calls["change_ds_state"] == [(200, False)]
    assert calls["delete_ds_info"] == [[200]]