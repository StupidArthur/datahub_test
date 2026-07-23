"""fixtures/environment.py:测试运行环境 fixture(起 mock / 登录 / 选 endpoint)。"""
from __future__ import annotations

from ua_test_harness.context import RunContext
from ua_test_harness.clients import mock_control


def ensure_mock_ready(ctx: RunContext, key: str = "functional") -> str:
    """确保指定 mock 已 ready,返回 endpoint。"""
    configured = {
        "functional": ctx.config.mock.endpoints.functional,
        "reconnect": ctx.config.mock.endpoints.reconnect,
        "performance": ctx.config.mock.endpoints.performance,
        "abnormal": ctx.config.mock.endpoints.abnormal,
    }.get(key, "")
    if ctx.config.mock.control_mode == "external-script" and configured:
        return configured
    if mock_control.status(key) not in ("ready", "running"):
        mock_control.start_mock(key)
        mock_control.wait_ready(key, timeout=120.0, ctx=ctx)
    return configured or mock_control.get_endpoint(key, ctx)


def ensure_logged_in(ctx: RunContext) -> None:
    """触发 login,失败抛 assertion。"""
    from ua_test_harness.clients.tpt_client import get_api
    get_api(ctx)
