"""test_assertions.py:断言辅助。"""
from __future__ import annotations

import pytest

from ua_test_harness.assertions import AssertFail, check_close, check_eq, check_in, check_true


def test_check_eq_pass():
    check_eq("t", 1, 1)


def test_check_eq_fail():
    with pytest.raises(AssertFail):
        check_eq("t", 1, 2)


def test_check_true_with_hint():
    with pytest.raises(AssertFail) as ei:
        check_true("t", False, "explain")
    assert "explain" in str(ei.value)


def test_check_in():
    check_in("t", "a", ["a", "b"])
    with pytest.raises(AssertFail):
        check_in("t", "x", ["a", "b"])


def test_check_close():
    check_close("t", 100, 105, rel=0.1)
    with pytest.raises(AssertFail):
        check_close("t", 100, 200, rel=0.1)