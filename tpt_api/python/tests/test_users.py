"""TPT admin 用户管理测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from tpt_api import AlgAPI, User, UserDraft
from tpt_api import users as users_module


def test_list_users_empty_keyword(api, mock_transport) -> None:
    mock_transport.register(
        "/xpt-system/api/system-manager/umsAdmin/listByOrgId",
        {"code": "00000", "content": {"records": [], "total": 0, "size": 10, "current": 1, "pages": 0}},
    )
    resp = users_module.list_users(api, page=1, page_size=10)
    assert resp.total == 0
    assert resp.records == []


def test_list_users_with_keyword(api, mock_transport) -> None:
    """关键词搜索：adminWhere 应当是 {"*nickName*|...": "kw"}。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "content": {
                "records": [
                    {"id": 1, "username": "u1", "nickName": "n1", "email": "e1@x", "phone": "138"}
                ],
                "total": 1, "size": 10, "current": 1, "pages": 1,
            },
        }, request=request)

    # 重置 transport 为自定义
    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    api.client.headers["Authorization"] = "Bearer abc"

    resp = users_module.list_users(api, page=1, page_size=10, keyword="u1")
    assert captured["body"]["data"]["adminWhere"] == {"*nickName*|*username*|*phone*|*email*": "u1"}
    assert len(resp.records) == 1
    assert resp.records[0].username == "u1"


def test_create_user_defaults(api, mock_transport) -> None:
    """CreateUser body 必须含硬编码默认值 orgIds=[1], roleIds="5", type="2"。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "00000", "msg": "OK"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"

    users_module.create_user(api, UserDraft(
        username="alice", password="p", nickName="A", email="a@x", phone="1",
    ))

    data = captured["body"]["data"]
    assert data["orgIds"] == [1]
    assert data["roleIds"] == "5"
    assert data["type"] == "2"
    assert data["gender"] == "1"
    assert data["orgName"] == "默认组织"
    assert data["code"] == "alice"  # code 沿用 username
    assert data["icon"] == ""


def test_get_all_users_paginates(api) -> None:
    """get_all_users 自动翻页：第一页满，第二页空。"""
    import httpx as _httpx
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> _httpx.Response:
        call_count["n"] += 1
        body = json.loads(request.content)
        page = body["requestBase"]["page"]
        if page == "1-2":
            # 1 record（< page_size=2）→ loop breaks
            return _httpx.Response(200, json={
                "code": "00000",
                "content": {
                    "records": [{"id": 1}],
                    "total": 1, "size": 2, "current": 1, "pages": 1,
                },
            }, request=request)
        return _httpx.Response(200, json={
            "code": "00000",
            "content": {"records": [], "total": 0, "size": 2, "current": 2, "pages": 0},
        }, request=request)

    api.client = _httpx.Client(base_url=api.base_url, transport=_httpx.MockTransport(handler))
    api.token = "abc"
    all_users = users_module.get_all_users(api, page_size=2)
    assert len(all_users) == 1
    assert call_count["n"] == 1  # 第一页不足 page_size，循环停下


def test_user_from_dict() -> None:
    u = User.from_dict({
        "id": 1, "username": "u", "code": "u", "nickName": "n",
        "email": "e@x", "phone": "138", "status": 0, "type": 2,
    })
    assert u.id == 1
    assert u.username == "u"
    assert u.status == 0
    assert u.type == 2
