"""polling.py:通用轮询与具体场景等待。

禁止在功能测试中使用固定长 sleep 替代状态等待(plan.md 5.6)。
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class WaitTimeout(Exception):
    pass


def wait_until(
    name: str,
    condition: Callable[[], bool],
    timeout: float,
    interval: float = 0.5,
    stable_count: int = 1,
    on_poll: Callable[[int, float], None] | None = None,
) -> None:
    """轮询 condition,直到返回 True 持续 stable_count 次,或超时。

    超时抛 WaitTimeout。
    """
    if timeout <= 0:
        raise WaitTimeout(f"{name}: timeout<=0")
    deadline = time.monotonic() + timeout
    streak = 0
    polls = 0
    while True:
        polls += 1
        try:
            ok = bool(condition())
        except Exception:
            ok = False
        if on_poll is not None:
            try:
                on_poll(polls, time.monotonic())
            except Exception:
                pass
        if ok:
            streak += 1
            if streak >= stable_count:
                return
        else:
            streak = 0
        if time.monotonic() >= deadline:
            raise WaitTimeout(f"{name}: timed out after {timeout:.1f}s, polls={polls}")
        time.sleep(max(0.05, interval))


def wait_for_value(
    name: str,
    fetch: Callable[[], T],
    predicate: Callable[[T], bool],
    timeout: float,
    interval: float = 0.5,
) -> T:
    """拉取 fetch() 直到 predicate(value) 为 True;返回最后一个 value。"""
    deadline = time.monotonic() + timeout
    last: T = fetch()  # type: ignore[assignment]
    while not predicate(last):
        if time.monotonic() >= deadline:
            raise WaitTimeout(f"{name}: timed out after {timeout:.1f}s")
        time.sleep(max(0.05, interval))
        last = fetch()
    return last


# 场景封装 --------------------------------------------------------------
# 各用例可直接调这些高层 API;内部仍走 wait_until,只是把语义固化下来。

def wait_ds_alive(fetch_alive: Callable[[], bool], timeout: float = 60.0, interval: float = 1.0) -> None:
    wait_until("ds_alive", fetch_alive, timeout=timeout, interval=interval)


def wait_ds_offline(fetch_alive: Callable[[], bool], timeout: float = 60.0, interval: float = 1.0) -> None:
    wait_until("ds_offline", lambda: not fetch_alive(), timeout=timeout, interval=interval)


def wait_tag_visible(fetch_present: Callable[[], bool], timeout: float = 30.0, interval: float = 1.0) -> None:
    wait_until("tag_visible", fetch_present, timeout=timeout, interval=interval)


def wait_tag_absent(fetch_present: Callable[[], bool], timeout: float = 30.0, interval: float = 1.0) -> None:
    wait_until("tag_absent", lambda: not fetch_present(), timeout=timeout, interval=interval)