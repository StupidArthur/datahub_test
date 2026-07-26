from __future__ import annotations

import json
import time

import pytest

from tpt_api.datahub import write_tag_values
from tpt_api.errors import TptAPIError
from tpt_api.types import TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
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
    classify_write_result,
    is_wrap_behaviour,
    strict_teardown,
    wait_integer_write_closed_loop,
)
from tests.support.ua2_value_normalization import normalize_int

from asyncua import ua

_TYPE_CONFIG = {
    # data_type: (type_name, node_suffix, variant_type, default)
    2: ("SByte", "sbyte_w_1", ua.VariantType.SByte, 7),
    3: ("Byte", "byte_w_1", ua.VariantType.Byte, 7),
    4: ("Int16", "int16_w_1", ua.VariantType.Int16, 123),
    5: ("UInt16", "uint16_w_1", ua.VariantType.UInt16, 123),
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

        for val in boundary_values:
            resp = write_tag_values(api, {tag_name: val})
            assert_write_accepted(resp, tag_name)

            result = wait_integer_write_closed_loop(
                api,
                endpoint=endpoint, node_name=node_name, namespace_index=1,
                ds_id=ctx["ds_id"], tag_name=tag_name,
                data_type=data_type, expected_value=val,
                timeout=30.0, interval=0.5,
            )

            _verify_variant_type(endpoint, node_name, variant_type)

            rv = normalize_int(result["rt"]["tagValue"])
            qv = normalize_int(result["qwq"]["tagValue"])
            assert result["source"] == val, \
                f"source mismatch for {val}: {result['source']!r}"
            assert rv == val, \
                f"RT mismatch for {val}: {rv}"
            assert qv == val, \
                f"QwQ mismatch for {val}: {qv}"
            assert result["rt"].get("quality") not in (None, 0)
            assert result["qwq"].get("quality") not in (None, 0)
            parse_required_timestamp(result["rt"].get("tagTime", ""))
            parse_required_timestamp(result["qwq"].get("tagTime", ""))

        opcua_write_sync(endpoint, node_name, cfg[3], namespace_index=1, variant_type=variant_type)

    finally:
        strict_teardown(api, tag_id=ctx["tag_id"], tag_name=tag_name,
                        ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                        mocker=ctx.get("mocker"))


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

        for val in out_of_range_values:
            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)
            _wait_source_rt_qwq_sync(api, endpoint, node_name, ds_id=ctx["ds_id"],
                                      tag_name=tag_name, data_type=data_type,
                                      expected=default_val)

            obs: dict = {
                "input_value": val,
                "input_type": type(val).__name__,
            }

            try:
                resp = write_tag_values(api, {tag_name: val})
                obs["write_exception"] = None
                obs["write_response"] = resp
            except TptAPIError as exc:
                obs["write_exception"] = {"code": exc.code, "msg": exc.msg}
                obs["write_response"] = None

            verdict = classify_write_result(
                obs.get("write_response"), tag_name,
                exception=obs.get("write_exception"),
            )
            obs["verdict"] = verdict

            time.sleep(3.0)

            source_final = opcua_read_sync(endpoint, node_name, namespace_index=1)
            obs["source_final"] = source_final
            obs["source_final_type"] = type(source_final).__name__
            try:
                sf_val, sf_vt = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=1)
                obs["source_variant_type"] = sf_vt.name
            except Exception as exc:
                obs["source_variant_type_error"] = str(exc)

            rt_final = get_rt_point(api, tag_name)
            obs["rt_final"] = rt_final.get("tagValue")
            obs["rt_quality"] = rt_final.get("quality")
            obs["rt_tagTime"] = rt_final.get("tagTime")

            try:
                from tpt_api.datahub import query_tags_with_quality
                qwq_all = query_tags_with_quality(api, ds_id=ctx["ds_id"], tag_name=tag_name)
                qrecs = (qwq_all.get("tagInfoList") or {}).get("records") or []
                qmatch = [r for r in qrecs if r.get("tagName") == tag_name]
                qwq_rec = qmatch[0] if qmatch else {}
                obs["qwq_final"] = qwq_rec.get("tagValue")
                obs["qwq_quality"] = qwq_rec.get("quality")
            except Exception as exc:
                obs["qwq_error"] = str(exc)

            if verdict == "rejected":
                assert isinstance(source_final, int) and not isinstance(source_final, bool), \
                    f"source type after rejection: {type(source_final).__name__}"
                assert source_final == default_val, \
                    f"source changed after rejection: {source_final} != {default_val}"
                assert rt_final.get("tagValue") is not None, "RT missing after rejection"
                try:
                    rfv = normalize_int(rt_final["tagValue"])
                except (TypeError, ValueError):
                    rfv = None
                assert rfv == default_val, \
                    f"RT changed after rejection: {rfv} != {default_val}"
                assert rt_final.get("quality") not in (None, 0)

                if is_wrap_behaviour(data_type, val):
                    expected_wrap = WRAP_MAP.get((data_type, val))
                    if expected_wrap is not None and source_final == expected_wrap:
                        pytest.fail(
                            f"silent wrap detected: {val} → {source_final} "
                            f"(expected {default_val} for rejection)"
                        )
            else:
                assert isinstance(source_final, int) and not isinstance(source_final, bool), \
                    f"source type after acceptance: {type(source_final).__name__}"
                assert rt_final.get("quality") not in (None, 0)
                if rt_final.get("tagTime"):
                    parse_required_timestamp(rt_final["tagTime"])

            observations.append(obs)
            record_property("observation", obs)

            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)

    finally:
        try:
            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)
        except Exception:
            pass
        strict_teardown(api, tag_id=ctx["tag_id"], tag_name=tag_name,
                        ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
                        mocker=ctx.get("mocker"))

    return observations


