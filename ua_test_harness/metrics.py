"""metrics.py:运行时指标(响应时间等)收集。

指标通过 EventEmitter.metric 发出;runner 负责汇总到 report.json。
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from .events import EventEmitter


@contextmanager
def measure_ms(emitter: EventEmitter, case_id: str, name: str, unit: str = "ms") -> Iterator[dict]:
    """上下文管理器:记录耗时(ms)并 metric 事件。"""
    holder: dict = {"value": 0.0}
    t0 = time.monotonic()
    try:
        yield holder
    finally:
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        holder["value"] = elapsed_ms
        emitter.metric(case_id=case_id, name=name, value=elapsed_ms, unit=unit)


def report_value(
    emitter: EventEmitter,
    case_id: str,
    name: str,
    value: float,
    unit: str = "",
    labels: dict[str, str] | None = None,
) -> None:
    emitter.metric(case_id=case_id, name=name, value=value, unit=unit, labels=labels)


def report_text(
    emitter: EventEmitter,
    case_id: str,
    name: str,
    text: str,
    labels: dict[str, str] | None = None,
) -> None:
    emitter.metric(case_id=case_id, name=name, text_value=text, unit="", labels=labels)