"""组态位号 → ua_mocker YAML(自动注入 heartbeat 节点)。

生成的 YAML 满足 ua_mocker/config_loader.py 校验:
- 顶层必填 server/port/cycle/namespace_index/nodes
- node 必填 name/type/count/change/writable
- change=false 必须有 default
"""
from __future__ import annotations

from pathlib import Path

import yaml

from app_config import UaInstance
from type_map import default_for

HEARTBEAT_TYPE = "Int32"


def endpoint_for(host: str, port: int) -> str:
    return f"opc.tcp://{host}:{port}/ua_mocker/"


def build_mocker_yaml(inst: UaInstance, heartbeat_tag: str, out_path: Path) -> Path:
    """把 UaInstance(组态模式)写成 ua_mocker YAML,自动追加 heartbeat 节点。"""
    nodes: list[dict] = []
    for n in inst.nodes:
        node = {
            "name": n.name,
            "type": n.type,
            "count": int(n.count),
            "change": bool(n.change),
            "writable": bool(n.writable),
        }
        if not n.change:
            node["default"] = n.default if n.default is not None else default_for(n.type)
        nodes.append(node)

    # 心跳节点:数值 Int32 change=true → 0~99 秒级 sawtooth(cycle=1000ms)
    nodes.append({
        "name": heartbeat_tag,
        "type": HEARTBEAT_TYPE,
        "count": 1,
        "change": True,
        "writable": False,
    })

    cfg = {
        "server": inst.host or "127.0.0.1",
        "port": int(inst.port),
        "cycle": int(inst.cycle_ms),
        "namespace_index": int(inst.namespace_index),
        "nodes": nodes,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return out_path
