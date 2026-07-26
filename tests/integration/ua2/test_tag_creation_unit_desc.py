from __future__ import annotations

import json

import pytest

from tpt_api.datahub import add_tag
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    find_unique_tag,
    setup_ds_and_tag,
)
from tests.support.ua2_cleanup import strict_cleanup_ua2_context


def _build_context(api, settings, tmp_path_factory, mocker_endpoint, case_id: str) -> dict:
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=True,
        namespace_index=2,
        cycle=500,
    )
    return ctx


@pytest.mark.case(
    id="UA-2-1-076", chapter="UA-2-1",
    title="单位_普通值",
    preconditions=["数据源 alive=true"],
    steps=["新增 unit='kW' 并查询", "验证实时采集"],
    expected=["新增成功", "unit='kW'", "不影响实时采集"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_unit_normal(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-076",
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=True,
        namespace_index=2,
        cycle=500,
        unit="kW",
    )
    tag_name = ctx["tag_name"]

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("unit") == "kW", f"unit mismatch: {rec.get('unit')!r} != 'kW'"

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
    id="UA-2-1-077", chapter="UA-2-1",
    title="单位_空值",
    preconditions=["数据源 alive=true"],
    steps=["不传 unit 或传空字符串", "查询值稳定一致", "验证实时采集"],
    expected=["按接口默认值保存", "查询值稳定一致", "不影响实时采集"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_unit_empty(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-077",
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=True,
        namespace_index=2,
        cycle=500,
    )
    tag_name = ctx["tag_name"]

    try:
        rec = find_unique_tag(api, tag_name)
        unit_val = rec.get("unit")
        assert unit_val is not None or unit_val == "", f"unit should be empty or default, got {unit_val!r}"

        rec2 = find_unique_tag(api, tag_name)
        assert rec2.get("unit") == unit_val, f"unit not stable: {rec2.get('unit')!r} != {unit_val!r}"

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
    id="UA-2-1-078", chapter="UA-2-1",
    title="单位_Unicode与长度",
    preconditions=["数据源 alive=true"],
    steps=["使用中文单位新增", "使用长字符串单位新增", "记录观察", "动态 XFAIL"],
    expected=["记录允许字符与最大长度", "成功时字段完整保存"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_unit_unicode_and_length(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    observations: list[dict] = []

    test_cases = [
        ("chinese_unit", "千瓦"),
        ("long_unit", "A" * 1000),
    ]

    for label, unit_val in test_cases:
        obs: dict = {
            "input_label": label,
            "input_unit": unit_val if len(unit_val) <= 100 else unit_val[:100] + "...",
            "input_length": len(unit_val),
        }

        try:
            ctx = setup_ds_and_tag(
                api, settings, mocker_endpoint, tmp_path_factory, f"UA-2-1-078-{label}",
                tag_base_name="2_smoke_static_1",
                data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"],
                only_read=True,
                namespace_index=2,
                cycle=500,
                unit=unit_val,
            )
            tag_name = ctx["tag_name"]

            try:
                rec = find_unique_tag(api, tag_name)
                saved_unit = rec.get("unit")
                obs["saved_unit"] = saved_unit if saved_unit and len(saved_unit) <= 100 else (saved_unit[:100] + "..." if saved_unit else saved_unit)
                obs["saved_length"] = len(saved_unit) if saved_unit else 0
                obs["matches"] = saved_unit == unit_val
                obs["verdict"] = "accepted"
            finally:
                strict_cleanup_ua2_context(
                    api,
                    tag_id=ctx["tag_id"], tag_name=tag_name,
                    ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                    mocker=ctx.get("mocker"),
                    host=ctx["host"], port=ctx["port"],
                )
        except TptAPIError as exc:
            obs["verdict"] = "rejected"
            obs["error_code"] = exc.code
            obs["error_msg"] = exc.msg

        observations.append(obs)
        record_property(
            f"observation_{label}",
            json.dumps(obs, ensure_ascii=False, default=str),
        )

    pytest.xfail(
        "UA-2-1-078 Unit Unicode and length semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-079", chapter="UA-2-1",
    title="描述_普通值",
    preconditions=["数据源 alive=true"],
    steps=["新增 tagDesc='test desc'", "查询记录"],
    expected=["查询记录 tagDesc='test desc'"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_desc_normal(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-079",
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=True,
        namespace_index=2,
        cycle=500,
        tag_desc="test desc",
    )
    tag_name = ctx["tag_name"]

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("tagDesc") == "test desc", f"tagDesc mismatch: {rec.get('tagDesc')!r} != 'test desc'"

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-080", chapter="UA-2-1",
    title="描述_默认值",
    preconditions=["数据源 alive=true"],
    steps=["不传 tagDesc 新增", "查询记录"],
    expected=["tagDesc='{tagName} 描述'"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_desc_default(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-080",
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=True,
        namespace_index=2,
        cycle=500,
    )
    tag_name = ctx["tag_name"]

    try:
        rec = find_unique_tag(api, tag_name)
        expected_desc = f"{tag_name} 描述"
        actual_desc = rec.get("tagDesc")
        assert actual_desc == expected_desc, f"tagDesc mismatch: {actual_desc!r} != {expected_desc!r}"

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-081", chapter="UA-2-1",
    title="描述_Unicode与长度",
    preconditions=["数据源 alive=true"],
    steps=["使用中文描述新增", "使用换行描述新增", "使用长描述新增", "记录观察", "动态 XFAIL"],
    expected=["记录字符和长度规则", "成功时内容完整保存"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_desc_unicode_and_length(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    observations: list[dict] = []

    test_cases = [
        ("chinese_desc", "这是一个测试描述"),
        ("newline_desc", "line1\nline2\nline3"),
        ("long_desc", "A" * 1000),
    ]

    for label, desc_val in test_cases:
        obs: dict = {
            "input_label": label,
            "input_desc": desc_val if len(desc_val) <= 100 else desc_val[:100] + "...",
            "input_length": len(desc_val),
        }

        try:
            ctx = setup_ds_and_tag(
                api, settings, mocker_endpoint, tmp_path_factory, f"UA-2-1-081-{label}",
                tag_base_name="2_smoke_static_1",
                data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"],
                only_read=True,
                namespace_index=2,
                cycle=500,
                tag_desc=desc_val,
            )
            tag_name = ctx["tag_name"]

            try:
                rec = find_unique_tag(api, tag_name)
                saved_desc = rec.get("tagDesc")
                obs["saved_desc"] = saved_desc if saved_desc and len(saved_desc) <= 100 else (saved_desc[:100] + "..." if saved_desc else saved_desc)
                obs["saved_length"] = len(saved_desc) if saved_desc else 0
                obs["matches"] = saved_desc == desc_val
                obs["verdict"] = "accepted"
            finally:
                strict_cleanup_ua2_context(
                    api,
                    tag_id=ctx["tag_id"], tag_name=tag_name,
                    ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                    mocker=ctx.get("mocker"),
                    host=ctx["host"], port=ctx["port"],
                )
        except TptAPIError as exc:
            obs["verdict"] = "rejected"
            obs["error_code"] = exc.code
            obs["error_msg"] = exc.msg

        observations.append(obs)
        record_property(
            f"observation_{label}",
            json.dumps(obs, ensure_ascii=False, default=str),
        )

    pytest.xfail(
        "UA-2-1-081 Description Unicode and length semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
