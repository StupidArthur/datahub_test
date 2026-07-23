"""把 Markdown 中尚未手写实现的 Case 注册为可执行 CaseDef。

本模块由 catalog.discover 最后导入：手写实现优先，剩余文档 Case 绑定到
scenario_policy。已覆盖文档动作的 Case 执行真实场景；缺失适配器或夹具的 Case
返回带明确原因的 BLOCKED，不允许普通冒烟替代边界场景并误判 PASS。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ua_test_harness.case_inventory import default_test_cases_dir, parse_case_doc
from ua_test_harness.catalog import all_defs, case
from ua_test_harness.models import StepDef
from ua_test_harness.scenario_policy import execute_documented_case

_KIND_MAP = {
    "回归": "regression",
    "探索": "exploratory",
    "性能": "performance",
    "响应时间": "response_time",
    "BLOCKED": "blocked",
}

_TIMEOUTS = {
    "UA-1": 300,
    "UA-2": 300,
    "UA-3": 600,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_documented_rows(repo_root: Path) -> list[dict[str, Any]]:
    docs = default_test_cases_dir(repo_root)
    rows: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []
    for path in sorted(docs.glob("*.md")):
        parsed, bad = parse_case_doc(path, repo_root)
        rows.extend(parsed)
        malformed.extend(bad)
    if malformed:
        details = ", ".join(f"{r['caseId']}@{r['path']}:{r['line']}" for r in malformed[:10])
        raise RuntimeError(f"documented Case rows malformed: {details}")
    ids = [row["id"] for row in rows]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise RuntimeError(f"duplicate documented Case IDs: {duplicates}")
    return rows


def _kind(row: dict[str, Any]) -> str:
    raw = str(row.get("kind") or "").strip()
    if raw in _KIND_MAP:
        return _KIND_MAP[raw]
    title = str(row.get("title") or "")
    if "性能" in title:
        return "performance"
    return "regression"


def _timeout(chapter: str, kind: str) -> int:
    if kind in ("performance", "response_time") or chapter in ("UA-3-5", "UA-3-6"):
        return 1800
    return next((seconds for prefix, seconds in _TIMEOUTS.items() if chapter.startswith(prefix)), 300)


def _make_impl(meta: dict[str, Any]):
    def documented_case(ctx, cc, _meta=meta):
        return execute_documented_case(ctx, cc, _meta)

    documented_case.__name__ = "case_" + meta["id"].lower().replace("-", "_")
    documented_case.__qualname__ = documented_case.__name__
    return documented_case


def register_documented_cases(repo_root: Path | None = None) -> int:
    root = (repo_root or _repo_root()).resolve()
    rows = _load_documented_rows(root)
    existing = {item.id for item in all_defs()}
    registered = 0
    for row in rows:
        case_id = row["id"]
        if case_id in existing:
            continue
        chapter = row["chapter"]
        kind = _kind(row)
        meta = dict(row)
        meta["kind"] = kind
        meta["repoRoot"] = str(root)
        impl = _make_impl(meta)
        case(
            id=case_id,
            title=row["title"],
            chapter=chapter,
            kind=kind,
            tags=["documented", chapter.lower(), "shared-executor"],
            timeout_sec=_timeout(chapter, kind),
            destructive=any(token in row["title"] for token in ("删除", "物理", "写入", "导入", "移动")),
            doc_path=row["docPath"],
            description=row.get("precondition", ""),
            steps=[StepDef(step_id="documented-flow", title=row.get("steps") or row["title"])],
            assertions=[row.get("expected") or "按文档验证实际结果"],
        )(impl)
        existing.add(case_id)
        registered += 1
    return registered


REGISTERED_DOCUMENTED_CASES = register_documented_cases()
