"""clients/tpt_client.py:TPT(被测对象) HTTP 客户端。

用于自动化用例内发起登录 / 数据源 / 位号 / 实时值 / 历史值等调用。
底层复用 tpt_api(同仓 python 子包)。
"""
from __future__ import annotations

from typing import Any

from ua_test_harness.context import RunContext


def _bag(ctx: RunContext, key: str) -> Any:
    return ctx.bag.get(key)


def get_api(ctx: RunContext) -> Any:
    """懒构造 AlgAPI;登录后缓存到 ctx.bag['tpt_api']。"""
    api = _bag(ctx, "tpt_api")
    if api is not None:
        return api
    from tpt_api.client import AlgAPI

    cfg = ctx.config.subject
    api = AlgAPI(base_url=cfg.base_url, timeout=20.0)
    api.login(cfg.username, cfg.password, cfg.tenant_id)
    ctx.bag["tpt_api"] = api
    return api


def endpoint_for(mock_key: str, ctx: RunContext) -> str:
    """按 mock key 查 RunConfig.mock.endpoints;无则用 localIp:18960 默认。"""
    cfg = ctx.config
    ep = {
        "functional": cfg.mock.endpoints.functional,
        "reconnect": cfg.mock.endpoints.reconnect,
        "performance": cfg.mock.endpoints.performance,
        "abnormal": cfg.mock.endpoints.abnormal,
    }.get(mock_key, "")
    if ep:
        return ep
    if cfg.local_ip:
        port = {"functional": 18960, "reconnect": 18961, "performance": 18962, "abnormal": 18963}.get(mock_key, 18960)
        return f"opc.tcp://{cfg.local_ip}:{port}/ua_mocker/"
    return ""