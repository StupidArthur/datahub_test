"""test_config.py:RunConfig 加载。"""
from __future__ import annotations

import json
from pathlib import Path


def _raw(tmp_path: Path) -> dict:
    return {
        "runId": "rid-1",
        "selectedCaseIds": ["UA-1", "UA-2"],
        "subject": {
            "baseUrl": "http://10.10.58.153:31501",
            "tenantId": "",
            "username": "admin",
            "password": "x",
            "token": "tok",
        },
        "localIp": "10.10.58.20",
        "mock": {
            "controlMode": "wails-managed",
            "endpoints": {
                "functional": "opc.tcp://10.10.58.20:18960/ua_mocker/",
            },
        },
        "timeouts": {"pollIntervalMs": 700, "rtVisibilitySec": 25},
        "paths": {"runDir": str(tmp_path), "reportPath": str(tmp_path / "r.json")},
        "note": "smoke",
    }


def _assert_loaded(cfg, tmp_path: Path) -> None:
    assert cfg.run_id == "rid-1"
    assert cfg.subject.base_url.endswith("31501")
    assert cfg.subject.username == "admin"
    assert cfg.subject.token == "tok"
    assert cfg.local_ip == "10.10.58.20"
    assert cfg.mock.endpoints.functional.startswith("opc.tcp://")
    assert cfg.timeouts.poll_interval_ms == 700
    assert cfg.timeouts.rt_visibility_sec == 25
    assert cfg.paths.run_dir == str(tmp_path)
    assert cfg.note == "smoke"


def test_load_roundtrip(tmp_path: Path):
    p = tmp_path / "rc.json"
    p.write_text(json.dumps(_raw(tmp_path)), encoding="utf-8")
    from ua_test_harness.config import RunConfig
    _assert_loaded(RunConfig.load(p), tmp_path)


def test_load_accepts_utf8_bom_from_windows_powershell(tmp_path: Path):
    p = tmp_path / "rc-bom.json"
    p.write_text(json.dumps(_raw(tmp_path)), encoding="utf-8-sig")
    from ua_test_harness.config import RunConfig
    _assert_loaded(RunConfig.load(p), tmp_path)
