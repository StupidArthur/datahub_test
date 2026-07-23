"""Case 实现保真度登记 — 区分严格 IMPLEMENTED 与 PARTIAL 派发。

维护两个集合:
  STRICT_IMPLEMENTED: 有真实 doc 断言、handler 内使用 check_* / AssertFail 闭环
  OBSERVED_ONLY:      已派发但仅 OBSERVED/夹具简化/探索记录,无完整断言

inventory 使用 resolve_implementation_status() 生成三态:
  IMPLEMENTED | PARTIAL | UNIMPLEMENTED
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

ImplementationStatus = Literal["IMPLEMENTED", "PARTIAL", "UNIMPLEMENTED"]


def _ids(chapter: str, nums: range | list[int]) -> frozenset[str]:
    """三位序号 (UA-2/UA-3)。"""
    if isinstance(nums, range):
        nums = list(nums)
    return frozenset(f"{chapter}-{n:03d}" for n in nums)


def _ids_ua1(chapter: str, nums: range | list[int]) -> frozenset[str]:
    """两位序号 (UA-1)。"""
    if isinstance(nums, range):
        nums = list(nums)
    return frozenset(f"{chapter}-{n:02d}" for n in nums)


def _build_strict_implemented() -> frozenset[str]:
    """有真实 doc 断言的 case — 任务 A 完成后从此集合扩展。"""
    out: set[str] = set()

    # --- UA-1: 手写 + runtime 核心回归 ---
    out |= _ids_ua1("UA-1-1", range(1, 5))      # 01~04 连接回归
    out.add("UA-1-1-12")                         # 重复 endpoint 拒绝
    out |= _ids_ua1("UA-1-2", [1, 2, 6, 7, 8])
    out |= _ids_ua1("UA-1-3", range(1, 9))
    out |= _ids_ua1("UA-1-4", range(1, 7))
    out |= {"UA-1-5-01", "UA-1-5-07"}
    out |= _ids_ua1("UA-1-6", range(1, 14))

    # --- UA-2-1: 核心读写/可用性/字段回归 ---
    out |= _ids("UA-2-1", range(1, 11))         # 001~010
    out.add("UA-2-1-014")                        # 空 tagBaseName 回归(任务 A)
    out |= _ids("UA-2-1", [13, 16, 17, 18, 19, 21, 22])
    out |= _ids("UA-2-1", range(26, 39))        # 类型读取闭环 026~038
    out |= {
        "UA-2-1-039", "UA-2-1-040",
        "UA-2-1-042", "UA-2-1-044", "UA-2-1-046", "UA-2-1-048",
        "UA-2-1-050", "UA-2-1-052",
        "UA-2-1-054", "UA-2-1-055", "UA-2-1-057", "UA-2-1-058",
        "UA-2-1-060", "UA-2-1-061", "UA-2-1-063", "UA-2-1-064",
        "UA-2-1-066", "UA-2-1-067", "UA-2-1-068",
        "UA-2-1-071", "UA-2-1-072", "UA-2-1-073", "UA-2-1-074",
    }
    # 任务 A 第三批: 探索类 doc 硬断言(拒绝不变/无残留/可用性)
    out |= {
        "UA-2-1-011", "UA-2-1-012",
        "UA-2-1-041", "UA-2-1-043", "UA-2-1-045", "UA-2-1-047", "UA-2-1-049",
        "UA-2-1-051", "UA-2-1-053", "UA-2-1-056", "UA-2-1-059", "UA-2-1-062",
        "UA-2-1-065", "UA-2-1-085",
    }
    out |= {"UA-2-1-099", "UA-2-1-102", "UA-2-1-104"}
    out |= _ids("UA-2-1", range(76, 81))        # 076~080 单位/描述
    out |= {"UA-2-1-082", "UA-2-1-084", "UA-2-1-086"}
    out |= {"UA-2-1-091", "UA-2-1-092", "UA-2-1-095"}
    out |= {"UA-2-1-098", "UA-2-1-103"}
    out |= _ids("UA-2-1", [105, 106, 107, 108])

    # --- UA-2-2: 首批 + 任务 A 第一批回归断言 ---
    out |= {
        "UA-2-2-001", "UA-2-2-002", "UA-2-2-003", "UA-2-2-004", "UA-2-2-005",
        "UA-2-2-006", "UA-2-2-008", "UA-2-2-011", "UA-2-2-012", "UA-2-2-014",
        "UA-2-2-015", "UA-2-2-016", "UA-2-2-017", "UA-2-2-018", "UA-2-2-019",
        "UA-2-2-020", "UA-2-2-022", "UA-2-2-023", "UA-2-2-024", "UA-2-2-025",
        "UA-2-2-026", "UA-2-2-027", "UA-2-2-028", "UA-2-2-029", "UA-2-2-030",
        "UA-2-2-031", "UA-2-2-032", "UA-2-2-033", "UA-2-2-034",
        "UA-2-2-035", "UA-2-2-036", "UA-2-2-037", "UA-2-2-038", "UA-2-2-039",
        "UA-2-2-040", "UA-2-2-041", "UA-2-2-042", "UA-2-2-045", "UA-2-2-048",
        "UA-2-2-049", "UA-2-2-050", "UA-2-2-051", "UA-2-2-052", "UA-2-2-054",
        "UA-2-2-055", "UA-2-2-056", "UA-2-2-057", "UA-2-2-058", "UA-2-2-059",
        "UA-2-2-060", "UA-2-2-061", "UA-2-2-062", "UA-2-2-065", "UA-2-2-066",
        "UA-2-2-067",
    }

    # --- UA-1: 任务 A 第二批回归断言 ---
    out |= _ids_ua1("UA-1-1", [5, 6, 7, 8])
    out.add("UA-1-2-03")

    # --- UA-2-3: 导入导出回归 ---
    out |= _ids("UA-2-3", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 19, 20, 21, 25, 26, 28, 29, 30, 31])

    # --- UA-2-4: 重构四件套 + 有 check 的 ---
    out |= {
        "UA-2-4-001", "UA-2-4-002", "UA-2-4-003", "UA-2-4-004", "UA-2-4-009",
        "UA-2-4-010", "UA-2-4-013", "UA-2-4-014", "UA-2-4-015", "UA-2-4-016",
        "UA-2-4-017", "UA-2-4-020", "UA-2-4-021", "UA-2-4-024", "UA-2-4-026",
    }

    # --- UA-2-5: 分组树 CRUD 回归 ---
    out |= _ids("UA-2-5", [1, 2, 3, 4, 5, 9, 10, 11, 14, 15, 16, 18, 22, 23, 24, 25, 26, 27])

    # --- UA-3: ua3_precise 单一调度(任务 C 合并 legacy 7 条) ---
    out |= _ids("UA-3-1", [1, 2, 3, 4, 5, 6, 8, 11, 13, 14, 15, 16, 18, 19])
    out |= _ids("UA-3-2", [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 14, 19, 20, 21])
    out |= _ids("UA-3-3", [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15, 17, 18, 19])
    out |= _ids("UA-3-4", [1, 2, 3, 4, 5, 7, 8])
    out |= _ids("UA-3-5", [1])
    out |= _ids("UA-3-6", [1, 2, 4, 5, 7, 10])

    return frozenset(out)


def _build_observed_only() -> frozenset[str]:
    """派发但无完整 doc 断言 — 探索/简化/环境依赖/OBSERVED 回退。"""
    out: set[str] = set()

    # UA-1: 鉴权/恢复/删除矩阵探索
    out |= _ids_ua1("UA-1-1", [9, 10, 11])
    out |= _ids_ua1("UA-1-2", [4, 5])
    out |= _ids_ua1("UA-1-5", [2, 3, 4, 5, 6, 8, 9])

    # UA-2-1: 探索写入/名称/频率/批量余量(无 doc 硬断言部分)
    out |= _ids("UA-2-1", [15, 20, 23, 24, 25])
    out |= {
        "UA-2-1-069", "UA-2-1-070", "UA-2-1-075",
        "UA-2-1-081", "UA-2-1-083",
        "UA-2-1-087", "UA-2-1-088", "UA-2-1-089", "UA-2-1-090",
        "UA-2-1-093", "UA-2-1-094", "UA-2-1-096", "UA-2-1-097",
        "UA-2-1-100", "UA-2-1-101",
        "UA-2-1-109", "UA-2-1-110", "UA-2-1-111", "UA-2-1-112",
    }

    # UA-2-2: 名称探索/browse 探索/GUI-DEFERRED/探索结果更新
    out |= _ids("UA-2-2", [7, 9, 10, 13, 21])
    out |= _ids("UA-2-2", [43, 44, 46, 47, 53])
    out |= _ids("UA-2-2", [63, 64])

    # UA-2-3: 探索导入
    out |= _ids("UA-2-3", [12, 18, 22, 23, 24, 27, 32])

    # UA-2-4: 软删探索/物理删探索
    out |= _ids("UA-2-4", [5, 6, 7, 8, 11, 12, 18, 19, 22, 23, 25])

    # UA-2-5: 分组探索
    out |= _ids("UA-2-5", [6, 7, 8, 12, 13, 17, 19, 20, 21])

    # UA-3: ua3_extra 探索 + 响应时间/性能全章
    out |= _ids("UA-3-1", [7, 9, 12, 17, 20])
    out |= _ids("UA-3-2", [10, 11, 15, 16, 17, 18])
    out |= _ids("UA-3-3", [8, 14, 16, 20, 21, 22])
    out |= _ids("UA-3-4", [6])
    out |= _ids("UA-3-5", range(1, 13))
    out |= _ids("UA-3-6", [3, 6, 8, 9, 11, 12, 13, 14, 15])

    return frozenset(out)


STRICT_IMPLEMENTED: frozenset[str] = _build_strict_implemented()
OBSERVED_ONLY: frozenset[str] = _build_observed_only()


@lru_cache(maxsize=1)
def _doc_kinds() -> dict[str, str]:
    from ua_test_harness.case_inventory import load_documented_cases

    repo = Path(__file__).resolve().parents[1]
    rows, _ = load_documented_cases(repo)
    return {row["id"]: str(row.get("kind") or "").strip() for row in rows}


def is_known_blocked(case_id: str) -> bool:
    from ua_test_harness.known_blocked import is_known_blocked as _kb

    return _kb(case_id)


def is_strict_implemented(case_id: str) -> bool:
    return case_id in STRICT_IMPLEMENTED


def is_observed_only(case_id: str) -> bool:
    if case_id in OBSERVED_ONLY:
        return True
    kind = _doc_kinds().get(case_id, "")
    if kind in ("探索", "GUI-DEFERRED"):
        return True
    return False


def resolve_implementation_status(case_id: str, *, has_dispatch: bool) -> ImplementationStatus:
    """根据派发与保真度集合解析三态。"""
    if not has_dispatch:
        return "UNIMPLEMENTED"
    if case_id in STRICT_IMPLEMENTED:
        return "IMPLEMENTED"
    return "PARTIAL"


def fidelity_summary() -> dict[str, int]:
    """在全部 419 条已派发前提下统计三态(供回报/单测)。"""
    from ua_test_harness.catalog import all_defs, discover

    discover()
    dispatched = {item.id for item in all_defs()}
    impl = partial = unimpl = 0
    for cid in _doc_kinds():
        status = resolve_implementation_status(cid, has_dispatch=cid in dispatched)
        if status == "IMPLEMENTED":
            impl += 1
        elif status == "PARTIAL":
            partial += 1
        else:
            unimpl += 1
    return {
        "implemented": impl,
        "partial": partial,
        "unimplemented": unimpl,
        "dispatched": len(dispatched),
    }


def partial_ids_by_chapter() -> dict[str, list[str]]:
    from ua_test_harness.catalog import all_defs, discover

    discover()
    dispatched = {item.id for item in all_defs()}
    by_ch: dict[str, list[str]] = {}
    for cid in sorted(_doc_kinds()):
        if resolve_implementation_status(cid, has_dispatch=cid in dispatched) != "PARTIAL":
            continue
        ch = "-".join(cid.split("-")[:3])
        by_ch.setdefault(ch, []).append(cid)
    return by_ch
