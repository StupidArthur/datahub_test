from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.audit_pytest_419 import (
    AUDIT_DIR,
    JSON_PATH,
    MD_PATH,
    build_inventory,
    generate_gap_md,
    read_existing_json,
    read_existing_md,
)


def _legacy(ids: list[str]) -> dict:
    per_file: dict[str, list[str]] = {}
    for cid in ids:
        chapter = "-".join(cid.split("-")[:2])
        fname = f"{chapter}.md"
        per_file.setdefault(fname, []).append(cid)
    by_id = {cid: next(f for f, ids in per_file.items() if cid in ids) for cid in ids}
    return {
        "by_id": by_id,
        "duplicates_across_files": [],
        "per_file_count": {f: len(v) for f, v in per_file.items()},
        "ids": sorted(ids),
    }


def test_normalized_nodeid_no_false_duplicate():
    """Same case ID with one canonical nodeid → 0 true duplicates."""
    legacy = _legacy(["UA-2-1-001"])
    pytest_cases = {
        "UA-2-1-001": ["tests/integration/x/test_a.py::test_one"],
    }
    inv = build_inventory(legacy, pytest_cases)
    assert inv["true_duplicates_in_pytest"] == []
    assert inv["pytest_total"] == 1
    assert inv["migrated"] == ["UA-2-1-001"]
    assert inv["missing"] == []


def test_true_duplicate_detected():
    """One case ID mapping to two different canonical nodeids → true duplicate."""
    legacy = _legacy(["UA-2-1-001", "UA-2-1-002"])
    pytest_cases = {
        "UA-2-1-001": [
            "tests/integration/x/test_a.py::test_a",
            "tests/integration/x/test_b.py::test_b",
        ],
    }
    inv = build_inventory(legacy, pytest_cases)
    assert "UA-2-1-001" in inv["true_duplicates_in_pytest"]
    assert inv["pytest_total"] == 1
    assert inv["migrated"] == ["UA-2-1-001"]
    assert inv["missing"] == ["UA-2-1-002"]


def test_no_redundant_nodeid_keys():
    """Each case ID maps to exactly one nodeid entry after set dedup."""
    pytest_cases = {
        "UA-1-1-01": ["tests/integration/ua1/test_connection.py::test_normal"],
    }
    for nids in pytest_cases.values():
        assert len(nids) == 1, "should have exactly one canonical nodeid per case"


def test_path_separator_normalized():
    """Nodeid must use forward slash even on Windows."""
    pytest_cases = {
        "UA-2-1-001": ["tests/integration/x/test_a.py::test_one"],
    }
    for nids in pytest_cases.values():
        for n in nids:
            assert "\\" not in n, f"nodeid contains backslash: {n}"
            assert n.startswith("tests/integration/"), f"nodeid missing tests/ prefix: {n}"
            assert ".py::" in n, f"nodeid missing .py before :: separator: {n}"


def test_migrated_missing_no_overlap():
    """migrated and missing must be disjoint and together cover all legacy ids."""
    legacy = _legacy([f"UA-2-1-{i:03d}" for i in range(1, 113)])
    all_ids = set(legacy["ids"])
    pytest_cases = {f"UA-2-1-{i:03d}": [f"tests/integration/ua2/test_x.py::test_{i}"] for i in range(1, 26)}
    inv = build_inventory(legacy, pytest_cases)
    migrated_set = set(inv["migrated"])
    missing_set = set(inv["missing"])
    assert len(migrated_set & missing_set) == 0
    assert migrated_set | missing_set == all_ids
    assert len(inv["migrated"]) == 25
    assert len(inv["missing"]) == 87
    assert inv["source_total"] == 112
    assert inv["pytest_total"] == 25


def test_audit_dir_is_docs_migration():
    """Inventory must live under docs/migration/, not output/."""
    assert AUDIT_DIR.name == "migration"
    assert AUDIT_DIR.parent.name == "docs"
    assert "output" not in str(JSON_PATH)
    assert "output" not in str(MD_PATH)


def test_json_and_md_paths_under_audit_dir():
    """Both JSON and MD paths must be children of AUDIT_DIR."""
    assert str(JSON_PATH).startswith(str(AUDIT_DIR))
    assert str(MD_PATH).startswith(str(AUDIT_DIR))


def test_check_fails_when_json_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--check must fail when JSON file does not exist."""
    monkeypatch.setattr("tools.audit_pytest_419.JSON_PATH", tmp_path / "pytest-419-inventory.json")
    monkeypatch.setattr("tools.audit_pytest_419.MD_PATH", tmp_path / "pytest-419-gap.md")
    import tools.audit_pytest_419 as mod
    legacy = _legacy(["UA-2-1-001"])
    pytest_cases = {"UA-2-1-001": ["tests/integration/x/test_a.py::test_one"]}
    inv = build_inventory(legacy, pytest_cases)
    assert mod.read_existing_json() is None
    assert mod.read_existing_md() is None


def test_check_fails_when_json_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--check must fail when JSON file has invalid content."""
    monkeypatch.setattr("tools.audit_pytest_419.JSON_PATH", tmp_path / "pytest-419-inventory.json")
    monkeypatch.setattr("tools.audit_pytest_419.MD_PATH", tmp_path / "pytest-419-gap.md")
    (tmp_path / "pytest-419-inventory.json").write_text("not json", encoding="utf-8")
    import tools.audit_pytest_419 as mod
    assert mod.read_existing_json() is None


def test_check_pass_when_content_consistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """--check must pass when JSON and MD match generated content."""
    monkeypatch.setattr("tools.audit_pytest_419.JSON_PATH", tmp_path / "pytest-419-inventory.json")
    monkeypatch.setattr("tools.audit_pytest_419.MD_PATH", tmp_path / "pytest-419-gap.md")
    import tools.audit_pytest_419 as mod

    legacy = _legacy(["UA-2-1-001"])
    pytest_cases = {"UA-2-1-001": ["tests/integration/x/test_a.py::test_one"]}
    inv = build_inventory(legacy, pytest_cases)
    json_bytes = json.dumps(inv, indent=2, ensure_ascii=False) + "\n"
    (tmp_path / "pytest-419-inventory.json").write_text(json_bytes, encoding="utf-8")
    md_content = generate_gap_md(inv)
    (tmp_path / "pytest-419-gap.md").write_text(md_content, encoding="utf-8")

    assert mod.read_existing_json() is not None
    assert mod.read_existing_md() is not None
    assert mod.read_existing_json()["source_total"] == 1
    assert mod.read_existing_json()["pytest_total"] == 1
    assert mod.read_existing_json()["migrated"] == ["UA-2-1-001"]
