"""test_polling.py:wait_until / wait_for_value 单测。"""
from __future__ import annotations

import pytest

from ua_test_harness.polling import wait_until, wait_for_value, WaitTimeout


def test_wait_until_immediate():
    wait_until("t", lambda: True, timeout=1.0, interval=0.05)


def test_wait_until_eventually():
    counter = {"n": 0}

    def cond():
        counter["n"] += 1
        return counter["n"] >= 3

    wait_until("t", cond, timeout=2.0, interval=0.05)
    assert counter["n"] >= 3


def test_wait_until_timeout():
    with pytest.raises(WaitTimeout):
        wait_until("never", lambda: False, timeout=0.3, interval=0.05)


def test_stable_count():
    state = {"ok": False, "next_change": 5}
    polls = {"n": 0}

    def cond():
        polls["n"] += 1
        if polls["n"] >= state["next_change"]:
            state["ok"] = True
        return state["ok"]

    # 必须连续 2 次为 True 才算通过
    state["next_change"] = 100  # 永不成立
    with pytest.raises(WaitTimeout):
        wait_until("unstable", cond, timeout=0.4, interval=0.05, stable_count=2)


def test_wait_for_value_returns_last():
    v = {"x": 0}

    def fetch():
        v["x"] += 1
        return v["x"]

    val = wait_for_value("t", fetch, lambda x: x >= 3, timeout=2.0, interval=0.05)
    assert val >= 3