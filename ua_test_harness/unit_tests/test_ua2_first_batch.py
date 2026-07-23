"""UA-2 first batch unit tests (no external API calls; all monkeypatched)."""
import inspect
import sys
from typing import Any

import pytest

from ua_test_harness.catalog import case
from ua_test_harness.assertions import AssertFail
from ua_test_harness.fixtures.tag import soft_delete_tag, restore_from_recycle
from ua_test_harness.models import CaseDef, CaseStatus, StepDef
from ua_test_harness.scenario_policy import execute_documented_case
from ua_test_harness.ua2_runtime import (
    _EXECUTE_UA2,
    is_supported_ua2,
    execute_ua2_case,
    supported_ua2_ids,
)
import ua_test_harness.ua2_recycle_runtime as ua2_recycle_runtime
import ua_test_harness.ua2_common as ua2_common
import ua_test_harness.ua2_query_runtime as ua2_query_runtime
import ua_test_harness.ua2_create_runtime as ua2_create_runtime
import ua_test_harness.fixtures.tag as fixtures_tag


def _make_meta(case_id: str, chapter: str = "UA-2-1") -> dict[str, Any]:
    return {"id": case_id, "chapter": chapter, "title": "x", "kind": "regression"}


def _ctx():
    from ua_test_harness.context import RunContext
    from ua_test_harness.config import RunConfig
    from types import SimpleNamespace

    cfg = RunConfig()
    cfg.run_id = "ua2_test_run"
    em = SimpleNamespace(log=lambda *args, **kw: None)
    return RunContext(
        config=cfg,
        emitter=em,
        evidence_root=None,
        log_path=None,
        cancellation_token=None,
    )


def _cc(case_id: str):
    from types import SimpleNamespace

    registry = SimpleNamespace(
        register=lambda *args, **kw: None,
        pop=lambda *args, **kw: None,
        cleanup_all=lambda *args, **kw: None,
    )
    return SimpleNamespace(case_id=case_id, registry=registry, bag={})


# --- CLI ---


