"""test_events.py:NDJSON 事件 schema 单测。"""
from __future__ import annotations

import io
import json

from ua_test_harness.events import EventEmitter


def _lines(buf: io.StringIO) -> list[dict]:
    return [json.loads(s) for s in buf.getvalue().splitlines() if s.strip()]


def test_run_started_emitted():
    buf = io.StringIO()
    e = EventEmitter(write=buf.write)
    e.run_started("rid-1", 3)
    lines = _lines(buf)
    assert len(lines) == 1
    assert lines[0]["event"] == "run_started"
    assert lines[0]["runId"] == "rid-1"
    assert lines[0]["total"] == 3
    assert "ts" in lines[0]


def test_case_lifecycle_emitted():
    buf = io.StringIO()
    e = EventEmitter(write=buf.write)
    e.case_started("UA-3-1-001", 1, 6)
    e.step_started("UA-3-1-001", "setup-tag", "create tag")
    e.step_finished("UA-3-1-001", "setup-tag", "PASS", 1200)
    e.metric("UA-3-1-001", "p95_ms", 12.5, unit="ms")
    e.evidence("UA-3-1-001", "api_response", "evidence/x.json", "tag add")
    e.case_finished("UA-3-1-001", "PASS", 3500)
    e.cleanup_finished("UA-3-1-001", "PASS")
    e.run_finished("FINISHED", {"passed": 1})
    out = _lines(buf)
    assert [o["event"] for o in out] == [
        "case_started",
        "step_started",
        "step_finished",
        "metric",
        "evidence",
        "case_finished",
        "cleanup_finished",
        "run_finished",
    ]
    assert out[3]["value"] == 12.5
    assert out[3]["unit"] == "ms"
    assert out[6]["caseId"] == "UA-3-1-001"


def test_protocol_error_carries_raw():
    buf = io.StringIO()
    e = EventEmitter(write=buf.write)
    e.protocol_error("bad json", raw='{"event":"oops"')
    line = _lines(buf)[0]
    assert line["event"] == "protocol_error"
    assert line["raw"].startswith('{"event"')


def test_log_event_emitted_with_case_id():
    buf = io.StringIO()
    e = EventEmitter(write=buf.write)
    e.log("INFO", "UA-3-1-001", "hello")
    line = _lines(buf)[0]
    assert line["event"] == "log"
    assert line["level"] == "INFO"
    assert line["caseId"] == "UA-3-1-001"