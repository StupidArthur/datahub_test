"""OS 环境检测与清理:端口 / 进程 / 本地 IP / 连通性。

- 端口 18960~18969(预留给 ua-server-mock)占用检测 + 一键杀进程
- 杀进程需二次确认;杀不掉提示用户自行处理
- 本地 IP 枚举(多 IP 时只有一个是 TPT 可连的,select 选)
- 与被测对象网络连通性(通过能否登录判定)
"""
from __future__ import annotations

import re
import socket
import subprocess
from dataclasses import dataclass, field

PORT_RANGE = range(18960, 18970)   # 18960~18969


@dataclass
class PortStatus:
    port: int
    in_use: bool
    pid: int = 0
    process: str = ""


@dataclass
class OsEnvReport:
    ports: list[PortStatus] = field(default_factory=list)
    local_ips: list[str] = field(default_factory=list)
    connectivity_ok: bool = False
    connectivity_msg: str = ""


def _is_port_free(port: int) -> bool:
    """connect 探测:连得上=占用(返回 False)。bind 探测会被 SO_REUSEADDR 误判。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect(("127.0.0.1", port))
        s.close()
        return False
    except OSError:
        return True


def _netstat_pids() -> dict[int, int]:
    """port -> pid(仅 LISTENING)。"""
    out: dict[int, int] = {}
    try:
        r = subprocess.run(["netstat", "-ano"], capture_output=True,
                           text=True, errors="replace")
    except Exception:
        return out
    for line in r.stdout.splitlines():
        if "LISTENING" not in line.upper():
            continue
        m = re.search(r":(\d+)\s+\S+\s+LISTENING\s+(\d+)", line, re.IGNORECASE)
        if m:
            out[int(m.group(1))] = int(m.group(2))
    return out


def _process_name(pid: int) -> str:
    if not pid:
        return ""
    try:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                           capture_output=True, text=True, errors="replace")
        first = r.stdout.strip().splitlines()
        if first:
            return first[0].split(",")[0].strip('"')
    except Exception:
        pass
    return ""


def scan_ports(ports=PORT_RANGE) -> list[PortStatus]:
    pid_map = _netstat_pids()
    result: list[PortStatus] = []
    for p in ports:
        in_use = not _is_port_free(p)
        pid = pid_map.get(p, 0)
        result.append(PortStatus(port=p, in_use=in_use, pid=pid,
                                 process=_process_name(pid) if pid else ""))
    return result


def kill_port(port: int) -> tuple[bool, str]:
    """杀占用 port 的进程。返回 (成功, 消息);杀不掉提示用户自行处理。"""
    pid = _netstat_pids().get(port, 0)
    if not pid:
        return False, f"端口 {port} 无占用进程"
    try:
        r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, text=True, errors="replace")
        if r.returncode == 0:
            return True, f"已杀 PID {pid}({port})"
        return False, (f"taskkill 失败 rc={r.returncode}: {r.stdout.strip()} {r.stderr.strip()}。"
                       f"请在任务管理器手动结束 PID {pid}")
    except Exception as e:
        return False, f"taskkill 异常: {e}。请手动结束 PID {pid}"


def list_local_ips() -> list[str]:
    """枚举本地 IPv4(选 TPT 可连的那个)。"""
    ips: set[str] = set()
    try:
        hostname = socket.gethostname()
        _, _, addrs = socket.gethostbyname_ex(hostname)
        ips.update(a for a in addrs if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", a))
    except Exception:
        pass
    try:
        r = subprocess.run(["ipconfig"], capture_output=True, text=True, errors="replace")
        for m in re.finditer(r"IPv4[^\d:]*:\s*(\d+\.\d+\.\d+\.\d+)", r.stdout):
            ips.add(m.group(1))
    except Exception:
        pass
    return sorted(ips)


def check_connectivity(base_url: str, user: str, password: str,
                      tenant_id: str = "") -> tuple[bool, str]:
    """通过能否登录判定与被测对象的连通性。"""
    from .subject import login_subject
    try:
        login_subject(base_url, user, password, tenant_id, timeout=15.0)
        return True, "登录成功"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
