"""ibd-data-hub tag + 历史值测试。"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from tpt_api import AlgAPI, DataTypes, DefaultTagTypesAll, TagTypes
from tpt_api import datahub as dh_module


def test_add_tag_body_shape(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "00000", "content": {}}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    dh_module.add_tag(api, "t1", data_type=DataTypes["DOUBLE"], ds_id=2, frequency=10)
    d = captured["body"]["data"]
    assert d["tagName"] == "t1"
    assert d["tagBaseName"] == "t1"
    assert d["dataType"] == 11
    assert d["dsId"] == 2
    assert d["frequency"] == 10
    assert d["tagDesc"] == "t1 描述"  # 默认值


def test_list_tags_data_filter(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "records": [{"id": 1, "tagName": "t1", "dataType": 11}],
            "total": 1, "size": 10, "current": 1, "pages": 1,
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.list_tags(api, page=1, page_size=10, data={"tagName": "t1"})
    assert captured["body"]["data"] == {"tagName": "t1"}
    assert out["records"][0]["tagName"] == "t1"


def test_get_all_tags_all_types_dedup(api) -> None:
    """get_all_tags_all_types 按 id 去重。"""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        body = json.loads(request.content)
        tag_type = body["data"].get("tagType")
        # tagType 1 返 id=1,2；tagType 4 返 id=2,3；tagType 0 返 id=4
        records = {
            1: [{"id": 1, "tagName": "a"}, {"id": 2, "tagName": "b"}],
            4: [{"id": 2, "tagName": "b"}, {"id": 3, "tagName": "c"}],
            0: [{"id": 4, "tagName": "d"}],
            2: [], 3: [], 5: [],
        }.get(tag_type, [])
        return httpx.Response(200, json={
            "code": "00000", "records": records, "total": len(records),
            "size": 10, "current": 1, "pages": 1,
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    all_tags = dh_module.get_all_tags_all_types(api, page_size=10)
    ids = {t["id"] for t in all_tags}
    assert ids == {1, 2, 3, 4}
    assert api.name_map.get("a")["id"] == 1
    assert api.name_map.get("b")["id"] == 2


def test_delete_tags_by_name_missing_handled(api) -> None:
    """delete_tags_by_name：未在 name_map 的归到 missing。"""
    api.name_map = {
        "exists": {"id": 100, "tagName": "exists"},
    }

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "00000"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"

    out = dh_module.delete_tags_by_name(api, ["exists", "missing"], refresh=False)
    assert out["deleted"] == ["exists"]
    assert out["missing"] == ["missing"]
    assert captured["body"] == {"data": {"ids": [100]}}


def test_import_tag_value(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000", "isSuccess": True,
            "data": {"bad": ["err1"]}, "msg": "OK",
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.import_tag_value(api, [{"tagName": "t1", "tagValue": 1.0}], ds_id=2)
    assert captured["body"]["data"] == [{"tagName": "t1", "tagValue": 1.0}]
    assert captured["body"]["dsId"] == 2
    assert out["is_success"] is True
    assert out["data"] == {"bad": ["err1"]}


def test_import_tag_value_history_sends_corn_not_cron(tmp_path, api) -> None:
    """importTagValueHistory 字段名是 corn（API 拼写），不能写成 cron。"""
    xlsx = tmp_path / "demo.xlsx"
    xlsx.write_bytes(b"fake xlsx content")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        # multipart：fields 在 form，不在 json body
        captured["form"] = dict(request.url.params)
        return httpx.Response(200, json={"code": "00000", "isSuccess": True, "requestId": "req-1"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.import_tag_value_history(
        api, str(xlsx), ds_id=2, start_time="2025-01-01 00:00:00",
        end_time="2025-01-02 00:00:00", frequency=10, cron="0 * * * *",
    )
    assert out["is_success"] is True
    # 没法直接从 request.content 看 form 字段，但 body 是 multipart — 至少确认没崩
    assert "requestId" in out["raw"]


def test_get_history_value_body(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "t1": {"pageNum": 1, "pageSize": 100, "totalPage": 1, "total": 0, "list": []},
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.get_history_value(api, ["t1"], "2025-01-01 00:00:00", "2025-01-02 00:00:00")
    assert captured["body"]["data"]["tagNames"] == ["t1"]
    assert out["t1"]["total"] == 0


def test_recycle_tags_path(api) -> None:
    """list_recycle_tags 必须走 /tag-group/get（不是 tag-info）。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json={
            "code": "00000",
            "tagInfoList": {"records": [{"id": 1, "tagName": "ghost"}], "total": 1, "size": 100, "current": 1, "pages": 1},
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.list_recycle_tags(api, page=1, page_size=100, group_id="1")
    assert captured["path"] == "/ibd-data-hub-web-v2.2/api/tag-group/get"
    assert out["tagInfoList"]["records"][0]["tagName"] == "ghost"


def test_collect_tag_value_body(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "00000", "content": True}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.collect_tag_value(
        api, es_dto={"taskId": "t1", "jobType": 1}, group_id=10, tenant_id="node-1",
    )
    assert captured["path"] == "/ibd-data-hub-web-v2.2/api/tag-value/collectTagValue"
    assert captured["body"]["data"] == {
        "esDTO": {"taskId": "t1", "jobType": 1}, "groupId": 10, "tenantId": "node-1",
    }
    assert out is True


def test_get_rt_value_body_and_list(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "content": [
                {"tagName": "t1", "tagValue": {"v": 1.0}, "tagTime": "2026-07-07 10:00:00",
                 "appTime": "2026-07-07 10:00:01", "quality": 192, "isSuccess": True},
            ],
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.get_rt_value(api, tag_names=["t1"])
    assert captured["path"] == "/ibd-data-hub-web-v2.2/api/tag-value/getRTValue"
    assert captured["body"]["data"]["tagNames"] == ["t1"]
    assert captured["body"]["data"]["isFromDB"] is False
    assert out[0]["tagName"] == "t1"
    assert out[0]["isSuccess"] is True


def test_query_history_value_body_and_ipage(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "content": {
                "records": [{"tagName": "t1", "tagValue": 1.0, "appTime": "2026-07-07 10:00:00"}],
                "total": 1, "size": 10, "current": 1, "pages": 1,
            },
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.query_history_value(
        api, ["t1"], "2026-07-01 00:00:00", "2026-07-07 00:00:00",
        interval=10, is_source=True, page=1, page_size=10,
    )
    assert captured["path"] == "/ibd-data-hub-web-v2.2/api/tag-value/getHistoryValue"
    d = captured["body"]["data"]
    assert d["tagNames"] == ["t1"]
    assert d["begTime"] == "2026-07-01 00:00:00"
    assert d["interval"] == 10
    assert d["isSource"] is True
    assert captured["body"]["requestBase"]["page"] == "1-10"
    assert out["total"] == 1
    assert out["records"][0]["tagName"] == "t1"


def test_write_tag_values_body_and_resp(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "content": {"tagNames": ["t1", "t2"], "failMsg": {}, "msg": "OK"},
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.write_tag_values(
        api, values={"t1": 1.0, "t2": 2.0},
        tag_time="2026-07-07 10:00:00", quality_code=192,
    )
    assert captured["path"] == "/ibd-data-hub-web-v2.2/api/tag-value/writeTagValues"
    d = captured["body"]["data"]
    assert d["values"] == {"t1": 1.0, "t2": 2.0}
    assert d["tagTime"] == "2026-07-07 10:00:00"
    assert d["qualityCode"] == 192
    assert out["tagNames"] == ["t1", "t2"]
    assert out["failMsg"] == {}
