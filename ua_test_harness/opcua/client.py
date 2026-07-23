"""OPC UA 源端 client(asyncua 封装):直连 ua_mocker/ua_player,读/写/发现节点。

绕过 TPT,用于:
- 验证 mock 节点确实存在 / 可读 / 可写
- 写源端值,再查 TPT RT/history 看传播
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from asyncua import Client, ua

# ua2_fixture_map type_key -> asyncua VariantType(与 ua_mocker/type_mapping 一致)
VARIANT_TYPE_BY_UA2_KEY: dict[str, ua.VariantType] = {
    "BOOLEAN": ua.VariantType.Boolean,
    "SBYTE": ua.VariantType.SByte,
    "BYTE": ua.VariantType.Byte,
    "INT16": ua.VariantType.Int16,
    "UINT16": ua.VariantType.UInt16,
    "INT32": ua.VariantType.Int32,
    "UINT32": ua.VariantType.UInt32,
    "INT64": ua.VariantType.Int64,
    "UINT64": ua.VariantType.UInt64,
    "FLOAT": ua.VariantType.Float,
    "DOUBLE": ua.VariantType.Double,
    "STRING": ua.VariantType.String,
    "DATETIME": ua.VariantType.DateTime,
}

_NUMERIC_VARIANT_TYPES = frozenset({
    ua.VariantType.SByte, ua.VariantType.Byte,
    ua.VariantType.Int16, ua.VariantType.UInt16,
    ua.VariantType.Int32, ua.VariantType.UInt32,
    ua.VariantType.Int64, ua.VariantType.UInt64,
    ua.VariantType.Float, ua.VariantType.Double,
})


def coerce_opcua_value(value: Any, variant_type: ua.VariantType) -> Any:
    """将 Python 值强制为 OPC UA 节点可接受的类型(写回/恢复源端用)。"""
    if value is None:
        if variant_type == ua.VariantType.Boolean:
            return False
        if variant_type in (ua.VariantType.Float, ua.VariantType.Double):
            return 0.0
        if variant_type == ua.VariantType.String:
            return ""
        if variant_type == ua.VariantType.DateTime:
            return datetime(2025, 1, 1, 0, 0, 0)
        return 0
    if variant_type == ua.VariantType.Boolean:
        return bool(value)
    if variant_type in _NUMERIC_VARIANT_TYPES:
        if variant_type in (ua.VariantType.Float, ua.VariantType.Double):
            return float(value)
        return int(value)
    if variant_type == ua.VariantType.String:
        return str(value)
    if variant_type == ua.VariantType.DateTime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    return value


@dataclass
class NodeInfo:
    browse_name: str
    node_id: str
    value: object = None


class UaSourceClient:
    def __init__(self, endpoint: str, namespace_index: int = 1):
        self.endpoint = endpoint
        self.ns = namespace_index

    def _nid(self, name: str) -> str:
        return f"ns={self.ns};s={name}"

    async def read(self, name: str):
        async with Client(self.endpoint) as client:
            return await client.get_node(self._nid(name)).read_value()

    async def write(self, name: str, value, *, type_key: str | None = None):
        async with Client(self.endpoint) as client:
            node = client.get_node(self._nid(name))
            if type_key:
                vt = VARIANT_TYPE_BY_UA2_KEY[type_key]
                coerced = coerce_opcua_value(value, vt)
                await node.write_value(coerced, varianttype=vt)
            else:
                await node.write_value(value)

    async def read_many(self, names: list[str]) -> dict:
        out: dict = {}
        async with Client(self.endpoint) as client:
            for n in names:
                try:
                    out[n] = await client.get_node(self._nid(n)).read_value()
                except Exception as e:
                    out[n] = f"<err: {e}>"
        return out

    async def discover(self) -> list[NodeInfo]:
        """列出 Objects 下本 namespace 的节点。"""
        infos: list[NodeInfo] = []
        async with Client(self.endpoint) as client:
            objects = client.get_objects_node()
            for ch in await objects.get_children():
                bn = await ch.read_browse_name()
                if bn.NamespaceIndex == self.ns:
                    nid = ch.nodeid.to_string()
                    val = None
                    try:
                        val = await ch.read_value()
                    except Exception:
                        pass
                    infos.append(NodeInfo(browse_name=bn.Name, node_id=nid, value=val))
        return infos

    # ---- 同步包装 ----
    def read_sync(self, name: str):
        return asyncio.run(self.read(name))

    def write_sync(self, name: str, value, *, type_key: str | None = None):
        return asyncio.run(self.write(name, value, type_key=type_key))

    def discover_sync(self) -> list[NodeInfo]:
        return asyncio.run(self.discover())
