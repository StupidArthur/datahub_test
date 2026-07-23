"""Generate a machine-readable matrix of documented and implemented Cases."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

CASE_ID_RE = re.compile(r"^UA-\d+-\d+-[A-Za-z0-9][A-Za-z0-9_-]*$")
HEADING_RE = re.compile(r"^#\s+(UA-\d+-\d+)\s*(.*)$")
_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    body = stripped[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in body.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(_SEPARATOR_RE.fullmatch(cell.replace(" ", "")) for cell in cells)


def _header_key(cell: str) -> str:
    compact = re.sub(r"[\s/（）()_-]+", "", cell).lower()
    aliases = {
        "编号": "id",
        "id": "id",
        "caseid": "id",
        "三级点": "title",
        "名称": "title",
        "标题": "title",
        "类型": "kind",
        "用例类型": "kind",
        "前置条件": "precondition",
        "前置": "precondition",
        "测试步骤": "steps",
        "步骤": "steps",
        "造数步骤": "steps",
        "操作": "steps",
        "测试数据": "testData",
        "数据": "testData",
        "预期结果": "expected",
        "预期结果断言": "expected",
        "断言": "expected",
        "预期": "expected",
        "验证手段": "verification",
        "验证": "verification",
        "清理": "cleanup",
        "清理恢复": "cleanup",
    }
    return aliases.get(compact, compact)


def _looks_like_header(cells: list[str]) -> bool:
    return bool(cells) and _header_key(cells[0]) == "id" and any(
        _header_key(cell) == "title" for cell in cells[1:]
    )


def _row_from_header(
    cells: list[str],
    header: list[str],
    *,
    chapter: str,
    chapter_title: str,
    path: Path,
    repo_root: Path,
    lineno: int,
) -> dict[str, Any]:
    warnings: list[str] = []
    if len(cells) < len(header):
        warnings.append(
            f"row has {len(cells)} cells but header has {len(header)}; missing trailing cells padded"
        )
        cells = cells + [""] * (len(header) - len(cells))
    elif len(cells) > len(header):
        warnings.append(
            f"row has {len(cells)} cells but header has {len(header)}; extra cells merged"
        )
        cells = cells[: len(header) - 1] + [" | ".join(cells[len(header) - 1 :])]

    data: dict[str, str] = {}
    for raw_key, value in zip(header, cells):
        key = _header_key(raw_key)
        if key in data and value:
            data[key] = f"{data[key]} | {value}" if data[key] else value
        else:
            data[key] = value

    steps = data.get("steps", "")
    test_data = data.get("testData", "")
    if not steps and test_data:
        steps = f"测试数据：{test_data}"

    return {
        "id": data.get("id", cells[0] if cells else ""),
        "chapter": chapter,
        "chapterTitle": chapter_title,
        "title": data.get("title", ""),
        "kind": data.get("kind", ""),
        "precondition": data.get("precondition", ""),
        "steps": steps,
        "testData": test_data,
        "expected": data.get("expected", ""),
        "verification": data.get("verification", ""),
        "cleanup": data.get("cleanup", ""),
        "docPath": path.relative_to(repo_root).as_posix(),
        "docLine": lineno,
        "documentWarnings": warnings,
    }


def parse_case_doc(path: Path, repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse Case tables by their headers instead of assuming a fixed column count."""
    chapter = path.stem
    chapter_title = chapter
    active_header: list[str] = []
    cases: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []

    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        heading = HEADING_RE.match(line.strip())
        if heading:
            chapter = heading.group(1)
            chapter_title = heading.group(2).strip() or chapter
            continue

        cells = _split_table_row(line)
        if not cells:
            continue
        if _looks_like_header(cells):
            active_header = cells
            continue
        if _is_separator(cells):
            continue
        if not CASE_ID_RE.fullmatch(cells[0]):
            continue

        if not active_header:
            malformed.append(
                {
                    "path": path.relative_to(repo_root).as_posix(),
                    "line": lineno,
                    "caseId": cells[0],
                    "columnCount": len(cells),
                    "reason": "case row has no preceding recognized header",
                    "raw": line,
                }
            )
            continue

        row = _row_from_header(
            cells,
            active_header,
            chapter=chapter,
            chapter_title=chapter_title,
            path=path,
            repo_root=repo_root,
            lineno=lineno,
        )
        if not row["title"]:
            malformed.append(
                {
                    "path": path.relative_to(repo_root).as_posix(),
                    "line": lineno,
                    "caseId": cells[0],
                    "columnCount": len(cells),
                    "reason": "case title is empty after header mapping",
                    "raw": line,
                }
            )
            continue
        cases.append(row)

    return cases, malformed


