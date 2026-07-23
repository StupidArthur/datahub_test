"""end_to_end_smoke_test.py:Phase 7 端到端冒烟自测。

在不依赖真实 TPT/Mock 的前提下,跑 runner 框架的 happy path + 协议不变量。
目标:
- catalog 能导出
- runner 能串行跑多个 case(PASS/FAIL/ERROR/MEASURED)
- 全部 stdout 是 NDJSON
- report.json 包含 cases / summary
- cleanup 总是执行

用法:
  PYTHONPATH=F:/github/supcon_tools python -m pytest ua_test_harness/unit_tests/test_e2e_smoke.py -q
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

from ua_test_harness.catalog import case, reset
from ua_test_harness.config import RunConfig, PathsConfig
from ua_test_harness.runner import Runner


REPO_ROOT = Path(__file__).resolve().parents[2]


def setup_function(_fn):
    reset()


def test_catalog_export(tmp_path: Path):
    out = tmp_path / "c.json"
    rc = subprocess.run(
        [sys.executable, "-m", "ua_test_harness.cli", "catalog", "--output", str(out)],
        env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert rc.returncode == 0, rc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["chapters"]) >= 6  # 至少有 UA-1/UA-2/UA-3 等

    # 至少包含首批冒烟需要的 6 个核心 case
    case_ids = []
    for ch in data["chapters"]:
        case_ids.extend(c["id"] for c in ch["cases"])
    required = ["UA-1-1-01", "UA-2-1-001", "UA-3-1-001", "UA-3-2-001", "UA-3-3-001", "UA-3-4-001"]
    missing = [r for r in required if r not in case_ids]
    assert not missing, f"missing smoke cases: {missing}"


def test_runner_dry_run(tmp_path: Path):
    """runner.run dry-run 路径:fake case + fake config + 写 report。"""
    @case(id="UA-T-9-001", title="e2e smoke pass", chapter="UA-T-9")
    def p(ctx, cc):
        return None

    @case(id="UA-T-9-002", title="e2e smoke fail", chapter="UA-T-9")
    def f(ctx, cc):
        raise AssertionError("intentional fail")

    @case(id="UA-T-9-003", title="e2e smoke observed", chapter="UA-T-9")
    def o(ctx, cc):
        from ua_test_harness.models import CaseStatus
        return CaseStatus.OBSERVED

    buf = io.StringIO()
    from ua_test_harness.events import EventEmitter

    em = EventEmitter(write=buf.write)
    cfg = RunConfig(run_id="rid-e2e", paths=PathsConfig(report_path=str(tmp_path / "report.json")))
    runner = Runner(cfg, cases=[p, f, o])
    runner.emitter = em
    rc = runner.run()
    # 包含 FAIL → exit 1
    assert rc == 1

    # 报告文件存在
    rep = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert rep["runId"] == "rid-e2e"
    s = rep["summary"]
    assert s["passed"] == 1
    assert s["failed"] == 1
    assert s["observed"] == 1
    assert s["errors"] == 0

    # NDJSON 不变量:每行都是合法 JSON,且至少包含 run_finished
    lines = [json.loads(s) for s in buf.getvalue().splitlines() if s.strip()]
    types = [e["event"] for e in lines]
    for must in ["run_started", "case_finished", "cleanup_finished", "run_finished"]:
        assert must in types


def test_smoke_preset_match(tmp_path: Path):
    """冒烟预设应能在 catalog 中找到 6 个核心 case。"""
    out = tmp_path / "c.json"
    rc = subprocess.run(
        [sys.executable, "-m", "ua_test_harness.cli", "catalog", "--output", str(out)],
        env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert rc.returncode == 0, rc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    ids = {c["id"] for ch in data["chapters"] for c in ch["cases"]}
    smoke = ["UA-1-1-01", "UA-2-1-001", "UA-3-1-001", "UA-3-2-001", "UA-3-3-001", "UA-3-4-001"]
    for s in smoke:
        assert s in ids, f"smoke case missing in catalog: {s}"


def test_run_cli_dry_run(tmp_path: Path):
    """run --dry-run 列出将执行的用例,不实际执行。"""
    cfg_path = tmp_path / "rc.json"
    cfg_path.write_text(json.dumps({"runId": "rid-dry", "selectedCaseIds": []}), encoding="utf-8")
    rc = subprocess.run(
        [
            sys.executable, "-m", "ua_test_harness.cli", "run",
            "--config", str(cfg_path),
            "--cases", "UA-1-1-01,UA-2-1-001",
            "--dry-run",
        ],
        env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert rc.returncode == 0, rc.stderr
    assert "UA-1-1-01" in rc.stdout
    assert "UA-2-1-001" in rc.stdout