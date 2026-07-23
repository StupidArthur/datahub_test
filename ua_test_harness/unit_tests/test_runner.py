"""Runner end-to-end tests using fake Cases only."""
from __future__ import annotations

import io
import json
from pathlib import Path

from ua_test_harness.catalog import case, reset
from ua_test_harness.config import PathsConfig, RunConfig
from ua_test_harness.events import EventEmitter
from ua_test_harness.runner import Runner


def setup_function(_fn):
    reset()


def _collect_emitter() -> tuple[io.StringIO, EventEmitter]:
    buf = io.StringIO()
    return buf, EventEmitter(write=buf.write)


def test_runner_pass_case(tmp_path: Path):
    @case(id="UA-T-1-001", title="happy", chapter="UA-T-1")
    def happy(ctx, cc):
        ctx.emitter.log("INFO", cc.case_id, "step ok")

    buf, emitter = _collect_emitter()
    cfg = RunConfig(
        run_id="rid-test",
        selected_case_ids=["UA-T-1-001"],
        paths=PathsConfig(report_path=str(tmp_path / "r.json")),
    )
    runner = Runner(cfg, cases=[happy])
    runner.emitter = emitter
    rc = runner.run()
    assert rc == 0
    events = [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]
    types = [event["event"] for event in events]
    assert "run_started" in types
    assert "case_started" in types
    assert "case_finished" in types
    assert "cleanup_finished" in types
    assert "run_finished" in types
    assert any(event["event"] == "case_finished" and event["status"] == "PASS" for event in events)
    assert (tmp_path / "r.json").is_file()


def test_runner_fail_case_returns_1(tmp_path: Path):
    @case(id="UA-T-1-002", title="boom", chapter="UA-T-1")
    def boom(ctx, cc):
        raise AssertionError("intentional")

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[boom]).run()
    assert rc == 1
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["summary"]["failed"] == 1
    assert report["cases"][0]["status"] == "FAIL"


def test_runner_error_case_returns_1(tmp_path: Path):
    @case(id="UA-T-1-003", title="err", chapter="UA-T-1")
    def err(ctx, cc):
        raise RuntimeError("kaboom")

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[err]).run()
    assert rc == 1
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["summary"]["errors"] == 1


def test_case_registry_cleanup_runs_lifo_on_pass(tmp_path: Path):
    calls: list[str] = []

    @case(id="UA-T-1-004", title="cleanup-pass", chapter="UA-T-1")
    def cleanup_pass(ctx, cc):
        ctx.registry.register("a", "fake", lambda: calls.append("a"))
        ctx.registry.register("b", "fake", lambda: calls.append("b"))

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[cleanup_pass]).run()
    assert rc == 0
    assert calls == ["b", "a"]
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["cases"][0]["cleanupStatus"] == "PASS"


def test_case_registry_cleanup_runs_on_failure(tmp_path: Path):
    calls: list[str] = []

    @case(id="UA-T-1-005", title="cleanup-fail-main", chapter="UA-T-1")
    def fail(ctx, cc):
        ctx.registry.register("resource", "fake", lambda: calls.append("cleaned"))
        raise AssertionError("nope")

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[fail]).run()
    assert rc == 1
    assert calls == ["cleaned"]
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["cases"][0]["status"] == "FAIL"
    assert report["cases"][0]["cleanupStatus"] == "PASS"


def test_case_registries_are_isolated(tmp_path: Path):
    calls: list[str] = []

    @case(id="UA-T-1-006", title="first", chapter="UA-T-1")
    def first(ctx, cc):
        ctx.registry.register("first", "fake", lambda: calls.append("first"))

    @case(id="UA-T-1-007", title="second", chapter="UA-T-1")
    def second(ctx, cc):
        assert calls == ["first"]
        ctx.registry.register("second", "fake", lambda: calls.append("second"))

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[first, second]).run()
    assert rc == 0
    assert calls == ["first", "second"]


def test_runner_observed_case_returns_0(tmp_path: Path):
    from ua_test_harness.models import CaseStatus

    @case(id="UA-T-1-008", title="observe", chapter="UA-T-1", kind="exploratory")
    def observed(ctx, cc):
        return CaseStatus.OBSERVED

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[observed]).run()
    assert rc == 0
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["summary"]["observed"] == 1


def test_runner_emits_registry_cleanup_failure(tmp_path: Path):
    @case(id="UA-T-1-009", title="cleanup-error", chapter="UA-T-1")
    def cleanup_error(ctx, cc):
        ctx.registry.register(
            "broken",
            "fake",
            lambda: (_ for _ in ()).throw(RuntimeError("cleanup boom")),
        )

    cfg = RunConfig(run_id="rid-test", paths=PathsConfig(report_path=str(tmp_path / "r.json")))
    rc = Runner(cfg, cases=[cleanup_error]).run()
    assert rc == 1
    report = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert report["summary"]["cleanupFailed"] == 1
    assert report["cases"][0]["cleanupStatus"] == "CLEANUP_FAILED"
    assert "cleanup boom" in report["cases"][0]["cleanupMessage"]
