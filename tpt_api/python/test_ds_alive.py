"""实测 ds-info alive 字段随 mock 启停变化的延迟。"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import yaml

from tpt_api import AlgAPI, datahub

BASE_URL = "http://10.10.58.153:31501"
USERNAME = "admin"
PASSWORD = "123456"
MOCK_PORT = 18970
MAX_WAIT_SEC = 180


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.10.58.153", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def wait_for_port(port, host="127.0.0.1", timeout=30):
    for i in range(timeout * 2):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            sock.connect((host, port))
            return i * 0.5
        except Exception:
            pass
        finally:
            sock.close()
        time.sleep(0.5)
    return None


def poll_alive(api, ds_id, expect_alive, max_sec):
    """轮询 alive 字段，直到等于 expect_alive 或超时。返回 (耗时秒, 是否达到预期)"""
    for i in range(max_sec):
        all_ds = datahub.get_all_ds_info(api)
        matched = [d for d in all_ds if d.get("id") == ds_id]
        if matched:
            alive = matched[0].get("alive")
            ds_status = matched[0].get("dsStatus")
            if i % 5 == 0 or alive == expect_alive:
                print(f"    t+{i}s: alive={alive} dsStatus={ds_status}")
            if alive == expect_alive:
                return i, True
        time.sleep(1)
    return max_sec, False


local_ip = get_local_ip()
print(f"本机 IP: {local_ip}")

# 1. 生成临时 mock 配置
repo_root = Path(__file__).resolve().parents[2]
mock_dir = repo_root / "ua_mocker"
config_path = mock_dir / "_test_alive_config.yaml"
config = {
    "server": "0.0.0.0",
    "port": MOCK_PORT,
    "cycle": 1000,
    "namespace_index": 1,
    "nodes": [
        {"name": "alive_test_wr", "type": "Double", "count": 1, "default": 0.0, "change": False, "writable": True}
    ],
}
with open(config_path, "w", encoding="utf-8") as f:
    yaml.dump(config, f, allow_unicode=True)
print(f"生成临时配置: {config_path}")

api = None
ds_id = None
proc = None

try:
    api = AlgAPI(BASE_URL, timeout=60.0)
    api.login(USERNAME, PASSWORD)

    # 2. 先创建数据源（此时 mock 未启动）
    ts = int(time.time())
    ds_name = f"test_alive_{ts}"
    endpoint = f"opc.tcp://{local_ip}:{MOCK_PORT}/ua_mocker/"
    print(f"\n创建数据源: {ds_name} -> {endpoint}")
    new_ds = datahub.add_ds_info(api, ds_name=ds_name, ds_tar_url=endpoint)
    ds_id = new_ds.get("id")
    print(f"dsId={ds_id}")

    # 3. mock 未启动时的初始状态
    all_ds = datahub.get_all_ds_info(api)
    matched = [d for d in all_ds if d.get("id") == ds_id]
    if matched:
        print(f"mock 未启动时: alive={matched[0].get('alive')} dsStatus={matched[0].get('dsStatus')}")

    # 4. 启动 mock，测 alive 变 True 的延迟
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, "main.py", str(config_path)],
        cwd=mock_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"\n启动 mock PID={proc.pid}")
    startup_delay = wait_for_port(MOCK_PORT)
    print(f"  mock 端口监听耗时: {startup_delay}s")

    print(f"\n[mock 启动后] 等待 alive 变 True（最长 {MAX_WAIT_SEC}s）...")
    dt, ok = poll_alive(api, ds_id, True, MAX_WAIT_SEC)
    print(f"  alive 变 True: 耗时={dt}s, 成功={ok}")

    # 5. 停止 mock，测 alive 变 False 的延迟
    print(f"\n停止 mock PID={proc.pid}...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("mock 已停止")

    # 确认端口确实不可达
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        sock.connect(("127.0.0.1", MOCK_PORT))
        print("  警告：端口仍可达")
    except Exception:
        print("  确认端口已不可达")
    finally:
        sock.close()

    print(f"\n[mock 停止后] 等待 alive 变 False（最长 {MAX_WAIT_SEC}s）...")
    dt, ok = poll_alive(api, ds_id, False, MAX_WAIT_SEC)
    print(f"  alive 变 False: 耗时={dt}s, 成功={ok}")

finally:
    # 清理
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            pass
    if api is not None and ds_id is not None:
        try:
            print(f"\n清理数据源 dsId={ds_id}...")
            datahub.delete_ds_info(api, [ds_id])
            print("  数据源删除成功")
        except Exception as e:
            print(f"  数据源删除失败: {e}")
    try:
        config_path.unlink()
        print(f"删除临时配置: {config_path}")
    except Exception:
        pass
