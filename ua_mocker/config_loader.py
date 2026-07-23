# -*- coding: utf-8 -*-
"""
组态加载：从 YAML 文件读取 OPC UA Mock Server 配置并做基本校验。
"""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 组态中必填顶层键
REQUIRED_TOP_KEYS = ("server", "port", "cycle", "namespace_index", "nodes")
# 节点项必填键
REQUIRED_NODE_KEYS = ("name", "type", "count", "change", "writable")


def load_config(config_path: str | Path) -> dict[str, Any]:
    """
    从 YAML 文件加载组态。

    :param config_path: 组态文件路径
    :return: 组态字典
    :raises FileNotFoundError: 文件不存在
    :raises ValueError: 格式或必填项缺失
    """
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"组态文件不存在: {path}")

    raw = path.read_text(encoding="utf-8")
    try:
        cfg = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise ValueError(f"YAML 解析失败: {e}") from e

    if not isinstance(cfg, dict):
        raise ValueError("组态根节点必须为键值对")

    for key in REQUIRED_TOP_KEYS:
        if key not in cfg:
            raise ValueError(f"组态缺少必填项: {key}")

    if not isinstance(cfg["nodes"], list):
        raise ValueError("组态中 nodes 必须为列表")

    for i, node in enumerate(cfg["nodes"]):
        if not isinstance(node, dict):
            raise ValueError(f"nodes[{i}] 必须为键值对")
        for k in REQUIRED_NODE_KEYS:
            if k not in node:
                raise ValueError(f"nodes[{i}] 缺少必填项: {k}")
        if node["change"] is False and "default" not in node:
            raise ValueError(f"nodes[{i}] change=false 时必须提供 default")

    logger.info("组态加载成功: %s", path)
    return cfg
