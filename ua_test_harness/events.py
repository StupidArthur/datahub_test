"""events.py:NDJSON 结构化事件发射器。

契约(plan.md 5.3):
- Python stdout 每行必须是一个 JSON 对象,不输出普通文本。
- 事件名:run_started / case_started / step_started / step_finished /
  log / metric / evidence / case_finished / cleanup_finished / run_finished /
  protocol_error
- 所有事件带 ts(ISO8601 UTC)。
- 普通日志写 stderr 和文件,不进 stdout。
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Callable

_LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class EventEmitter:
    """线程安全地向 stdout 写一行 JSON 事件。"""

    def __init__(self, write: Callable[[str], None] | None = None) -> None:
        self._flush = getattr(sys.stdout, "flush", lambda: None) if write is None else (lambda: None)

        def default(s: str) -> None:
            sys.stdout.write(s + "\n")

        if write is None:
            self._write = default
        else:
            # 自定义 write 也保证追加 \n(NDJSON 协议要求每行一个 JSON 对象)
            def wrapped(s: str) -> None:
                write(s)
                if not s.endswith("\n"):
                    write("\n")

            self._write = wrapped

    def emit(self, event: str, **fields: Any) -> None:
        payload = {"event": event, "ts": _now(), **fields}
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with _LOCK:
            self._write(line)
            try:
                self._flush()
            except Exception:
                pass

    # 便捷封装 -----------------------------------------------------------
    def run_started(self, run_id: str, total: int) -> None:
        self.emit("run_started", runId=run_id, total=total)

    def case_started(self, case_id: str, index: int, total: int) -> None:
        self.emit("case_started", caseId=case_id, index=index, total=total)

    def step_started(self, case_id: str, step_id: str, title: str) -> None:
        self.emit("step_started", caseId=case_id, stepId=step_id, title=title)

    def step_finished(
        self,
        case_id: str,
        step_id: str,
        status: str,
        duration_ms: int,
        message: str = "",
    ) -> None:
        self.emit(
            "step_finished",
            caseId=case_id,
            stepId=step_id,
            status=status,
            durationMs=duration_ms,
            message=message,
        )

    def case_finished(
        self,
        case_id: str,
        status: str,
        duration_ms: int,
        summary: str = "",
    ) -> None:
        self.emit(
            "case_finished",
            caseId=case_id,
            status=status,
            durationMs=duration_ms,
            summary=summary,
        )

    def cleanup_finished(self, case_id: str, status: str, message: str = "") -> None:
        self.emit(
            "cleanup_finished",
            caseId=case_id,
            status=status,
            message=message,
        )

    def run_finished(self, status: str, stats: dict[str, Any]) -> None:
        self.emit("run_finished", status=status, **stats)

    def log(self, level: str, case_id: str | None, message: str) -> None:
        # 结构化日志走 stdout(NDJSON);普通日志走 stderr/file。
        self.emit("log", level=level, caseId=case_id or "", message=message)

    def metric(
        self,
        case_id: str,
        name: str,
        value: float | None = None,
        unit: str = "",
        text_value: str | None = None,
        labels: dict[str, str] | None = None,
    ) -> None:
        self.emit(
            "metric",
            caseId=case_id,
            name=name,
            value=value,
            unit=unit,
            textValue=text_value,
            labels=labels or {},
        )

    def evidence(self, case_id: str, kind: str, path: str, title: str = "", metadata: dict[str, Any] | None = None) -> None:
        self.emit(
            "evidence",
            caseId=case_id,
            kind=kind,
            path=path,
            title=title,
            metadata=metadata or {},
        )

    def protocol_error(self, message: str, raw: str = "") -> None:
        self.emit("protocol_error", message=message, raw=raw[:500])