from __future__ import annotations

import json

import pytest

from tpt_api.datahub import write_tag_values
from tpt_api.errors import TptAPIError
from tpt_api.types import TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_cleanup import strict_cleanup_ua2_context
from tests.support.ua2_helpers import (
    find_unique_tag,
    opcua_read_sync,
    opcua_read_variant_type_sync,
    opcua_write_sync,
    setup_ds_and_tag,
)
from tests.support.ua2_rt_assertions import parse_required_timestamp
from tests.support.ua2_write_assertions import (
    WRAP_MAP,
    classify_outcome_value,
    classify_write_result,
    expected_wrap_value,
    is_wrap_behaviour,
    normalize_integer_decimal,
    observe_integer_write_outcome,
    wait_accepted_integer_outcome,
    wait_three_way_integer_decimal_sync,
    wait_three_way_sync,
)

from asyncua import ua

_TYPE_CONFIG = {
    8: ("Int64", "int64_w_1", ua.VariantType.Int64, 123456),
}


def _build_context(api, settings, tmp_path_factory, mocker_endpoint, case_id: str, data_type: int) -> dict:
    cfg = _TYPE_CONFIG[data_type]
    node = {
        "name": cfg[1].rstrip("1"),
        "type": cfg[0],
        "count": 1,
        "change": False,
        "writable": True,
        "default": cfg[3],
    }
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        tag_base_name=f"1_{cfg[1]}",
        data_type=data_type,
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[node],
        namespace_index=1,
        cycle=500,
    )
    return ctx


def _verify_tag_config(api, tag_name: str, data_type: int) -> dict:
    rec = find_unique_tag(api, tag_name)
    assert rec.get("dataType") == data_type, \
        f"dataType={rec.get('dataType')} != {data_type}"
    assert rec.get("onlyRead") is False, \
        f"onlyRead should be False, got {rec.get('onlyRead')}"
    return rec


def _verify_variant_type(endpoint: str, node_name: str, expected_vt) -> None:
    val, vt = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=1)
    assert vt == expected_vt, \
        f"VariantType mismatch: {vt} != {expected_vt} (expected {expected_vt.name})"
    assert not isinstance(val, bool), \
        f"source value is bool, expected int: {val!r}"


def _restore_source(endpoint: str, node_name: str, value: int, variant_type) -> None:
    opcua_write_sync(endpoint, node_name, value, namespace_index=1, variant_type=variant_type)
    check_val, check_vt = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=1)
    assert check_vt == variant_type, \
        f"restore VT mismatch: {check_vt} != {variant_type}"
    assert check_val == value, \
        f"restore value mismatch: {check_val} != {value}"


