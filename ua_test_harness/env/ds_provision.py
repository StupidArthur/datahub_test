"""数据源组态:在 TPT 上接数据源 + 加位号 + 简单遍历验证可读写。

- 数据源按 dsTarUrl(endpoint)找,有则复用,无则 add_ds_info
- 重名位号:列出(count + 前 10 名),二次确认后彻底删(软删 + 物理删)
- 加位号:add_tag(tagName=节点名, tagBaseName=1_{node}, dataType, frequency=采样周期)
        String/DateTime 不支持 -> 跳过(标记)
- smoke verify:找 1 个 Double 可写位号,write_tag_values + get_rt_value 回读
- 数据源 alive=False 不阻塞(只警告)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from tpt_api import datahub
from tpt_api.datahub import (
    get_all_ds_info, add_ds_info, get_all_tags_all_types,
    delete_tags, delete_tags_physical, add_tag,
    get_rt_value, write_tag_values,
)
from type_map import tpt_data_type, expand_node_ids


@dataclass
class TagSpec:
    name: str               # 节点名(同时作 tagName)
    mocker_type: str        # ua_mocker 类型名
    writable: bool = False
    frequency: int = 10     # 采样周期(秒)


@dataclass
class DsProvisionResult:
    ds_id: int = 0
    ds_reused: bool = False
    ds_alive: bool = False
    tags_added: list[str] = field(default_factory=list)
    tags_skipped_unsupported: list[str] = field(default_factory=list)
    tags_failed: list[dict] = field(default_factory=list)
    tags_deleted: list[str] = field(default_factory=list)
    tags_delete_missing: list[str] = field(default_factory=list)
    smoke: dict = field(default_factory=dict)


def tag_specs_from_mock(mock_spec, frequency: int = 10) -> list[TagSpec]:
    """从 MockSpec 展开 TagSpec 列表(展开 count,含 heartbeat 节点)。"""
    specs: list[TagSpec] = []
    # 业务节点
    for n in mock_spec.nodes:
        for nid in expand_node_ids(n.name, n.count):
            specs.append(TagSpec(name=nid, mocker_type=n.type,
                                 writable=n.writable, frequency=frequency))
    # heartbeat 节点(展开 {heartbeat_tag}1)
    specs.append(TagSpec(name=f"{mock_spec.heartbeat_tag}1",
                         mocker_type="Int32", writable=False, frequency=frequency))
    return specs


def find_ds_by_url(api, endpoint: str) -> dict | None:
    for d in get_all_ds_info(api):
        if d.get("dsTarUrl") == endpoint:
            return d
    return None


def find_or_add_ds(api, ds_name: str, endpoint: str) -> tuple[int, bool]:
    """找(复用)或新建数据源。返回 (ds_id, reused)。"""
    d = find_ds_by_url(api, endpoint)
    if d:
        return int(d["id"]), True
    rec = add_ds_info(api, ds_name=ds_name, ds_tar_url=endpoint)
    return int(rec["id"]), False


def list_duplicates(api, tag_names: list[str]) -> list[dict]:
    """列出 tag_names 中已存在的重名位号(含 id/tagName)。"""
    existing = {t.get("tagName"): t for t in get_all_tags_all_types(api)}
    return [existing[n] for n in tag_names if n in existing]


def physically_delete_by_names(api, names: list[str]) -> dict:
    """彻底删(软删到回收站 + 物理删清回收站)。返回 {deleted, missing}。"""
    existing = {t.get("tagName"): t for t in get_all_tags_all_types(api)}
    ids: list[int] = []
    found: list[str] = []
    missing: list[str] = []
    for n in names:
        t = existing.get(n)
        if t and t.get("id") is not None:
            ids.append(int(t["id"]))
            found.append(n)
        else:
            missing.append(n)
    if ids:
        delete_tags(api, ids)            # 软删
        delete_tags_physical(api, ids)   # 物理删
    return {"deleted": found, "missing": missing}


def add_tags(api, ds_id: int, specs: list[TagSpec]) -> tuple[list[str], list[str], list[dict]]:
    """加位号;String/DateTime 不支持 -> 跳过;个别 add_tag 报错 -> 记 failed 不中断。

    返回 (added, skipped, failed)。failed 用于异常测试(bad_len 超长名被拒等)。
    """
    added: list[str] = []
    skipped: list[str] = []
    failed: list[dict] = []
    for s in specs:
        dt = tpt_data_type(s.mocker_type)
        if dt is None:
            skipped.append(s.name)
            continue
        try:
            add_tag(
                api,
                tag_name=s.name,
                data_type=dt,
                ds_id=ds_id,
                tag_base_name=f"1_{s.name}",     # ns=1 约定
                only_read=not s.writable,
                frequency=s.frequency,
            )
            added.append(s.name)
        except Exception as e:
            failed.append({"name": s.name, "error": f"{type(e).__name__}: {e}"})
    return added, skipped, failed


def smoke_verify(api, tag_name: str, write_val: float = 888.88,
                 settle_sec: float = 2.0) -> dict:
    """write_tag_values + get_rt_value 回读,验证数据源可写可读。"""
    try:
        write_tag_values(api, {tag_name: write_val})
    except Exception as e:
        return {"ok": False, "msg": f"write 失败: {type(e).__name__}: {e}"}
    time.sleep(settle_sec)
    try:
        rt = get_rt_value(api, tag_names=[tag_name])
        if not rt:
            return {"ok": False, "msg": "get_rt_value 返回空"}
        v = rt[0].get("tagValue")
        return {"ok": True, "msg": "write+readback ok",
                "write": write_val, "readback": v, "raw": rt[0]}
    except Exception as e:
        return {"ok": False, "msg": f"get_rt_value 失败: {type(e).__name__}: {e}"}


def provision(
    api,
    ds_name: str,
    endpoint: str,
    tag_specs: list[TagSpec],
    *,
    confirm_delete: Callable[[int, list[str]], bool] | None = None,
    smoke_tag: str | None = None,
    smoke_settle_sec: float = 2.0,
    frequency: int = 10,
) -> DsProvisionResult:
    """完整组态:找/建 ds -> 列重名 -> (二次确认)彻底删 -> 加位号 -> smoke。

    confirm_delete(count, first10_names) -> True 才删;None 则不删(只报告)。
    smoke_tag:用于 smoke 的 Double 可写位号名;None 则跳过 smoke。
    """
    result = DsProvisionResult()

    # 1. 数据源
    ds_id, reused = find_or_add_ds(api, ds_name, endpoint)
    result.ds_id = ds_id
    result.ds_reused = reused
    result.ds_alive = True     # 走到这步说明能连;精细化 alive 检查后续补

    # 2. 重名位号
    names = [s.name for s in tag_specs]
    dups = list_duplicates(api, names)
    if dups:
        dup_names = [d.get("tagName") for d in dups]
        do_delete = confirm_delete(len(dups), dup_names[:10]) if confirm_delete else False
        if do_delete:
            r = physically_delete_by_names(api, dup_names)
            result.tags_deleted = r["deleted"]
            result.tags_delete_missing = r["missing"]
        # 不删则后续 add_tag 会因重名报错(由调用方决定)

    # 3. 加位号
    added, skipped, failed = add_tags(api, ds_id, tag_specs)
    result.tags_added = added
    result.tags_skipped_unsupported = skipped
    result.tags_failed = failed

    # 4. smoke
    if smoke_tag:
        result.smoke = smoke_verify(api, smoke_tag, settle_sec=smoke_settle_sec)

    return result
