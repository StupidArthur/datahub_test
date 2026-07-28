"""UA-2-4: 位号删除 — 恢复（回收站恢复、源节点、历史）."""
from __future__ import annotations

import json

import pytest

from tpt_api.datahub import (
    delete_tags,
    get_history_value,
    list_recycle_tags,
    query_tags_with_quality,
    remove_tag_group_relation,
    write_tag_values,
)
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
    {"name": f"rs_{i}", "type": "Double", "default": float(i * 10),
     "count": 1, "change": False, "writable": False}
    for i in range(12)
]


# ── UA-2-4-010: 恢复_源节点 ────────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-010", chapter="UA-2-4",
    title="恢复_源节点",
    preconditions=["数据源 alive", "位号已创建", "RT 可读", "OPC UA 源值可读"],
    steps=["记录删除前源值", "软删除", "恢复", "重新读取 OPC UA 源值"],
    expected=["源节点连接正常，读值不受删除/恢复影响"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_restore_source_node(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-010",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        source_before = opcua_read_sync(endpoint, "smoke_static_1", namespace_index=2)
        record_property("source_before", source_before)

        delete_tags(api, [tag_id])

        remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])

        wait_until(f"rt:{tag_name}_after_restore", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        source_after = opcua_read_sync(endpoint, "smoke_static_1", namespace_index=2)
        record_property("source_after", source_after)

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-011: 恢复_历史_新采集 ──────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-011", chapter="UA-2-4",
    title="恢复_历史_新采集",
    preconditions=["数据源 alive", "位号已创建并产生过历史数据"],
    steps=["记录恢复前历史样本数", "软删除", "恢复", "写入新值", "查询恢复后历史"],
    expected=["恢复后新写入的值能被历史记录"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_restore_history_new(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-011",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        observations["rt_before"] = str(get_rt_point(api, tag_name).get("tagValue"))

        try:
            resp = get_history_value(api, [tag_name], beg_time="2025-01-01 00:00:00", end_time="2026-12-31 23:59:59")
            observations["history_before"] = _safe_json(resp.get(tag_name))
        except (TptAPIError, TypeError) as exc:
            observations["history_before_error"] = str(exc)

        delete_tags(api, [tag_id])

        remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])

        wait_until(f"rt_after_restore:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        observations["rt_after_restore"] = str(get_rt_point(api, tag_name).get("tagValue"))

        try:
            write_tag_values(api, {tag_name: 200.0})
            observations["write_after_restore"] = "accepted"
        except TptAPIError as exc:
            observations["write_after_restore"] = {"code": exc.code, "msg": exc.msg}

        try:
            resp = get_history_value(api, [tag_name], beg_time="2025-01-01 00:00:00", end_time="2026-12-31 23:59:59")
            observations["history_after"] = _safe_json(resp.get(tag_name))
        except (TptAPIError, TypeError) as exc:
            observations["history_after_error"] = str(exc)

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-011: spec pending, recording history observation")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-012: 恢复_历史_已有 ─────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-012", chapter="UA-2-4",
    title="恢复_历史_已有",
    preconditions=["位号已有历史数据"],
    steps=["记录历史数据快照", "软删除", "恢复", "对比恢复后的历史数据"],
    expected=["软删除后的历史数据不丢失"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_restore_history_existing(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-012",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        observations["rt_before"] = str(get_rt_point(api, tag_name).get("tagValue"))

        try:
            resp = get_history_value(api, [tag_name], beg_time="2025-01-01 00:00:00", end_time="2026-12-31 23:59:59")
            observations["history_before"] = _safe_json(resp.get(tag_name))
        except (TptAPIError, TypeError) as exc:
            observations["history_before_error"] = str(exc)

        delete_tags(api, [tag_id])

        remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])

        wait_until(f"rt_after_restore:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        observations["rt_after_restore"] = str(get_rt_point(api, tag_name).get("tagValue"))

        try:
            resp = get_history_value(api, [tag_name], beg_time="2025-01-01 00:00:00", end_time="2026-12-31 23:59:59")
            observations["history_after"] = _safe_json(resp.get(tag_name))
        except (TptAPIError, TypeError) as exc:
            observations["history_after_error"] = str(exc)

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA2-4-012: spec pending, recording history observation")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-013: 恢复_单个位号 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-013", chapter="UA-2-4",
    title="恢复_单个位号",
    preconditions=["一个位号已在回收站"],
    steps=["确认回收站中有位号", "remove_tag_group_relation(group_id=1, [tag_id])",
           "确认回收站中无该位号", "确认 RT 正常"],
    expected=["位号离开回收站", "RT 可读"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_restore_single_tag(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-013",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]

    try:
        delete_tags(api, [tag_id])

        recycle_before = list_recycle_tags(api, page=1, page_size=999)
        recs_before = _recycle_records(recycle_before)
        assert any(int(r.get("id", -1)) == tag_id for r in recs_before), \
            f"tag {tag_id} not in recycle before restore"

        resp = remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])
        record_property("restore_response", json.dumps(resp, ensure_ascii=False, default=str))

        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        recs_after = _recycle_records(recycle_after)
        assert not any(int(r.get("id", -1)) == tag_id for r in recs_after), \
            f"tag {tag_id} still in recycle after restore"

        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-014: 恢复_多个位号 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-014", chapter="UA-2-4",
    title="恢复_多个位号",
    preconditions=["10 个位号已在回收站"],
    steps=["批量软删除 10 个位号", "确认回收站有 10 条", "批量恢复",
           "确认回收站中无这些位号", "确认 RT 正常"],
    expected=["所有位号离开回收站", "RT 可读"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_restore_multiple_tags(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-014",
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
            tn = f"{settings.test_prefix}UA-2-4-014_b_{i}"
            tag_infos.append({
                "dsId": ds_id, "tagName": tn,
                "tagBaseName": entry.get("tagBaseName", ""),
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "groupId": "0", "frequency": 1, "onlyRead": True,
                "needPush": True, "isVector": True,
            })
            created_names.append(tn)

        result = _batch_add(api, tag_infos)
        for rec in result:
            tid = rec.get("id")
            if tid:
                created_ids.append(int(tid))

        for tn in created_names:
            wait_until(f"rt:{tn}", lambda n=tn: (
                get_rt_point(api, n).get("tagValue") is not None
            ), timeout=30.0)

        delete_tags(api, created_ids)

        recycle_before = list_recycle_tags(api, page=1, page_size=999)
        recs_before = _recycle_records(recycle_before)
        recycle_ids_before = {
            int(r["id"]) for r in recs_before
            if r.get("id") is not None and int(r["id"]) in created_ids
        }
        assert len(recycle_ids_before) == 10, \
            f"expected 10 tags in recycle, got {len(recycle_ids_before)}"

        resp = remove_tag_group_relation(api, group_id="1", tag_ids=created_ids)
        record_property("restore_response", json.dumps(resp, ensure_ascii=False, default=str))

        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        recs_after = _recycle_records(recycle_after)
        recycle_ids_after = {
            int(r["id"]) for r in recs_after
            if r.get("id") is not None
        }
        leftover = set(created_ids) & recycle_ids_after
        assert not leftover, f"tags still in recycle after restore: {leftover}"

        for tn in created_names:
            wait_until(f"rt:{tn}_restored", lambda n=tn: (
                get_rt_point(api, n).get("tagValue") is not None
            ), timeout=30.0)

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


# ── UA-2-4-015: 恢复_跨数据源 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-015", chapter="UA-2-4",
    title="恢复_跨数据源",
    preconditions=["两个数据源各自有位号在回收站"],
    steps=["DS-A 位号软删除", "DS-B 位号软删除", "同批恢复",
           "确认两回收站均无", "确认 RT 正常"],
    expected=["各按 dsId 正确恢复", "不串源"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_restore_cross_ds(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx_a = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-015-A",
                             tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ctx_b = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-015-B",
                             tag_base_name="2_smoke_change_1", data_type=DataTypes["INT"])
    errors: list[str] = []

    try:
        delete_tags(api, [ctx_a["tag_id"], ctx_b["tag_id"]])

        recycle_before = list_recycle_tags(api, page=1, page_size=999)
        recs_before = _recycle_records(recycle_before)
        for expected_id in [ctx_a["tag_id"], ctx_b["tag_id"]]:
            assert any(int(r.get("id", -1)) == expected_id for r in recs_before), \
                f"tag {expected_id} not in recycle before restore"

        resp = remove_tag_group_relation(api, group_id="1",
                                         tag_ids=[ctx_a["tag_id"], ctx_b["tag_id"]])
        record_property("restore_response", json.dumps(resp, ensure_ascii=False, default=str))

        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        recs_after = _recycle_records(recycle_after)
        for expected_id in [ctx_a["tag_id"], ctx_b["tag_id"]]:
            assert not any(int(r.get("id", -1)) == expected_id for r in recs_after), \
                f"tag {expected_id} still in recycle after restore"

        for tag_name in [ctx_a["tag_name"], ctx_b["tag_name"]]:
            wait_until(f"rt:{tag_name}", lambda n=tag_name: (
                get_rt_point(api, n).get("tagValue") is not None
            ), timeout=30.0)

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


# ── UA-2-4-016: 恢复_重复提交 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-016", chapter="UA-2-4",
    title="恢复_重复提交",
    preconditions=["一个位号已在回收站"],
    steps=["首次恢复", "再次恢复同一 ID", "查询回收站"],
    expected=["二次操作幂等；记录不重复"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_restore_duplicate(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-016",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        delete_tags(api, [tag_id])

        resp1 = remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])
        observations["first_restore_response"] = _safe_json(resp1)

        recycle_after_first = list_recycle_tags(api, page=1, page_size=999)
        observations["recycle_count_after_first"] = len(
            [t for t in _recycle_records(recycle_after_first)
             if int(t.get("id", -1)) == tag_id]
        )

        try:
            resp2 = remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])
            observations["second_restore_response"] = _safe_json(resp2)
        except TptAPIError as exc:
            observations["second_restore_error"] = {"code": exc.code, "msg": exc.msg}

        recycle_after_second = list_recycle_tags(api, page=1, page_size=999)
        observations["recycle_count_after_second"] = len(
            [t for t in _recycle_records(recycle_after_second)
             if int(t.get("id", -1)) == tag_id]
        )

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-016: spec pending, recording idempotent restore behavior")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-017: 恢复_无效ID ────────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-017", chapter="UA-2-4",
    title="恢复_无效ID",
    preconditions=[],
    steps=["使用不存在的 ID 调用恢复", "记录响应"],
    expected=["记录响应；现有数据不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_restore_invalid_id(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-017")
    ds_id = ctx["ds_id"]
    observations: dict = {}

    try:
        fake_id = 99999999
        try:
            resp = remove_tag_group_relation(api, group_id="1", tag_ids=[fake_id])
            observations["invalid_id_response"] = _safe_json(resp)
        except TptAPIError as exc:
            observations["invalid_id_error"] = {"code": exc.code, "msg": exc.msg}

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-017: spec pending, recording invalid id behavior")

    finally:
        strict_cleanup_ua2_context(api, ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-018: 恢复_已恢复位号 ─────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-018", chapter="UA-2-4",
    title="恢复_已恢复位号",
    preconditions=["位号已存在且未被删除"],
    steps=["对正常在位位号直接调用恢复", "记录响应", "确认位号状态不变"],
    expected=["记录行为；已恢复位号的 RT 不受影响"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_restore_already_active(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-018",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        pt_before = get_rt_point(api, tag_name)
        observations["rt_before"] = {k: str(v) for k, v in pt_before.items()}

        try:
            resp = remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])
            observations["restore_active_response"] = _safe_json(resp)
        except TptAPIError as exc:
            observations["restore_active_error"] = {"code": exc.code, "msg": exc.msg}

        pt_after = get_rt_point(api, tag_name)
        observations["rt_after"] = {k: str(v) for k, v in pt_after.items()}

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-018: spec pending, recording active-tag restore behavior")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-019: 恢复_混合场景 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-019", chapter="UA-2-4",
    title="恢复_混合场景",
    preconditions=["一个有效位号在回收站"],
    steps=["同批传入有效回收站 ID 和无效 ID", "记录响应", "查询位号状态"],
    expected=["记录事务规则；有效项最终状态可确认"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_restore_mixed(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-019",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        delete_tags(api, [tag_id])

        recycle_before = list_recycle_tags(api, page=1, page_size=999)
        recs_before = _recycle_records(recycle_before)
        observations["in_recycle_before"] = any(
            int(r.get("id", -1)) == tag_id for r in recs_before
        )

        fake_id = 99999999
        try:
            resp = remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id, fake_id])
            observations["mixed_restore_response"] = _safe_json(resp)
        except TptAPIError as exc:
            observations["mixed_restore_error"] = {"code": exc.code, "msg": exc.msg}

        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        recs_after = _recycle_records(recycle_after)
        observations["valid_in_recycle_after"] = any(
            int(r.get("id", -1)) == tag_id for r in recs_after
        )

        if not observations["valid_in_recycle_after"]:
            try:
                pt = get_rt_point(api, tag_name)
                observations["rt_after"] = {k: str(v) for k, v in pt.items()}
            except TptAPIError as exc:
                observations["rt_after_error"] = {"code": exc.code, "msg": exc.msg}

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-019: spec pending, recording mixed restore behavior")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── Helpers ──────────────────────────────────────────────────────────────────


def _batch_add(api, tag_infos: list[dict]) -> list[dict]:
    from tpt_api.datahub import batch_add_tags
    return batch_add_tags(api, tag_infos, conflict_strategy=0)


def _safe_json(obj: object) -> dict:
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return {"_serialize_error": str(obj)}


def _recycle_records(resp: dict) -> list[dict]:
    return (resp.get("tagInfoList") or {}).get("records") or []
