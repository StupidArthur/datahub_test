"""UA 实例进程管理:生成 YAML + spawn ua_mocker(组态模式)/ spawn ua_player(excel 模式)。

组态模式(Task2):build_mocker_yaml → spawn ua_mocker.exe / python main.py
excel 模式(Task6):supcon_io 转 CSV → spawn ua_player(此处先占位)。
"""
from __future__ import annotations

import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app_config import AppConfig, UaInstance
from ua_config_builder import build_mocker_yaml, endpoint_for

WORK_DIR = Path.home() / ".ua_tpt_manager" / "work"
PORT_BASE = 18950


@dataclass
class UaRuntime:
    name: str
    port: int = 0
    endpoint: str = ""
    pid: int = 0
    status: str = "stopped"          # stopped/starting/running/failed
    proc: subprocess.Popen | None = None
    config_path: str = ""
    log_path: str = ""
    work_dir: str = ""
    log_file: Any = None


class UaProcessManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self._run: dict[str, UaRuntime] = {}

    # ---- 端口分配 ----
    def _used_ports(self) -> set[int]:
        return {r.port for r in self._run.values() if r.port}

    @staticmethod
    def _is_free(port: int) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("0.0.0.0", port))
            s.close()
            return True
        except OSError:
            return False

    def allocate_port(self, preferred: int = 0) -> int:
        if preferred and preferred not in self._used_ports() and self._is_free(preferred):
            return preferred
        port = PORT_BASE
        while port < PORT_BASE + 1000:
            if port not in self._used_ports() and self._is_free(port):
                return port
            port += 1
        raise RuntimeError("无可用端口(18950-19949 均被占用)")

    # ---- 启停 ----
    def start(self, inst: UaInstance) -> UaRuntime:
        rt = self._run.get(inst.name)
        if rt and rt.status == "running":
            raise RuntimeError(f"{inst.name} 已在运行")
        port = self.allocate_port(inst.port or 0)
        host = inst.host or "127.0.0.1"
        if inst.mode == "config":
            endpoint = endpoint_for(host, port)        # opc.tcp://host:port/ua_mocker/
        else:
            endpoint = f"opc.tcp://{host}:{port}/"     # ua_player endpoint 无路径后缀
        rt = UaRuntime(
            name=inst.name, port=port,
            endpoint=endpoint, status="starting",
        )
        wdir = WORK_DIR / inst.name
        wdir.mkdir(parents=True, exist_ok=True)
        rt.work_dir = str(wdir)
        rt.log_path = str(wdir / "server.log")

        if inst.mode == "config":
            self._start_mocker(inst, port, rt, wdir)
        elif inst.mode == "excel":
            self._start_player(inst, port, rt, wdir)
        else:
            raise ValueError(f"未知模式: {inst.mode}")

        self._run[inst.name] = rt
        rt.status = "running"
        return rt

    def _start_mocker(self, inst: UaInstance, port: int, rt: UaRuntime, wdir: Path) -> None:
        yaml_path = wdir / "config.yaml"
        # 用分配到的端口生成 YAML(不写回 inst.port,保持配置里的 0=自动)
        orig_port = inst.port
        inst.port = port
        try:
            build_mocker_yaml(inst, self.config.heartbeat_tag, yaml_path)
        finally:
            inst.port = orig_port
        rt.config_path = str(yaml_path)

        exe = self.config.ua_mocker_exe
        if exe and Path(exe).exists():
            cmd = [exe, str(yaml_path)]
        else:
            root = Path(__file__).resolve().parent.parent
            mocker_main = str(root / "ua_mocker" / "main.py")
            cmd = [sys.executable, mocker_main, str(yaml_path)]

        rt.log_file = open(rt.log_path, "w", encoding="utf-8")
        rt.proc = subprocess.Popen(
            cmd, stdout=rt.log_file, stderr=subprocess.STDOUT, cwd=str(wdir),
        )
        rt.pid = rt.proc.pid

    def _start_player(self, inst: UaInstance, port: int, rt: UaRuntime, wdir: Path) -> None:
        """excel 模式:supcon_io 读 excel → 转 ua_player CSV(注入心跳)→ spawn ua_player。"""
        from excel_to_player_csv import convert

        if not inst.excel_path or not Path(inst.excel_path).exists():
            raise FileNotFoundError(f"excel 文件不存在: {inst.excel_path}")
        csv_path = wdir / "player.csv"
        convert(inst.excel_path, self.config.heartbeat_tag, csv_path)
        rt.config_path = str(csv_path)

        player_main = self.config.ua_player_main
        if not player_main or not Path(player_main).exists():
            raise FileNotFoundError(f"ua_player main.py 未配置: {player_main}")
        cmd = [
            sys.executable, player_main, str(csv_path),
            "--port", str(port), "--interval", "1",
        ]
        rt.log_file = open(rt.log_path, "w", encoding="utf-8")
        rt.proc = subprocess.Popen(
            cmd, stdout=rt.log_file, stderr=subprocess.STDOUT, cwd=str(wdir),
        )
        rt.pid = rt.proc.pid

    def stop(self, name: str) -> None:
        rt = self._run.get(name)
        if not rt or not rt.proc:
            return
        try:
            rt.proc.terminate()
            try:
                rt.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                rt.proc.kill()
                rt.proc.wait(timeout=2)
        finally:
            rt.status = "stopped"
            rt.proc = None
            if rt.log_file:
                try:
                    rt.log_file.close()
                except Exception:
                    pass
                rt.log_file = None

    def stop_all(self) -> None:
        for name in list(self._run.keys()):
            self.stop(name)

    # ---- 状态 ----
    def status(self, name: str) -> str:
        rt = self._run.get(name)
        if not rt:
            return "stopped"
        if rt.proc is not None:
            rc = rt.proc.poll()
            if rc is None:
                rt.status = "running"
            else:
                rt.status = "failed" if rc != 0 else "stopped"
        return rt.status

    def runtime(self, name: str) -> UaRuntime | None:
        return self._run.get(name)
