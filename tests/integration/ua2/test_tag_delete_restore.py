"""UA-2-4: 位号删除 — 删除影响与恢复."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
import time

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

_NODES_15 = [
    {"name": f"rr_{i}", "type": "Double", "default": float(i * 10),
     "count": 1, "change": False, "writable": False}
    for i in range(15)
]


# ── UA-2-4-010: 删除影响_源端节点 ────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-010", chapter="UA-2-4",
    title="删除影响_源端节点",
    preconditions=["数据源 alive", "位号已创建", "RT 可读", "OPC UA 源值可读"],
    steps=["记录删除前源值", "软删除（不恢复）", "重新读取 OPC UA 源值"],
    expected=["源节点连接正常，读值不受删除影响"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_delete_impact_source_node(api, settings, tmp_path_factory, mocker_endpoint, record_property):
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

        source_after = opcua_read_sync(endpoint, "smoke_static_1", namespace_index=2)
        record_property("source_after", source_after)

        assert source_after == source_before, (
            "UA-2-4-010 OPC UA source value changed after soft delete: "
            f"before={source_before!r}, after={source_after!r}"
        )

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-011: 删除影响_新增历史 ────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-011", chapter="UA-2-4",
    title="删除影响_新增历史",
    preconditions=["数据源 alive", "位号已创建并产生过历史数据"],
    steps=["记录删除前历史样本数", "软删除", "用窄时间窗口查询历史",
           "记录观察"],
    expected=["观察删除后位号历史是否仍可查（spec_pending）"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_delete_impact_history_new(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-011",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        observations["rt_before"] = str(get_rt_point(api, tag_name).get("tagValue"))

        delete_tags(api, [tag_id])

        end_dt = datetime.utcnow()
        beg_dt = end_dt - timedelta(minutes=5)
        beg = beg_dt.strftime("%Y-%m-%d %H:%M:%S")
        end = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        observations["window"] = {"beg": beg, "end": end}

        try:
            resp = get_history_value(api, [tag_name], beg_time=beg, end_time=end)
            observations["history_after_delete"] = _safe_json(resp.get(tag_name))
        except (TptAPIError, TypeError) as exc:
            observations["history_after_delete_error"] = str(exc)

        try:
            write_resp = write_tag_values(api, {tag_name: 200.0})
            observations["write_after_delete"] = _safe_json(write_resp)
        except TptAPIError as exc:
            observations["write_after_delete_error"] = {"code": exc.code, "msg": exc.msg}

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-011: spec pending, recording delete-impact history observation")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-012: 删除影响_既有历史 ────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-012", chapter="UA-2-4",
    title="删除影响_既有历史",
    preconditions=["位号已有历史数据"],
    steps=["计算运行时滑动时间窗口", "查询删除前历史", "软删除",
           "用相同窗口查询历史", "记录观察"],
    expected=["观察删除后既有历史数据是否丢失（spec_pending）"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_delete_impact_history_existing(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-012",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        end_dt = datetime.utcnow()
        beg_dt = end_dt - timedelta(hours=1)
        beg = beg_dt.strftime("%Y-%m-%d %H:%M:%S")
        end = end_dt.strftime("%Y-%m-%d %H:%M:%S")
        observations["window"] = {"beg": beg, "end": end}

        try:
            resp = get_history_value(api, [tag_name], beg_time=beg, end_time=end)
            history_before = _safe_json(resp.get(tag_name))
            observations["history_before"] = history_before
            observations["count_before"] = (
                history_before.get("total", 0) if isinstance(history_before, dict) else 0
            )
        except (TptAPIError, TypeError) as exc:
            observations["history_before_error"] = str(exc)

        delete_tags(api, [tag_id])

        try:
            resp = get_history_value(api, [tag_name], beg_time=beg, end_time=end)
            history_after = _safe_json(resp.get(tag_name))
            observations["history_after"] = history_after
            observations["count_after"] = (
                history_after.get("total", 0) if isinstance(history_after, dict) else 0
            )
        except (TptAPIError, TypeError) as exc:
            observations["history_after_error"] = str(exc)

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-012: spec pending, recording delete-impact existing-history observation")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-013: 恢复_单个位号 ────────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-013", chapter="UA-2-4",
    title="恢复_单个位号",
    preconditions=["一个位号已在回收站"],
    steps=["快照删除前身份", "软删除", "确认回收站中位号",
           "remove_tag_group_relation(group_id=1, [tag_id])", "确认回收站中无该位号",
           "确认 RT 正常", "比对身份"],
    expected=["位号离开回收站", "RT 可读", "tagName/dsId/dataType 不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_restore_single_tag(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-013",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]

    try:
        before = find_unique_tag(api, tag_name)
        assert before, f"tag {tag_name!r} not found before delete"

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

        after = find_unique_tag(api, tag_name)
        assert after, f"tag {tag_name!r} not found after restore"
        assert after.get("tagName") == before.get("tagName"), \
            f"tagName changed: before={before.get('tagName')!r} after={after.get('tagName')!r}"
        assert int(after.get("dsId", -1)) == int(before.get("dsId", -1)), \
            f"dsId changed: before={before.get('dsId')!r} after={after.get('dsId')!r}"
        assert int(after.get("dataType", -1)) == int(before.get("dataType", -1)), \
            f"dataType changed: before={before.get('dataType')!r} after={after.get('dataType')!r}"

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-014: 恢复_多个位号 ────────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-014", chapter="UA-2-4",
    title="恢复_多个位号",
    preconditions=["11 个位号已创建且 RT 正常"],
    steps=["batchAdd 创建 11 个位号", "批量软删除 11 个", "确认回收站有 11 条",
           "恢复 10 个，留 1 个作控制", "确认回收站仅剩 1 个控制位号",
           "确认 10 个已恢复标签 RT 正常"],
    expected=["10 个位号离开回收站", "控制位号仍在回收站", "10 个 RT 可读"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_restore_multiple_tags(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-014",
                        nodes=_NODES_15)
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]

    created_ids: list[int] = []
    created_names: list[str] = []
    errors: list[str] = []

    try:
        avail = pick_unused_nodes(api, ds_id, count=11, namespace_index=2)
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

        assert len(created_ids) == 11, \
            f"expected 11 tags created, got {len(created_ids)}"

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
        assert len(recycle_ids_before) == 11, \
            f"expected 11 tags in recycle, got {len(recycle_ids_before)}"

        restore_ids = created_ids[1:]
        control_id = created_ids[0]

        resp = remove_tag_group_relation(api, group_id="1", tag_ids=restore_ids)
        record_property("restore_response", json.dumps(resp, ensure_ascii=False, default=str))

        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        recs_after = _recycle_records(recycle_after)
        recycle_ids_after = {
            int(r["id"]) for r in recs_after
            if r.get("id") is not None and int(r["id"]) in created_ids
        }
        assert recycle_ids_after == {control_id}, (
            f"expected only control id={control_id} in recycle, got {recycle_ids_after}"
        )

        for tn in created_names[1:]:
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


# ── UA-2-4-015: 恢复_身份配置保持 ────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-015", chapter="UA-2-4",
    title="恢复_身份配置保持",
    preconditions=["位号已配置 unit/tagDesc/tagType"],
    steps=["快照完整身份与配置", "软删除", "恢复",
           "查询位号", "比对 id/tagName/tagBaseName/dsId/dataType/unit/tagDesc/tagType"],
    expected=["身份与配置字段完全保持"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_restore_identity_kept(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-015",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"],
                           unit="kW", tag_desc="UA-2-4-15 identity kept")
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        before = find_unique_tag(api, tag_name)
        assert before, f"tag {tag_name!r} not found before delete"

        delete_tags(api, [tag_id])

        resp = remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])
        record_property("restore_response", json.dumps(resp, ensure_ascii=False, default=str))

        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        after = find_unique_tag(api, tag_name)
        assert after, f"tag {tag_name!r} not found after restore"

        for field in ("id", "tagName", "tagBaseName", "dsId", "dataType",
                      "unit", "tagDesc", "tagType"):
            assert before.get(field) == after.get(field), (
                f"UA-2-4-015 field {field!r} changed after restore: "
                f"before={before.get(field)!r} after={after.get(field)!r}"
            )

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-016: 恢复_RT质量闭环 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-016", chapter="UA-2-4",
    title="恢复_RT质量闭环",
    preconditions=["位号已创建", "RT 有效", "OPC UA 源值可读"],
    steps=["软删除", "恢复", "query_tags_with_quality 质量非 0",
           "RT 取值有效", "OPC UA 源值可读"],
    expected=["恢复后 RT、质量、源端都重新生效"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_restore_rt_quality_loop(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-016",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        delete_tags(api, [tag_id])

        resp = remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])
        record_property("restore_response", json.dumps(resp, ensure_ascii=False, default=str))

        def _quality_valid() -> bool:
            qwq = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
            recs = (qwq.get("tagInfoList") or {}).get("records") or []
            return any(r.get("tagName") == tag_name and r.get("quality") not in (None, 0)
                       for r in recs)

        wait_until(f"qwq:{tag_name}", _quality_valid, timeout=30.0)

        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        source = opcua_read_sync(endpoint, "smoke_static_1", namespace_index=2)
        record_property("source_after_restore", source)

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-017: 恢复_返回false但生效 ─────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-017", chapter="UA-2-4",
    title="恢复_返回false但生效",
    preconditions=["位号已在回收站"],
    steps=["软删除", "确认回收站", "remove_tag_group_relation 调用",
           "无论返回 false/true 均验证回收站已清", "RT 验证"],
    expected=["API 可能返回 false，但实际生效"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_restore_false_but_works(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-017",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]

    try:
        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

        delete_tags(api, [tag_id])

        recycle_before = list_recycle_tags(api, page=1, page_size=999)
        recs_before = _recycle_records(recycle_before)
        assert any(int(r.get("id", -1)) == tag_id for r in recs_before), \
            f"tag {tag_id} not in recycle before restore"

        resp = remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])
        record_property("restore_response", _safe_json(resp))

        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        recs_after = _recycle_records(recycle_after)
        leftover = [int(r["id"]) for r in recs_after
                    if r.get("id") is not None and int(r["id"]) == tag_id]
        assert not leftover, \
            f"tag {tag_id} still in recycle after restore: {leftover}"

        wait_until(f"rt:{tag_name}", lambda: (
            get_rt_point(api, tag_name).get("tagValue") is not None
        ), timeout=30.0)

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-018: 恢复_重复提交 ────────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-018", chapter="UA-2-4",
    title="恢复_重复提交",
    preconditions=["一个位号已在回收站"],
    steps=["首次恢复", "再次恢复同一 ID", "查询回收站"],
    expected=["二次操作幂等；记录不重复（spec_pending）"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_restore_duplicate(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-018",
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
        pytest.xfail("UA-2-4-018: spec pending, recording idempotent restore behavior")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-019: 恢复_有效无效混合 ────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-019", chapter="UA-2-4",
    title="恢复_有效无效混合",
    preconditions=["一个有效位号在回收站"],
    steps=["同批传入有效回收站 ID 和动态不存在的 ID", "记录响应", "查询位号状态"],
    expected=["记录事务规则；有效项最终状态可确认（spec_pending）"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_restore_mixed_valid_invalid(api, settings, tmp_path_factory, mocker_endpoint, record_property):
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

        fake_id = -1
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