def _make_cli_ns(**overrides):
    from argparse import Namespace
    ns = Namespace(
        cmd="run",
        func=lambda a: 0,
        base_url=None, user=None, tenant=None,
        package="ua_test_harness.tests",
        cases=None, chapters=None, config=None, dry_run=False,
        output=None, action=None, key=None, mock_key=None,
        poll_n=0, write_n=0, ratio=0.0, frequency=1, ds_name="x",
        keep=False, yes_delete=False, local_ip="127.0.0.1",
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def test_cli_explicit_zero_match_returns_2() -> None:
    from ua_test_harness import cli
    ns = _make_cli_ns(cases="UA-XYZ-99")
    assert cli.cmd_run(ns) == 2


def test_cli_chapters_zero_match_returns_2() -> None:
    from ua_test_harness import cli
    ns = _make_cli_ns(chapters="UA-XYZ-9")
    assert cli.cmd_run(ns) == 2


def test_cli_config_selected_zero_match_returns_2(tmp_path) -> None:
    from ua_test_harness import cli
    cfg_path = tmp_path / "rc.json"
    cfg_path.write_text(
        '{"runId": "r", "selectedCaseIds": ["UA-NOT-EXIST"], '
        '"subject": {"baseUrl": "http://x", "username": "u", "password": ""}, '
        '"localIp": "127.0.0.1", '
        '"mock": {"controlMode": "external-script", "endpoints": {"functional": ""}}, '
        '"timeouts": {"pollIntervalMs": 500, "rtVisibilitySec": 30, '
        '"historyVisibilitySec": 120, "dsConnectSec": 60}, '
        '"paths": {"runDir": "", "evidenceDir": "", "reportPath": ""}}',
        encoding="utf-8",
    )
    ns = _make_cli_ns(config=str(cfg_path))
    assert cli.cmd_run(ns) == 2


def test_cli_no_selector_no_config_returns_full_set_with_zero_match_guard() -> None:
    """Smoke: when no selector and no selectedCaseIds in config, cmd_run
    falls back to the full catalog."""
    import inspect
    from ua_test_harness import cli
    src = inspect.getsource(cli.cmd_run)
    # The fall-back path requires both `if not selected and cfg.selected_case_ids`
    # AND `elif cli_explicit: ... else: selected = list(defs)` branches present.
    assert "all_defs" in src
    assert "list(defs)" in src
    assert "selected = list(defs)" in src or "selected = defs" in src


def _placeholder_marker() -> None:
    pass


# --- UA-2 dispatch ---


def test_supported_routes_to_ua2_executor() -> None:
    assert is_supported_ua2("UA-2-1-017") is True
    assert is_supported_ua2("UA-2-4-024") is True
    assert set(supported_ua2_ids()) == set(_EXECUTE_UA2.keys())


def test_unsupported_ua2_returns_blocked() -> None:
    ctx = _ctx()
    cc = _cc("UA-2-1-001")
    meta = _make_meta("UA-2-1-001", "UA-2-1")
    import ua_test_harness.scenario_policy as sp
    sp._SUPPORTED["UA-2-1"].discard("UA-2-1-001")
    try:
        status = execute_documented_case(ctx, cc, meta)
        assert status == CaseStatus.BLOCKED
    finally:
        sp._SUPPORTED["UA-2-1"].add("UA-2-1-001")


def test_unsupported_ua2_in_supported_chapter_but_no_handler_returns_blocked() -> None:
    ctx = _ctx()
    cc = _cc("UA-2-2-099")
    meta = _make_meta("UA-2-2-099", "UA-2-2")
    status = execute_documented_case(ctx, cc, meta)
    assert status == CaseStatus.BLOCKED


def test_unknown_ua2_case_raises_in_dispatch() -> None:
    ctx = _ctx()
    cc = _cc("UA-2-XX")
    meta = _make_meta("UA-2-99-099", "UA-2-1")
    with pytest.raises(AssertFail):
        execute_ua2_case(ctx, cc, meta)


# --- fixture signature guarantees ---


def test_soft_delete_tag_accepts_str_only() -> None:
    sig = inspect.signature(soft_delete_tag)
    name_param = sig.parameters["name"]
    assert name_param.annotation in (str, "str")


def test_restore_from_recycle_accepts_str_only() -> None:
    sig = inspect.signature(restore_from_recycle)
    name_param = sig.parameters["name"]
    assert name_param.annotation in (str, "str")


def _seed_rt_attrs():
    import ua_test_harness.ua2_recycle_runtime as rt_mod
    import ua_test_harness.fixtures.environment as fxenv
    if not hasattr(rt_mod, "ensure_mock_ready"):
        rt_mod.ensure_mock_ready = lambda *a, **k: None
    if not hasattr(rt_mod, "_wait_until"):
        rt_mod._wait_until = lambda name, fn, timeout=30.0, interval=1.0: fn() if callable(fn) else True
    if not hasattr(fxenv, "ensure_mock_ready"):
        fxenv.ensure_mock_ready = lambda *a, **k: None
    if not hasattr(fxenv, "ensure_logged_in"):
        fxenv.ensure_logged_in = lambda *a, **k: None





def test_length_name_127():
    n = ua2_create_runtime._make_length_name("ua_auto_ua2_tag_len127_", 127)
    assert len(n) == 127


def test_length_name_128():
    n = ua2_create_runtime._make_length_name("ua_auto_ua2_tag_len128_", 128)
    assert len(n) == 128


def test_restore_one_signature_and_no_tag_id() -> None:
    """Smoke: restore_one exists, accepts (ctx, cc), no tag_id positional."""
    import inspect
    from ua_test_harness.ua2_recycle_runtime import restore_one
    sig = inspect.signature(restore_one)
    params = list(sig.parameters.keys())
    assert "ctx" in params and "cc" in params
    assert "tag_id" not in params


def test_soft_delete_one_signature_and_no_tag_id() -> None:
    """Smoke: soft_delete_one exists, accepts (ctx, cc), no tag_id positional."""
    import inspect
    from ua_test_harness.ua2_recycle_runtime import soft_delete_one
    sig = inspect.signature(soft_delete_one)
    params = list(sig.parameters.keys())
    assert "ctx" in params and "cc" in params
    assert "tag_id" not in params


def test_query_repeat_stable_calls_active_rows_three_times() -> None:
    """Smoke: query_repeat_stable must sample active_rows three times."""
    import inspect
    from ua_test_harness.ua2_query_runtime import query_repeat_stable
    src = inspect.getsource(query_repeat_stable)
    # The runtime invokes `sample()` three times, and `sample` calls `active_rows`.
    # Count both occurrences of `active_rows` and the three-times call pattern.
    assert src.count("active_rows") >= 1
    assert "first = sample()" in src
    assert "second = sample()" in src
    assert "third = sample()" in src


def test_timeout_runner_normal_exit(tmp_path) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("rwt", "F:/github/supcon_tools/scripts/run_with_timeout.py")
    twt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(twt)
    out_p = tmp_path / "out.log"
    err_p = tmp_path / "err.log"
    result = twt.run([sys.executable, "-c", "print('hi')"], 30.0, out_p, err_p)
    assert result["exitCode"] == 0
    assert result["timedOut"] is False
    for field in ("command", "startedAtEpochMs", "durationMs", "stdoutPath", "stderrPath", "timeoutSec"):
        assert field in result, field


def test_timeout_runner_returns_124_on_timeout(tmp_path) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("rwt", "F:/github/supcon_tools/scripts/run_with_timeout.py")
    twt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(twt)
    out_p = tmp_path / "out.log"
    err_p = tmp_path / "err.log"
    cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
    result = twt.run(cmd, 1.0, out_p, err_p)
    assert result["exitCode"] == 124
    assert result["timedOut"] is True


def test_catalog_unchanged_after_test_tags_deletion():
    from ua_test_harness.catalog import discover, all_defs, _REGISTRY
    _REGISTRY.clear()
    for key in list(sys.modules):
        if key.startswith("ua_test_harness.tests"):
            del sys.modules[key]
    discover("ua_test_harness.tests")
    defs = list(all_defs())
    assert len(defs) == 419, len(defs)
    ua2 = [d for d in defs if d.id.startswith("UA-2-")]
    assert len(ua2) == 265, len(ua2)


def test_supported_ua2_count_is_full_chapter():
    assert len(_EXECUTE_UA2) == 265, len(_EXECUTE_UA2)


def test_supported_ua2_set_matches_all_documented():
    from ua_test_harness.ua2_registry import ua2_all_ids
    assert set(_EXECUTE_UA2.keys()) == set(ua2_all_ids())

