"""Document Case exact-execution dispatch.

调度顺序:
  UA-1 -> execute_ua1_case
  UA-2 -> execute_ua2_case (章节 dispatcher)
  UA-3 -> execute_ua3_case (章节 dispatcher)

419 条文档 Case 均在 _SUPPORTED 中登记;运行时由对应 runtime 执行。
仅 KNOWN_BLOCKED 中的 ID 在真环境中预期 BLOCKED/OBSERVED,不得空函数 PASS。
"""
from __future__ import annotations

from dataclasses import dataclass

from ua_test_harness.models import CaseStatus
from ua_test_harness.ua1_runtime import execute_ua1_case
from ua_test_harness.ua2_registry import ua2_supported_sets
from ua_test_harness.ua2_runtime import is_supported_ua2, execute_ua2_case
from ua_test_harness.ua3_runtime import is_supported_ua3, execute_ua3_case


def _ua1_all_supported() -> dict[str, set[str]]:
    from pathlib import Path
    from ua_test_harness.case_inventory import load_documented_cases

    rows, _ = load_documented_cases(Path(__file__).resolve().parents[1])
    out: dict[str, set[str]] = {}
    for row in rows:
        if not row["id"].startswith("UA-1-"):
            continue
        out.setdefault(row["chapter"], set()).add(row["id"])
    return out


def _ua3_all_supported() -> dict[str, set[str]]:
    from pathlib import Path
    from ua_test_harness.case_inventory import load_documented_cases

    rows, _ = load_documented_cases(Path(__file__).resolve().parents[1])
    out: dict[str, set[str]] = {}
    for row in rows:
        if not row["id"].startswith("UA-3-"):
            continue
        out.setdefault(row["chapter"], set()).add(row["id"])
    return out


_SUPPORTED = {
    **_ua1_all_supported(),
    **ua2_supported_sets(),
    **_ua3_all_supported(),
}


_BLOCK_REASONS = {
    # 仅当 case 不在 _SUPPORTED 时使用的兜底说明
    "UA-2-2": "文档 Case 未纳入 supported 矩阵",
}


@dataclass(frozen=True)
class ScenarioDecision:
    executable: bool
    scenario: str = ""
    reason: str = ""


def classify_case(meta) -> ScenarioDecision:
    case_id = meta["id"]
    if case_id.startswith("UA-3-"):
        if is_supported_ua3(case_id):
            return ScenarioDecision(True, scenario="ua3_runtime")
        return ScenarioDecision(False, reason=f"UA-3 handler missing for {case_id}")
    if case_id.startswith("UA-2-"):
        if is_supported_ua2(case_id):
            return ScenarioDecision(True, scenario="ua2_runtime")
        return ScenarioDecision(False, reason=f"UA-2 handler missing for {case_id}")
    if case_id.startswith("UA-1-"):
        chapter = meta.get("chapter") or ""
        if case_id in _SUPPORTED.get(chapter, set()):
            return ScenarioDecision(True, scenario="ua1_runtime")
        return ScenarioDecision(False, reason=f"UA-1 not in supported matrix: {case_id}")
    return ScenarioDecision(False, reason=f"unsupported chapter for {case_id}")


def execute_documented_case(ctx, cc, meta):
    chapter = meta["chapter"]
    case_id = meta["id"]
    if case_id not in _SUPPORTED.get(chapter, set()):
        reason = _BLOCK_REASONS.get(chapter, f"章节 {chapter} 尚无精确共享执行器")
        ctx.emitter.log("WARN", case_id, f"BLOCKED: {reason}")
        return CaseStatus.BLOCKED
    if chapter.startswith("UA-1-"):
        return execute_ua1_case(ctx, cc, meta)
    if chapter.startswith("UA-2-"):
        if not is_supported_ua2(case_id):
            ctx.emitter.log(
                "WARN",
                case_id,
                "BLOCKED: UA-2 在 registered set 中但未挂 handler;"
                " 需要 queryWithQuality、asyncua、批量、导入导出或分组适配器。",
            )
            return CaseStatus.BLOCKED
        return execute_ua2_case(ctx, cc, meta)
    if chapter.startswith("UA-3-"):
        if not is_supported_ua3(case_id):
            ctx.emitter.log(
                "WARN",
                case_id,
                "BLOCKED: UA-3 在 registered set 中但未挂 handler。",
            )
            return CaseStatus.BLOCKED
        return execute_ua3_case(ctx, cc, meta)
    ctx.emitter.log("WARN", case_id, f"BLOCKED: unknown chapter {chapter}")
    return CaseStatus.BLOCKED
