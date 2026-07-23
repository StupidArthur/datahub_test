"""models.py:UA 自动化共享数据模型。

包含:
- CaseStatus:用例与步骤状态枚举(对齐 plan.md 5.3)
- CaseDef / StepDef:用例与步骤定义(由装饰器生成)
- CaseResult / StepResult:运行结果
- RunStats:汇总计数
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CaseStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"
    BLOCKED = "BLOCKED"
    OBSERVED = "OBSERVED"
    MEASURED = "MEASURED"
    CANCELLED = "CANCELLED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    TIMEOUT = "TIMEOUT"

    @classmethod
    def from_str(cls, v: str) -> "CaseStatus":
        try:
            return cls(v)
        except ValueError:
            return cls.ERROR


@dataclass
class StepDef:
    step_id: str
    title: str


@dataclass
class CaseDef:
    id: str
    title: str
    chapter: str
    kind: str = "regression"  # regression | exploratory | performance | response_time
    tags: list[str] = field(default_factory=list)
    timeout_sec: int = 600
    exclusive_resources: list[str] = field(default_factory=list)
    destructive: bool = False
    doc_path: str = ""
    description: str = ""
    steps: list[StepDef] = field(default_factory=list)
    assertions: list[str] = field(default_factory=list)
    impl_func: Any = field(default=None, repr=False, compare=False)
    file_path: str = ""
    lineno: int = 0


@dataclass
class StepResult:
    case_id: str
    step_id: str
    title: str
    status: CaseStatus = CaseStatus.PENDING
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    message: str = ""


@dataclass
class CaseResult:
    case_id: str
    title: str
    status: CaseStatus = CaseStatus.PENDING
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    summary: str = ""
    cleanup_status: CaseStatus = CaseStatus.PASS
    cleanup_message: str = ""
    steps: list[StepResult] = field(default_factory=list)
    metrics: list["Metric"] = field(default_factory=list)
    evidences: list["Evidence"] = field(default_factory=list)


@dataclass
class Metric:
    case_id: str
    name: str
    value: float | None = None
    text_value: str | None = None
    unit: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    ts: str = ""


@dataclass
class Evidence:
    case_id: str
    kind: str  # api_response | source_value | log | file | screenshot
    path: str
    title: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    ts: str = ""


@dataclass
class RunStats:
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    blocked: int = 0
    observed: int = 0
    measured: int = 0
    cleanup_failed: int = 0
    timeout_count: int = 0

    def add(self, status: CaseStatus) -> None:
        self.total += 1
        m = {
            CaseStatus.PASS: "passed",
            CaseStatus.FAIL: "failed",
            CaseStatus.ERROR: "errors",
            CaseStatus.SKIP: "skipped",
            CaseStatus.BLOCKED: "blocked",
            CaseStatus.OBSERVED: "observed",
            CaseStatus.MEASURED: "measured",
            CaseStatus.CLEANUP_FAILED: "cleanup_failed",
            CaseStatus.TIMEOUT: "timeout_count",
        }.get(status)
        if m:
            setattr(self, m, getattr(self, m) + 1)

    def to_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "blocked": self.blocked,
            "observed": self.observed,
            "measured": self.measured,
            "cleanupFailed": self.cleanup_failed,
            "timeoutCount": self.timeout_count,
        }