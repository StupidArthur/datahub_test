"""clients/opcua_client.py:asyncua 直读 Mock 节点的客户端封装。

用例通常需要直读源端事实(避开 DataHub 中转)。底层用 asyncua。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from ua_test_harness.context import RunContext

log = logging.getLogger(__name__)


async def _read_async(endpoint: str, node_id: str) -> Any:
    from asyncua import Client, ua

    async with Client(url=endpoint) as client:
        # node_id 形如 "ns=1;s=mock_Double_static_ro_1"
        nid = ua.NodeId.from_string(node_id)
        node = client.get_node(nid)
        return await node.read_value()


def read_value(endpoint: str, node_id: str, timeout: float = 5.0) -> Any:
    return asyncio.run(asyncio.wait_for(_read_async(endpoint, node_id), timeout=timeout))


async def _write_async(endpoint: str, node_id: str, value: Any) -> None:
    from asyncua import Client, ua

    async with Client(url=endpoint) as client:
        nid = ua.NodeId.from_string(node_id)
        node = client.get_node(nid)
        await node.write_value(value)


def write_value(endpoint: str, node_id: str, value: Any, timeout: float = 5.0) -> None:
    asyncio.run(asyncio.wait_for(_write_async(endpoint, node_id, value), timeout=timeout))


def get_endpoint(mock_key: str, ctx: RunContext) -> str:
    from .tpt_client import endpoint_for
    return endpoint_for(mock_key, ctx)