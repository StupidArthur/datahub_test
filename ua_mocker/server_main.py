# -*- coding: utf-8 -*-
"""
OPC UA Mock Server 主逻辑：根据组态创建命名空间与变量节点，
所有变量挂在 Objects 下的容器对象「mocker」之下（浏览路径：Objects → mocker → 变量）。
对 change=true 的节点按 cycle 周期更新值；可写节点由客户端写后持久化（由 asyncua 负责）。
控制台仅输出：开始构建节点树、构建完成、服务启动成功+端口、节点数量、designed by yzc，以及客户端写值消息。
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from asyncua import Server, ua
from asyncua.common.callback import CallbackType
from asyncua.common.node_factory import make_node

from change_engines import next_value
from config_loader import load_config
from type_mapping import (
    coerce_to_type,
    get_variant_type_and_default,
)

logger = logging.getLogger(__name__)

# 控制台仅打印的固定信息与署名
CONSOLE_BUILD_START = "开始构建节点树"
CONSOLE_BUILD_DONE = "构建完成"
CONSOLE_SERVER_START = "服务启动成功"
CONSOLE_DESIGNED_BY = "designed by yzc"

# 变量节点父对象：Objects 下的对象 BrowseName
CONTAINER_OBJECT_NAME = "mocker"


def _node_id_string(name_prefix: str, index: int) -> str:
    """组态 name + 下标拼接为 NodeId 的字符串标识。"""
    return f"{name_prefix}{index}"


def _initial_value(node_cfg: dict, variant_type: ua.VariantType, default_py: Any) -> Any:
    """取节点初始值：change=false 用 default（并做类型转换），change=true 用引擎的起始值。"""
    if node_cfg.get("change") is True:
        return next_value(variant_type, None)
    raw = node_cfg.get("default", default_py)
    return coerce_to_type(raw, variant_type)


async def run_server(config_path: str) -> None:
    """
    加载组态并启动 OPC UA 服务器，阻塞直到被中断。

    :param config_path: 组态文件路径（YAML）
    """
    cfg = load_config(config_path)
    server = Server()
    await server.init()

    host = cfg["server"]
    port = int(cfg["port"])
    cycle_ms = int(cfg["cycle"])
    namespace_index = int(cfg["namespace_index"])

    endpoint = f"opc.tcp://{host}:{port}/ua_mocker/"
    server.set_endpoint(endpoint)
    logger.info("OPC UA 端点: %s", endpoint)

    # 使用组态中的 namespace_index 创建节点，使客户端看到的 ns 与配置文件一致
    ns_idx = namespace_index
    logger.info("命名空间索引(与配置一致): %s", ns_idx)

    objects = server.nodes.objects
    mocker_root = await objects.add_object(
        ns_idx,
        CONTAINER_OBJECT_NAME,
        ua.ObjectIds.BaseObjectType,
    )
    logger.info("变量父节点: Objects/%s (ns=%s)", CONTAINER_OBJECT_NAME, ns_idx)

    # 记录 change=true 的节点：(node, variant_type) 用于周期更新
    change_nodes: list[tuple[Any, ua.VariantType]] = []
    total_node_count = 0

    # 预解析每类节点的类型与默认值(避免在循环内重复查表)
    node_specs = []
    for node_cfg in cfg["nodes"]:
        variant_type, default_py = get_variant_type_and_default(node_cfg["type"])
        node_specs.append((node_cfg, variant_type, default_py, int(node_cfg["count"])))

    # 批量加节点:绕过 add_variable 的逐个往返,直接构造 AddNodesItem 列表走 session.add_nodes
    # (OPC UA AddNodes 服务原生支持批量);writable 的 AccessLevel 在 attrs 内联,省 set_writable 往返。
    session = mocker_root.session
    read_mask = ua.AccessLevel.CurrentRead.mask
    write_mask = ua.AccessLevel.CurrentWrite.mask

    # 分容器:每 1000 节点挂一个子容器,避免单 parent 的 references 遍历 O(n²)
    # (asyncua _add_node 对每个新节点遍历 parent.references 查 BrowseName 重名,单容器 1.1w 节点累计 ~1.2 亿次比较)。
    # NodeId 仍为全局唯一字符串,客户端按 NodeId 直访,不依赖 browse path。
    CONTAINER_BATCH = 1000
    total_planned = sum(count for _, _, _, count in node_specs)
    n_containers = max(1, (total_planned + CONTAINER_BATCH - 1) // CONTAINER_BATCH)
    container_nodeids = []
    for ci in range(n_containers):
        c = await mocker_root.add_object(ns_idx, f"{CONTAINER_OBJECT_NAME}_{ci}", ua.ObjectIds.BaseObjectType)
        container_nodeids.append(c.nodeid)

    def _build_addnode(node_cfg, variant_type, default_py, i: int, global_idx: int):
        node_id_str = _node_id_string(node_cfg["name"], i)
        node_id = ua.NodeId(node_id_str, ns_idx)
        qname = ua.QualifiedName(node_id_str, ns_idx)
        initial = _initial_value(node_cfg, variant_type, default_py)
        var = ua.Variant(initial, variant_type)
        writable = node_cfg["writable"] is True

        addnode = ua.AddNodesItem()
        addnode.RequestedNewNodeId = node_id
        addnode.BrowseName = qname
        addnode.NodeClass = ua.NodeClass.Variable
        addnode.ParentNodeId = container_nodeids[global_idx // CONTAINER_BATCH]
        addnode.ReferenceTypeId = ua.NodeId(ua.ObjectIds.HasComponent)
        addnode.TypeDefinition = ua.NodeId(ua.ObjectIds.BaseDataVariableType)

        attrs = ua.VariableAttributes()
        attrs.Description = ua.LocalizedText(node_id_str)
        attrs.DisplayName = ua.LocalizedText(node_id_str)
        attrs.DataType = ua.NodeId(getattr(ua.ObjectIds, variant_type.name))
        attrs.Value = var
        attrs.ValueRank = ua.ValueRank.Scalar
        attrs.ArrayDimensions = None
        attrs.WriteMask = 0
        attrs.UserWriteMask = 0
        attrs.Historizing = False
        access = read_mask | (write_mask if writable else 0)
        attrs.AccessLevel = access
        attrs.UserAccessLevel = access
        addnode.NodeAttributes = attrs
        return addnode, (node_id, variant_type) if node_cfg["change"] is True else None

    print(CONSOLE_BUILD_START)
    addnodes: list = []
    change_info: list = []
    writable_node_ids: list = []
    global_idx = 0
    for node_cfg, variant_type, default_py, count in node_specs:
        for i in range(1, count + 1):
            total_node_count += 1
            addnode, chg = _build_addnode(node_cfg, variant_type, default_py, i, global_idx)
            addnodes.append(addnode)
            if chg is not None:
                change_info.append(chg)
            if node_cfg["writable"] is True:
                writable_node_ids.append(addnode.RequestedNewNodeId)
            global_idx += 1

    # 分批 add_nodes(每批 1000),逐个 check StatusCode
    BATCH = 1000
    for i in range(0, len(addnodes), BATCH):
        results = await session.add_nodes(addnodes[i:i + BATCH])
        for r in results:
            r.StatusCode.check()

    # change 节点用 RequestedNewNodeId 构造 Node(成功时 AddedNodeId 与请求一致)
    change_nodes = [(make_node(session, nid), vt) for nid, vt in change_info]
    print(CONSOLE_BUILD_DONE)

    # 可写节点 setter:拦截客户端写入,强制使用服务器时间戳(参考 ua_player)
    # 解决:asyncua 客户端写入时 SourceTimestamp 为 None,读取时显示 1601-01-01
    def _writable_setter(node_data, attr, dv):
        if dv is None:
            return
        now_ts = datetime.now(timezone.utc)
        object.__setattr__(dv, "SourceTimestamp", now_ts)
        object.__setattr__(dv, "ServerTimestamp", now_ts)
        object.__setattr__(dv, "SourcePicoseconds", None)
        object.__setattr__(dv, "ServerPicoseconds", None)
        node_data.attributes[attr].value = dv

    for nid in writable_node_ids:
        server.set_attribute_value_setter(nid, _writable_setter)
    if writable_node_ids:
        print(f"可写节点 setter 已设置({len(writable_node_ids)} 个,强制使用服务器时间戳)")

    async def _on_client_write(event: Any, _callback_svc: Any = None) -> None:
        """客户端写值时：控制台打印并写文件日志。"""
        if not getattr(event, "is_external", True):
            return
        params = getattr(event, "request_params", None)
        if not params or not getattr(params, "NodesToWrite", None):
            return
        for wv in params.NodesToWrite:
            node_id = getattr(wv, "NodeId", None) or getattr(wv, "NodeId_", None)
            data_value = getattr(wv, "Value", None)
            val = data_value.Value.Value if data_value and getattr(data_value, "Value", None) else None
            msg = f"写值 NodeId={node_id} Value={val}"
            print(msg)
            logger.info(msg)

    server.subscribe_server_callback(CallbackType.PostWrite, _on_client_write)

    print(f"{CONSOLE_SERVER_START} {endpoint}")
    print(f"节点数量: {total_node_count}")
    print(CONSOLE_DESIGNED_BY)

    if change_nodes:
        async def _update_loop() -> None:
            while True:
                await asyncio.sleep(cycle_ms / 1000.0)
                for n, vt in change_nodes:
                    try:
                        cur = await n.get_value()
                        nxt = next_value(vt, cur)
                        await n.write_value(coerce_to_type(nxt, vt), varianttype=vt)
                    except Exception as e:
                        logger.debug("更新节点 %s 失败: %s", n, e)

        asyncio.create_task(_update_loop())

    logger.info("服务器已启动，cycle=%d ms，change 节点数=%d", cycle_ms, len(change_nodes))
    async with server:
        while True:
            await asyncio.sleep(3600)
