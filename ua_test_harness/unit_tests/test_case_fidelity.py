"""case_fidelity 与 inventory 三态单测。"""
from __future__ import annotations

from pathlib import Path

from ua_test_harness.case_fidelity import (
    OBSERVED_ONLY,
    STRICT_IMPLEMENTED,
    fidelity_summary,
    partial_ids_by_chapter,
    resolve_implementation_status,
)
from ua_test_harness.case_inventory import build_inventory, load_documented_cases


def test_strict_and_observed_disjoint_from_documented():
    repo = Path(__file__).resolve().parents[2]
    rows, _ = load_documented_cases(repo)
    doc_ids = {r["id"] for r in rows}
    assert len(doc_ids) == 419
    assert STRICT_IMPLEMENTED <= doc_ids
    assert OBSERVED_ONLY <= doc_ids


def test_fidelity_summary_totals_419():
    s = fidelity_summary()
    assert s["implemented"] + s["partial"] + s["unimplemented"] == 419
    assert s["dispatched"] == 419
    assert s["unimplemented"] == 0
    assert s["implemented"] > 0
    assert s["partial"] > 0


def test_resolve_implementation_status_three_states():
    assert resolve_implementation_status("UA-2-1-019", has_dispatch=True) == "IMPLEMENTED"
    assert resolve_implementation_status("UA-2-1-041", has_dispatch=True) == "IMPLEMENTED"
    assert resolve_implementation_status("UA-2-1-069", has_dispatch=True) == "PARTIAL"
    assert resolve_implementation_status("UA-MISSING", has_dispatch=False) == "UNIMPLEMENTED"


def test_build_inventory_emits_partial_count():
    repo = Path(__file__).resolve().parents[2]
    report = build_inventory(repo, expected_total=419)
    summary = report["summary"]
    assert summary["documented"] == 419
    assert summary["structureOk"] is True
    assert summary["implemented"] + summary["partial"] + summary["unimplemented"] == 419
    assert summary["partial"] > 0
    assert summary["coveragePercent"] == round(summary["implemented"] / 419 * 100, 2)
    statuses = {c["implementationStatus"] for c in report["cases"]}
    assert statuses <= {"IMPLEMENTED", "PARTIAL", "UNIMPLEMENTED"}


def test_partial_by_chapter_non_empty():
    by_ch = partial_ids_by_chapter()
    assert sum(len(v) for v in by_ch.values()) == fidelity_summary()["partial"]
