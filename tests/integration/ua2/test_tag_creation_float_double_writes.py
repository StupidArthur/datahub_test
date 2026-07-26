from __future__ import annotations

import json
import math

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
    setup_ds_and_tag,
)
from tests.support.ua2_rt_assertions import parse_required_timestamp
from tests.support.ua2_write_assertions import (
    restore_and_verify_source,
)

from asyncua import ua

_TYPE_CONFIG = {
    10: ("Float", "float_w_1", ua.VariantType.Float, 123.456),
    11: ("Double", "double_w_1", ua.VariantType.Double, 123.456),
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
        f"source value is bool, expected float: {val!r}"


def _assert_float_close(actual: float, expected: float, rel_tol: float = 1e-6, abs_tol: float = 1e-9) -> None:
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), \
        f"actual value is not numeric: {type(actual).__name__}"
    assert math.isclose(actual, expected, rel_tol=rel_tol, abs_tol=abs_tol), \
        f"float mismatch: actual={actual}, expected={expected}, rel_tol={rel_tol}, abs_tol={abs_tol}"


def _float_restore_and_cleanup(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    original_value: float,
    original_variant_type,
    tag_id: int | None,
    tag_name: str | None,
    ds_id: int | None,
    ds_name: str | None,
    mocker,
    host: str | None,
    port: int | None,
    rel_tol: float = 1e-6,
    abs_tol: float = 1e-9,
) -> None:
    from tests.support.ua2_cleanup import strict_cleanup_ua2_context
    from tests.support.ua2_helpers import opcua_write_sync

    errors: list[str] = []

    if mocker is None:
        errors.append("restore_unavailable: mocker is None")
    elif mocker.process.poll() is not None:
        errors.append(f"restore_unavailable: mocker exited, returncode={mocker.process.poll()}")
    else:
        try:
            opcua_write_sync(endpoint, node_name, original_value, namespace_index=namespace_index, variant_type=original_variant_type)
            src = opcua_read_sync(endpoint, node_name, namespace_index=namespace_index)
            if not math.isclose(src, original_value, rel_tol=rel_tol, abs_tol=abs_tol):
                errors.append(f"restore_source: value mismatch: got {src} != {original_value}")
        except Exception as exc:
            errors.append(f"restore_source: {exc}")

    cleanup_errors: list[str] = []
    try:
        strict_cleanup_ua2_context(
            api,
            tag_id=tag_id, tag_name=tag_name,
            ds_id=ds_id, ds_name=ds_name,
            mocker=mocker,
            host=host, port=port,
        )
    except AssertionError as exc:
        cleanup_errors.append(str(exc))
    except Exception as exc:
        cleanup_errors.append(f"cleanup_unexpected: {exc}")

    if cleanup_errors:
        errors.extend(cleanup_errors)

    if errors:
        raise AssertionError("_float_restore_and_cleanup errors: " + "; ".join(errors))


