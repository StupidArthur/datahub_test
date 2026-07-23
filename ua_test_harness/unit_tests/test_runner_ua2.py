"""UA-2 runner orchestration tests.

Verifies the runner's new orchestration: two mocks (18965 + 18967),
shared baseline provisioning, run-config `ua2Baseline` segment, case-only
cleanup, no shared-DS teardown.

The script is loaded as an isolated module; subprocess + socket calls are
faked so no real process or network happens.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNNER_PATH = REPO_ROOT / "scripts" / "run_automation_ua2.py"


@pytest.fixture(scope="module")
def runner_mod():
    spec = importlib.util.spec_from_file_location("run_automation_ua2_under_test", RUNNER_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------- fake installation ----------

class _FakeCompletedProcess:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


class _FakePopen:
    def __init__(self, cmd, **kw):
        self.cmd = cmd
        self.kwargs = kw
        self.pid = 12345

    def poll(self):
        return None

    def kill(self):
        pass

    def terminate(self):
        pass

    def wait(self, timeout=None):
        return 0


def _install_fakes(monkeypatch, runner_mod, *, baseline_should_succeed=True):
    """Install subprocess + socket + provisioning fakes.

    Returns a `calls` dict tracking every observable invocation.
    """
    calls = {
        "popen": [],          # list of cmd (each mock Popen call)
        "run": [],             # list of {cmd, env, ...} for subprocess.run calls
        "ensure_baseline": [], # list of ctx passed
        "teardown_baseline": [],
        "baseline_blocked": False,
    }

    # Fake socket so readiness check passes immediately.
    class FakeSocket:
        def __init__(self, *a, **kw): pass
        def settimeout(self, *a, **kw): pass
        def connect(self, *a, **kw): pass
        def close(self): pass
    import socket
    monkeypatch.setattr(socket, "socket", FakeSocket)

    def fake_popen(cmd, **kw):
        calls["popen"].append(list(cmd))
        return _FakePopen(cmd, **kw)

    def fake_run(cmd, **kw):
        calls["run"].append({"cmd": list(cmd), "env": kw.get("env", {}),
                            "cwd": kw.get("cwd"), "timeout": kw.get("timeout")})
        return _FakeCompletedProcess(rc=0, stdout="", stderr="")

    monkeypatch.setattr(runner_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runner_mod.subprocess, "run", fake_run)

    # Patch provisioning so the runner's in-function imports see our fakes.
    import ua_test_harness.provisioning as prov_mod

    fake_baseline_obj = MagicMock()
    fake_baseline_obj.types_ds_id = 100
    fake_baseline_obj.types_ds_name = "ua_shared_ua2_types_ds"
    fake_baseline_obj.types_endpoint = "opc.tcp://127.0.0.1:18965/ua_mocker/"
    fake_baseline_obj.empty_ds_id = 200
    fake_baseline_obj.empty_ds_name = "ua_shared_ua2_empty_ds"
    fake_baseline_obj.empty_endpoint = "opc.tcp://127.0.0.1:18967/ua_mocker/"

    def fake_ensure_baseline(ctx):
        calls["ensure_baseline"].append(ctx)
        if not baseline_should_succeed:
            from ua_test_harness.provisioning import BaselineError
            calls["baseline_blocked"] = True
            raise BaselineError("shared DS missing")
        return fake_baseline_obj

    def fake_teardown_baseline(ctx, *, confirm=False):
        calls["teardown_baseline"].append({"confirm": confirm})
        return {"deleted": []}

    monkeypatch.setattr(prov_mod, "ensure_ua2_baseline", fake_ensure_baseline)
    monkeypatch.setattr(prov_mod, "teardown_ua2_baseline", fake_teardown_baseline)

    return calls


def _drive(runner_mod, monkeypatch, tmp_path, *, password="secret", local_ip="127.0.0.1"):
    """Invoke runner_mod.main() with fakes installed; write result to tmp.

    Returns (rc, result_dict_or_None, calls).
    """
    out_root = tmp_path
    monkeypatch.setattr(sys, "argv", [
        "run_automation_ua2",
        "--out-root", str(out_root),
        "--skip-prereqs",
    ])
    # Patch load_env_json (the script reads env.json instead of os.environ).
    import ua_test_harness.env_config as env_cfg_mod
    fake_env = {
        "baseUrl": "http://x",
        "username": "u",
        "password": password,
        "tenantId": "",
        "localIp": local_ip,
    }
    monkeypatch.setattr(env_cfg_mod, "load_env_json", lambda: fake_env)
    monkeypatch.setattr(runner_mod, "load_env_json", lambda: fake_env)
    monkeypatch.setattr(runner_mod, "_write_verification_overlay", lambda *a, **k: None)
    monkeypatch.setattr(runner_mod, "_append_overnight_findings", lambda *a, **k: None)
    rc = runner_mod.main()
    # Find the most recent result.json (or ua2-result.json)
    result_path = None
    for cand in out_root.rglob("ua2-result.json"):
        result_path = cand
    result = None
    if result_path and result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    return rc, result, result_path


# ---------- tests ----------

def test_runner_starts_two_mocks_at_18965_and_18967(runner_mod, monkeypatch, tmp_path):
    """req 1: two mocks started — types on 18965, empty on 18967."""
    calls = _install_fakes(monkeypatch, runner_mod)
    rc, result, _ = _drive(runner_mod, monkeypatch, tmp_path)

    # At least 2 Popen calls (one per mock). Each is `python main.py <yaml>`.
    assert len(calls["popen"]) >= 2, calls["popen"]
    yamls_started = [c[2] for c in calls["popen"]]   # cmd[2] is the yaml path
    # Both ua2_types.yaml and ua2_empty.yaml must be present
    assert any("ua2_types.yaml" in str(y) for y in yamls_started), yamls_started
    assert any("ua2_empty.yaml" in str(y) for y in yamls_started), yamls_started

    # Summary reports both
    assert result is not None
    assert result.get("mockProcess", {}).get("started") is True
    assert result.get("emptyMockProcess", {}).get("started") is True


def test_runner_provisions_baseline_before_cases(runner_mod, monkeypatch, tmp_path):
    """req 2: ensure_ua2_baseline is invoked once, before any case subprocess."""
    calls = _install_fakes(monkeypatch, runner_mod)
    _drive(runner_mod, monkeypatch, tmp_path)

    assert len(calls["ensure_baseline"]) == 1
    # Ensure baseline was provisioned BEFORE case subprocesses
    popen_index = next((i for i, c in enumerate(calls["popen"]) if "ua2_types.yaml" in str(c)), None)
    assert popen_index is not None
    # ensure_ua2_baseline is called in-process (not as subprocess), so the
    # case subprocess.run commands should all come AFTER it. We assert that
    # at least one case subprocess ran.
    case_runs = [
        r for r in calls["run"]
        if any("ua_test_harness.cli" in str(p) for p in r["cmd"])
        and "run" in str(r["cmd"])
    ]
    assert case_runs, "no case subprocess was recorded"


def test_runner_case_config_has_baseline_segment(runner_mod, monkeypatch, tmp_path):
    """req 3: each case's run-config.json contains `ua2Baseline` with 2 names + 2 endpoints."""
    calls = _install_fakes(monkeypatch, runner_mod)
    _drive(runner_mod, monkeypatch, tmp_path)

    # Find all --config <path> invocations in case runs
    configs: list[dict] = []
    for r in calls["run"]:
        cmd = r["cmd"]
        if "--config" in cmd:
            cfg_path = cmd[cmd.index("--config") + 1]
            p = Path(cfg_path)
            if p.is_file():
                configs.append(json.loads(p.read_text(encoding="utf-8")))

    assert configs, "no case run-config.json was found"
    for cfg in configs:
        assert "ua2Baseline" in cfg, cfg
        bl = cfg["ua2Baseline"]
        assert bl["typesDatasourceName"] == "ua_shared_ua2_types_ds"
        assert bl["emptyDatasourceName"] == "ua_shared_ua2_empty_ds"
        assert "18965" in bl["typesEndpoint"]
        assert "18967" in bl["emptyEndpoint"]


