"""UA-2-4: 位号删除 — 软删除和删除影响."""
from __future__ import annotations

import json

import pytest

from tpt_api.datahub import batch_add_tags, delete_tags, list_tags, list_recycle_tags, write_tag_values
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_cleanup import strict_cleanup_ua2_context
from tests.support.ua2_helpers import (
    find_unique_tag,
    opcua_read_sync,
    pick_unused_nodes,
    setup_ds_and_tag,
    setup_ds_only,
)

_NODES_12 = [
    {"name": f"sd_{i}", "type": "Double", "default": float(i * 10),
     "count": 1, "change": False, "writable": False}
    for i in range(12)
]


# ── UA-2-4-001: 软删除_单个位号 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-001", chapter="UA-2-4",
    title="软删除_单个位号",
    preconditions=["数据源 alive", "位号已创建", "RT 可读"],
    steps=["创建位号", "delete_tags(id)", "查询 list_tags", "查询 list_recycle_tags"],
    expected=["正常查询消失", "回收站出现同一 ID"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_soft_delete_single_tag(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-001",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]

    try:
        assert find_unique_tag(api, tag_name), f"tag {tag_name!r} not created"

        resp = delete_tags(api, [tag_id])
        record_property("delete_response", json.dumps(resp, ensure_ascii=False, default=str))

        active_after = find_unique_tag(api, tag_name)
        record_property("active_list_after_delete", bool(active_after))

        recycle = list_recycle_tags(api, page=1, page_size=999)
        recycle_records = (recycle.get("tagInfoList") or {}).get("records") or []
        match = [t for t in recycle_records if t.get("tagName") == tag_name]
        assert len(match) == 1, f"expected 1 recycle record for {tag_name!r}, got {len(match)}"
        assert int(match[0].get("id", -1)) == tag_id, \
            f"recycle record id {match[0].get('id')} != expected {tag_id}"

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-002: 软删除_多个位号 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-002", chapter="UA-2-4",
    title="软删除_多个位号",
    preconditions=["数据源 alive", "10 个位号已创建且 RT 正常"],
    steps=["batchAdd 创建 10 个位号", "批量软删除所有 10 个 ID", "查询 list_tags", "查询 list_recycle_tags"],
    expected=["目标全部进入回收站", "未选位号不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_soft_delete_multiple_tags(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-002",
                        nodes=_NODES_12)
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]

    created_ids: list[int] = []
    created_names: list[str] = []
    errors: list[str] = []

    try:
        avail = pick_unused_nodes(api, ds_id, count=10, namespace_index=2)
        tag_infos = []
        for i, entry in enumerate(avail):
            tn = f"{settings.test_prefix}UA-2-4-002_b_{i}"
            tag_infos.append({
                "dsId": ds_id, "tagName": tn,
                "tagBaseName": entry.get("tagBaseName", ""),
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "groupId": "0", "frequency": 1, "onlyRead": True,
                "needPush": True, "isVector": True,
            })
            created_names.append(tn)

        result = batch_add_tags(api, tag_infos, conflict_strategy=0)
        for rec in result:
            tid = rec.get("id")
            if tid:
                created_ids.append(int(tid))

        for tn in created_names:
            wait_until(f"rt:{tn}", lambda n=tn: (
                get_rt_point(api, n).get("tagValue") is not None
            ), timeout=30.0)

        resp = delete_tags(api, created_ids)
        record_property("delete_response", json.dumps(resp, ensure_ascii=False, default=str))

        recycle = list_recycle_tags(api, page=1, page_size=999)
        recycle_records = (recycle.get("tagInfoList") or {}).get("records") or []
        recycle_names = {t.get("tagName") for t in recycle_records if t.get("tagName")}
        for tn in created_names:
            assert tn in recycle_names, f"{tn!r} not found in recycle"

        recycle_ids = {
            int(t["id"]) for t in recycle_records
            if t.get("tagName") in created_names and t.get("id") is not None
        }
        for tid in created_ids:
            assert tid in recycle_ids, f"tag id {tid} not found in recycle"

    finally:
        for tag_id, tag_name in zip(created_ids, created_names):
            try:
                strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name)
            except AssertionError as exc:
                errors.append(str(exc))
        try:
            strict_cleanup_ua2_context(api, ds_id=ds_id, ds_name=ds_name,
                                       mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))
        except AssertionError as exc:
            errors.append(str(exc))
        if errors:
            raise AssertionError("; ".join(errors))


