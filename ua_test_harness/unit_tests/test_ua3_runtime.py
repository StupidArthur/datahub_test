"""UA-3 runtime 注册与 dispatcher 冒烟单测。"""
from __future__ import annotations

from ua_test_harness.ua3_runtime import _CHAPTER_DISPATCH, is_supported_ua3, supported_ua3_ids


def test_ua3_all_chapters_registered():
    ids = supported_ua3_ids()
    assert len(ids) == 98
    for cid in ids:
        assert is_supported_ua3(cid)
        chapter = "-".join(cid.split("-")[:3])
        assert chapter in _CHAPTER_DISPATCH


def test_ua3_chapter_counts():
    ids = supported_ua3_ids()
    chapters = {
        "UA-3-1": 20,
        "UA-3-2": 21,
        "UA-3-3": 22,
        "UA-3-4": 8,
        "UA-3-5": 12,
        "UA-3-6": 15,
    }
    for ch, expected in chapters.items():
        got = sum(1 for i in ids if i.startswith(ch))
        assert got == expected, f"{ch}: expected {expected}, got {got}"