def default_test_cases_dir(repo_root: Path | None = None) -> Path:
    """Return the canonical test-case spec directory.

    When *repo_root* is given the directory is resolved relative to it
    (``<repo_root>/ua_test_harness/test_cases``).  Otherwise the directory
    is located relative to this file's package, which makes the harness
    work without depending on the GUI source tree.
    """
    if repo_root is not None:
        return repo_root.resolve() / "ua_test_harness" / "test_cases"
    return Path(__file__).resolve().parent / "test_cases"


def load_documented_cases(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    repo_root = repo_root.resolve()
    docs_dir = default_test_cases_dir(repo_root)
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"test case docs directory not found: {docs_dir}")
    rows: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []
    for path in sorted(docs_dir.glob("*.md")):
        parsed, bad = parse_case_doc(path, repo_root)
        rows.extend(parsed)
        malformed.extend(bad)
    return rows, malformed


def _implementation_map() -> dict[str, dict[str, Any]]:
    from ua_test_harness.catalog import all_defs, discover

    discover()
    return {
        item.id: {
            "filePath": item.file_path,
            "lineno": item.lineno,
            "kind": item.kind,
            "timeoutSec": item.timeout_sec,
            "tags": item.tags,
        }
        for item in all_defs()
    }


def _load_verification_overlay(path: Path | None) -> dict[str, dict[str, Any]]:
    """Load case_id -> {status, ...} from a patch JSON or existing inventory."""
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload.get("cases"), list):
        overlay: dict[str, dict[str, Any]] = {}
        for row in payload["cases"]:
            cid = row.get("id")
            status = row.get("verificationStatus")
            if cid and status and status != "NOT_VERIFIED":
                overlay[cid] = {
                    "status": status,
                    "verifiedAt": row.get("verifiedAt"),
                    "runReportPath": row.get("runReportPath"),
                    "runStatus": row.get("runStatus"),
                }
        return overlay
    if isinstance(payload.get("overlay"), dict):
        return dict(payload["overlay"])
    if all(isinstance(v, (str, dict)) for v in payload.values()):
        overlay = {}
        for cid, value in payload.items():
            if isinstance(value, str):
                overlay[cid] = {"status": value}
            elif isinstance(value, dict) and value.get("status"):
                overlay[cid] = value
        return overlay
    return {}


