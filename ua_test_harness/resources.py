"""resources.py:资源注册表 + LIFO 清理。

约束(plan.md 5.5):
- 每创建资源立即登记清理动作;
- 清理按 LIFO 执行;
- 无论 PASS/FAIL/ERROR/取消,都必须执行清理。
"""
from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from .models import CaseStatus


@dataclass
class Resource:
    name: str
    kind: str
    cleanup: Callable[[], None]
    payload: Any = None


class ResourceRegistry:
    def __init__(self, owner: str = "") -> None:
        self._stack: list[Resource] = []
        self._lock = threading.Lock()
        self.owner = owner

    def register(self, name: str, kind: str, cleanup: Callable[[], None], payload: Any = None) -> Resource:
        r = Resource(name=name, kind=kind, cleanup=cleanup, payload=payload)
        with self._lock:
            self._stack.append(r)
        return r

    def pop(self, name: str) -> Resource | None:
        with self._lock:
            for i in range(len(self._stack) - 1, -1, -1):
                if self._stack[i].name == name:
                    return self._stack.pop(i)
        return None

    def snapshot(self) -> list[dict[str, str]]:
        with self._lock:
            return [{"name": r.name, "kind": r.kind} for r in self._stack]

    def cleanup_all(self, errors: list[str] | None = None) -> CaseStatus:
        """LIFO 清理。返回最终状态:PASS 或 CLEANUP_FAILED。"""
        errors = errors if errors is not None else []
        failed = False
        while True:
            with self._lock:
                if not self._stack:
                    break
                r = self._stack.pop()
            try:
                r.cleanup()
            except Exception as e:
                failed = True
                errors.append(f"{r.kind}:{r.name}: {e}")
        return CaseStatus.CLEANUP_FAILED if failed else CaseStatus.PASS

    def size(self) -> int:
        with self._lock:
            return len(self._stack)