@pytest.mark.case(
    id="UA-2-1-054", chapter="UA-2-1",
    title="Int64 JS 安全范围值",
    preconditions=["数据源 alive=true", "Int64 可写节点初始为 123456"],
    steps=["写入 9999999999", "验证三端一致"],
    expected=["写响应成功", "源端精确为 9999999999", "VariantType 保持 Int64", "RT/QwQ 一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_int64_js_safe_value(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 8
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-054", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        wait_three_way_sync(
            api, endpoint=endpoint, node_name=node_name, namespace_index=1,
            ds_id=ctx["ds_id"], tag_name=tag_name,
            data_type=data_type, expected_value=default_val,
            expected_variant_type=variant_type,
            mocker=ctx.get("mocker"),
        )

        value = 9999999999
        resp = write_tag_values(api, {tag_name: value})
        from tests.support.ua2_helpers import assert_write_accepted
        assert_write_accepted(resp, tag_name)

        expected_decimal = "9999999999"

        trio = wait_three_way_integer_decimal_sync(
            api, endpoint=endpoint, node_name=node_name, namespace_index=1,
            ds_id=ctx["ds_id"], tag_name=tag_name,
            data_type=data_type, expected_decimal=expected_decimal,
            expected_variant_type=variant_type,
            mocker=ctx.get("mocker"),
        )

        _verify_variant_type(endpoint, node_name, variant_type)

        src = trio["source"]
        assert isinstance(src, int) and not isinstance(src, bool), \
            f"source Python type: {type(src).__name__}"
        rv_str = normalize_integer_decimal(trio["rt"]["tagValue"], data_type)
        qv_str = normalize_integer_decimal(trio["qwq"]["tagValue"], data_type)
        assert trio["datasource_alive"] is True
        assert trio["rt"].get("quality") not in (None, 0)
        assert trio["qwq"].get("quality") not in (None, 0)
        parse_required_timestamp(trio["rt"]["tagTime"])
        parse_required_timestamp(trio["qwq"]["tagTime"])

        _restore_source(endpoint, node_name, default_val, variant_type)

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-055", chapter="UA-2-1",
    title="Int64 最小值与最大值",
    preconditions=["数据源 alive=true", "Int64 可写节点初始为 123456"],
    steps=["写入 -9223372036854775808", "验证三端一致", "写入 9223372036854775807", "验证三端一致"],
    expected=["写响应成功", "源端值正确", "VariantType 不变", "RT/QwQ 一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_int64_min_max(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 8
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-055", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        wait_three_way_sync(
            api, endpoint=endpoint, node_name=node_name, namespace_index=1,
            ds_id=ctx["ds_id"], tag_name=tag_name,
            data_type=data_type, expected_value=default_val,
            expected_variant_type=variant_type,
            mocker=ctx.get("mocker"),
        )

        boundary_values = ["-9223372036854775808", "9223372036854775807"]

        for input_string in boundary_values:
            resp = write_tag_values(api, {tag_name: input_string})
            from tests.support.ua2_helpers import assert_write_accepted
            assert_write_accepted(resp, tag_name)

            trio = wait_three_way_integer_decimal_sync(
                api, endpoint=endpoint, node_name=node_name, namespace_index=1,
                ds_id=ctx["ds_id"], tag_name=tag_name,
                data_type=data_type, expected_decimal=input_string,
                expected_variant_type=variant_type,
                mocker=ctx.get("mocker"),
            )

            _verify_variant_type(endpoint, node_name, variant_type)

            src = trio["source"]
            assert isinstance(src, int) and not isinstance(src, bool), \
                f"source Python type: {type(src).__name__}"
            rv_str = normalize_integer_decimal(trio["rt"]["tagValue"], data_type)
            qv_str = normalize_integer_decimal(trio["qwq"]["tagValue"], data_type)
            assert rv_str == input_string, \
                f"RT mismatch for {input_string}: {rv_str}"
            assert qv_str == input_string, \
                f"QwQ mismatch for {input_string}: {qv_str}"
            assert trio["datasource_alive"] is True
            assert trio["rt"].get("quality") not in (None, 0)
            assert trio["qwq"].get("quality") not in (None, 0)
            parse_required_timestamp(trio["rt"]["tagTime"])
            parse_required_timestamp(trio["qwq"]["tagTime"])

            _restore_source(endpoint, node_name, default_val, variant_type)

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-056", chapter="UA-2-1",
    title="Int64 越界值",
    preconditions=["数据源 alive=true", "Int64 可写节点初始为 123456"],
    steps=["写入 -9223372036854775809", "记录观察", "写入 9223372036854775808", "记录观察", "动态 XFAIL"],
    expected=["记录拒绝或转换行为", "被拒绝时源端保持 123456", "VariantType 不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_int64_out_of_range(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    data_type = 8
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-056", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    observations: list[dict] = []

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        wait_three_way_sync(
            api, endpoint=endpoint, node_name=node_name, namespace_index=1,
            ds_id=ctx["ds_id"], tag_name=tag_name,
            data_type=data_type, expected_value=default_val,
            expected_variant_type=variant_type,
            mocker=ctx.get("mocker"),
        )

        oor_values = ["-9223372036854775809", "9223372036854775808"]

        for input_string in oor_values:
            _restore_source(endpoint, node_name, default_val, variant_type)

            wait_three_way_integer_decimal_sync(
                api, endpoint=endpoint, node_name=node_name, namespace_index=1,
                ds_id=ctx["ds_id"], tag_name=tag_name,
                data_type=data_type, expected_decimal=str(default_val),
                expected_variant_type=variant_type,
                mocker=ctx.get("mocker"),
            )

            obs: dict = {
                "input_value": input_string,
                "input_python_type": str,
            }

            try:
                resp = write_tag_values(api, {tag_name: input_string})
                obs["write_exception"] = None
                obs["write_response"] = resp
            except TptAPIError as exc:
                resp = None
                obs["write_exception"] = {"code": exc.code, "msg": exc.msg}
                obs["write_response"] = None

            verdict = classify_write_result(resp, tag_name, exception=obs.get("write_exception"))
            obs["verdict"] = verdict

            if verdict == "rejected":
                outcome = observe_integer_write_outcome(
                    api, endpoint=endpoint, node_name=node_name, namespace_index=1,
                    ds_id=ctx["ds_id"], tag_name=tag_name,
                    data_type=data_type, input_value=0, baseline_value=default_val,
                    expected_variant_type=variant_type, mocker=ctx.get("mocker"),
                    min_observation_period=4.0,
                )
                obs["observation"] = outcome

                stable = outcome["stable"]
                assert stable["stable"], \
                    f"rejected but observation not stable: {stable['issues']}"

                final_source = opcua_read_sync(endpoint, node_name, namespace_index=1)
                _, final_vt = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=1)
                obs["source_final"] = normalize_integer_decimal(final_source, data_type)
                obs["source_python_type"] = type(final_source).__name__
                obs["source_variant_type"] = final_vt.name

                rt_final = get_rt_point(api, tag_name)
                obs["rt_final"] = rt_final.get("tagValue")
                obs["rt_quality"] = rt_final.get("quality")
                obs["rt_tagTime"] = rt_final.get("tagTime")

                assert not isinstance(final_source, bool), \
                    f"source type after rejection: {type(final_source).__name__}"
                assert normalize_integer_decimal(final_source, data_type) == str(default_val), \
                    f"source changed after rejection: {final_source} != {default_val}"
                assert rt_final.get("tagValue") is not None, "RT missing after rejection"
                assert rt_final.get("quality") not in (None, 0), "RT quality invalid after rejection"

                osv = normalize_integer_decimal(final_source, data_type)
                assert osv == str(default_val), \
                    f"rejected source changed: {osv} != {default_val}"

                assert final_vt == variant_type, \
                    f"VariantType changed after rejection: {final_vt} != {variant_type}"

            else:
                outcome = wait_accepted_integer_outcome(
                    api, endpoint=endpoint, node_name=node_name, namespace_index=1,
                    ds_id=ctx["ds_id"], tag_name=tag_name,
                    data_type=data_type, expected_variant_type=variant_type,
                    mocker=ctx.get("mocker"),
                )

                final_value = outcome["source"]
                vt_name = outcome["variant_type"].name
                final_decimal = str(final_value)
                obs["source_final"] = final_decimal
                obs["source_python_type"] = type(final_value).__name__
                obs["source_variant_type"] = vt_name
                obs["rt_final"] = outcome["rt"].get("tagValue")
                obs["rt_quality"] = outcome["rt"].get("quality")
                obs["rt_tagTime"] = outcome["rt"].get("tagTime")
                obs["qwq_final"] = outcome["qwq"].get("tagValue")
                obs["qwq_quality"] = outcome["qwq"].get("quality")
                obs["qwq_tagTime"] = outcome["qwq"].get("tagTime")
                obs["datasource_alive"] = outcome["datasource_alive"]
                obs["mocker_alive"] = outcome["mocker_alive"]

                ooc = classify_outcome_value(data_type, final_value, default_val)
                obs["outcome_classification"] = ooc
                assert ooc != "out_of_range", \
                    f"accepted write produced out-of-range final value: {final_value} (input={input_string})"

                silent_wrap = False
                wrap_key = (data_type, int(float(input_string)))
                if is_wrap_behaviour(data_type, wrap_key[1]):
                    wrap = expected_wrap_value(data_type, wrap_key[1])
                    if final_value == wrap:
                        silent_wrap = True
                        pytest.fail(
                            f"silent wrap detected: input={input_string}, "
                            f"final={final_value}, dataType={data_type}"
                        )
                obs["silent_wrap_detected"] = silent_wrap

            observations.append(obs)
            record_property(
                f"observation_{input_string}",
                json.dumps(obs, ensure_ascii=False, default=str),
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
        "UA-2-1-056 Int64 overflow semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
