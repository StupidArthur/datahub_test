"""419 条文档 Case 挂接矩阵单测 — 不跑真环境。"""
from __future__ import annotations

from pathlib import Path

from ua_test_harness.case_inventory import load_documented_cases
from ua_test_harness.known_blocked import KNOWN_BLOCKED
from ua_test_harness.scenario_policy import _SUPPORTED, execute_documented_case
from ua_test_harness.models import CaseStatus
from ua_test_harness.ua2_runtime import is_supported_ua2, supported_ua2_ids
from ua_test_harness.ua3_runtime import is_supported_ua3, supported_ua3_ids


def _repo() -> Path:
    return Path(__file__).resolve().parents[2]


def test_documented_case_count_is_419():
    rows, _ = load_documented_cases(_repo())
    assert len(rows) == 419


def test_all_documented_ids_in_supported_matrix():
    rows, _ = load_documented_cases(_repo())
    missing: list[str] = []
    for row in rows:
        cid, ch = row["id"], row["chapter"]
        if cid not in _SUPPORTED.get(ch, set()):
            missing.append(cid)
    assert missing == [], f"missing from _SUPPORTED: {missing}"


def test_chapter_totals():
    rows, _ = load_documented_cases(_repo())
    by_prefix: dict[str, int] = {}
    for row in rows:
        parts = row["id"].split("-")
        key = f"{parts[0]}-{parts[1]}"
        by_prefix[key] = by_prefix.get(key, 0) + 1
    assert by_prefix == {"UA-1": 56, "UA-2": 265, "UA-3": 98}


def test_ua2_all_ids_have_runtime_handler():
    assert len(supported_ua2_ids()) == 265
    for cid in supported_ua2_ids():
        assert is_supported_ua2(cid)


def test_ua3_all_ids_have_runtime_handler():
    assert len(supported_ua3_ids()) == 98
    for cid in supported_ua3_ids():
        assert is_supported_ua3(cid)


def test_known_blocked_still_registered():
    for cid in KNOWN_BLOCKED:
        parts = cid.split("-")
        chapter = f"{parts[0]}-{parts[1]}-{parts[2]}"
        assert cid in _SUPPORTED.get(chapter, set()), cid


def test_execute_routes_ua3_not_shared_scenario(monkeypatch):
    """UA-3 必须走 ua3_runtime,不能落回遗留共享场景。"""
    called = {"ua3": 0}

    def fake_ua3(ctx, cc, meta):
        called["ua3"] += 1
        return CaseStatus.PASS

    monkeypatch.setattr("ua_test_harness.scenario_policy.execute_ua3_case", fake_ua3)

    class _Ctx:
        class emitter:
            @staticmethod
            def log(*_a, **_k):
                pass

    class _Cc:
        pass

    meta = {"id": "UA-3-1-001", "chapter": "UA-3-1", "title": "采集"}
    status = execute_documented_case(_Ctx(), _Cc(), meta)
    assert status == CaseStatus.PASS
    assert called["ua3"] == 1
