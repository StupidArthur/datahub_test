"""UA-1-5 datasource deletion cases.

Migrated from the legacy Harness specification
(ua_test_harness/test_cases/UA-1-5.md). All nine cases implemented.

Covers the disable/enable x with/without tags delete matrix, recycle-bin
residual behavior, rebuild-after-delete, and cross-datasource impact.
Behavior-recording cases (direct delete vs. fallback path) log the actual
product path via record_property while still asserting the final resource
is gone, so the test remains executable and deterministic.
"""
from __future__ import annotations

import time

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    delete_ds_info,
    delete_tags,
    delete_tags_physical,
    list_ds_info,
    list_recycle_tags,
    list_tags,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, DsSubTypes, DsTypes, TagTypes

from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists
from tests.support.endpoints import parse_mocker_endpoint
from tests.support.mocker_process import (
    find_free_port,
    start_mocker,
    stop_mocker,
    write_mocker_config,
)
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import is_ds_alive


def _setup_ds(
    api, mocker_endpoint, settings, tmp_path_factory, case_id: str,
    suffix: str = "ds", launch_mocker: bool = True,
) -> dict:
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, f"{case_id}-{suffix}")

    mocker = None
    if launch_mocker:
        tmp_dir = tmp_path_factory.mktemp(f"m_{case_id.lower()}_{suffix}")
        cfg_path = write_mocker_config(tmp_dir, port)
        mocker = start_mocker(cfg_path, port, host=parsed.host)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    change_ds_state(api, ds_id, True)
    wait_until(f"ds_alive:{ds_id}", lambda: is_ds_alive(api, ds_id), timeout=60.0)

    return {
        "ds_id": ds_id, "ds_name": ds_name, "mocker": mocker,
        "port": port, "host": parsed.host, "endpoint": endpoint,
    }


def _register_static_tag(api, ctx: dict, settings, suffix: str = "tag") -> dict:
    tag_name = unique_name(settings.test_prefix, f"UA-1-5-{suffix}")
    tag_data = add_tag(
        api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
        tag_base_name="2_smoke_static_1",
    )
    ctx["tag_id"] = int(tag_data.get("id") or tag_data.get("tagId"))
    ctx["tag_name"] = tag_name
    return ctx


def _try_delete_ds(api, ds_id: int) -> dict:
    """Attempt direct delete; return {ok, error}."""
    try:
        delete_ds_info(api, [ds_id])
        return {"ok": True}
    except TptAPIError as exc:
        return {"ok": False, "error": exc}


def _wait_ds_gone(api, ds_id: int, name: str, timeout: float = 30.0) -> None:
    def _gone():
        page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
        return not any(int(r.get("id", -1)) == ds_id for r in (page.get("records") or []))
    wait_until(f"ds_gone:{ds_id}", _gone, timeout=timeout)
    if not _gone():
        raise AssertionError(f"ds id={ds_id} name={name!r} still exists after delete")


def _teardown_ds(api, ctx: dict) -> None:
    if ctx.get("tag_id"):
        try:
            delete_tag_if_exists(api, ctx["tag_id"], ctx["tag_name"])
        except Exception:
            pass
    if ctx.get("ds_id"):
        try:
            change_ds_state(api, ctx["ds_id"], False)
        except Exception:
            pass
        delete_datasource_if_exists(api, ctx["ds_id"], ctx["ds_name"])
    if ctx.get("mocker"):
        try:
            stop_mocker(ctx["mocker"])
        except Exception:
            pass


def _recycle_tag_ids(api, tag_name: str) -> list[int]:
    page = list_recycle_tags(api, page=1, page_size=200)
    records = ((page or {}).get("tagInfoList") or {}).get("records") or []
    return [int(r["id"]) for r in records if r.get("tagName") == tag_name]


def _purge_recycle_tag(api, tag_name: str) -> None:
    for tid in _recycle_tag_ids(api, tag_name):
        try:
            delete_tags_physical(api, [tid])
        except Exception:
            pass


