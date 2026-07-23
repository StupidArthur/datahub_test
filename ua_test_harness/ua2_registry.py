"""UA-2 case ID 注册表: 从文档加载各章全部 ID。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ua_test_harness.case_inventory import load_documented_cases


@lru_cache(maxsize=1)
def ua2_cases_by_chapter() -> dict[str, list[dict]]:
    repo = Path(__file__).resolve().parents[1]
    rows, _ = load_documented_cases(repo)
    out: dict[str, list[dict]] = {}
    for row in rows:
        if not row["id"].startswith("UA-2-"):
            continue
        out.setdefault(row["chapter"], []).append(row)
    for ch in out:
        out[ch].sort(key=lambda r: r["id"])
    return out


def ua2_all_ids() -> list[str]:
    return [r["id"] for rows in ua2_cases_by_chapter().values() for r in rows]


def ua2_supported_sets() -> dict[str, set[str]]:
    return {ch: {r["id"] for r in rows} for ch, rows in ua2_cases_by_chapter().items()}
