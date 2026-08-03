from __future__ import annotations

import json

import pytest

from tpt_api.datahub import write_tag_values
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    assert_write_accepted,
    find_unique_tag,
    opcua_read_sync,
    opcua_write_sync,
    setup_ds_and_tag,
    setup_ds_only,
    try_add_tag,
)
from tests.support.ua2_rt_assertions import parse_required_timestamp
from tests.support.ua2_cleanup import strict_cleanup_ua2_context

from asyncua import ua


def _build_context(api, settings, tmp_path_factory, mocker_endpoint, case_id: str, **kwargs) -> dict:
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=True,
        namespace_index=2,
        cycle=500,
        **kwargs,
    )
    return ctx


@pytest.mark.case(
    id="UA-2-1-091", chapter="UA-2-1",
    title="量程_字段保存",
    preconditions=["数值型节点"],
    steps=["新增 hiEU=100, loEU=0 并查询"],
    expected=["hiEU=100、loEU=0 精确保存", "不影响范围内值采集"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_range_field_save(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-091", hi_eu=100.0, lo_eu=0.0)
    tag_name = ctx["tag_name"]

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("hiEU") == 100.0, f"hiEU mismatch: {rec.get('hiEU')} != 100.0"
        assert rec.get("loEU") == 0.0, f"loEU mismatch: {rec.get('loEU')} != 0.0"

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
    id="UA-2-1-092", chapter="UA-2-1",
    title="量程_范围内写值",
    preconditions=["可写数值位号", "hiEU=100, loEU=0"],
    steps=["写入 50 并闭环验证"],
    expected=["源端和 RT 均为 50", "质量有效"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_range_within_write(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-092",
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        namespace_index=2,
        cycle=500,
        hi_eu=100.0,
        lo_eu=0.0,
    )
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    node_name = "smoke_static_1"
    ns = 2

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("hiEU") == 100.0
        assert rec.get("loEU") == 0.0

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        original_src = opcua_read_sync(endpoint, node_name, namespace_index=ns)

        value = 50.0
        resp = write_tag_values(api, {tag_name: value})
        assert_write_accepted(resp, tag_name)

        def _source_matches():
            src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
            return isinstance(src, (int, float)) and not isinstance(src, bool) and abs(src - value) < 1e-6
        wait_until(f"source_sync:{tag_name}", _source_matches, timeout=30.0, interval=0.5)

        def _rt_matches():
            pt = get_rt_point(api, tag_name)
            tv = pt.get("tagValue")
            return tv is not None and isinstance(tv, (int, float)) and not isinstance(tv, bool) and abs(tv - value) < 1e-6
        wait_until(f"rt_sync:{tag_name}", _rt_matches, timeout=30.0, interval=0.5)

        src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
        assert abs(src - value) < 1e-6, f"source mismatch: {src} != {value}"

        pt = get_rt_point(api, tag_name)
        assert abs(pt["tagValue"] - value) < 1e-6, f"RT mismatch: {pt['tagValue']} != {value}"
        assert pt.get("quality") not in (None, 0)
        parse_required_timestamp(pt["tagTime"])

    finally:
        opcua_write_sync(endpoint, node_name, original_src, namespace_index=ns, variant_type=ua.VariantType.Double)
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-093", chapter="UA-2-1",
    title="量程_超范围写值",
    preconditions=["可写数值位号", "hiEU=100, loEU=0"],
    steps=["分别写 150、-50", "记录观察", "动态 XFAIL"],
    expected=["记录量程仅作元数据、拒绝或裁剪的实际规则", "源端与 RT 必须一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_range_out_of_range_write(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-093",
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        namespace_index=2,
        cycle=500,
        hi_eu=100.0,
        lo_eu=0.0,
    )
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    node_name = "smoke_static_1"
    ns = 2
    observations: list[dict] = []

    try:
        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        original_src = opcua_read_sync(endpoint, node_name, namespace_index=ns)

        test_values = [150.0, -50.0]

        for value in test_values:
            opcua_write_sync(endpoint, node_name, original_src, namespace_index=ns, variant_type=ua.VariantType.Double)

            obs: dict = {
                "input_value": value,
            }

            try:
                resp = write_tag_values(api, {tag_name: value})
                obs["write_accepted"] = tag_name in (resp.get("tagNames") or [])
                obs["write_response"] = resp
            except TptAPIError as exc:
                obs["write_accepted"] = False
                obs["write_error"] = {"code": exc.code, "msg": exc.msg}

            if obs["write_accepted"]:
                def _source_matches():
                    src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
                    return isinstance(src, (int, float)) and not isinstance(src, bool)
                wait_until(f"source_sync:{tag_name}:{value}", _source_matches, timeout=30.0, interval=0.5)

                src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
                pt = get_rt_point(api, tag_name)
                obs["source_final"] = str(src)
                obs["rt_final"] = str(pt.get("tagValue"))
                obs["source_rt_match"] = abs(src - pt.get("tagValue", 0)) < 1e-6 if pt.get("tagValue") is not None else False

            observations.append(obs)
            record_property(
                f"observation_{value}",
                json.dumps(obs, ensure_ascii=False, default=str),
            )

    finally:
        opcua_write_sync(endpoint, node_name, original_src, namespace_index=ns, variant_type=ua.VariantType.Double)
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        "UA-2-1-093 range out-of-range write semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-094", chapter="UA-2-1",
    title="量程_配置非法",
    preconditions=["数值型节点"],
    steps=["分别新增 hiEU=loEU、hiEU<loEU、仅传一个边界", "记录观察", "动态 XFAIL"],
    expected=["记录校验规则", "成功时字段值必须与请求一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_range_invalid_config(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    observations: list[dict] = []

    test_cases = [
        ("equal", {"hi_eu": 100.0, "lo_eu": 100.0}),
        ("inverted", {"hi_eu": 0.0, "lo_eu": 100.0}),
        ("only_hi", {"hi_eu": 100.0}),
        ("only_lo", {"lo_eu": 0.0}),
    ]

    for label, kwargs in test_cases:
        obs: dict = {
            "input_label": label,
            "input_kwargs": kwargs,
        }

        ctx = setup_ds_only(
            api, settings, mocker_endpoint, tmp_path_factory, f"UA-2-1-094-{label}",
            namespace_index=2,
            cycle=500,
        )
        tag_name = unique_name(settings.test_prefix, f"UA-2-1-094-{label}-tag")
        tag_id = None
        try:
            result = try_add_tag(
                api, tag_name=tag_name,
                data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"],
                ds_id=ctx["ds_id"],
                only_read=True,
                tag_base_name="2_smoke_static_1",
                **kwargs,
            )
            if not result["ok"]:
                obs["verdict"] = "rejected"
                obs["error_code"] = result["error"].code
                obs["error_msg"] = result["error"].msg
            else:
                tag_id = int(result["data"].get("id") or result["data"].get("tagId"))
                rec = find_unique_tag(api, tag_name)
                obs["saved_hiEU"] = rec.get("hiEU")
                obs["saved_loEU"] = rec.get("loEU")
                obs["verdict"] = "accepted"
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
        "UA-2-1-094 range invalid config semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-095", chapter="UA-2-1",
    title="报警限_合法递增",
    preconditions=["数值型节点"],
    steps=["新增 低低低=0, 低低=5, 低=10, 高=80, 高高=90, 高高高=100"],
    expected=["新增成功", "六个字段精确保存", "字段顺序关系正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_alarm_limits_legal(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_context(
        api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-095",
        limit_down_down_down=0.0,
        limit_down_down=5.0,
        limit_down=10.0,
        limit_up=80.0,
        limit_up_up=90.0,
        limit_up_up_up=100.0,
    )
    tag_name = ctx["tag_name"]

    try:
        rec = find_unique_tag(api, tag_name)
        assert float(rec.get("limitDownDownDown")) == 0.0
        assert float(rec.get("limitDownDown")) == 5.0
        assert float(rec.get("limitDown")) == 10.0
        assert float(rec.get("limitUp")) == 80.0
        assert float(rec.get("limitUpUp")) == 90.0
        assert float(rec.get("limitUpUpUp")) == 100.0

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-096", chapter="UA-2-1",
    title="报警限_顺序非法",
    preconditions=["数值型节点"],
    steps=["提交低限逆序或高限逆序配置", "记录观察", "动态 XFAIL"],
    expected=["记录拒绝或接受规则", "若接受，字段不得被静默改写"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_alarm_limits_invalid_order(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    observations: list[dict] = []

    test_cases = [
        ("low_inverted", {"limit_down_down_down": 10.0, "limit_down_down": 5.0, "limit_down": 0.0}),
        ("high_inverted", {"limit_up": 100.0, "limit_up_up": 90.0, "limit_up_up_up": 80.0}),
    ]

    for label, kwargs in test_cases:
        obs: dict = {
            "input_label": label,
            "input_kwargs": kwargs,
        }

        ctx = setup_ds_only(
            api, settings, mocker_endpoint, tmp_path_factory, f"UA-2-1-096-{label}",
            namespace_index=2,
            cycle=500,
        )
        tag_name = unique_name(settings.test_prefix, f"UA-2-1-096-{label}-tag")
        tag_id = None
        try:
            result = try_add_tag(
                api, tag_name=tag_name,
                data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"],
                ds_id=ctx["ds_id"],
                only_read=True,
                tag_base_name="2_smoke_static_1",
                **kwargs,
            )
            if not result["ok"]:
                obs["verdict"] = "rejected"
                obs["error_code"] = result["error"].code
                obs["error_msg"] = result["error"].msg
            else:
                tag_id = int(result["data"].get("id") or result["data"].get("tagId"))
                rec = find_unique_tag(api, tag_name)
                obs["saved_fields"] = {k: rec.get(k) for k in kwargs.keys()}
                obs["verdict"] = "accepted"
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
        "UA-2-1-096 alarm limits invalid order semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-097", chapter="UA-2-1",
    title="报警限_超出量程",
    preconditions=["hiEU=50, loEU=0"],
    steps=["分别提交 limitUp=80、limitDown=-20", "记录观察", "动态 XFAIL"],
    expected=["记录报警限与工程量范围的约束关系"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_alarm_limits_out_of_range(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    observations: list[dict] = []

    test_cases = [
        ("limit_up_out", {"hi_eu": 50.0, "lo_eu": 0.0, "limit_up": 80.0}),
        ("limit_down_out", {"hi_eu": 50.0, "lo_eu": 0.0, "limit_down": -20.0}),
    ]

    for label, kwargs in test_cases:
        obs: dict = {
            "input_label": label,
            "input_kwargs": kwargs,
        }

        try:
            ctx = setup_ds_and_tag(
                api, settings, mocker_endpoint, tmp_path_factory, f"UA-2-1-097-{label}",
                tag_base_name="2_smoke_static_1",
                data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"],
                only_read=True,
                namespace_index=2,
                cycle=500,
                **kwargs,
            )
            tag_name = ctx["tag_name"]

            try:
                rec = find_unique_tag(api, tag_name)
                obs["saved_fields"] = {k: rec.get(k) for k in kwargs.keys()}
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
        "UA-2-1-097 alarm limits out of range semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
