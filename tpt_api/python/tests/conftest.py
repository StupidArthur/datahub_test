"""tpt_api 测试公共 fixture + mock transport。"""

from __future__ import annotations

import json
from typing import Any

import pytest
import httpx


class MockTransport(httpx.BaseTransport):
    """把 request 路由到 handler 字典（按 path 匹配）。"""

    def __init__(self) -> None:
        self.handlers: dict[str, Any] = {}

    def register(self, path: str, response: dict | Exception, status: int = 200) -> None:
        self.handlers[path] = (status, response)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for prefix, (status, body) in self.handlers.items():
            if path.startswith(prefix):
                if isinstance(body, Exception):
                    raise body
                return httpx.Response(status, json=body, request=request)
        return httpx.Response(404, json={"code": "NOT_FOUND", "msg": f"no handler for {path}"}, request=request)


@pytest.fixture
def mock_transport() -> MockTransport:
    return MockTransport()


@pytest.fixture
def api(mock_transport: MockTransport):
    """默认登录过的 AlgAPI（token=abc）。"""
    from tpt_api import AlgAPI
    a = AlgAPI("http://test")
    a.client = httpx.Client(base_url=a.base_url, transport=mock_transport)
    a.token = "abc"
    a.client.headers["Authorization"] = "Bearer abc"
    return a
