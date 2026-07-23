"""test_resources.py:ResourceRegistry LIFO 单测。"""
from __future__ import annotations

import pytest

from ua_test_harness.resources import ResourceRegistry
from ua_test_harness.models import CaseStatus


def test_lifo_cleanup_order():
    order: list[str] = []
    r = ResourceRegistry()
    r.register("a", "tag", lambda: order.append("a"))
    r.register("b", "tag", lambda: order.append("b"))
    r.register("c", "tag", lambda: order.append("c"))
    status = r.cleanup_all()
    assert order == ["c", "b", "a"]
    assert status == CaseStatus.PASS
    assert r.size() == 0


def test_cleanup_continues_on_error():
    order: list[str] = []
    r = ResourceRegistry()
    r.register("a", "tag", lambda: order.append("a"))
    r.register("b", "tag", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r.register("c", "tag", lambda: order.append("c"))
    errs: list[str] = []
    status = r.cleanup_all(errs)
    assert order == ["c", "a"]  # b 抛错但 c 已被 LIFO pop,仍执行;a 最后执行
    assert status == CaseStatus.CLEANUP_FAILED
    assert any("boom" in e for e in errs)


def test_pop_specific():
    r = ResourceRegistry()
    r.register("a", "tag", lambda: None)
    r.register("b", "tag", lambda: None)
    popped = r.pop("a")
    assert popped is not None and popped.name == "a"
    assert r.size() == 1
    assert r.pop("nope") is None


def test_empty_cleanup_passes():
    r = ResourceRegistry()
    assert r.cleanup_all() == CaseStatus.PASS