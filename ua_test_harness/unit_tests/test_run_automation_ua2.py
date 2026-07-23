"""run_automation_ua2 case 选择逻辑单测。"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.run_automation_ua2 import (  # noqa: E402
    _auto_batch_limit,
    resolve_selected_cases,
)
from ua_test_harness.case_fidelity import STRICT_IMPLEMENTED


def test_chapter_ua21_selects_strict_only():
    selected, meta = resolve_selected_cases(
        cases_arg="",
        chapter="UA-2-1",
        limit=5,
        skip_verified=True,
        chapter_timeout_sec=2700.0,
        skip_prereqs=True,
    )
    assert meta["selectionMode"] == "chapter"
    assert all(cid in STRICT_IMPLEMENTED for cid in selected)
    assert 1 <= len(selected) <= 5


def test_auto_batch_limit_respects_timeout():
    ids = [f"UA-2-1-{i:03d}" for i in range(1, 21)]
    n = _auto_batch_limit(ids, 2700.0, skip_prereqs=True)
    assert 1 <= n < len(ids)


def test_default_batch_includes_verified_cases():
    from scripts.run_automation_ua2 import CASES_UA2_DEFAULT

    selected, meta = resolve_selected_cases(
        cases_arg="",
        chapter="",
        limit=0,
        skip_verified=True,
        chapter_timeout_sec=2700.0,
        skip_prereqs=False,
    )
    assert meta["selectionMode"] == "default_batch"
    assert "UA-2-1-017" in selected
    assert len(selected) == len([c for c in CASES_UA2_DEFAULT if c in STRICT_IMPLEMENTED])
