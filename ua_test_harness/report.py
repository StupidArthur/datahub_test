"""report.py:report.json 主报告。

字段(plan.md 15.4):
- runId / startedAt / finishedAt / status
- summary:passe/failed/...
- cases:每用例 {id, title, status, durationMs, summary, steps[], cleanupStatus, metrics[], evidences[]}
- events:可选,精简
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CaseResult, CaseStatus, Metric, Evidence, RunStats, StepResult


def build_report(
    run_id: str,
    started_at: str,
    finished_at: str,
    status: str,
    stats: RunStats,
    cases: list[CaseResult],
    note: str = "",
) -> dict[str, Any]:
    return {
        "version": 1,
        "runId": run_id,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "status": status,
        "note": note,
        "summary": stats.to_dict(),
        "cases": [_case_to_dict(c) for c in cases],
    }


def _case_to_dict(c: CaseResult) -> dict[str, Any]:
    return {
        "id": c.case_id,
        "title": c.title,
        "status": c.status.value if isinstance(c.status, CaseStatus) else str(c.status),
        "startedAt": c.started_at,
        "finishedAt": c.finished_at,
        "durationMs": c.duration_ms,
        "summary": c.summary,
        "cleanupStatus": c.cleanup_status.value if isinstance(c.cleanup_status, CaseStatus) else str(c.cleanup_status),
        "cleanupMessage": c.cleanup_message,
        "steps": [_step_to_dict(s) for s in c.steps],
        "metrics": [_metric_to_dict(m) for m in c.metrics],
        "evidences": [_evidence_to_dict(e) for e in c.evidences],
    }


def _step_to_dict(s: StepResult) -> dict[str, Any]:
    return {
        "stepId": s.step_id,
        "title": s.title,
        "status": s.status.value if isinstance(s.status, CaseStatus) else str(s.status),
        "startedAt": s.started_at,
        "finishedAt": s.finished_at,
        "durationMs": s.duration_ms,
        "message": s.message,
    }


def _metric_to_dict(m: Metric) -> dict[str, Any]:
    return {
        "name": m.name,
        "value": m.value,
        "textValue": m.text_value,
        "unit": m.unit,
        "labels": m.labels,
        "ts": m.ts,
    }


def _evidence_to_dict(e: Evidence) -> dict[str, Any]:
    return {
        "kind": e.kind,
        "path": e.path,
        "title": e.title,
        "metadata": e.metadata,
        "ts": e.ts,
    }


def write_report(report: dict[str, Any], out_path: str | Path) -> None:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")