def verification_overlay_from_run(case_results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map automation case summaries to verification overlay entries."""
    overlay: dict[str, dict[str, Any]] = {}
    for row in case_results:
        cid = row.get("caseId") or row.get("id")
        if not cid:
            continue
        run_status = row.get("status", "UNKNOWN")
        if run_status == "PASS":
            vstatus = "VERIFIED"
        elif run_status == "FAIL":
            vstatus = "VERIFIED_FAIL"
        elif run_status in {"BLOCKED", "TIMEOUT", "ERROR"}:
            vstatus = "VERIFIED_BLOCKED"
        else:
            continue
        overlay[cid] = {
            "status": vstatus,
            "runStatus": run_status,
            "runReportPath": row.get("reportPath"),
            "cleanupStatus": row.get("cleanupStatus"),
        }
    return overlay


def build_inventory(
    repo_root: Path,
    *,
    implemented: dict[str, dict[str, Any]] | None = None,
    expected_total: int = 419,
    verification_overlay: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from ua_test_harness.case_fidelity import resolve_implementation_status

    repo_root = repo_root.resolve()
    rows, malformed = load_documented_cases(repo_root)
    implementation = implemented if implemented is not None else _implementation_map()
    counts = Counter(row["id"] for row in rows)
    duplicates = sorted(case_id for case_id, count in counts.items() if count > 1)
    documented_ids = set(counts)
    orphan_implementations = sorted(set(implementation) - documented_ids)

    cases: list[dict[str, Any]] = []
    status_counts = Counter()
    verification_counts = Counter()
    overlay = verification_overlay or {}
    for row in sorted(rows, key=lambda item: item["id"]):
        impl = implementation.get(row["id"])
        cid = row["id"]
        status = resolve_implementation_status(cid, has_dispatch=impl is not None)
        status_counts[status] += 1
        fidelity = "STRICT" if status == "IMPLEMENTED" else (
            "OBSERVED_ONLY" if status == "PARTIAL" else "NONE"
        )
        vinfo = overlay.get(cid) or {}
        vstatus = vinfo.get("status", "NOT_VERIFIED")
        verification_counts[vstatus] += 1
        case_row = {
            **row,
            "implementationStatus": status,
            "fidelityTier": fidelity,
            "implementation": impl,
            "verificationStatus": vstatus,
        }
        if vinfo.get("verifiedAt"):
            case_row["verifiedAt"] = vinfo["verifiedAt"]
        if vinfo.get("runReportPath"):
            case_row["runReportPath"] = vinfo["runReportPath"]
        if vinfo.get("runStatus"):
            case_row["runStatus"] = vinfo["runStatus"]
        cases.append(case_row)

    document_count = len(cases)
    strict_count = status_counts["IMPLEMENTED"]
    partial_count = status_counts["PARTIAL"]
    unimpl_count = status_counts["UNIMPLEMENTED"]
    warning_count = sum(len(row.get("documentWarnings") or []) for row in cases)
    summary = {
        "expectedTotal": expected_total,
        "documented": document_count,
        "implemented": strict_count,
        "partial": partial_count,
        "unimplemented": unimpl_count,
        "dispatched": strict_count + partial_count,
        "coveragePercent": round((strict_count / document_count * 100.0), 2) if document_count else 0.0,
        "duplicateDocumentIds": len(duplicates),
        "malformedRows": len(malformed),
        "documentWarnings": warning_count,
        "orphanImplementations": len(orphan_implementations),
        "structureOk": document_count == expected_total and not duplicates and not malformed,
        "verified": verification_counts.get("VERIFIED", 0),
        "verifiedFail": verification_counts.get("VERIFIED_FAIL", 0),
        "verifiedBlocked": verification_counts.get("VERIFIED_BLOCKED", 0),
        "notVerified": verification_counts.get("NOT_VERIFIED", 0),
    }
    return {
        "schemaVersion": 3,
        "generatedAt": _now(),
        "repoRoot": str(repo_root),
        "summary": summary,
        "duplicates": duplicates,
        "malformed": malformed,
        "orphanImplementations": [
            {"id": case_id, "implementation": implementation[case_id]}
            for case_id in orphan_implementations
        ],
        "cases": cases,
    }


def structural_failures(report: dict[str, Any]) -> list[str]:
    summary = report["summary"]
    failures: list[str] = []
    if summary["documented"] != summary["expectedTotal"]:
        failures.append(
            f"documented case count {summary['documented']} != expected {summary['expectedTotal']}"
        )
    if summary["duplicateDocumentIds"]:
        failures.append(f"duplicate document ids: {summary['duplicateDocumentIds']}")
    if summary["malformedRows"]:
        failures.append(f"malformed rows: {summary['malformedRows']}")
    return failures


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ua_test_harness.case_inventory")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-total", type=int, default=419)
    parser.add_argument("--strict-structure", action="store_true")
    parser.add_argument(
        "--verification-overlay",
        default="",
        help="JSON patch / existing inventory to preserve verificationStatus",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    overlay_path = Path(args.verification_overlay).expanduser() if args.verification_overlay else None
    overlay = _load_verification_overlay(overlay_path) if overlay_path else {}
    report = build_inventory(
        Path(args.repo_root),
        expected_total=args.expected_total,
        verification_overlay=overlay,
    )
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    print(
        "case inventory written: "
        f"{output} documented={summary['documented']} "
        f"implemented={summary['implemented']} "
        f"partial={summary['partial']} "
        f"unimplemented={summary['unimplemented']} "
        f"verified={summary.get('verified', 0)} "
        f"verifiedFail={summary.get('verifiedFail', 0)} "
        f"coverage={summary['coveragePercent']}%"
    )
    failures = structural_failures(report)
    if args.strict_structure and failures:
        for failure in failures:
            print(f"STRUCTURE_ERROR: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
