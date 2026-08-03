from __future__ import annotations

import json
import time

import pytest

from tpt_api.datahub import add_tag, get_history_value
from tpt_api.types import DataTypes, TagTypes

from tests.support.naming import unique_name
from tests.support.polling import WaitTimeout, wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    find_unique_tag,
    setup_ds_and_tag,
    setup_ds_only,
    try_add_tag,
)
from tests.support.ua2_cleanup import strict_cleanup_ua2_context


def _build_context(api, settings, tmp_path_factory, mocker_endpoint, case_id: str, frequency: int | None = None) -> dict:
    kwargs = {
        "tag_base_name": "2_smoke_change_1",
        "data_type": DataTypes["INT"],
        "tag_type": TagTypes["一次位号"],
        "only_read": True,
        "namespace_index": 2,
        "cycle": 500,
    }
    if frequency is not None:
        kwargs["frequency"] = frequency
    
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        **kwargs,
    )
    return ctx


@pytest.mark.case(
    id="UA-2-1-086", chapter="UA-2-1",
    title="频率_默认值",
    preconditions=["数据源 alive=true"],
    steps=["不传 frequency 新增并查询"],
    expected=["新增成功", "frequency=10", "RT 可正常读取"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_frequency_default(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-086")
    tag_name = ctx["tag_name"]

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("frequency") == 10, f"frequency should be 10, got {rec.get('frequency')}"

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        pt = get_rt_point(api, tag_name)
        assert pt.get("quality") not in (None, 0)

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-087", chapter="UA-2-1",
    title="频率_1秒效果",
    preconditions=["Mock 值每秒变化", "新增 frequency=1"],
    steps=["运行 30s", "采集 RT 时间戳和历史记录", "统计数量与间隔"],
    expected=["记录 RT 刷新间隔", "记录历史数量和中位间隔", "记录首次采集延迟"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_frequency_1s_effect(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-087", frequency=1)
    tag_name = ctx["tag_name"]
    observations: dict = {}

    try:
        rec = find_unique_tag(api, tag_name)
        observations["config_frequency"] = rec.get("frequency")

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        start_time = time.monotonic()
        rt_timestamps = []
        
        for _ in range(30):
            pt = get_rt_point(api, tag_name)
            if pt.get("tagTime"):
                rt_timestamps.append(pt["tagTime"])
            time.sleep(1.0)

        observations["rt_sample_count"] = len(rt_timestamps)
        observations["observation_duration"] = time.monotonic() - start_time

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
        "UA-2-1-087 frequency effect semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-088", chapter="UA-2-1",
    title="频率_5秒效果",
    preconditions=["Mock 值持续变化", "新增 frequency=5"],
    steps=["运行 60s 并统计 RT、历史时间间隔"],
    expected=["输出 5 秒配置下的实测模型"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_frequency_5s_effect(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-088", frequency=5)
    tag_name = ctx["tag_name"]
    observations: dict = {}

    try:
        rec = find_unique_tag(api, tag_name)
        observations["config_frequency"] = rec.get("frequency")

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        start_time = time.monotonic()
        rt_timestamps = []
        
        for _ in range(12):
            pt = get_rt_point(api, tag_name)
            if pt.get("tagTime"):
                rt_timestamps.append(pt["tagTime"])
            time.sleep(5.0)

        observations["rt_sample_count"] = len(rt_timestamps)
        observations["observation_duration"] = time.monotonic() - start_time

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
        "UA-2-1-088 frequency effect semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-089", chapter="UA-2-1",
    title="频率_30秒效果",
    preconditions=["Mock 值持续变化", "新增 frequency=30"],
    steps=["运行 120s 并统计 RT、历史时间间隔"],
    expected=["输出 30 秒配置下的实测模型"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_frequency_30s_effect(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-089", frequency=30)
    tag_name = ctx["tag_name"]
    observations: dict = {}

    try:
        rec = find_unique_tag(api, tag_name)
        observations["config_frequency"] = rec.get("frequency")

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        start_time = time.monotonic()
        rt_timestamps = []
        
        for _ in range(4):
            pt = get_rt_point(api, tag_name)
            if pt.get("tagTime"):
                rt_timestamps.append(pt["tagTime"])
            time.sleep(30.0)

        observations["rt_sample_count"] = len(rt_timestamps)
        observations["observation_duration"] = time.monotonic() - start_time

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
        "UA-2-1-089 frequency effect semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-090", chapter="UA-2-1",
    title="频率_非法值",
    preconditions=["数据源 alive=true"],
    steps=["分别使用 0、负数、极大值新增", "记录观察", "动态 XFAIL"],
    expected=["记录校验和默认规则", "成功时查询实际保存值", "不得导致采集线程异常"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_frequency_invalid(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    observations: list[dict] = []

    test_cases = [
        ("zero", 0),
        ("negative", -1),
        ("huge", 999999999),
    ]

    for label, freq_val in test_cases:
        obs: dict = {
            "input_label": label,
            "input_frequency": freq_val,
        }

        ctx = setup_ds_only(
            api, settings, mocker_endpoint, tmp_path_factory, f"UA-2-1-090-{label}",
            namespace_index=2,
            cycle=500,
        )
        tag_name = unique_name(settings.test_prefix, f"UA-2-1-090-{label}-tag")
        tag_id = None
        try:
            result = try_add_tag(
                api, tag_name=tag_name,
                data_type=DataTypes["INT"],
                tag_type=TagTypes["一次位号"],
                ds_id=ctx["ds_id"],
                only_read=True,
                tag_base_name="2_smoke_change_1",
                frequency=freq_val,
            )
            if not result["ok"]:
                obs["verdict"] = "rejected"
                obs["error_code"] = result["error"].code
                obs["error_msg"] = result["error"].msg
            else:
                tag_id = int(result["data"].get("id") or result["data"].get("tagId"))
                rec = find_unique_tag(api, tag_name)
                obs["saved_frequency"] = rec.get("frequency")
                obs["verdict"] = "accepted"

                def _has_rt():
                    pt = get_rt_point(api, tag_name)
                    return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
                try:
                    wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)
                    pt = get_rt_point(api, tag_name)
                    obs["rt_available"] = pt.get("tagValue") is not None
                except WaitTimeout:
                    obs["rt_available"] = False
                    obs["rt_timeout"] = True
        finally:
            strict_cleanup_ua2_context(
                api,
                tag_id=tag_id, tag_name=tag_name,
                ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                mocker=ctx.get("mocker"),
                host=ctx["host"], port=ctx["port"],
            )

        observations.append(obs)
        record_property(
            f"observation_{label}",
            json.dumps(obs, ensure_ascii=False, default=str),
        )

    pytest.xfail(
        "UA-2-1-090 frequency invalid value semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
