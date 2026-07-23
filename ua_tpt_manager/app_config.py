"""配置持久化:多 TPT 环境 + 多 UA 实例 + 偏好。

JSON 文件存业务配置(环境/实例/路径),QSettings 存窗口状态(见 main_window)。
密码默认不落盘,勾选「记住密码」才存。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(
    os.environ.get("UA_TPT_MANAGER_HOME", str(Path.home() / ".ua_tpt_manager"))
)
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class TptEnv:
    name: str = ""
    base_url: str = ""
    username: str = ""
    password: str = ""
    tenant_id: str = ""
    remember_password: bool = False


@dataclass
class UaNodeSpec:
    """组态模式下一条 ua_mocker 节点定义。"""
    name: str
    type: str = "Double"          # ua_mocker 类型名(Int32/Double/Boolean/...)
    count: int = 1                # 展开为 name1..nameN
    change: bool = True
    writable: bool = False
    default: Any = None           # change=False 时必填


@dataclass
class UaInstance:
    name: str
    mode: str = "config"          # "config" | "excel"
    host: str = "127.0.0.1"
    port: int = 0                 # 0 = 启动时自动分配
    namespace_index: int = 1
    cycle_ms: int = 1000
    nodes: list[UaNodeSpec] = field(default_factory=list)
    excel_path: str = ""
    # 运行态(assigned_port/pid/status/ds_id)不持久化,内存中维护


@dataclass
class AppConfig:
    envs: list[TptEnv] = field(default_factory=list)
    instances: list[UaInstance] = field(default_factory=list)
    ua_mocker_exe: str = ""
    ua_player_main: str = ""
    heartbeat_tag: str = "heartbeat"
    poll_interval_sec: int = 3
    current_env: str = ""

    def to_dict(self) -> dict:
        d = {
            "envs": [asdict(e) for e in self.envs],
            "instances": [asdict(i) for i in self.instances],
            "ua_mocker_exe": self.ua_mocker_exe,
            "ua_player_main": self.ua_player_main,
            "heartbeat_tag": self.heartbeat_tag,
            "poll_interval_sec": self.poll_interval_sec,
            "current_env": self.current_env,
        }
        for e in d["envs"]:
            if not e.get("remember_password"):
                e["password"] = ""
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        envs = [TptEnv(**e) for e in d.get("envs", [])]
        insts = [UaInstance(**i) for i in d.get("instances", [])]
        return cls(
            envs=envs,
            instances=insts,
            ua_mocker_exe=d.get("ua_mocker_exe", ""),
            ua_player_main=d.get("ua_player_main", ""),
            heartbeat_tag=d.get("heartbeat_tag", "heartbeat"),
            poll_interval_sec=d.get("poll_interval_sec", 3),
            current_env=d.get("current_env", ""),
        )


def default_mocker_exe() -> str:
    here = Path(__file__).resolve().parent
    cand = here.parent / "ua_mocker" / "ua_mock_v1.exe"
    return str(cand) if cand.exists() else ""


def default_player_main() -> str:
    here = Path(__file__).resolve().parent
    cand = here.parent / "ua_player" / "main.py"
    return str(cand) if cand.exists() else ""


def load_config() -> AppConfig:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg = AppConfig.from_dict(data)
        except Exception:
            cfg = AppConfig()
    else:
        cfg = AppConfig()
    if not cfg.ua_mocker_exe:
        cfg.ua_mocker_exe = default_mocker_exe()
    if not cfg.ua_player_main:
        cfg.ua_player_main = default_player_main()
    return cfg


def save_config(cfg: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