@pytest.mark.case(
    id="UA-2-1-060", chapter="UA-2-1",
    title="Float 普通值与负数",
    preconditions=["数据源 alive=true", "Float 可写节点初始为 123.456"],
    steps=["写入 1.25", "验证三端一致", "写入 -999.99", "验证三端一致"],
    expected=["写响应成功", "源端与 RT 在 Float 误差阈值内相等", "VariantType 保持 Float"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_float_normal_and_negative(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 10
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-060", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        test_values = [1.25, -999.99]

        for value in test_values:
            resp = write_tag_values(api, {tag_name: value})
            assert_write_accepted(resp, tag_name)

            def _source_matches():
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                return isinstance(src, (int, float)) and not isinstance(src, bool) and math.isclose(src, value, rel_tol=1e-6, abs_tol=1e-9)
            wait_until(f"source_sync:{tag_name}:{value}", _source_matches, timeout=30.0, interval=0.5)

            def _rt_matches():
                pt = get_rt_point(api, tag_name)
                tv = pt.get("tagValue")
                return tv is not None and isinstance(tv, (int, float)) and not isinstance(tv, bool) and math.isclose(tv, value, rel_tol=1e-6, abs_tol=1e-9)
            wait_until(f"rt_sync:{tag_name}:{value}", _rt_matches, timeout=30.0, interval=0.5)

            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            _assert_float_close(src, value)
            _verify_variant_type(endpoint, node_name, variant_type)

            pt = get_rt_point(api, tag_name)
            _assert_float_close(pt["tagValue"], value)
            assert pt.get("quality") not in (None, 0)
            parse_required_timestamp(pt["tagTime"])

    finally:
        _float_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
            rel_tol=1e-6, abs_tol=1e-9,
        )


@pytest.mark.case(
    id="UA-2-1-061", chapter="UA-2-1",
    title="Float 有效位数与小数",
    preconditions=["数据源 alive=true", "Float 可写节点初始为 123.456"],
    steps=["写入 1.23456789", "验证 Float32 精度", "写入 0.000001", "验证 Float32 精度"],
    expected=["返回值符合 Float32 精度", "使用相对误差或绝对误差判定"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_float_precision(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 10
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-061", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        test_values = [1.23456789, 0.000001]

        for value in test_values:
            resp = write_tag_values(api, {tag_name: value})
            assert_write_accepted(resp, tag_name)

            def _source_matches():
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                return isinstance(src, (int, float)) and not isinstance(src, bool) and math.isclose(src, value, rel_tol=1e-5, abs_tol=1e-9)
            wait_until(f"source_sync:{tag_name}:{value}", _source_matches, timeout=30.0, interval=0.5)

            def _rt_matches():
                pt = get_rt_point(api, tag_name)
                tv = pt.get("tagValue")
                return tv is not None and isinstance(tv, (int, float)) and not isinstance(tv, bool) and math.isclose(tv, value, rel_tol=1e-5, abs_tol=1e-9)
            wait_until(f"rt_sync:{tag_name}:{value}", _rt_matches, timeout=30.0, interval=0.5)

            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            _assert_float_close(src, value, rel_tol=1e-5, abs_tol=1e-9)
            _verify_variant_type(endpoint, node_name, variant_type)

            pt = get_rt_point(api, tag_name)
            _assert_float_close(pt["tagValue"], value, rel_tol=1e-5, abs_tol=1e-9)
            assert pt.get("quality") not in (None, 0)
            parse_required_timestamp(pt["tagTime"])

    finally:
        _float_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
            rel_tol=1e-5, abs_tol=1e-9,
        )


@pytest.mark.case(
    id="UA-2-1-062", chapter="UA-2-1",
    title="Float NaN 与无穷值",
    preconditions=["数据源 alive=true", "Float 可写节点初始为 123.456"],
    steps=["写入 NaN", "记录观察", "写入 +Inf", "记录观察", "写入 -Inf", "记录观察", "动态 XFAIL"],
    expected=["记录序列化和服务端处理规则", "拒绝时原值保持"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_float_nan_and_inf(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    data_type = 10
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-062", data_type)
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

        special_values = [
            ("NaN", float("nan")),
            ("+Inf", float("inf")),
            ("-Inf", float("-inf")),
        ]

        for label, value in special_values:
            from tests.support.ua2_helpers import opcua_write_sync
            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            assert math.isclose(src, default_val, rel_tol=1e-6, abs_tol=1e-9), \
                f"restore failed: {src} != {default_val}"

            obs: dict = {
                "input_label": label,
                "input_value": str(value),
                "input_python_type": type(value).__name__,
            }

            try:
                resp = write_tag_values(api, {tag_name: value})
                obs["write_exception"] = None
                obs["write_response"] = resp
            except TptAPIError as exc:
                resp = None
                obs["write_exception"] = {"code": exc.code, "msg": exc.msg}
                obs["write_response"] = None
            except ValueError as exc:
                resp = None
                obs["write_exception"] = {"type": "ValueError", "msg": str(exc)}
                obs["write_response"] = None

            if resp is not None and tag_name in (resp.get("tagNames") or []):
                obs["verdict"] = "accepted"
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                obs["source_final"] = str(src)
                obs["source_python_type"] = type(src).__name__
                if isinstance(src, float):
                    obs["source_is_nan"] = math.isnan(src)
                    obs["source_is_inf"] = math.isinf(src)
            else:
                obs["verdict"] = "rejected"
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                obs["source_final"] = str(src)
                obs["source_python_type"] = type(src).__name__
                assert math.isclose(src, default_val, rel_tol=1e-6, abs_tol=1e-9), \
                    f"rejected but source changed: {src} != {default_val}"

            observations.append(obs)
            record_property(
                f"observation_{label}",
                json.dumps(obs, ensure_ascii=False, default=str),
            )

    finally:
        _float_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
            rel_tol=1e-6, abs_tol=1e-9,
        )

    pytest.xfail(
        "UA-2-1-062 Float NaN/Inf semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-063", chapter="UA-2-1",
    title="Double 普通值与负数",
    preconditions=["数据源 alive=true", "Double 可写节点初始为 123.456"],
    steps=["写入 1.25", "验证三端一致", "写入 -999.99", "验证三端一致"],
    expected=["写响应成功", "源端与 RT 在 Double 误差阈值内相等", "VariantType 保持 Double"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_double_normal_and_negative(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 11
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-063", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        test_values = [1.25, -999.99]

        for value in test_values:
            resp = write_tag_values(api, {tag_name: value})
            assert_write_accepted(resp, tag_name)

            def _source_matches():
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                return isinstance(src, (int, float)) and not isinstance(src, bool) and math.isclose(src, value, rel_tol=1e-9, abs_tol=1e-12)
            wait_until(f"source_sync:{tag_name}:{value}", _source_matches, timeout=30.0, interval=0.5)

            def _rt_matches():
                pt = get_rt_point(api, tag_name)
                tv = pt.get("tagValue")
                return tv is not None and isinstance(tv, (int, float)) and not isinstance(tv, bool) and math.isclose(tv, value, rel_tol=1e-9, abs_tol=1e-12)
            wait_until(f"rt_sync:{tag_name}:{value}", _rt_matches, timeout=30.0, interval=0.5)

            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            _assert_float_close(src, value, rel_tol=1e-9, abs_tol=1e-12)
            _verify_variant_type(endpoint, node_name, variant_type)

            pt = get_rt_point(api, tag_name)
            _assert_float_close(pt["tagValue"], value, rel_tol=1e-9, abs_tol=1e-12)
            assert pt.get("quality") not in (None, 0)
            parse_required_timestamp(pt["tagTime"])

    finally:
        _float_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
            rel_tol=1e-9, abs_tol=1e-12,
        )


@pytest.mark.case(
    id="UA-2-1-064", chapter="UA-2-1",
    title="Double 有效位数与小数",
    preconditions=["数据源 alive=true", "Double 可写节点初始为 123.456"],
    steps=["写入 1.23456789012345", "验证 Float64 精度", "写入 0.0000000001", "验证 Float64 精度"],
    expected=["返回值符合 Float64 精度", "使用相对误差或绝对误差判定"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_double_precision(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 11
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-064", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        test_values = [1.23456789012345, 0.0000000001]

        for value in test_values:
            resp = write_tag_values(api, {tag_name: value})
            assert_write_accepted(resp, tag_name)

            def _source_matches():
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                return isinstance(src, (int, float)) and not isinstance(src, bool) and math.isclose(src, value, rel_tol=1e-12, abs_tol=1e-15)
            wait_until(f"source_sync:{tag_name}:{value}", _source_matches, timeout=30.0, interval=0.5)

            def _rt_matches():
                pt = get_rt_point(api, tag_name)
                tv = pt.get("tagValue")
                return tv is not None and isinstance(tv, (int, float)) and not isinstance(tv, bool) and math.isclose(tv, value, rel_tol=1e-12, abs_tol=1e-15)
            wait_until(f"rt_sync:{tag_name}:{value}", _rt_matches, timeout=30.0, interval=0.5)

            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            _assert_float_close(src, value, rel_tol=1e-12, abs_tol=1e-15)
            _verify_variant_type(endpoint, node_name, variant_type)

            pt = get_rt_point(api, tag_name)
            _assert_float_close(pt["tagValue"], value, rel_tol=1e-12, abs_tol=1e-15)
            assert pt.get("quality") not in (None, 0)
            parse_required_timestamp(pt["tagTime"])

    finally:
        _float_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
            rel_tol=1e-12, abs_tol=1e-15,
        )


@pytest.mark.case(
    id="UA-2-1-065", chapter="UA-2-1",
    title="Double NaN 与无穷值",
    preconditions=["数据源 alive=true", "Double 可写节点初始为 123.456"],
    steps=["写入 NaN", "记录观察", "写入 +Inf", "记录观察", "写入 -Inf", "记录观察", "动态 XFAIL"],
    expected=["记录序列化和服务端处理规则", "拒绝时原值保持"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_double_nan_and_inf(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    data_type = 11
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-065", data_type)
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

        special_values = [
            ("NaN", float("nan")),
            ("+Inf", float("inf")),
            ("-Inf", float("-inf")),
        ]

        for label, value in special_values:
            from tests.support.ua2_helpers import opcua_write_sync
            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            assert math.isclose(src, default_val, rel_tol=1e-9, abs_tol=1e-12), \
                f"restore failed: {src} != {default_val}"

            obs: dict = {
                "input_label": label,
                "input_value": str(value),
                "input_python_type": type(value).__name__,
            }

            try:
                resp = write_tag_values(api, {tag_name: value})
                obs["write_exception"] = None
                obs["write_response"] = resp
            except TptAPIError as exc:
                resp = None
                obs["write_exception"] = {"code": exc.code, "msg": exc.msg}
                obs["write_response"] = None
            except ValueError as exc:
                resp = None
                obs["write_exception"] = {"type": "ValueError", "msg": str(exc)}
                obs["write_response"] = None

            if resp is not None and tag_name in (resp.get("tagNames") or []):
                obs["verdict"] = "accepted"
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                obs["source_final"] = str(src)
                obs["source_python_type"] = type(src).__name__
                if isinstance(src, float):
                    obs["source_is_nan"] = math.isnan(src)
                    obs["source_is_inf"] = math.isinf(src)
            else:
                obs["verdict"] = "rejected"
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                obs["source_final"] = str(src)
                obs["source_python_type"] = type(src).__name__
                assert math.isclose(src, default_val, rel_tol=1e-9, abs_tol=1e-12), \
                    f"rejected but source changed: {src} != {default_val}"

            observations.append(obs)
            record_property(
                f"observation_{label}",
                json.dumps(obs, ensure_ascii=False, default=str),
            )

    finally:
        _float_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
            rel_tol=1e-9, abs_tol=1e-12,
        )

    pytest.xfail(
        "UA-2-1-065 Double NaN/Inf semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
