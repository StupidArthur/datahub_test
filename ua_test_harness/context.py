"""context.py:RunContext / CaseContext。

承载一次 run 与一个 case 的共享状态(配置、事件、资源表、临时数据)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import RunConfig
from .events import EventEmitter
from .resources import ResourceRegistry


@dataclass
class CaseContext:
    case_id: str
    title: str
    registry: ResourceRegistry = field(default_factory=ResourceRegistry)
    bag: dict[str, Any] = field(default_factory=dict)
    evidence_dir: Path | None = None


@dataclass
class RunContext:
    config: RunConfig
    emitter: EventEmitter
    registry: ResourceRegistry = field(default_factory=ResourceRegistry)
    bag: dict[str, Any] = field(default_factory=dict)
    evidence_root: Path | None = None
    log_path: Path | None = None
    cancellation_token: Any = None  # threading.Event-like, runner 自管

    def case_context(self, case_id: str, title: str) -> CaseContext:
        ed = None
        if self.evidence_root:
            ed = self.evidence_root / "evidence" / case_id
            ed.mkdir(parents=True, exist_ok=True)
        return CaseContext(case_id=case_id, title=title, evidence_dir=ed)