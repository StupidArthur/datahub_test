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
    assert_write_accepted,
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
    observe_integer_write_outcome,
    wait_accepted_integer_outcome,
    wait_three_way_sync,
)
from tests.support.ua2_value_normalization import normalize_int

from asyncua import ua

_TYPE_CONFIG = {
    6: ("Int32", "int32_w_1", ua.VariantType.Int32, 123456),
    7: ("UInt32", "uint32_w_1", ua.VariantType.UInt32, 123456),
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


def _run_boundary_case(
    api, settings, tmp_path_factory, mocker_endpoint,
    case_id: str, data_type: int,
    boundary_values: list[int],
) -> None:
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, case_id, data_type)
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

        for val in boundary_values:
            resp = write_tag_values(api, {tag_name: val})
            assert_write_accepted(resp, tag_name)

            trio = wait_three_way_sync(
                api, endpoint=endpoint, node_name=node_name, namespace_index=1,
                ds_id=ctx["ds_id"], tag_name=tag_name,
                data_type=data_type, expected_value=val,
                expected_variant_type=variant_type,
                mocker=ctx.get("mocker"),
            )

            _verify_variant_type(endpoint, node_name, variant_type)

            rv = normalize_int(trio["rt"]["tagValue"])
            qv = normalize_int(trio["qwq"]["tagValue"])
            assert trio["source"] == val, \
                f"source mismatch for {val}: {trio['source']!r}"
            assert rv == val, \
                f"RT mismatch for {val}: {rv}"
            assert qv == val, \
                f"QwQ mismatch for {val}: {qv}"
            assert trio["rt"].get("quality") not in (None, 0)
            assert trio["qwq"].get("quality") not in (None, 0)
            parse_required_timestamp(trio["rt"].get("tagTime", ""))
            parse_required_timestamp(trio["qwq"].get("tagTime", ""))
            assert trio["datasource_alive"] is True, \
                f"datasource not alive during {val}"

        opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


def _run_out_of_range_case(
    api, settings, tmp_path_factory, mocker_endpoint,
    case_id: str, data_type: int,
    out_of_range_values: list[int],
    record_property,
) -> list[dict]:
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, case_id, data_type)
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

        for val in out_of_range_values:
            wait_three_way_sync(
                api, endpoint=endpoint, node_name=node_name, namespace_index=1,
                ds_id=ctx["ds_id"], tag_name=tag_name,
                data_type=data_type, expected_value=default_val,
                expected_variant_type=variant_type,
                mocker=ctx.get("mocker"),
            )

            obs: dict = {
                "input_value": val,
                "input_type": type(val).__name__,
            }

            try:
                resp = write_tag_values(api, {tag_name: val})
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
                    data_type=data_type, input_value=val, baseline_value=default_val,
                    expected_variant_type=variant_type, mocker=ctx.get("mocker"),
                    min_observation_period=4.0,
                )
                obs["observation"] = outcome

                stable = outcome["stable"]
                assert stable["stable"], \
                    f"rejected but observation not stable: {stable['issues']}"

                final_source = opcua_read_sync(endpoint, node_name, namespace_index=1)
                _, final_vt = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=1)
                obs["source_final"] = final_source
                obs["source_python_type"] = type(final_source).__name__
                obs["source_variant_type"] = final_vt.name

                rt_final = get_rt_point(api, tag_name)
                obs["rt_final"] = rt_final.get("tagValue")
                obs["rt_quality"] = rt_final.get("quality")
                obs["rt_tagTime"] = rt_final.get("tagTime")

                assert not isinstance(final_source, bool), \
                    f"source type after rejection: {type(final_source).__name__}"
                assert final_source == default_val, \
                    f"source changed after rejection: {final_source} != {default_val}"
                assert rt_final.get("tagValue") is not None, "RT missing after rejection"
                assert rt_final.get("quality") not in (None, 0), "RT quality invalid after rejection"

            else:
                outcome = wait_accepted_integer_outcome(
                    api, endpoint=endpoint, node_name=node_name, namespace_index=1,
                    ds_id=ctx["ds_id"], tag_name=tag_name,
                    data_type=data_type, expected_variant_type=variant_type,
                    mocker=ctx.get("mocker"),
                )

                final_value = outcome["source"]
                vt_name = outcome["variant_type"].name
                obs["source_final"] = final_value
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
                    f"accepted write produced out-of-range final value: {final_value} (input={val})"

                silent_wrap = False
                if is_wrap_behaviour(data_type, val):
                    wrap = expected_wrap_value(data_type, val)
                    if final_value == wrap:
                        silent_wrap = True
                        pytest.fail(
                            f"silent wrap detected: input={val}, "
                            f"final={final_value}, dataType={data_type}"
                        )
                obs["silent_wrap_detected"] = silent_wrap

            observations.append(obs)
            record_property(
                f"observation_{val}",
                json.dumps(obs, ensure_ascii=False, default=str),
            )

            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )

    return observations


