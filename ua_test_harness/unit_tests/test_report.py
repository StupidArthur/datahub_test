"""test_report.py:report.json 字段完整性。"""
from __future__ import annotations

from ua_test_harness.models import CaseResult, CaseStatus, Metric, Evidence, RunStats, StepResult
from ua_test_harness.report import build_report


def test_build_report_includes_summary_and_cases():
    cr = CaseResult(case_id="UA-1", title="t", status=CaseStatus.PASS,
                    started_at="s", finished_at="f", duration_ms=10, summary="ok")
    cr.steps.append(StepResult(case_id="UA-1", step_id="s1", title="t", status=CaseStatus.PASS, duration_ms=5))
    cr.metrics.append(Metric(case_id="UA-1", name="p95", value=12.3, unit="ms"))
    cr.evidences.append(Evidence(case_id="UA-1", kind="api_response", path="x.json"))
    stats = RunStats()
    stats.add(CaseStatus.PASS)
    rep = build_report("rid", "s", "f", "FINISHED", stats, [cr], note="")
    assert rep["runId"] == "rid"
    assert rep["summary"]["passed"] == 1
    assert rep["cases"][0]["id"] == "UA-1"
    assert rep["cases"][0]["metrics"][0]["value"] == 12.3
    assert rep["cases"][0]["evidences"][0]["path"] == "x.json"