def _wait_source_rt_qwq_sync(api, endpoint, node_name, *, ds_id, tag_name, data_type, expected, timeout=30.0):
    from tests.support.polling import wait_until
    def _synced():
        src = opcua_read_sync(endpoint, node_name, namespace_index=1)
        if isinstance(src, bool) or src is None:
            return False
        try:
            sv = normalize_int(src)
        except (TypeError, ValueError):
            return False
        if sv != expected:
            return False
        pt = get_rt_point(api, tag_name)
        if pt.get("tagValue") is None or pt.get("quality") in (None, 0):
            return False
        try:
            pv = normalize_int(pt["tagValue"])
        except (TypeError, ValueError):
            return False
        return pv == expected
    wait_until(f"sync:{tag_name}", _synced, timeout=timeout, interval=0.5)


@pytest.mark.case(
    id="UA-2-1-042", chapter="UA-2-1",
    title="SByte 最小值与最大值",
    preconditions=["数据源 alive=true", "SByte 可写节点初始为 7"],
    steps=["写入 -128", "验证三端一致", "写入 127", "验证三端一致"],
    expected=["写响应成功", "源端值正确", "VariantType 不变", "RT/QwQ 一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_sbyte_min_max(api, settings, tmp_path_factory, mocker_endpoint):
    _run_boundary_case(api, settings, tmp_path_factory, mocker_endpoint,
                       "UA-2-1-042", 2, [-128, 127])


@pytest.mark.case(
    id="UA-2-1-043", chapter="UA-2-1",
    title="SByte 越界值",
    preconditions=["数据源 alive=true", "SByte 可写节点初始为 7"],
    steps=["写入 -129", "记录观察", "写入 128", "记录观察", "动态 XFAIL"],
    expected=["记录拒绝或转换行为", "被拒绝时源端保持 7", "VariantType 不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_sbyte_out_of_range(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    obs = _run_out_of_range_case(api, settings, tmp_path_factory, mocker_endpoint,
                                  "UA-2-1-043", 2, [-129, 128], record_property)
    pytest.xfail(
        "UA-2-1-043 SByte overflow semantics not specified; "
        f"observed: {json.dumps(obs, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-044", chapter="UA-2-1",
    title="Byte 最小值与最大值",
    preconditions=["数据源 alive=true", "Byte 可写节点初始为 7"],
    steps=["写入 0", "验证三端一致", "写入 255", "验证三端一致"],
    expected=["写响应成功", "源端值正确", "VariantType 不变", "RT/QwQ 一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_byte_min_max(api, settings, tmp_path_factory, mocker_endpoint):
    _run_boundary_case(api, settings, tmp_path_factory, mocker_endpoint,
                       "UA-2-1-044", 3, [0, 255])


@pytest.mark.case(
    id="UA-2-1-045", chapter="UA-2-1",
    title="Byte 越界值",
    preconditions=["数据源 alive=true", "Byte 可写节点初始为 7"],
    steps=["写入 -1", "记录观察", "写入 256", "记录观察", "动态 XFAIL"],
    expected=["记录拒绝或转换行为", "被拒绝时源端保持 7", "VariantType 不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_byte_out_of_range(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    obs = _run_out_of_range_case(api, settings, tmp_path_factory, mocker_endpoint,
                                  "UA-2-1-045", 3, [-1, 256], record_property)
    pytest.xfail(
        "UA-2-1-045 Byte overflow semantics not specified; "
        f"observed: {json.dumps(obs, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-046", chapter="UA-2-1",
    title="Int16 最小值与最大值",
    preconditions=["数据源 alive=true", "Int16 可写节点初始为 123"],
    steps=["写入 -32768", "验证三端一致", "写入 32767", "验证三端一致"],
    expected=["写响应成功", "源端值正确", "VariantType 不变", "RT/QwQ 一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_int16_min_max(api, settings, tmp_path_factory, mocker_endpoint):
    _run_boundary_case(api, settings, tmp_path_factory, mocker_endpoint,
                       "UA-2-1-046", 4, [-32768, 32767])


@pytest.mark.case(
    id="UA-2-1-047", chapter="UA-2-1",
    title="Int16 越界值",
    preconditions=["数据源 alive=true", "Int16 可写节点初始为 123"],
    steps=["写入 -32769", "记录观察", "写入 32768", "记录观察", "动态 XFAIL"],
    expected=["记录拒绝或转换行为", "被拒绝时源端保持 123", "VariantType 不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_int16_out_of_range(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    obs = _run_out_of_range_case(api, settings, tmp_path_factory, mocker_endpoint,
                                  "UA-2-1-047", 4, [-32769, 32768], record_property)
    pytest.xfail(
        "UA-2-1-047 Int16 overflow semantics not specified; "
        f"observed: {json.dumps(obs, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-048", chapter="UA-2-1",
    title="UInt16 最小值与最大值",
    preconditions=["数据源 alive=true", "UInt16 可写节点初始为 123"],
    steps=["写入 0", "验证三端一致", "写入 65535", "验证三端一致"],
    expected=["写响应成功", "源端值正确", "VariantType 不变", "RT/QwQ 一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_uint16_min_max(api, settings, tmp_path_factory, mocker_endpoint):
    _run_boundary_case(api, settings, tmp_path_factory, mocker_endpoint,
                       "UA-2-1-048", 5, [0, 65535])


@pytest.mark.case(
    id="UA-2-1-049", chapter="UA-2-1",
    title="UInt16 越界值",
    preconditions=["数据源 alive=true", "UInt16 可写节点初始为 123"],
    steps=["写入 -1", "记录观察", "写入 65536", "记录观察", "动态 XFAIL"],
    expected=["记录拒绝或转换行为", "被拒绝时源端保持 123", "VariantType 不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_uint16_out_of_range(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    obs = _run_out_of_range_case(api, settings, tmp_path_factory, mocker_endpoint,
                                  "UA-2-1-049", 5, [-1, 65536], record_property)
    pytest.xfail(
        "UA-2-1-049 UInt16 overflow semantics not specified; "
        f"observed: {json.dumps(obs, ensure_ascii=False, default=str)}"
    )
