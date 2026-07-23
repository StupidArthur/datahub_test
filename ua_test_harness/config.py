"""config.py:RunConfig 加载与模型。

Go 侧 automation.Service 每次启动任务生成 run-config.json,
Python runner 读取后驱动执行(plan.md 5.2)。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SubjectConfig:
    base_url: str = ""
    tenant_id: str = ""
    username: str = ""
    password: str = ""
    token: str = ""


@dataclass
class MockEndpointConfig:
    functional: str = ""
    reconnect: str = ""
    performance: str = ""
    abnormal: str = ""


@dataclass
class MockConfig:
    control_mode: str = "wails-managed"
    endpoints: MockEndpointConfig = field(default_factory=MockEndpointConfig)


@dataclass
class TimeoutsConfig:
    poll_interval_ms: int = 500
    rt_visibility_sec: int = 30
    history_visibility_sec: int = 120
    ds_connect_sec: int = 60


@dataclass
class PathsConfig:
    run_dir: str = ""
    evidence_dir: str = ""
    report_path: str = ""


@dataclass
class RunConfig:
    run_id: str = ""
    selected_case_ids: list[str] = field(default_factory=list)
    subject: SubjectConfig = field(default_factory=SubjectConfig)
    local_ip: str = ""
    mock: MockConfig = field(default_factory=MockConfig)
    timeouts: TimeoutsConfig = field(default_factory=TimeoutsConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    note: str = ""

    @classmethod
    def load(cls, path: str | Path) -> "RunConfig":
        text = Path(path).read_text(encoding="utf-8-sig")
        return cls.from_json(text)

    @classmethod
    def from_json(cls, text: str) -> "RunConfig":
        d = json.loads(text.lstrip("\ufeff"))
        subj = d.get("subject") or {}
        subj_cfg = SubjectConfig(
            base_url=subj.get("baseUrl") or os.getenv("DATAHUB_BASE_URL", ""),
            tenant_id=subj.get("tenantId") or os.getenv("DATAHUB_TENANT_ID", ""),
            username=subj.get("username") or os.getenv("DATAHUB_USER", ""),
            password=subj.get("password") or os.getenv("DATAHUB_PASSWORD", ""),
            token=subj.get("token") or os.getenv("DATAHUB_TOKEN", ""),
        )
        m = d.get("mock") or {}
        ep_raw = m.get("endpoints") or {}
        ep = MockEndpointConfig(
            functional=ep_raw.get("functional", ""),
            reconnect=ep_raw.get("reconnect", ""),
            performance=ep_raw.get("performance", ""),
            abnormal=ep_raw.get("abnormal", ""),
        )
        mock_cfg = MockConfig(control_mode=m.get("controlMode", "wails-managed"), endpoints=ep)
        t = d.get("timeouts") or {}
        to = TimeoutsConfig(
            poll_interval_ms=int(t.get("pollIntervalMs", 500)),
            rt_visibility_sec=int(t.get("rtVisibilitySec", 30)),
            history_visibility_sec=int(t.get("historyVisibilitySec", 120)),
            ds_connect_sec=int(t.get("dsConnectSec", 60)),
        )
        p = d.get("paths") or {}
        paths = PathsConfig(
            run_dir=p.get("runDir", ""),
            evidence_dir=p.get("evidenceDir", ""),
            report_path=p.get("reportPath", ""),
        )
        return cls(
            run_id=d.get("runId", ""),
            selected_case_ids=list(d.get("selectedCaseIds") or []),
            subject=subj_cfg,
            local_ip=d.get("localIp", ""),
            mock=mock_cfg,
            timeouts=to,
            paths=paths,
            note=d.get("note", ""),
        )
