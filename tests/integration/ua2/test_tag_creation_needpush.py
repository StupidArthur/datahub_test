from __future__ import annotations

import json
import time

import pytest

from tpt_api.types import DataTypes, TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    find_unique_tag,
    setup_ds_and_tag,
)
from tests.support.ua2_cleanup import strict_cleanup_ua2_context


def _build_context(api, settings, tmp_path_factory, mocker_endpoint, case_id: str, need_push: bool | None = None) -> dict:
    kwargs = {
        "tag_base_name": "2_smoke_change_1",
        "data_type": DataTypes["INT"],
        "tag_type": TagTypes["一次位号"],
        "only_read": True,
        "namespace_index": 2,
        "cycle": 500,
    }
    if need_push is not None:
        kwargs["need_push"] = need_push
    
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        **kwargs,
    )
    return ctx


@pytest.mark.case(
    id="UA-2-1-098", chapter="UA-2-1",
    title="实时推送_默认值",
    preconditions=["数据源 alive=true"],
    steps=["不传 needPush 新增并查询"],
    expected=["needPush=true"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_needpush_default(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-098")
    tag_name = ctx["tag_name"]

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("needPush") is True, f"needPush should be True, got {rec.get('needPush')}"

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-099", chapter="UA-2-1",
    title="实时推送_关闭字段",
    preconditions=["数据源 alive=true"],
    steps=["新增 needPush=false 并查询"],
    expected=["needPush=false"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_needpush_false(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-099", need_push=False)
    tag_name = ctx["tag_name"]

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("needPush") is False, f"needPush should be False, got {rec.get('needPush')}"

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-100", chapter="UA-2-1",
    title="实时推送_关闭后RT行为",
    preconditions=["needPush=false", "Mock 值持续变化"],
    steps=["连续读取 RT 与质量", "记录观察", "动态 XFAIL"],
    expected=["记录 RT 是否继续更新、更新周期和质量变化"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_needpush_false_rt_behavior(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-100", need_push=False)
    tag_name = ctx["tag_name"]
    observations: dict = {}

    try:
        rec = find_unique_tag(api, tag_name)
        observations["config_needPush"] = rec.get("needPush")

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        start_time = time.monotonic()
        rt_samples = []
        
        for _ in range(10):
            pt = get_rt_point(api, tag_name)
            rt_samples.append({
                "tagValue": pt.get("tagValue"),
                "quality": pt.get("quality"),
                "tagTime": pt.get("tagTime"),
            })
            time.sleep(1.0)

        observations["rt_sample_count"] = len(rt_samples)
        observations["observation_duration"] = time.monotonic() - start_time
        observations["rt_values_change"] = len(set(str(s["tagValue"]) for s in rt_samples)) > 1

        record_property(
            "observation",
            json.dumps(observations, ensure_ascii=False, default=str),
        )

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        "UA-2-1-100 needPush=false RT behavior semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-101", chapter="UA-2-1",
    title="实时推送_关闭后历史行为",
    preconditions=["needPush=false", "Mock 值持续变化"],
    steps=["运行 30s 后查询历史", "记录观察", "动态 XFAIL"],
    expected=["记录是否落历史、数量和时间间隔"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_needpush_false_history_behavior(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-101", need_push=False)
    tag_name = ctx["tag_name"]
    observations: dict = {}

    try:
        rec = find_unique_tag(api, tag_name)
        observations["config_needPush"] = rec.get("needPush")

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        time.sleep(30.0)

        observations["observation_duration"] = 30.0
        observations["note"] = "History query not implemented in this test"

        record_property(
            "observation",
            json.dumps(observations, ensure_ascii=False, default=str),
        )

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        "UA-2-1-101 needPush=false history behavior semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
