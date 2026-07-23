"""alg-manager 算法管理（与 alg_update/common/api.py 1:1 对齐）。

端点（POST，统一 base URL）：
- /alg-manager-web-v2.2-tpt/api/algorithm/page/1           分页列表
- /alg-manager-web-v2.2-tpt/api/algorithm/release         发布/取消发布
- /alg-manager-web-v2.2-tpt/api/algorithm/edit/1          提交算法元数据
- /alg-manager-web-v2.2-tpt/encryption/upload_file_to_minio  上传 zip
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .client import AlgAPI

log = logging.getLogger(__name__)


# alg-manager 端点常量。
AlgoListPath = "/alg-manager-web-v2.2-tpt/api/algorithm/page/1"
AlgoReleasePath = "/alg-manager-web-v2.2-tpt/api/algorithm/release"
AlgoEditPath = "/alg-manager-web-v2.2-tpt/api/algorithm/edit/1"
AlgoUploadPathMinIO = "/alg-manager-web-v2.2-tpt/encryption/upload_file_to_minio"

# 资源类型常量。
ResourceTypeCPU = 1
ResourceTypeGPU = 2


def list_algorithms(
    api: AlgAPI,
    page: int = 1,
    page_size: int = 10,
    extend: int = 0,
    create_time_begin: str = "",
    create_time_end: str = "",
    sort: str = "-createTime",
) -> dict[str, Any]:
    """获取算法列表（单页）。"""
    body: dict[str, Any] = {
        "data": {
            "createTime_begin": create_time_begin,
            "createTime_end": create_time_end,
        },
        "requestBase": {
            "page": f"{page}-{page_size}",
            "sort": sort,
        },
    }
    params = {"extend": extend}
    return api._request("POST", AlgoListPath, body=body, params=params, wrap=False)


def get_all_algorithms(
    api: AlgAPI,
    extend: int = 0,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """自动翻页，获取所有算法信息并缓存到 api.algorithms。"""
    all_records: list[dict[str, Any]] = []
    page = 1
    while True:
        result = list_algorithms(api, page=page, page_size=page_size, extend=extend)
        records = result.get("records", [])
        if not records:
            break
        all_records.extend(records)
        if len(records) < page_size:
            break
        page += 1
    api.algorithms = all_records
    api.source_map = {a.get("sourcePath"): a for a in all_records if a.get("sourcePath")}
    log.info("get_all_algorithms 完成: 共 %d", len(all_records))
    return all_records


def get_by_source_path(api: AlgAPI, source_path: str) -> dict[str, Any] | None:
    """通过 sourcePath 获取缓存的算法信息。"""
    return api.source_map.get(source_path)


def get_by_id(api: AlgAPI, algo_id: int | float) -> dict[str, Any] | None:
    """通过 id 获取缓存的算法信息。"""
    for a in api.algorithms:
        if a.get("id") == algo_id:
            return a
    return None


def release_algorithm(
    api: AlgAPI,
    algo_id: int | float,
    is_release: int,
    cores: int = 1,
    resource_type: int = ResourceTypeCPU,
    num_replicas: int = 1,
) -> Any:
    """发布或取消发布算法。

    is_release: 0=取消发布, 1=发布
    resource_type: 1=CPU, 2=GPU
    """
    body: dict[str, Any] = {
        "id": algo_id,
        "isRelease": is_release,
        "cores": cores,
        "resourceType": resource_type,
        "numReplicas": num_replicas,
    }
    return api._request("POST", AlgoReleasePath, body=body, wrap=False)


def upload_file(api: AlgAPI, file_path: str, built_in: int = 1) -> dict[str, Any]:
    """上传 zip 文件到 MinIO。

    built_in: 1
    返回上传结果 dict。
    """
    url = f"{api.base_url}{AlgoUploadPathMinIO}"
    with open(file_path, "rb") as f:
        files = {
            "file": (os.path.basename(file_path), f, "application/x-zip-compressed"),
        }
        r = api.client.post(url, params={"built_in": built_in}, files=files)
    r.raise_for_status()
    return r.json()


def edit_algorithm(
    api: AlgAPI,
    source_path: str | None = None,
    algo_id: int | float | None = None,
) -> Any:
    """提交算法信息（需先上传文件）。

    只需传入 source_path 或 algo_id，从缓存中读取算法信息并自动拼接 type 字段。
    """
    if source_path:
        info = api.source_map.get(source_path)
    elif algo_id is not None:
        info = get_by_id(api, algo_id)
    else:
        raise ValueError("必须传入 source_path 或 algo_id")

    if not info:
        raise ValueError(f"未找到算法: source_path={source_path}, algo_id={algo_id}")

    algo_info = dict(info)
    algo_info["type"] = f"{info.get('categoryOne', 1)}-{info.get('categoryTwo', 0)}"
    url = f"{api.base_url}{AlgoEditPath}"
    algorithm_json = json.dumps(algo_info)
    files = {"algorithm": ("blob", algorithm_json, "application/json")}
    r = api.client.post(url, files=files)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "00000":
        raise Exception(f"[{data.get('code')}] {data.get('msg')}")
    return data.get("content", data)


def match_local_files(api: AlgAPI, resource_dir: str = "resource") -> list[dict[str, Any]]:
    """拿本地文件名匹配 api.source_map，返回完整算法信息 dict 列表。

    匹配到的条目包含算法全部字段 + name + isExist=True；未匹配的条目只有 name + isExist=False。
    """
    local_files = list_local_resources(resource_dir)
    result: list[dict[str, Any]] = []
    for f in local_files:
        info = api.source_map.get(f)
        if info:
            item = dict(info)
            item["name"] = f
            item["isExist"] = True
            item["cores"] = int(item.get("cores", 1.0))
            result.append(item)
        else:
            result.append({
                "name": f,
                "isExist": False,
            })
    return result


def list_local_resources(dir_path: str = "resource") -> list[str]:
    """读取指定目录下所有 .zip 和 .py 文件名（带后缀）。"""
    if not os.path.isdir(dir_path):
        return []
    return [f for f in os.listdir(dir_path) if f.endswith(".zip") or f.endswith(".py")]
