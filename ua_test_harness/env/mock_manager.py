"""ua-server-mock 管理:4 套位号方案 + 起/停 ua_mocker。

4 个本地 mock server(固定端口,互不冲突):
- 功能遍历 18960:13 类型 × 2 模式(r/w) × 10 = 260 位号  mock_{type}_{mode}_{i}
- 断线重连 18961:13 × 2 × 10 = 260 位号                  connect_{type}_{mode}_{i}
- 性能测试 18962:轮询 Double×N + 可写(Double 9 : Bool 1)
- 异常测试 18963:bad_len 5 档(名长 8/64/128/256/512) + bad_val 13 类型可写

mode: r=轮询(change=True 自动变,不可写)  w=可写(change=False 静止,靠写值变)

复用:ua_tpt_manager 的 build_mocker_yaml / type_map / UaInstance / UaNodeSpec(纯函数+数据类)。
自己封装 spawn:每个 server 独立 heartbeat 名(避免注册到 TPT 时重名)。
"""
from __future__ import annotations

import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import ua_test_harness._paths  # noqa: F401 — ua_tpt_manager 扁平 import 需要 path

from app_config import UaInstance, UaNodeSpec
from type_map import ALL_TYPES, default_for
from ua_config_builder import build_mocker_yaml, endpoint_for

# ---- 端口规划(18960~18969 预留给 ua-server-mock)----
PORT_FUNCTIONAL = 18960
PORT_RECONNECT = 18961
PORT_PERFORMANCE = 18962
PORT_ABNORMAL = 18963

# ua_mock_v1.exe 默认位置(supcon_tools/ua_mocker/)
_REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_MOCKER_EXE = str(_REPO / "ua_mocker" / "ua_mock_v1.exe")
DEFAULT_MOCKER_MAIN = str(_REPO / "ua_mocker" / "main.py")

# 异常测试:位号名长度档
BAD_LEN_TARGETS = [8, 64, 128, 256, 512]


@dataclass
class MockSpec:
    key: str                       # functional/reconnect/performance/abnormal
    name: str                      # 中文用途
    port: int
    cycle_ms: int
    nodes: list[UaNodeSpec]
    heartbeat_tag: str             # per-server 唯一(展开为 {tag}1)
    desc: str = ""

    @property
    def endpoint(self) -> str:
        return endpoint_for("127.0.0.1", self.port)

    @property
    def node_count(self) -> int:
        return sum(max(1, n.count) for n in self.nodes)


def _mode_nodes(prefix: str, count: int) -> list[UaNodeSpec]:
    """每类型每模式 1 个 spec:prefix_{type}_{mode}_ ,count 展开为 _1..N。"""
    nodes: list[UaNodeSpec] = []
    for t in ALL_TYPES:
        # r: 轮询(自动变,不可写)
        nodes.append(UaNodeSpec(name=f"{prefix}_{t}_r_", type=t, count=count,
                                change=True, writable=False))
        # w: 可写(静止,靠写值变;change=False 必须 default)
        nodes.append(UaNodeSpec(name=f"{prefix}_{t}_w_", type=t, count=count,
                                change=False, writable=True, default=default_for(t)))
    return nodes


def build_functional() -> MockSpec:
    return MockSpec(
        key="functional", name="功能遍历", port=PORT_FUNCTIONAL, cycle_ms=1000,
        nodes=_mode_nodes("mock", 10), heartbeat_tag="mock_hb",
        desc="13 类型 × 2 模式(轮询/可写) × 10 = 260 位号,遍历读写全类型",
    )


def build_reconnect() -> MockSpec:
    return MockSpec(
        key="reconnect", name="断线重连", port=PORT_RECONNECT, cycle_ms=1000,
        nodes=_mode_nodes("connect", 10), heartbeat_tag="connect_hb",
        desc="13 × 2 × 10 = 260 位号;起停此 server 测 TPT 断线重连",
    )


def build_performance(poll_n: int = 10000, write_n: int = 1000,
                      write_double_ratio: float = 0.9) -> MockSpec:
    """性能测试:poll_n 个轮询 Double + write_n 个可写(Double:Bool = ratio : 1-ratio)。"""
    n_double = round(write_n * write_double_ratio)
    n_bool = write_n - n_double
    nodes = [
        UaNodeSpec(name="perf_Double_r_", type="Double", count=poll_n,
                   change=True, writable=False),
        UaNodeSpec(name="perf_Double_w_", type="Double", count=n_double,
                   change=False, writable=True, default=0.0),
        UaNodeSpec(name="perf_Boolean_w_", type="Boolean", count=n_bool,
                   change=False, writable=True, default=False),
    ]
    return MockSpec(
        key="performance", name="性能测试", port=PORT_PERFORMANCE, cycle_ms=1000,
        nodes=nodes, heartbeat_tag="perf_hb",
        desc=f"轮询 Double×{poll_n} + 可写 Double×{n_double}/Bool×{n_bool}",
    )


