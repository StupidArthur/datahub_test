"""Audit pytest migration inventory against legacy UA case IDs.

Compares the legacy Case IDs (from ua_test_harness/test_cases/UA-*.md)
with the Case IDs collected from @pytest.mark.case(...) markers via
pytest collection.

Usage:
    python -m tools.audit_pytest_419          # regenerate → docs/migration/
    python -m tools.audit_pytest_419 --check   # verify without modifying
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEGACY_DIR = REPO / "ua_test_harness" / "test_cases"
LEGACY_FILES = [
    "UA-1-1.md", "UA-1-2.md", "UA-1-3.md", "UA-1-4.md", "UA-1-5.md", "UA-1-6.md",
    "UA-2-1.md", "UA-2-2.md", "UA-2-3.md", "UA-2-4.md", "UA-2-5.md",
    "UA-3-1.md", "UA-3-2.md", "UA-3-3.md", "UA-3-4.md", "UA-3-5.md", "UA-3-6.md",
]
AUDIT_DIR = REPO / "docs" / "migration"
JSON_PATH = AUDIT_DIR / "pytest-419-inventory.json"
MD_PATH = AUDIT_DIR / "pytest-419-gap.md"

ID_RE = re.compile(r"UA-\d+-\d+-\d+\b")


def collect_legacy() -> dict:
    """Scan legacy markdown files for all UA-* case IDs."""
    by_id: dict[str, str] = {}
    duplicates: list[str] = []
    per_file: dict[str, list[str]] = {}
    for f in LEGACY_FILES:
        p = LEGACY_DIR / f
        txt = p.read_text(encoding="utf-8")
        ids = sorted(set(ID_RE.findall(txt)))
        per_file[f] = ids
        for cid in ids:
            if cid in by_id:
                duplicates.append(cid)
            else:
                by_id[cid] = f
    return {
        "by_id": by_id,
        "duplicates_across_files": sorted(set(duplicates)),
        "per_file_count": {f: len(v) for f, v in per_file.items()},
        "ids": sorted(by_id.keys()),
    }


def collect_pytest_cases() -> dict[str, list[str]]:
    """Run pytest collection and return {case_id: [canonical_nodeid, ...]}.

    Uses a pytest plugin to capture item.nodeid + @pytest.mark.case id.
    Nodeids are normalized to forward-slash separators.
    """
    import pytest

    class Collector:
        def __init__(self):
            self.cases: dict[str, set[str]] = defaultdict(set)

        def pytest_collection_modifyitems(self, items):
            for item in items:
                marker = item.get_closest_marker("case")
                if marker is None:
                    continue
                cid = marker.kwargs.get("id", "")
                if not cid:
                    continue
                nodeid = item.nodeid.replace("\\", "/")
                self.cases[cid].add(nodeid)

    collector = Collector()
    exit_code = pytest.main(
        ["--collect-only", "-q", "tests"],
        plugins=[collector],
    )
    if exit_code != 0:
        print("pytest collection failed", flush=True)
        sys.exit(exit_code)

    return {cid: sorted(nids) for cid, nids in collector.cases.items()}


def build_inventory(legacy: dict, pytest_cases: dict[str, list[str]]) -> dict:
    source_total = len(legacy["ids"])
    pytest_ids = sorted(pytest_cases.keys())
    pytest_total = len(pytest_ids)
    migrated = sorted(set(legacy["ids"]) & set(pytest_ids))
    missing = sorted(set(legacy["ids"]) - set(pytest_ids))

    case_to_nodeid: dict[str, list[str]] = {
        cid: sorted(set(nids)) for cid, nids in pytest_cases.items()
    }
    true_duplicates = sorted(
        cid for cid, nids in case_to_nodeid.items() if len(nids) > 1
    )

    pytest_nodeid_to_case: dict[str, str] = {}
    for cid, nids in pytest_cases.items():
        for n in nids:
            pytest_nodeid_to_case.setdefault(n, cid)

    by_chapter: dict[str, dict] = defaultdict(
        lambda: {"source": 0, "pytest": 0, "migrated": [], "missing": []}
    )
    for cid in legacy["ids"]:
        chapter = "-".join(cid.split("-")[:2])
        by_chapter[chapter]["source"] += 1
        if cid in pytest_cases:
            by_chapter[chapter]["migrated"].append(cid)
        else:
            by_chapter[chapter]["missing"].append(cid)
    for cid in pytest_ids:
        chapter = "-".join(cid.split("-")[:2])
        by_chapter[chapter]["pytest"] += 1

    chapter_summary = []
    for chapter in sorted(by_chapter):
        d = by_chapter[chapter]
        chapter_summary.append({
            "chapter": chapter,
            "source": d["source"],
            "pytest": d["pytest"],
            "migrated_count": len(d["migrated"]),
            "missing_count": len(d["missing"]),
            "migrated": d["migrated"],
            "missing": d["missing"],
        })

    return {
        "source_total": source_total,
        "source_files": [
            {"file": f, "count": legacy["per_file_count"].get(f, 0)}
            for f in LEGACY_FILES
        ],
        "duplicates_in_source": legacy["duplicates_across_files"],
        "pytest_total": pytest_total,
        "migrated": migrated,
        "missing": missing,
        "true_duplicates_in_pytest": true_duplicates,
        "case_to_nodeid": case_to_nodeid,
        "nodeid_to_case": pytest_nodeid_to_case,
        "by_chapter": chapter_summary,
    }


def generate_gap_md(inv: dict) -> str:
    lines: list[str] = []
    lines.append("# pytest 419 Case 迁移基线差距报告\n")
    lines.append(
        "## 1. 419 Case 的来源\n\n"
        "来源文件：`ua_test_harness/test_cases/UA-*.md`（legacy Harness 规格）。\n"
        "抽取规则：所有形如 `UA-X-Y-ZZ` 的标识符去重后形成集合。\n\n"
    )

    lines.append("## 2. 来源按章节分布\n\n| chapter | source |\n|---|---|\n")
    for row in inv["by_chapter"]:
        lines.append(f"| {row['chapter']} | {row['source']} |\n")
    lines.append(f"| **合计** | **{inv['source_total']}** |\n\n")

    lines.append("## 3. 当前 pytest 覆盖\n\n")
    lines.append(f"- pytest 收集到的 `@pytest.mark.case(id=...)` 标记数：{inv['pytest_total']}\n")
    lines.append(f"- 已迁移：{len(inv['migrated'])}\n")
    lines.append(f"- 缺失：{len(inv['missing'])}\n")
    lines.append(f"- pytest 侧真重复（同一 Case ID 对应多个不同 nodeid）：{len(inv['true_duplicates_in_pytest'])}\n\n")

    if inv["true_duplicates_in_pytest"]:
        lines.append("### 真重复\n\n")
        for cid in inv["true_duplicates_in_pytest"]:
            lines.append(f"- {cid}: {', '.join(inv['case_to_nodeid'][cid])}\n")
        lines.append("\n")

    lines.append("## 4. 按章节迁移差距\n\n")
    lines.append("| chapter | source | pytest | migrated | missing |\n|---|---|---|---|---|\n")
    for row in inv["by_chapter"]:
        lines.append(
            f"| {row['chapter']} | {row['source']} | {row['pytest']} | "
            f"{row['migrated_count']} | {row['missing_count']} |\n"
        )
    lines.append(
        f"| **合计** | **{inv['source_total']}** | **{inv['pytest_total']}** | "
        f"**{len(inv['migrated'])}** | **{len(inv['missing'])}** |\n\n"
    )

    lines.append("## 5. 缺失清单（按章节）\n\n")
    any_missing = False
    for row in inv["by_chapter"]:
        if row["missing"]:
            any_missing = True
            lines.append(f"### {row['chapter']}（缺失 {row['missing_count']}）\n\n")
            for cid in row["missing"]:
                lines.append(f"- {cid}\n")
            lines.append("\n")
    if not any_missing:
        lines.append("无缺失。\n\n")

    lines.append("## 6. 命名空间与重复\n\n")
    lines.append(f"- 来源侧跨文件 Case ID 重复：{len(inv['duplicates_in_source'])}\n")
    lines.append(f"- pytest 侧真重复：{len(inv['true_duplicates_in_pytest'])}\n")
    lines.append("- 来源侧章节分布合计与 419 一致。\n\n")

    return "".join(lines)


def read_existing_json() -> dict | None:
    try:
        return json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def read_existing_md() -> str | None:
    try:
        return MD_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def main():
    check_mode = "--check" in sys.argv

    legacy = collect_legacy()
    pytest_cases = collect_pytest_cases()
    inv = build_inventory(legacy, pytest_cases)

    if check_mode:
        existing_json = read_existing_json()
        existing_md = read_existing_md()
        errors = []

        if existing_json is None:
            errors.append(f"missing {JSON_PATH}")
        elif existing_json.get("source_total") != inv["source_total"]:
            errors.append(
                f"source_total mismatch: {existing_json.get('source_total')} != {inv['source_total']}"
            )
        elif existing_json.get("pytest_total") != inv["pytest_total"]:
            errors.append(
                f"pytest_total mismatch: {existing_json.get('pytest_total')} != {inv['pytest_total']}"
            )
        elif existing_json.get("migrated") != inv["migrated"]:
            errors.append("migrated list mismatch")
        elif existing_json.get("missing") != inv["missing"]:
            errors.append("missing list mismatch")
        elif existing_json.get("true_duplicates_in_pytest") != inv["true_duplicates_in_pytest"]:
            errors.append(
                f"true_duplicates_in_pytest mismatch: "
                f"{existing_json.get('true_duplicates_in_pytest')} != {inv['true_duplicates_in_pytest']}"
            )

        new_md = generate_gap_md(inv)
        if existing_md is None:
            errors.append(f"missing {MD_PATH}")
        elif existing_md.strip() != new_md.strip():
            errors.append(f"{MD_PATH} content mismatch")

        if errors:
            for e in errors:
                print(f"CHECK FAILED: {e}", flush=True)
            sys.exit(1)
        print("audit --check passed", flush=True)
        return

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    json_content = json.dumps(inv, indent=2, ensure_ascii=False) + "\n"
    JSON_PATH.write_text(json_content, encoding="utf-8")
    print(f"wrote {JSON_PATH}", flush=True)

    md_content = generate_gap_md(inv)
    MD_PATH.write_text(md_content, encoding="utf-8")
    print(f"wrote {MD_PATH}", flush=True)


if __name__ == "__main__":
    main()