@pytest.mark.case(
    id="UA-2-1-050", chapter="UA-2-1",
    title="Int32 最小值与最大值",
    preconditions=["数据源 alive=true", "Int32 可写节点初始为 123456"],
    steps=["写入 -2147483648", "验证三端一致", "写入 2147483647", "验证三端一致"],
    expected=["写响应成功", "源端值正确", "VariantType 不变", "RT/QwQ 一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_int32_min_max(api, settings, tmp_path_factory, mocker_endpoint):
    _run_boundary_case(api, settings, tmp_path_factory, mocker_endpoint,
                       "UA-2-1-050", 6, [-2147483648, 2147483647])


@pytest.mark.case(
    id="UA-2-1-051", chapter="UA-2-1",
    title="Int32 越界值",
    preconditions=["数据源 alive=true", "Int32 可写节点初始为 123456"],
    steps=["写入 -2147483649", "记录观察", "写入 2147483648", "记录观察", "动态 XFAIL"],
    expected=["记录拒绝或转换行为", "被拒绝时源端保持 123456", "VariantType 不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_int32_out_of_range(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    obs = _run_out_of_range_case(api, settings, tmp_path_factory, mocker_endpoint,
                                 "UA-2-1-051", 6, [-2147483649, 2147483648], record_property)
    pytest.xfail(
        "UA-2-1-051 Int32 overflow semantics are not specified; "
        f"observed: {json.dumps(obs, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-052", chapter="UA-2-1",
    title="UInt32 最小值与最大值",
    preconditions=["数据源 alive=true", "UInt32 可写节点初始为 123456"],
    steps=["写入 0", "验证三端一致", "写入 4294967295", "验证三端一致"],
    expected=["写响应成功", "源端值正确", "VariantType 不变", "RT/QwQ 一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_uint32_min_max(api, settings, tmp_path_factory, mocker_endpoint):
    _run_boundary_case(api, settings, tmp_path_factory, mocker_endpoint,
                       "UA-2-1-052", 7, [0, 4294967295])


@pytest.mark.case(
    id="UA-2-1-053", chapter="UA-2-1",
    title="UInt32 越界值",
    preconditions=["数据源 alive=true", "UInt32 可写节点初始为 123456"],
    steps=["写入 -1", "记录观察", "写入 4294967296", "记录观察", "动态 XFAIL"],
    expected=["记录拒绝或转换行为", "被拒绝时源端保持 123456", "VariantType 不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_uint32_out_of_range(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    obs = _run_out_of_range_case(api, settings, tmp_path_factory, mocker_endpoint,
                                 "UA-2-1-053", 7, [-1, 4294967296], record_property)
    pytest.xfail(
        "UA-2-1-053 UInt32 overflow semantics are not specified; "
        f"observed: {json.dumps(obs, ensure_ascii=False, default=str)}"
    )
