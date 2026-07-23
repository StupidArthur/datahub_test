"""任务 C: UA-3 legacy 7 条双轨合并验收。"""
from __future__ import annotations

from unittest.mock import MagicMock

from ua_test_harness.catalog import all_defs, discover, reset
from ua_test_harness.models import CaseStatus
from ua_test_harness.scenario_policy import execute_documented_case


LEGACY_IDS = (
    "UA-3-1-001",
    "UA-3-1-004",
    "UA-3-2-001",
    "UA-3-2-012",
    "UA-3-3-001",
    "UA-3-4-001",
    "UA-3-5-001",
)


def _reload_catalog():
    reset()
    discover("ua_test_harness.tests")
    from ua_test_harness.tests.zz_documented_cases import register_documented_cases
    register_documented_cases()


def test_legacy_ids_use_documented_dispatcher_not_handwritten():
    _reload_catalog()
    by_id = {item.id: item for item in all_defs()}
    for cid in LEGACY_IDS:
        item = by_id[cid]
        assert "documented" in item.tags, cid
        assert item.impl_func.__name__.startswith("case_ua_3"), cid


def test_legacy_ids_route_through_ua3_runtime(monkeypatch):
    routed: list[str] = []

    def fake_ua3(ctx, cc, meta):
        routed.append(meta["id"])
        return CaseStatus.PASS

    monkeypatch.setattr("ua_test_harness.scenario_policy.execute_ua3_case", fake_ua3)

    class _Ctx:
        class emitter:
            @staticmethod
            def log(*_a, **_k):
                pass

    class _Cc:
        pass

    for cid in LEGACY_IDS:
        chapter = "-".join(cid.split("-")[:3])
        meta = {"id": cid, "chapter": chapter, "title": "legacy merge"}
        status = execute_documented_case(_Ctx(), _Cc(), meta)
        assert status == CaseStatus.PASS
    assert set(routed) == set(LEGACY_IDS)
