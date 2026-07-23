"""assertions.py:用例断言辅助。

设计目标:失败信息可定位到字段,evidence 可附带前后值。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AssertFail(AssertionError):
    """断言失败,带字段名和期望/实际值。"""


@dataclass
class CheckResult:
    name: str
    ok: bool
    expected: Any = None
    actual: Any = None
    message: str = ""


def check_eq(name: str, expected: Any, actual: Any) -> None:
    if expected != actual:
        raise AssertFail(f"[{name}] expected={expected!r} actual={actual!r}")


def check_true(name: str, cond: bool, hint: str = "") -> None:
    if not cond:
        raise AssertFail(f"[{name}] not true. {hint}".strip())


def check_in(name: str, value: Any, container) -> None:
    if value not in container:
        raise AssertFail(f"[{name}] {value!r} not in {list(container)!r}")


def check_close(name: str, expected: float, actual: float, rel: float = 0.1, abs_tol: float = 1e-6) -> None:
    if abs(expected - actual) <= max(abs_tol, rel * max(abs(expected), abs(actual))):
        return
    raise AssertFail(f"[{name}] expected≈{expected} actual={actual} rel={rel}")