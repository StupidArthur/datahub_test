"""UA-2-4 补充观察：跨数据源恢复、无效 ID、活跃位号.

NON-CANONICAL observation-only tests (no ``@pytest.mark.case``).
These were previously located in ``test_tag_delete_restore.py`` as
canonical cases (UA-2-4-015/017/018) and are now tracked as
``spec_pending`` observations. They execute the same product path but
record observations via ``record_property`` and end with
``pytest.xfail`` rather than hard assertions.
"""
from __future__ import annotations

import json

import pytest

from tpt_api.datahub import (
    delete_tags,
    list_recycle_tags,
    remove_tag_group_relation,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_cleanup import strict_cleanup_ua2_context
from tests.support.ua2_helpers import (
    setup_ds_and_tag,
    setup_ds_only,
)


# ── 观察：跨数据源批量恢复 ──────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_observe_restore_cross_ds(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    """Observation: 两个独立 DS 各一个位号，批量软删除后批量恢复。

    观察每个位号是否各自回到原 DS（不串源），以及 RT 是否可读。
    """
    ctx_a = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory,
        "UA-2-4-sup-cross-ds-A",
        tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"],
    )
    ctx_b = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory,
        "UA-2-4-sup-cross-ds-B",
        tag_base_name="2_smoke_change_1", data_type=DataTypes["INT"],
    )
    observations: dict = {}
    errors: list[str] = []

    try:
        # 软删除两个位号
        delete_tags(api, [ctx_a["tag_id"], ctx_b["tag_id"]])

        # 确认两个位号都在回收站
        recycle_before = list_recycle_tags(api, page=1, page_size=999)
        recs_before = _recycle_records(recycle_before)
        for ctx, label in [(ctx_a, "a"), (ctx_b, "b")]:
            observations[f"tag_{label}_in_recycle_before"] = any(
                int(r.get("id", -1)) == ctx["tag_id"] for r in recs_before
            )

        # 批量恢复
        try:
            resp = remove_tag_group_relation(
                api, group_id="1",
                tag_ids=[ctx_a["tag_id"], ctx_b["tag_id"]],
            )
            observations["restore_response"] = _safe_json(resp)
        except TptAPIError as exc:
            observations["restore_error"] = {"code": exc.code, "msg": exc.msg}

        # 确认两个回收站均无这些位号
        recycle_after = list_recycle_tags(api, page=1, page_size=999)
        recs_after = _recycle_records(recycle_after)
        for ctx, label in [(ctx_a, "a"), (ctx_b, "b")]:
            observations[f"tag_{label}_in_recycle_after"] = any(
                int(r.get("id", -1)) == ctx["tag_id"] for r in recs_after
            )

        # 确认 RT 可读
        for ctx, label in [(ctx_a, "a"), (ctx_b, "b")]:
            tag_name = ctx["tag_name"]
            try:
                wait_until(f"rt:{tag_name}", lambda n=tag_name: (
                    get_rt_point(api, n).get("tagValue") is not None
                ), timeout=30.0)
                observations[f"tag_{label}_rt_restored"] = str(
                    get_rt_point(api, tag_name).get("tagValue")
                )
            except Exception as exc:
                observations[f"tag_{label}_rt_restore_error"] = str(exc)

        record_property("observations",
                        json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("observation: cross-DS batch restore behavior")

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


# ── 观察：恢复_无效ID ────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_observe_restore_invalid_id(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    """Observation: 对不存在的位号 ID 调用恢复，记录产品行为。"""
    ctx = setup_ds_only(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-4-sup-invalid-id",
    )
    observations: dict = {}

    try:
        fake_id = -1
        try:
            resp = remove_tag_group_relation(api, group_id="1", tag_ids=[fake_id])
            observations["invalid_id_response"] = _safe_json(resp)
        except TptAPIError as exc:
            observations["invalid_id_error"] = {"code": exc.code, "msg": exc.msg}

        record_property("observations",
                        json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("observation: invalid ID restore behavior")

    finally:
        strict_cleanup_ua2_context(
            api, ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"),
        )


# ── 观察：恢复_已恢复（活跃）位号 ──────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_observe_restore_already_active(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    """Observation: 对未被删除的活跃位号直接调用恢复，记录响应与 RT 变化。"""
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory,
        "UA-2-4-sup-already-active",
        tag_base_name="2_smoke_static_1", data_type=DataTypes["DOUBLE"],
    )
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

        record_property("observations",
                        json.dumps(observations, ensure_ascii=False, default=str))
        pytest.xfail("observation: active-tag restore behavior")

    finally:
        strict_cleanup_ua2_context(
            api, tag_id=tag_id, tag_name=tag_name,
            ds_id=ds_id, ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"), host=ctx.get("host"), port=ctx.get("port"),
        )


# ── Helpers ──────────────────────────────────────────────────────────────


def _safe_json(obj: object) -> dict:
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        return {"_serialize_error": str(obj)}


def _recycle_records(resp: dict) -> list[dict]:
    return (resp.get("tagInfoList") or {}).get("records") or []