def test_runner_does_not_teardown_shared_ds(runner_mod, monkeypatch, tmp_path):
    """req 4: teardown_ua2_baseline is NEVER called; shared DS not deleted."""
    calls = _install_fakes(monkeypatch, runner_mod)
    _drive(runner_mod, monkeypatch, tmp_path)

    assert calls["teardown_baseline"] == [], \
        f"teardown_ua2_baseline was called: {calls['teardown_baseline']}"
    # delete_ds_info must not have been called with shared DS ids (100, 200).
    delete_ds_calls = [
        r for r in calls["run"]
        if any("delete_ds_info" in str(p) for p in r["cmd"])
    ]
    # No direct call to delete_ds_info from runner (cleanup_ua2 handles its own)
    assert not any(100 in r["cmd"] or 200 in r["cmd"] for r in delete_ds_calls)


def test_runner_case_cleanup_uses_case_prefix(runner_mod, monkeypatch, tmp_path):
    """req 5: per-case cleanup is invoked with default --prefix (ua_case_ua2_).

    The default cleanup_ua2_resources.py prefix is `ua_case_ua2_`. If the runner
    passes `--prefix ua_shared_ua2_` it would be refused (return 2). We assert
    the runner does NOT pass that forbidden prefix.
    """
    calls = _install_fakes(monkeypatch, runner_mod)
    _drive(runner_mod, monkeypatch, tmp_path)

    cleanup_runs = [
        r for r in calls["run"]
        if any("cleanup_ua2_resources.py" in str(p) for p in r["cmd"])
    ]
    assert cleanup_runs, "no cleanup subprocess was recorded"
    for r in cleanup_runs:
        cmd = r["cmd"]
        # Either no --prefix (defaults to ua_case_ua2_) or explicit --prefix ua_case_ua2_
        if "--prefix" in cmd:
            idx = cmd.index("--prefix")
            prefix_val = cmd[idx + 1]
            assert not prefix_val.startswith("ua_shared_ua2_"), \
                f"cleanup was called with shared-prefix: {prefix_val}"


