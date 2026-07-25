"""Unit tests for tests/support/rt_helpers.py.

These tests use httpx.MockTransport to simulate DataHub responses,
matching the pattern in tpt_api/python/tests.
"""
from __future__ import annotations

import json

import httpx
import pytest

from tpt_api.client import AlgAPI
from tpt_api.errors import TptAPIError

from tests.support import rt_helpers


@pytest.fixture
def api():
    a = AlgAPI("http://test")
    a.token = "abc"
    a.client.headers["Authorization"] = "Bearer abc"
    return a


def _make_transport(handler):
    return httpx.MockTransport(handler)


def test_get_rt_point_returns_first_record(api):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "content": [
                {"tagName": "t1", "tagValue": 12.5, "quality": 192},
                {"tagName": "t2", "tagValue": 0, "quality": 0},
            ],
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=_make_transport(handler))

    pt = rt_helpers.get_rt_point(api, "t1")
    assert pt == {"tagName": "t1", "tagValue": 12.5, "quality": 192}
    assert captured["body"]["data"]["tagNames"] == ["t1"]


def test_get_rt_point_propagates_tag_missing(api):
    """The historical bug was swallowing Tag-Dose-Not-Exist here."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "A0001",
            "msg": "Tag Dose Not Exist",
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=_make_transport(handler))

    with pytest.raises(TptAPIError) as exc_info:
        rt_helpers.get_rt_point(api, "ghost")
    assert "tag dose not exist" in exc_info.value.msg.lower()


def test_get_rt_point_empty_list_returns_empty_dict(api):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "00000", "content": []}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=_make_transport(handler))
    assert rt_helpers.get_rt_point(api, "x") == {}


def test_try_get_rt_point_swallows_tag_missing(api):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "A0001", "msg": "Tag Does Not Exist"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=_make_transport(handler))
    assert rt_helpers.try_get_rt_point(api, "ghost") == {}


def test_try_get_rt_point_returns_data_when_present(api):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000",
            "content": [{"tagName": "t1", "tagValue": 1.0, "quality": 192}],
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=_make_transport(handler))
    assert rt_helpers.try_get_rt_point(api, "t1") == {"tagName": "t1", "tagValue": 1.0, "quality": 192}


def test_try_get_rt_point_propagates_other_errors(api):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "A0201", "msg": "登录已超时"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=_make_transport(handler))
    with pytest.raises(TptAPIError) as exc_info:
        rt_helpers.try_get_rt_point(api, "t1")
    assert exc_info.value.code == "A0201"


def test_assert_rt_unavailable_passes_on_tag_missing(api):
    """Real UA-1-2-02 behavior: read throws TptAPIError after disable."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "A0001", "msg": "Tag Dose Not Exist"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=_make_transport(handler))
    rt_helpers.assert_rt_unavailable(api, "ghost")


def test_assert_rt_unavailable_fails_on_success(api):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000",
            "content": [{"tagName": "t1", "tagValue": 1.0, "quality": 192}],
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=_make_transport(handler))
    with pytest.raises(AssertionError, match="expected TptAPIError"):
        rt_helpers.assert_rt_unavailable(api, "t1")


def test_assert_rt_unavailable_polls_until_unavailable(api):
    """With timeout > 0, helper polls until read throws."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(200, json={
                "code": "00000",
                "content": [{"tagName": "t1", "tagValue": 1.0, "quality": 192}],
            }, request=request)
        return httpx.Response(200, json={"code": "A0001", "msg": "Tag Dose Not Exist"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=_make_transport(handler))
    rt_helpers.assert_rt_unavailable(api, "t1", timeout=5.0)
    assert call_count["n"] == 3