@pytest.mark.case(
    id="UA-1-5-01",
    chapter="UA-1-5",
    title="删除_禁用+无位号",
    preconditions=[
        "数据源已注册，无位号，已禁用(alive=false)",
    ],
    steps=[
        "delete_ds_info([id])",
        "list_ds_info",
    ],
    expected=[
        "删除成功；数据源不再出现",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_delete_disabled_no_tags(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-01", suffix="ds")
    try:
        change_ds_state(api, ctx["ds_id"], False)
        wait_until(
            f"ds_offline:{ctx['ds_id']}",
            lambda: not is_ds_alive(api, ctx["ds_id"]),
            timeout=60.0,
        )
        res = _try_delete_ds(api, ctx["ds_id"])
        assert res["ok"], f"direct delete of disabled no-tag ds failed: {res.get('error')}"
        _wait_ds_gone(api, ctx["ds_id"], ctx["ds_name"])
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-5-02",
    chapter="UA-1-5",
    title="删除_禁用+有位号",
    preconditions=[
        "数据源已禁用，下有 N 个位号",
    ],
    steps=[
        "delete_ds_info([id])",
        "list_ds_info",
        "list_tags(按原 dsId)",
    ],
    expected=[
        "验证能否直接删除；若不能，需先删位号；记录报错信息",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_delete_disabled_with_tags(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-02", suffix="ds")
    try:
        _register_static_tag(api, ctx, settings, "02")
        change_ds_state(api, ctx["ds_id"], False)
        wait_until(
            f"ds_offline:{ctx['ds_id']}",
            lambda: not is_ds_alive(api, ctx["ds_id"]),
            timeout=60.0,
        )

        res = _try_delete_ds(api, ctx["ds_id"])
        record_property("direct_delete_ok", str(res["ok"]))
        if not res["ok"]:
            record_property("direct_delete_error", res["error"].msg)
            delete_tag_if_exists(api, ctx["tag_id"], ctx["tag_name"])
            ctx["tag_id"] = None
            res2 = _try_delete_ds(api, ctx["ds_id"])
            assert res2["ok"], f"delete after tag removal failed: {res2.get('error')}"
        _wait_ds_gone(api, ctx["ds_id"], ctx["ds_name"])

        page = list_tags(api, page=1, page_size=50, data={"dsId": ctx["ds_id"]})
        assert not (page.get("records") or []), "tags should not reference a deleted ds"
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-5-03",
    chapter="UA-1-5",
    title="删除_启用+无位号",
    preconditions=[
        "数据源已启用(alive=true)，无位号",
    ],
    steps=[
        "delete_ds_info([id])",
        "list_ds_info",
    ],
    expected=[
        "删除成功或需先禁用；记录行为",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_delete_enabled_no_tags(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-03", suffix="ds")
    try:
        res = _try_delete_ds(api, ctx["ds_id"])
        record_property("direct_delete_ok", str(res["ok"]))
        if not res["ok"]:
            record_property("direct_delete_error", res["error"].msg)
            change_ds_state(api, ctx["ds_id"], False)
            res2 = _try_delete_ds(api, ctx["ds_id"])
            assert res2["ok"], f"delete after disable failed: {res2.get('error')}"
        _wait_ds_gone(api, ctx["ds_id"], ctx["ds_name"])
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-5-04",
    chapter="UA-1-5",
    title="删除_启用+有位号",
    preconditions=[
        "数据源已启用，下有 N 个位号，正常采集",
    ],
    steps=[
        "delete_ds_info([id])",
        "list_ds_info",
        "list_tags(按原 dsId)",
    ],
    expected=[
        "验证能否直接删除；若不能，需先禁用或删位号；记录报错信息",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_delete_enabled_with_tags(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-04", suffix="ds")
    try:
        _register_static_tag(api, ctx, settings, "04")
        res = _try_delete_ds(api, ctx["ds_id"])
        record_property("direct_delete_ok", str(res["ok"]))
        if not res["ok"]:
            record_property("direct_delete_error", res["error"].msg)
            try:
                change_ds_state(api, ctx["ds_id"], False)
            except TptAPIError:
                pass
            delete_tag_if_exists(api, ctx["tag_id"], ctx["tag_name"])
            ctx["tag_id"] = None
            res2 = _try_delete_ds(api, ctx["ds_id"])
            assert res2["ok"], f"delete after disable+tag removal failed: {res2.get('error')}"
        _wait_ds_gone(api, ctx["ds_id"], ctx["ds_name"])

        page = list_tags(api, page=1, page_size=50, data={"dsId": ctx["ds_id"]})
        assert not (page.get("records") or []), "tags should not reference a deleted ds"
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-5-05",
    chapter="UA-1-5",
    title="删除_位号进回收站后删除数据源",
    preconditions=[
        "数据源下有位号；位号已软删（进入回收站）",
    ],
    steps=[
        "delete_tags(软删)",
        "确认位号在回收站",
        "delete_ds_info([id])",
        "list_ds_info",
    ],
    expected=[
        "验证位号进回收站后数据源能否删除；若能删，回收站位号是否还在",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_delete_ds_after_tag_soft_delete(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-05", suffix="ds")
    try:
        _register_static_tag(api, ctx, settings, "05")
        delete_tags(api, [ctx["tag_id"]])
        wait_until(
            f"tag_in_recycle:{ctx['tag_name']}",
            lambda: len(_recycle_tag_ids(api, ctx["tag_name"])) == 1,
            timeout=30.0,
        )
        record_property("recycle_before_delete", str(len(_recycle_tag_ids(api, ctx["tag_name"]))))

        try:
            change_ds_state(api, ctx["ds_id"], False)
        except TptAPIError:
            pass
        res = _try_delete_ds(api, ctx["ds_id"])
        record_property("ds_delete_ok_with_recycle_tag", str(res["ok"]))
        if not res["ok"]:
            record_property("ds_delete_error", res["error"].msg)
            pytest.xfail(
                f"UA-1-5-05 ds cannot be deleted while recycle tag exists; "
                f"error={res['error'].msg}"
            )
        _wait_ds_gone(api, ctx["ds_id"], ctx["ds_name"])

        recycle_after = _recycle_tag_ids(api, ctx["tag_name"])
        record_property("recycle_after_delete_count", str(len(recycle_after)))
        assert len(recycle_after) == 1, (
            f"recycle tag {ctx['tag_name']} should survive ds deletion; got {len(recycle_after)}"
        )
        ctx["tag_id"] = None
    finally:
        _purge_recycle_tag(api, ctx.get("tag_name") or "__none__")
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-5-06",
    chapter="UA-1-5",
    title="删除后重建回收站位号残留",
    preconditions=[
        "UA-1-5-05 数据源已删除，回收站有残留位号",
    ],
    steps=[
        "add_ds_info(同 url)",
        "list_recycle_tags",
    ],
    expected=[
        "验证回收站中的位号是否还存在；是否关联到新数据源",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_rebuild_recycle_tag_residual(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-06", suffix="old")
    original_endpoint = ctx["endpoint"]
    try:
        _register_static_tag(api, ctx, settings, "06")
        delete_tags(api, [ctx["tag_id"]])
        wait_until(
            f"tag_in_recycle:{ctx['tag_name']}",
            lambda: len(_recycle_tag_ids(api, ctx["tag_name"])) == 1,
            timeout=30.0,
        )
        try:
            change_ds_state(api, ctx["ds_id"], False)
        except TptAPIError:
            pass
        res = _try_delete_ds(api, ctx["ds_id"])
        if not res["ok"]:
            pytest.xfail(f"UA-1-5-06 ds delete failed; cannot proceed: {res['error'].msg}")
        _wait_ds_gone(api, ctx["ds_id"], ctx["ds_name"])
        ctx["ds_id"] = None

        new_name = unique_name(settings.test_prefix, "UA-1-5-06-new")
        data = add_ds_info(
            api, ds_name=new_name,
            ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
            ds_tar_url=original_endpoint,
        )
        new_ds_id = int(data.get("id") or data.get("dsId"))
        ctx["ds_id"] = new_ds_id
        ctx["ds_name"] = new_name

        recycle_after = _recycle_tag_ids(api, ctx["tag_name"])
        record_property("recycle_after_rebuild_count", str(len(recycle_after)))
        assert len(recycle_after) == 1, (
            f"recycle tag {ctx['tag_name']} should still be in recycle after rebuild; "
            f"got {len(recycle_after)}"
        )
        ctx["tag_id"] = None
    finally:
        _purge_recycle_tag(api, ctx.get("tag_name") or "__none__")
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-5-07",
    chapter="UA-1-5",
    title="删除后同地址重建",
    preconditions=[
        "数据源已删除，mock 仍在运行",
    ],
    steps=[
        "add_ds_info(同 url)",
        "启用",
        "注册位号",
        "等待采集",
    ],
    expected=[
        "新数据源注册成功；alive=true；位号正常采集",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_rebuild_same_endpoint(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-07", suffix="old")
    original_endpoint = ctx["endpoint"]
    try:
        try:
            change_ds_state(api, ctx["ds_id"], False)
        except TptAPIError:
            pass
        res = _try_delete_ds(api, ctx["ds_id"])
        assert res["ok"], f"ds delete failed: {res.get('error')}"
        _wait_ds_gone(api, ctx["ds_id"], ctx["ds_name"])

        new_name = unique_name(settings.test_prefix, "UA-1-5-07-new")
        data = add_ds_info(
            api, ds_name=new_name,
            ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
            ds_tar_url=original_endpoint,
        )
        new_ds_id = int(data.get("id") or data.get("dsId"))
        ctx["ds_id"] = new_ds_id
        ctx["ds_name"] = new_name
        change_ds_state(api, new_ds_id, True)
        wait_until(f"ds_alive:{new_ds_id}", lambda: is_ds_alive(api, new_ds_id), timeout=60.0)

        new_tag_name = unique_name(settings.test_prefix, "UA-1-5-07-tag")
        tag_data = add_tag(
            api, tag_name=new_tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=new_ds_id, only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        ctx["tag_id"] = int(tag_data.get("id") or tag_data.get("tagId"))
        ctx["tag_name"] = new_tag_name

        def _has_rt():
            pt = get_rt_point(api, new_tag_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt:{new_tag_name}", _has_rt, timeout=60.0)
        pt = get_rt_point(api, new_tag_name)
        assert pt.get("tagValue") is not None, "rebuilt ds tag has no RT value"
        assert pt.get("quality", 0) != 0, "rebuilt ds tag quality is 0"
    finally:
        _teardown_ds(api, ctx)


@pytest.mark.case(
    id="UA-1-5-08",
    chapter="UA-1-5",
    title="删除不影响其他数据源",
    preconditions=[
        "ds-A、ds-B 均正常",
    ],
    steps=[
        "delete_ds_info([ds-A])",
        "验证 ds-B",
    ],
    expected=[
        "ds-A 被删除",
        "ds-B 不受影响、alive=true、值继续变化",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_delete_does_not_affect_other_ds(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-08", suffix="a")
    ctx_b = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-08", suffix="b")
    try:
        tag_b_name = unique_name(settings.test_prefix, "UA-1-5-08-tagb")
        tag_b = add_tag(
            api, tag_name=tag_b_name, data_type=DataTypes["INT"],
            tag_type=TagTypes["一次位号"], ds_id=ctx_b["ds_id"], only_read=True,
            tag_base_name="2_smoke_change_1",
        )
        ctx_b["tag_id"] = int(tag_b.get("id") or tag_b.get("tagId"))
        ctx_b["tag_name"] = tag_b_name

        def _b_has_rt():
            pt = get_rt_point(api, tag_b_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt_b:{tag_b_name}", _b_has_rt, timeout=60.0)
        v1 = get_rt_point(api, tag_b_name).get("tagValue")
        time.sleep(2)
        v2 = get_rt_point(api, tag_b_name).get("tagValue")
        assert v1 != v2, "ds-B tag should be changing before deletion"

        try:
            change_ds_state(api, ctx_a["ds_id"], False)
        except TptAPIError:
            pass
        res = _try_delete_ds(api, ctx_a["ds_id"])
        assert res["ok"], f"ds-A delete failed: {res.get('error')}"
        _wait_ds_gone(api, ctx_a["ds_id"], ctx_a["ds_name"])
        ctx_a["ds_id"] = None

        assert is_ds_alive(api, ctx_b["ds_id"]), "ds-B should stay alive after ds-A deleted"
        deadline = time.monotonic() + 30.0
        changed = False
        while time.monotonic() < deadline:
            v3 = get_rt_point(api, tag_b_name).get("tagValue")
            if v3 != v1 and v3 != v2:
                changed = True
                break
            time.sleep(1)
        assert changed, "ds-B tag value stopped changing after ds-A deletion"
    finally:
        _teardown_ds(api, ctx_a)
        _teardown_ds(api, ctx_b)


@pytest.mark.case(
    id="UA-1-5-09",
    chapter="UA-1-5",
    title="删除后位号 RT 状态",
    preconditions=[
        "数据源已删除，原位号仍存在（前置条件可能无法满足）",
    ],
    steps=[
        "getRTValue 读原位号",
    ],
    expected=[
        "验证 RT 返回什么：报错、quality=0、还是返回最后值（若前置条件无法满足则标记 NA）",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_rt_state_after_ds_delete(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _setup_ds(api, mocker_endpoint, settings, tmp_path_factory, "UA-1-5-09", suffix="ds")
    try:
        _register_static_tag(api, ctx, settings, "09")
        v_before = get_rt_point(api, ctx["tag_name"]).get("tagValue")
        record_property("rt_before_delete", str(v_before))

        res = _try_delete_ds(api, ctx["ds_id"])
        record_property("ds_delete_ok_with_active_tag", str(res["ok"]))
        if not res["ok"]:
            record_property("ds_delete_error", res["error"].msg)
            pytest.xfail(
                "UA-1-5-09 NA: ds cannot be deleted while active tags remain; "
                f"error={res['error'].msg}"
            )
        _wait_ds_gone(api, ctx["ds_id"], ctx["ds_name"])

        try:
            pt = get_rt_point(api, ctx["tag_name"])
            record_property("rt_after_delete", str(pt))
            pytest.xfail(
                f"UA-1-5-09 RT after ds delete is not specified; observed={pt}"
            )
        except TptAPIError as exc:
            record_property("rt_after_delete_error", exc.msg)
            pytest.xfail(
                f"UA-1-5-09 RT after ds delete raises; msg={exc.msg}"
            )
    finally:
        _teardown_ds(api, ctx)