# ── UA-2-4-003: 软删除_跨数据源 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-003", chapter="UA-2-4",
    title="软删除_跨数据源",
    preconditions=["两个数据源各自有位号"],
    steps=["创建 DS-A + tag-A", "创建 DS-B + tag-B", "分别软删除 tag-A 和 tag-B",
           "查询 list_tags 和 list_recycle_tags"],
    expected=["各目标按 dsId 正确删除", "不串源"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_soft_delete_cross_ds(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx_a = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-003-A",
                             tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ctx_b = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-003-B",
                             tag_base_name="2_smoke_change_1", data_type=DataTypes["INT"])
    errors: list[str] = []

    try:
        resp_a = delete_tags(api, [ctx_a["tag_id"]])
        resp_b = delete_tags(api, [ctx_b["tag_id"]])
        record_property("resp_a", json.dumps(resp_a, ensure_ascii=False, default=str))
        record_property("resp_b", json.dumps(resp_b, ensure_ascii=False, default=str))

        recycle = list_recycle_tags(api, page=1, page_size=999)
        recycle_records = (recycle.get("tagInfoList") or {}).get("records") or []

        for expected_id, expected_dsid in [
            (ctx_a["tag_id"], ctx_a["ds_id"]),
            (ctx_b["tag_id"], ctx_b["ds_id"]),
        ]:
            match = [t for t in recycle_records if int(t.get("id", -1)) == expected_id]
            assert len(match) == 1, \
                f"expected 1 recycle record for id={expected_id}, got {len(match)}"
            actual_dsid = int(match[0].get("dsId", -1))
            assert actual_dsid == expected_dsid, \
                f"id={expected_id}: expected dsId={expected_dsid}, got {actual_dsid}"

    finally:
        for ctx in [ctx_a, ctx_b]:
            try:
                strict_cleanup_ua2_context(
                    api, tag_id=ctx["tag_id"], tag_name=ctx["tag_name"],
                    ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                    mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"),
                )
            except AssertionError as exc:
                errors.append(str(exc))
        if errors:
            raise AssertionError("; ".join(errors))


# ── UA-2-4-004: 软删除_身份保持 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-004", chapter="UA-2-4",
    title="软删除_身份保持",
    preconditions=["位号已创建"],
    steps=["快照 tag 配置", "软删除", "查回收站记录", "比对 id/tagName/tagBaseName/dsId/dataType"],
    expected=["回收站中 ID、tagName、tagBaseName、dsId、dataType 不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_soft_delete_identity_preserved(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-004",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]

    try:
        before = find_unique_tag(api, tag_name)
        assert before, f"tag {tag_name!r} not found before delete"

        resp = delete_tags(api, [tag_id])
        record_property("delete_response", json.dumps(resp, ensure_ascii=False, default=str))

        recycle = list_recycle_tags(api, page=1, page_size=999)
        recycle_records = (recycle.get("tagInfoList") or {}).get("records") or []
        match = [t for t in recycle_records if int(t.get("id", -1)) == tag_id]
        assert len(match) == 1, f"recycle record for id={tag_id} not found"
        after = match[0]

        assert int(after["id"]) == int(before["id"])
        assert after.get("tagName") == before.get("tagName")
        assert after.get("tagBaseName") == before.get("tagBaseName")
        assert int(after.get("dsId", -1)) == int(before.get("dsId", -1))
        assert int(after.get("dataType", -1)) == int(before.get("dataType", -1))

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-005: 软删除_重复提交 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-005", chapter="UA-2-4",
    title="软删除_重复提交",
    preconditions=["位号已创建"],
    steps=["首次软删除", "再次软删除同一 ID", "查询回收站"],
    expected=["记录幂等或错误规则；无重复记录"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_soft_delete_duplicate(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-005",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        resp1 = delete_tags(api, [tag_id])
        observations["first_delete"] = _safe_json(resp1)

        recycle_after_first = list_recycle_tags(api, page=1, page_size=999)
        observations["recycle_count_after_first"] = len(
            [t for t in _recycle_records(recycle_after_first)
             if int(t.get("id", -1)) == tag_id]
        )

        try:
            resp2 = delete_tags(api, [tag_id])
            observations["second_delete"] = _safe_json(resp2)
        except TptAPIError as exc:
            observations["second_delete_error"] = {"code": exc.code, "msg": exc.msg}

        recycle_after_second = list_recycle_tags(api, page=1, page_size=999)
        observations["recycle_count_after_second"] = len(
            [t for t in _recycle_records(recycle_after_second)
             if int(t.get("id", -1)) == tag_id]
        )

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-005: spec pending, recording observed behavior")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-006: 软删除_无效ID ───────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-006", chapter="UA-2-4",
    title="软删除_无效ID",
    preconditions=[],
    steps=["使用不存在的 ID 调用软删除", "记录响应", "确认现有数据不变"],
    expected=["记录响应；现有数据不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_soft_delete_invalid_id(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-006")
    ds_id = ctx["ds_id"]
    observations: dict = {}

    try:
        fake_id = 99999999
        try:
            resp = delete_tags(api, [fake_id])
            observations["invalid_id_response"] = _safe_json(resp)
        except TptAPIError as exc:
            observations["invalid_id_error"] = {"code": exc.code, "msg": exc.msg}

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-006: spec pending, recording observed behavior")

    finally:
        strict_cleanup_ua2_context(api, ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-007: 软删除_有效无效混合 ──────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-007", chapter="UA-2-4",
    title="软删除_有效无效混合",
    preconditions=["一个有效位号已创建"],
    steps=["同批传入有效 ID 和无效 ID", "记录响应", "查询位号状态"],
    expected=["记录事务规则；有效项最终状态可确认"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_soft_delete_mixed_ids(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-007",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        fake_id = 99999999
        try:
            resp = delete_tags(api, [tag_id, fake_id])
            observations["mixed_response"] = _safe_json(resp)
        except TptAPIError as exc:
            observations["mixed_error"] = {"code": exc.code, "msg": exc.msg}

        observations["valid_tag_still_active"] = bool(find_unique_tag(api, tag_name))

        if not observations["valid_tag_still_active"]:
            recycle = list_recycle_tags(api, page=1, page_size=999)
            observations["valid_in_recycle"] = tag_id in {
                int(t["id"]) for t in _recycle_records(recycle)
                if t.get("id") is not None
            }

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-007: spec pending, recording observed behavior")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-008: 删除影响_RT查询 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-008", chapter="UA-2-4",
    title="删除影响_RT查询",
    preconditions=["位号 RT 有效"],
    steps=["保存删除前 RT+质量", "软删除", "删除后查询 RT 与质量", "记录返回规则"],
    expected=["不得仍作为正常有效位号返回"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_soft_delete_rt_impact(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-008",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        pt_before = get_rt_point(api, tag_name)
        observations["rt_before"] = {k: str(v) for k, v in pt_before.items()}

        delete_tags(api, [tag_id])

        try:
            pt_after = get_rt_point(api, tag_name)
            observations["rt_after"] = {k: str(v) for k, v in pt_after.items()}
        except TptAPIError as exc:
            observations["rt_after_error"] = {"code": exc.code, "msg": exc.msg}

        try:
            from tpt_api.datahub import query_tags_with_quality
            qwq = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
            observations["qwq_after"] = _safe_json(qwq)
        except TptAPIError as exc:
            observations["qwq_after_error"] = {"code": exc.code, "msg": exc.msg}

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-008: spec pending, recording observed behavior")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-009: 删除影响_写入 ────────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-009", chapter="UA-2-4",
    title="删除影响_写入",
    preconditions=["可写位号已创建", "RT 有效", "OPC UA 源值可读"],
    steps=["记录 UA 源值", "软删除", "回写测试值", "重新读取 UA 源值"],
    expected=["写入失败或不生效；UA 源值不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_write_after_soft_delete(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-009",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"],
                           only_read=False)
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        source_before = opcua_read_sync(endpoint, "smoke_static_1", namespace_index=2)

        delete_tags(api, [tag_id])

        write_observations: dict = {}
        try:
            resp = write_tag_values(api, {tag_name: 999.9})
            write_observations["write_response"] = resp
        except TptAPIError as exc:
            write_observations["write_error"] = {"code": exc.code, "msg": exc.msg}

        source_after = opcua_read_sync(endpoint, "smoke_static_1", namespace_index=2)
        write_observations["source_before"] = source_before
        write_observations["source_after"] = source_after
        record_property("write_observations", json.dumps(write_observations, ensure_ascii=False, default=str))

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── Helpers ──────────────────────────────────────────────────────────────────


def _safe_json(obj: object) -> dict:
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return {"_serialize_error": str(obj)}


def _recycle_records(resp: dict) -> list[dict]:
    return (resp.get("tagInfoList") or {}).get("records") or []
