"""UA-2-4: 位号删除 — 物理删除."""
from __future__ import annotations

import json

import pytest

from tpt_api.datahub import (
    add_tag,
    delete_tags,
    delete_tags_physical,
    list_recycle_tags,
    list_tags,
    remove_tag_group_relation,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_cleanup import strict_cleanup_ua2_context
from tests.support.ua2_helpers import (
    find_unique_tag,
    pick_unused_nodes,
    setup_ds_and_tag,
    setup_ds_only,
)

_NODES_12 = [
    {"name": f"pd_{i}", "type": "Double", "default": float(i * 10),
     "count": 1, "change": False, "writable": False}
    for i in range(12)
]


# ── UA-2-4-020: 物理删除_单个位号 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-020", chapter="UA-2-4",
    title="物理删除_单个位号",
    preconditions=["数据源 alive", "位号已创建", "RT 可读"],
    steps=["创建位号", "delete_tags(id)", "确认在回收站", "delete_tags_physical(id)",
           "list_recycle_tags 确认不在回收站", "list_tags 确认不在活动列表"],
    expected=["物理删除后回收站与活动列表均无此位号"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_physical_delete_single(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-020",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]

    try:
        assert find_unique_tag(api, tag_name), f"tag {tag_name!r} not created"

        resp_soft = delete_tags(api, [tag_id])
        record_property("soft_delete_response", json.dumps(resp_soft, ensure_ascii=False, default=str))

        recycle_after_soft = list_recycle_tags(api, page=1, page_size=999)
        recs_after_soft = _recycle_records(recycle_after_soft)
        assert any(int(t.get("id", -1)) == tag_id for t in recs_after_soft), \
            f"UA-2-4-020: tag {tag_id} not in recycle after soft delete"

        resp_phys = delete_tags_physical(api, [tag_id])
        record_property("physical_delete_response", json.dumps(resp_phys, ensure_ascii=False, default=str))

        recycle_after_phys = list_recycle_tags(api, page=1, page_size=999)
        recs_after_phys = _recycle_records(recycle_after_phys)
        assert not any(int(t.get("id", -1)) == tag_id for t in recs_after_phys), (
            f"UA-2-4-020: tag {tag_id} still in recycle after physical delete"
        )

        active_after = find_unique_tag(api, tag_name)
        assert not active_after, (
            "UA-2-4-020 physical-deleted tag remains in active list: "
            f"id={tag_id}, tagName={tag_name!r}, record={active_after!r}"
        )

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-021: 物理删除_多个位号 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-021", chapter="UA-2-4",
    title="物理删除_多个位号",
    preconditions=["数据源 alive", "10 个位号已创建且 RT 正常"],
    steps=["batchAdd 创建 10 个位号", "批量软删除 10 个 ID", "确认 10 个均在回收站",
           "delete_tags_physical 批量物理删除", "list_recycle_tags 与 list_tags 确认全部清空"],
    expected=["物理删除后回收站与活动列表均无这些位号"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_physical_delete_multiple(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-021",
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
            tn = f"{settings.test_prefix}UA-2-4-021_b_{i}"
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

        resp_soft = delete_tags(api, created_ids)
        record_property("soft_delete_response", json.dumps(resp_soft, ensure_ascii=False, default=str))

        recycle_after_soft = list_recycle_tags(api, page=1, page_size=999)
        recs_after_soft = _recycle_records(recycle_after_soft)
        recycle_ids_after_soft = {
            int(t["id"]) for t in recs_after_soft
            if t.get("id") is not None and int(t["id"]) in created_ids
        }
        assert len(recycle_ids_after_soft) == 10, (
            f"UA-2-4-021: expected 10 tags in recycle, got {len(recycle_ids_after_soft)}"
        )

        resp_phys = delete_tags_physical(api, created_ids)
        record_property("physical_delete_response", json.dumps(resp_phys, ensure_ascii=False, default=str))

        recycle_after_phys = list_recycle_tags(api, page=1, page_size=999)
        recs_after_phys = _recycle_records(recycle_after_phys)
        leftover_recycle = set(created_ids) & {
            int(t["id"]) for t in recs_after_phys if t.get("id") is not None
        }
        assert not leftover_recycle, (
            f"UA-2-4-021: tags still in recycle after physical delete: {leftover_recycle}"
        )

        for tn in created_names:
            active_after = find_unique_tag(api, tn)
            assert not active_after, (
                "UA-2-4-021 physical-deleted tag remains in active list: "
                f"tagName={tn!r}, record={active_after!r}"
            )

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


# ── UA-2-4-022: 物理删除_重复提交 ──────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-022", chapter="UA-2-4",
    title="物理删除_重复提交",
    preconditions=["位号已软删除至回收站"],
    steps=["首次 delete_tags_physical(id)", "再次对同一 ID 调用 delete_tags_physical",
           "记录响应", "查询回收站"],
    expected=["记录幂等或错误规则；回收站无重复记录"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_physical_delete_duplicate(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-022",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        delete_tags(api, [tag_id])

        try:
            resp1 = delete_tags_physical(api, [tag_id])
            observations["first_physical_delete"] = _safe_json(resp1)
        except TptAPIError as exc:
            observations["first_physical_delete_error"] = {"code": exc.code, "msg": exc.msg}

        recycle_after_first = list_recycle_tags(api, page=1, page_size=999)
        observations["recycle_count_after_first"] = len(
            [t for t in _recycle_records(recycle_after_first)
             if int(t.get("id", -1)) == tag_id]
        )

        try:
            resp2 = delete_tags_physical(api, [tag_id])
            observations["second_physical_delete"] = _safe_json(resp2)
        except TptAPIError as exc:
            observations["second_physical_delete_error"] = {"code": exc.code, "msg": exc.msg}

        recycle_after_second = list_recycle_tags(api, page=1, page_size=999)
        observations["recycle_count_after_second"] = len(
            [t for t in _recycle_records(recycle_after_second)
             if int(t.get("id", -1)) == tag_id]
        )

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-022: spec pending, recording duplicate physical delete behavior")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-023: 物理删除_有效无效混合 ─────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-023", chapter="UA-2-4",
    title="物理删除_有效无效混合",
    preconditions=["一个有效位号已软删除至回收站"],
    steps=["同批传入有效 ID 与动态不存在的 fake_id=-1 调用 delete_tags_physical",
           "记录响应", "查询回收站与活动列表确认有效位号状态"],
    expected=["记录事务规则；有效位号最终状态可确认"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_physical_delete_mixed(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-023",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        delete_tags(api, [tag_id])

        recycle_before = list_recycle_tags(api, page=1, page_size=999)
        observations["valid_in_recycle_before"] = any(
            int(t.get("id", -1)) == tag_id for t in _recycle_records(recycle_before)
        )

        fake_id = -1
        try:
            resp = delete_tags_physical(api, [tag_id, fake_id])
            observations["mixed_response"] = _safe_json(resp)
        except TptAPIError as exc:
            observations["mixed_error"] = {"code": exc.code, "msg": exc.msg}

        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        observations["valid_in_recycle_after"] = any(
            int(t.get("id", -1)) == tag_id for t in _recycle_records(recycle_after)
        )

        active_after = find_unique_tag(api, tag_name)
        observations["valid_in_active_after"] = bool(active_after)

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-023: spec pending, recording mixed physical delete behavior")

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-024: 物理删除_删除后恢复 ───────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-024", chapter="UA-2-4",
    title="物理删除_删除后恢复",
    preconditions=["位号已物理删除"],
    steps=["delete_tags + delete_tags_physical",
           "对已物理删除的 ID 调用 remove_tag_group_relation(group_id='1') 恢复",
           "记录响应", "查询回收站与活动列表"],
    expected=["恢复失败；位号不可恢复"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_physical_delete_restore_fails(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-024",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    observations: dict = {}

    try:
        resp_soft = delete_tags(api, [tag_id])
        record_property("soft_delete_response", json.dumps(resp_soft, ensure_ascii=False, default=str))

        resp_phys = delete_tags_physical(api, [tag_id])
        record_property("physical_delete_response", json.dumps(resp_phys, ensure_ascii=False, default=str))

        try:
            resp_restore = remove_tag_group_relation(api, group_id="1", tag_ids=[tag_id])
            observations["restore_response"] = _safe_json(resp_restore)
        except TptAPIError as exc:
            observations["restore_error"] = {"code": exc.code, "msg": exc.msg}

        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        observations["in_recycle_after"] = any(
            int(t.get("id", -1)) == tag_id for t in _recycle_records(recycle_after)
        )
        active_after = find_unique_tag(api, tag_name)
        observations["in_active_after"] = bool(active_after)

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))

        assert not observations["in_recycle_after"], (
            f"UA-2-4-024: physical-deleted tag {tag_id} reappeared in recycle after restore attempt"
        )
        assert not observations["in_active_after"], (
            f"UA-2-4-024: physical-deleted tag {tag_id} reappeared in active list after restore attempt"
        )

    finally:
        strict_cleanup_ua2_context(api, tag_id=tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-025: 物理删除_同名重建 ────────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-025", chapter="UA-2-4",
    title="物理删除_同名重建",
    preconditions=["位号已物理删除"],
    steps=["delete_tags + delete_tags_physical",
           "用原 tagName 通过 add_tag 重建位号（不指定 tagBaseName）",
           "记录是否成功", "记录新位号 id"],
    expected=["记录同名重建规则"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_physical_delete_rebuild_same_name(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-025",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id, tag_id, tag_name = ctx["ds_id"], ctx["tag_id"], ctx["tag_name"]
    new_tag_id: int | None = None
    observations: dict = {}

    try:
        resp_soft = delete_tags(api, [tag_id])
        record_property("soft_delete_response", json.dumps(resp_soft, ensure_ascii=False, default=str))

        resp_phys = delete_tags_physical(api, [tag_id])
        record_property("physical_delete_response", json.dumps(resp_phys, ensure_ascii=False, default=str))

        try:
            new_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True)
            new_tag_id = int(new_data.get("id") or new_data.get("tagId"))
            observations["rebuild_success"] = True
            observations["new_tag_id"] = new_tag_id
        except TptAPIError as exc:
            observations["rebuild_success"] = False
            observations["rebuild_error"] = {"code": exc.code, "msg": exc.msg}

        record_property("observations", json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("UA-2-4-025: spec pending, recording same-name rebuild behavior")

    finally:
        cleanup_tag_id = new_tag_id if new_tag_id is not None else tag_id
        strict_cleanup_ua2_context(api, tag_id=cleanup_tag_id, tag_name=tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-026: 物理删除_同名同节点重建 ───────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-026", chapter="UA-2-4",
    title="物理删除_同名同节点重建",
    preconditions=["位号已物理删除"],
    steps=["记录原 tagName 和 tagBaseName", "delete_tags + delete_tags_physical",
           "在同 DS 上用相同 tagName 与 tagBaseName 重建位号",
           "确认新位号 RT 可读", "记录新旧 id 差异"],
    expected=["重建成功；新位号独立 id；RT 正常"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_physical_delete_rebuild_same_name_node(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-026",
                           tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"])
    ds_id = ctx["ds_id"]
    old_tag_id = ctx["tag_id"]
    old_tag_name = ctx["tag_name"]
    new_tag_id: int | None = None

    try:
        before = find_unique_tag(api, old_tag_name)
        assert before, f"UA-2-4-026: tag {old_tag_name!r} not found before delete"
        original_tag_base = before.get("tagBaseName")
        record_property("original_tag_base", original_tag_base)

        resp_soft = delete_tags(api, [old_tag_id])
        record_property("soft_delete_response", json.dumps(resp_soft, ensure_ascii=False, default=str))

        resp_phys = delete_tags_physical(api, [old_tag_id])
        record_property("physical_delete_response", json.dumps(resp_phys, ensure_ascii=False, default=str))

        new_data = add_tag(api, tag_name=old_tag_name, data_type=DataTypes["DOUBLE"],
                           tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
                           tag_base_name=original_tag_base)
        new_tag_id = int(new_data.get("id") or new_data.get("tagId"))
        record_property("new_tag_id", new_tag_id)
        record_property("old_tag_id", old_tag_id)

        assert new_tag_id != old_tag_id, (
            f"UA-2-4-026: new tag id {new_tag_id} should differ from old {old_tag_id}"
        )

        wait_until(f"rt:{old_tag_name}", lambda: (
            get_rt_point(api, old_tag_name).get("tagValue") is not None
        ), timeout=60.0)

        new_record = find_unique_tag(api, old_tag_name)
        assert new_record, f"UA-2-4-026: new tag {old_tag_name!r} not found in active list"
        assert int(new_record.get("id", -1)) == new_tag_id, (
            f"UA-2-4-026: active record id {new_record.get('id')} != new_tag_id {new_tag_id}"
        )

    finally:
        cleanup_tag_id = new_tag_id if new_tag_id is not None else old_tag_id
        strict_cleanup_ua2_context(api, tag_id=cleanup_tag_id, tag_name=old_tag_name,
                                   ds_id=ds_id, ds_name=ctx["ds_name"],
                                   mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"))


# ── UA-2-4-027: 物理删除_数据源隔离 ───────────────────────────────────────────


@pytest.mark.case(
    id="UA-2-4-027", chapter="UA-2-4",
    title="物理删除_数据源隔离",
    preconditions=["同一数据源有两个位号 A 与 B", "RT 均有效"],
    steps=["软删除 A", "物理删除 A", "确认 B 仍在活动列表", "确认 B 仍可 RT 读取"],
    expected=["A 完全消失，B 不受影响；不串源"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_physical_delete_untouched(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-027",
                        nodes=_NODES_12)
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]

    created_ids: list[int] = []
    created_names: list[str] = []
    errors: list[str] = []

    try:
        avail = pick_unused_nodes(api, ds_id, count=2, namespace_index=2)
        name_a = f"{settings.test_prefix}UA-2-4-027_a"
        name_b = f"{settings.test_prefix}UA-2-4-027_b"
        base_a = avail[0].get("tagBaseName", "")
        base_b = avail[1].get("tagBaseName", "")
        created_names.extend([name_a, name_b])

        tag_infos = [
            {
                "dsId": ds_id, "tagName": name_a,
                "tagBaseName": base_a,
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "groupId": "0", "frequency": 1, "onlyRead": True,
                "needPush": True, "isVector": True,
            },
            {
                "dsId": ds_id, "tagName": name_b,
                "tagBaseName": base_b,
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "groupId": "0", "frequency": 1, "onlyRead": True,
                "needPush": True, "isVector": True,
            },
        ]

        result = _batch_add(api, tag_infos)
        for rec in result:
            tid = rec.get("id")
            if tid:
                created_ids.append(int(tid))

        id_a = created_ids[0]
        id_b = created_ids[1]

        for tn in created_names:
            wait_until(f"rt:{tn}", lambda n=tn: (
                get_rt_point(api, n).get("tagValue") is not None
            ), timeout=30.0)

        resp_soft = delete_tags(api, [id_a])
        record_property("soft_delete_response", json.dumps(resp_soft, ensure_ascii=False, default=str))

        resp_phys = delete_tags_physical(api, [id_a])
        record_property("physical_delete_response", json.dumps(resp_phys, ensure_ascii=False, default=str))

        active_b = find_unique_tag(api, name_b)
        assert active_b, (
            "UA-2-4-027: tag B disappeared from active list after deleting A: "
            f"tagName={name_b!r}, id={id_b}"
        )
        assert int(active_b.get("id", -1)) == id_b, (
            f"UA-2-4-027: active B id {active_b.get('id')} != expected {id_b}"
        )

        wait_until(f"rt_after_delete:{name_b}", lambda: (
            get_rt_point(api, name_b).get("tagValue") is not None
        ), timeout=30.0)

        active_a = find_unique_tag(api, name_a)
        assert not active_a, (
            "UA-2-4-027: physical-deleted tag A still in active list: "
            f"tagName={name_a!r}, id={id_a}"
        )

        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        leftover = any(
            int(t.get("id", -1)) == id_a for t in _recycle_records(recycle_after)
        )
        assert not leftover, f"UA-2-4-027: tag A id={id_a} still in recycle after physical delete"

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