def build_abnormal() -> MockSpec:
    nodes: list[UaNodeSpec] = []
    # bad_len:5 档位号名长度。count=1 展开为 name1,故 name 长度 = target-1
    for target in BAD_LEN_TARGETS:
        base = "badlen"
        name = base + "x" * (target - 1 - len(base))
        nodes.append(UaNodeSpec(name=name, type="Double", count=1,
                                change=True, writable=False))
    # bad_val:13 类型各 1 个可写节点
    for t in ALL_TYPES:
        nodes.append(UaNodeSpec(name=f"bad_val_{t}_", type=t, count=1,
                                change=False, writable=True, default=default_for(t)))
    return MockSpec(
        key="abnormal", name="异常测试", port=PORT_ABNORMAL, cycle_ms=1000,
        nodes=nodes, heartbeat_tag="bad_hb",
        desc=f"bad_len 5 档(名长 {BAD_LEN_TARGETS}) + bad_val 13 类型可写 = {len(nodes)} 位号",
    )


def all_specs() -> list[MockSpec]:
    return [build_functional(), build_reconnect(), build_performance(), build_abnormal()]


@dataclass
class MockRuntime:
    spec: MockSpec
    pid: int = 0
    proc: subprocess.Popen | None = None
    config_path: str = ""
    log_path: str = ""
    status: str = "stopped"        # stopped/running/failed


class MockManager:
    """起/停 4 套 mock server。端口固定,被占用则报错(由 OS 环境页负责清理)。"""

    def __init__(self, mocker_exe: str | None = None,
                 work_dir: Path | None = None):
        # 默认 None -> 用 python 跑 main.py 源码(无窗口、可调试);
        # 显式传 exe 路径才用打包 exe(PyInstaller console 程序会弹窗,不优雅)
        self.mocker_exe = mocker_exe
        self.work_dir = work_dir or (Path.home() / ".ua_test_harness" / "mock_work")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._run: dict[str, MockRuntime] = {}

    @staticmethod
    def is_port_free(port: int) -> bool:
        """connect 探测:连得上=有服务在听=占用(返回 False)。

        bind 探测会被 SO_REUSEADDR 误判(asyncua server 设了 REUSEADDR,
        允许重复 bind),故改 connect 实际握手。
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect(("127.0.0.1", port))
            s.close()
            return False
        except OSError:
            return True

    def start(self, spec: MockSpec) -> MockRuntime:
        rt = self._run.get(spec.key)
        if rt and rt.status == "running":
            raise RuntimeError(f"{spec.name}({spec.port}) 已在运行")
        if not self.is_port_free(spec.port):
            raise RuntimeError(f"端口 {spec.port} 被占用,先在 OS 环境页清理")
        wdir = self.work_dir / spec.key
        wdir.mkdir(parents=True, exist_ok=True)
        yaml_path = wdir / "config.yaml"
        inst = UaInstance(
            name=spec.key, mode="config", host="0.0.0.0", port=spec.port,
            namespace_index=1, cycle_ms=spec.cycle_ms, nodes=spec.nodes,
        )
        build_mocker_yaml(inst, spec.heartbeat_tag, yaml_path)

        exe = self.mocker_exe
        # cwd 必须设到 main.py 所在目录(ua_mocker/),否则 import 同级模块失败
        mocker_dir = str(Path(DEFAULT_MOCKER_MAIN).parent)
        if exe and Path(exe).exists():
            cmd = [exe, str(yaml_path)]
        else:
            cmd = [sys.executable, DEFAULT_MOCKER_MAIN, str(yaml_path)]
        log_path = wdir / "server.log"
        log_file = open(log_path, "w", encoding="utf-8")
        popen_kwargs: dict = {
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "cwd": mocker_dir,
        }
        if sys.platform == "win32":
            # 新进程组 + 无窗口:cli 退出后 mock 继续跑,且不弹控制台窗口
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        proc = subprocess.Popen(cmd, **popen_kwargs)
        rt = MockRuntime(spec=spec, pid=proc.pid, proc=proc,
                         config_path=str(yaml_path), log_path=str(log_path),
                         status="running")
        self._run[spec.key] = rt
        return rt

    def _spec(self, key: str) -> MockSpec | None:
        for s in all_specs():
            if s.key == key:
                return s
        return None

    def status(self, key: str) -> str:
        rt = self._run.get(key)
        if rt and rt.proc is not None:
            if rt.proc.poll() is None:
                rt.status = "running"
            else:
                rt.status = "failed"
            return rt.status
        # 跨进程:按端口占用判定(本进程没起过也要能看)
        spec = self._spec(key)
        if spec and not self.is_port_free(spec.port):
            return "running"
        return "stopped"

    def stop(self, key: str) -> None:
        rt = self._run.get(key)
        if rt and rt.proc:
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
            return
        # 跨进程:本进程没起过,按端口杀
        spec = self._spec(key)
        if spec:
            from .os_env import kill_port
            kill_port(spec.port)

    def stop_all(self) -> None:
        for s in all_specs():
            self.stop(s.key)

    def runtime(self, key: str) -> MockRuntime | None:
        return self._run.get(key)