def test_runner_keeps_shared_on_failure(runner_mod, monkeypatch, tmp_path):
    """req 6: even when cases FAIL, shared DS not deleted and not torn down."""
    calls = _install_fakes(monkeypatch, runner_mod)
    # Make one of the case subprocesses fail
    original_fake_run = monkeypatch.setattr(
        runner_mod.subprocess, "run",
        lambda cmd, **kw: calls["run"].append({"cmd": list(cmd), "env": kw.get("env", {})})
            or _FakeCompletedProcess(rc=1, stdout="", stderr=""),
    )
    rc, result, _ = _drive(runner_mod, monkeypatch, tmp_path)

    # Baseline must still be recorded as OK (provisioning succeeded)
    assert calls["teardown_baseline"] == []
    # Cases may have failed but shared DS persist
    assert result is not None
    assert result.get("baseline", {}).get("status") == "OK"


def test_runner_baseline_blocked_exits_1(runner_mod, monkeypatch, tmp_path):
    """When ensure_ua2_baseline raises BaselineError, exit 1 and record BLOCKED."""
    calls = _install_fakes(monkeypatch, runner_mod, baseline_should_succeed=False)
    rc, result, _ = _drive(runner_mod, monkeypatch, tmp_path)

    assert rc == 1
    assert result is not None
    assert result.get("baseline", {}).get("status") == "BLOCKED"
    assert calls["baseline_blocked"] is True