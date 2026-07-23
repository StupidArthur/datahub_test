from __future__ import annotations

from ua_test_harness.scenario_policy import _SUPPORTED, classify_case


def test_ua1_precise_matrix_contains_all_chapters() -> None:
    total = sum(len(v) for k, v in _SUPPORTED.items() if k.startswith("UA-1-"))
    assert total == 56, total
    assert "UA-1-2-03" in _SUPPORTED.get("UA-1-2", set())
    assert "UA-1-5-03" in _SUPPORTED.get("UA-1-5", set())


def test_runtime_classify_routes_to_chapter_handlers() -> None:
    ua3 = classify_case({"id": "UA-3-6-001", "title": "性能", "chapter": "UA-3-6"})
    assert ua3.executable is True
    assert ua3.scenario == "ua3_runtime"
    ua2 = classify_case({"id": "UA-2-1-001", "title": "新增", "chapter": "UA-2-1"})
    assert ua2.executable is True
    assert ua2.scenario == "ua2_runtime"
