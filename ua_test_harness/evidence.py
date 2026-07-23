"""evidence.py:evidence 文件写入辅助。

每次轮询/断言失败时,把相关 raw 数据落盘,便于事后分析。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .events import EventEmitter


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def write_json_evidence(
    emitter: EventEmitter,
    case_id: str,
    evidence_dir: Path | None,
    *,
    kind: str,
    title: str,
    payload: Any,
    filename: str | None = None,
) -> str | None:
    """写一份 JSON evidence,并发事件。

    返回写入路径;evidence_dir 为空则只发事件不落盘。
    """
    if evidence_dir is None:
        path = ""
    else:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        path = str(evidence_dir / (filename or f"{kind}-{_ts()}.json"))
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    emitter.evidence(case_id=case_id, kind=kind, path=path, title=title)
    return path


def write_text_evidence(
    emitter: EventEmitter,
    case_id: str,
    evidence_dir: Path | None,
    *,
    kind: str,
    title: str,
    text: str,
    filename: str | None = None,
) -> str | None:
    if evidence_dir is None:
        path = ""
    else:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        path = str(evidence_dir / (filename or f"{kind}-{_ts()}.txt"))
        Path(path).write_text(text, encoding="utf-8")
    emitter.evidence(case_id=case_id, kind=kind, path=path, title=title)
    return path