"""alg-manager 算法管理测试。"""

from __future__ import annotations

import json
import os
import zipfile

import httpx
import pytest

from tpt_api import AlgAPI
from tpt_api import algorithms as alg_module


def test_list_algorithms_extend_in_query(api, mock_transport) -> None:
    """extend 必须出现在 query param（不是 body）。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["query"] = dict(request.url.params)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "code": "00000", "records": [],
        }, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    alg_module.list_algorithms(api, page=1, page_size=10, extend=0)
    assert captured["query"]["extend"] == "0"


def test_get_all_algorithms_paginates(api) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(200, json={
                "code": "00000",
                "records": [{"id": 1, "sourcePath": "a.py"}, {"id": 2, "sourcePath": "b.py"}],
            }, request=request)
        return httpx.Response(200, json={"code": "00000", "records": []}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    all_algos = alg_module.get_all_algorithms(api, page_size=2)
    assert len(all_algos) == 2
    # 缓存填充
    assert alg_module.get_by_source_path(api, "a.py") is not None
    assert alg_module.get_by_id(api, 1) is not None
    assert alg_module.get_by_id(api, 99) is None


def test_release_algorithm_body_shape(api) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": "00000"}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    alg_module.release_algorithm(api, 10, is_release=1, cores=2,
                                  resource_type=alg_module.ResourceTypeGPU, num_replicas=3)
    assert captured["body"] == {
        "id": 10, "isRelease": 1, "cores": 2, "resourceType": 2, "numReplicas": 3,
    }


def test_upload_file(tmp_path, api) -> None:
    """UploadFile 用 multipart/form-data，built_in 在 query。"""
    z = tmp_path / "pkg.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("x.py", "print(1)")

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type", "")
        captured["query"] = dict(request.url.params)
        return httpx.Response(200, json={"code": "00000", "data": {"fileName": "pkg.zip"}}, request=request)

    api.client = httpx.Client(base_url=api.base_url, transport=httpx.MockTransport(handler))
    api.token = "abc"
    out = alg_module.upload_file(api, str(z), built_in=1)
    assert "multipart/form-data" in captured["content_type"]
    assert captured["query"]["built_in"] == "1"
    assert out["data"]["fileName"] == "pkg.zip"


def test_match_local_files_mixed(tmp_path, api) -> None:
    """本地有 in_platform.zip / not_in_platform.py / readme.txt；缓存里只有 in_platform.zip。"""
    (tmp_path / "in_platform.zip").write_text("x")
    (tmp_path / "not_in_platform.py").write_text("x")
    (tmp_path / "readme.txt").write_text("x")  # 过滤

    api.source_map = {"in_platform.zip": {"id": 1, "sourcePath": "in_platform.zip", "cores": 2.0}}
    api.algorithms = list(api.source_map.values())

    matched = alg_module.match_local_files(api, str(tmp_path))
    exist = {m["name"] for m in matched if m["isExist"]}
    missing = {m["name"] for m in matched if not m["isExist"]}
    assert "in_platform.zip" in exist
    assert "not_in_platform.py" in missing
    assert "readme.txt" not in exist and "readme.txt" not in missing


def test_list_local_resources_filters_extensions(tmp_path) -> None:
    (tmp_path / "a.zip").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    (tmp_path / "subdir").mkdir()
    files = alg_module.list_local_resources(str(tmp_path))
    names = set(files)
    assert names == {"a.zip", "b.py"}
