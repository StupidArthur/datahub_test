"""ibd-data-hub 数据源 (ds-info) 测试。"""

from __future__ import annotations

import json

import httpx
import pytest

from tpt_api import AlgAPI, DsInfo, DsSubTypes, DsTypes
from tpt_api import datahub as dh_module


def test_list_ds_info_shape(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "records": [
                {
                    "id": 2,
                    "name": "omc167",
                    "dsName": "omc167",
                    "dsType": 1,
                    "dsTypeDesc": "Real time database",
                    "dsSubType": 4,
                    "dsSubTypeDesc": "OPC-UA-Server",
                    "dsTarUrl": "opc.tcp://172.20.58.167:18950",
                    "dsStatus": 1,
                    "alive": True,
                    "supportSub": False,
                    "dsExtInfo": {},
                    "createBy": "admin",
                    "updateBy": "admin",
                    "createTime": "2026-07-02 11:11:30",
                    "updateTime": "2026-07-02 11:16:09",
                },
            ],
            "total": 1, "size": 10, "current": 1, "pages": 1,
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"

    out = dh_module.list_ds_info(api, page=1, page_size=10)
    # 验证 body 形状
    assert captured["body"]["data"] == {}
    assert captured["body"]["requestBase"] == {"page": "1-10", "sort": "-createTime"}
    # 验证响应
    assert out["total"] == 1
    rec = out["records"][0]
    assert rec["id"] == 2
    assert rec["dsName"] == "omc167"
    assert rec["dsType"] == 1
    assert rec["dsSubType"] == 4
    assert rec["alive"] is True


def test_get_all_ds_info_paginates(api) -> None:
    """get_all_ds_info 自动翻页：第一页满，第二页空。"""
    import httpx as _httpx
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> _httpx.Response:
        call_count["n"] += 1
        body = json.loads(request.content)
        page = body["requestBase"]["page"]
        if page == "1-2":
            # 1 record < page_size=2 → loop breaks
            return _httpx.Response(200, json={
                "code": "00000",
                "records": [{"id": 1, "dsName": "omc1"}],
                "total": 1, "size": 2, "current": 1, "pages": 1,
            }, request=request)
        return _httpx.Response(200, json={
            "code": "00000",
            "records": [], "total": 0, "size": 2, "current": 2, "pages": 0,
        }, request=request)

    api.client = _httpx.Client(base_url=api.base_url, transport=_httpx.MockTransport(handler))
    api.token = "abc"
    all_ds = dh_module.get_all_ds_info(api, page_size=2)
    assert len(all_ds) == 1
    assert call_count["n"] == 1


def test_get_ds_info_by_id_and_name() -> None:
    records = [
        {"id": 1, "dsName": "omc1", "name": "omc1"},
        {"id": 2, "dsName": "omc2", "name": "omc2-display"},
    ]
    assert dh_module.get_ds_info_by_id(records, 1)["dsName"] == "omc1"
    assert dh_module.get_ds_info_by_id(records, 99) is None
    assert dh_module.get_ds_info_by_name(records, "omc2")["id"] == 2
    # name 字段也能匹配
    assert dh_module.get_ds_info_by_name(records, "omc2-display")["id"] == 2
    assert dh_module.get_ds_info_by_name(records, "nope") is None


def test_ds_info_to_model() -> None:
    raw = {
        "id": 3,
        "name": "ds3",
        "dsName": "ds3",
        "dsType": DsTypes["REAL_TIME_DB"],
        "dsTypeDesc": "Real time database",
        "dsSubType": DsSubTypes["OPC_UA_SERVER"],
        "dsSubTypeDesc": "OPC-UA-Server",
        "dsTarUrl": "opc.tcp://x:1234",
        "dsStatus": 1,
        "alive": True,
        "supportSub": True,
        "dsExtInfo": {"k": "v"},
        "createBy": "admin", "updateBy": "admin",
        "createTime": "2026-07-02 11:11:30",
        "updateTime": "2026-07-02 11:16:09",
    }
    ds = dh_module.ds_info_to_model(raw)
    assert isinstance(ds, DsInfo)
    assert ds.id == 3
    assert ds.dsTarUrl == "opc.tcp://x:1234"
    assert ds.alive is True
    assert ds.supportSub is True
    assert ds.dsExtInfo == {"k": "v"}


def test_ds_types_constants() -> None:
    from tpt_api import DsTypes, DsSubTypes
    assert DsTypes["REAL_TIME_DB"] == 1
    assert DsSubTypes["OPC_UA_SERVER"] == 4


def test_add_ds_info_success(api) -> None:
    """add_ds_info 必须把 dsType/dsSubType 序列化为字符串。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000",
            "id": 42,
            "createTime": "2026-07-06 16:21:07",
            "updateTime": "2026-07-06 16:21:07",
            "createBy": "admin",
            "updateBy": "admin",
            "dsName": "demo",
            "dsType": 1,
            "dsSubType": 4,
            "dsTarUrl": "opc.tcp://10.30.70.77:18950",
            "dsExtInfo": {},
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = dh_module.add_ds_info(api, ds_name="demo", ds_tar_url="opc.tcp://10.30.70.77:18950")
    # 关键断言：dsType / dsSubType 是字符串
    d = captured["body"]["data"]
    assert d["dsName"] == "demo"
    assert d["dsType"] == "1"
    assert d["dsSubType"] == "4"
    assert d["dsTarUrl"] == "opc.tcp://10.30.70.77:18950"
    # 默认值
    assert d.get("dsExtInfo") is None  # 未传，不发
    # 响应
    assert out["id"] == 42
    assert out["dsName"] == "demo"


def test_add_ds_info_duplicate_url_raises(api) -> None:
    """重复 URL 抛 TptAPIError，code=A0001，is_auth_error=False。"""
    from tpt_api import TptAPIError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "A0001",
            "msg": "[A0001]Client error:Duplicate data source address",
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    with pytest.raises(TptAPIError) as exc_info:
        dh_module.add_ds_info(api, ds_name="dup", ds_tar_url="opc.tcp://x:1")
    assert exc_info.value.code == "A0001"
    assert exc_info.value.is_auth_error is False
    assert "Duplicate" in exc_info.value.msg


def test_add_ds_info_missing_required_raises_locally(api) -> None:
    """必填字段缺一：本地 ValueError，不发请求。"""
    import httpx as _httpx
    called = {"n": 0}

    def handler(request: _httpx.Request) -> _httpx.Response:
        called["n"] += 1
        return _httpx.Response(200, json={"code": "00000"}, request=request)

    api.client = _httpx.Client(base_url=api.base_url, transport=_httpx.MockTransport(handler))
    api.token = "abc"
    with pytest.raises(ValueError, match="ds_name"):
        dh_module.add_ds_info(api, ds_name="", ds_tar_url="opc.tcp://x:1")
    with pytest.raises(ValueError, match="ds_tar_url"):
        dh_module.add_ds_info(api, ds_name="x", ds_tar_url="")
    assert called["n"] == 0


def test_add_ds_info_with_optional_fields(api) -> None:
    """name 和 dsExtInfo 可选。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "00000", "id": 1}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    dh_module.add_ds_info(
        api, ds_name="demo", ds_tar_url="opc.tcp://x:1",
        name="display name", ds_ext_info={"k": "v"},
    )
    d = captured["body"]["data"]
    assert d["name"] == "display name"
    assert d["dsExtInfo"] == {"k": "v"}
