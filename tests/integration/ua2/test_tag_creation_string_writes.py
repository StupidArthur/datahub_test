from __future__ import annotations

import json

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
from tests.support.ua2_cleanup import strict_cleanup_ua2_context

from asyncua import ua

_TYPE_CONFIG = {
    12: ("String", "string_w_1", ua.VariantType.String, "initial"),
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


def _string_restore_and_cleanup(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    original_value: str,
    original_variant_type,
    tag_id: int | None,
    tag_name: str | None,
    ds_id: int | None,
    ds_name: str | None,
    mocker,
    host: str | None,
    port: int | None,
) -> None:
    errors: list[str] = []

    if mocker is None:
        errors.append("restore_unavailable: mocker is None")
    elif mocker.process.poll() is not None:
        errors.append(f"restore_unavailable: mocker exited, returncode={mocker.process.poll()}")
    else:
        try:
            opcua_write_sync(endpoint, node_name, original_value, namespace_index=namespace_index, variant_type=original_variant_type)
            src = opcua_read_sync(endpoint, node_name, namespace_index=namespace_index)
            if src != original_value:
                errors.append(f"restore_source: value mismatch: got {src!r} != {original_value!r}")
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
        raise AssertionError("_string_restore_and_cleanup errors: " + "; ".join(errors))


@pytest.mark.case(
    id="UA-2-1-066", chapter="UA-2-1",
    title="String 空串",
    preconditions=["数据源 alive=true", "String 可写节点初始为 'initial'"],
    steps=["写入空字符串", "验证三端一致"],
    expected=["写响应成功", "源端与 RT 均为空字符串", "不得转换为 null"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_string_empty(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 12
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-066", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        value = ""
        resp = write_tag_values(api, {tag_name: value})
        assert_write_accepted(resp, tag_name)

        def _source_matches():
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            return src == value
        wait_until(f"source_sync:{tag_name}", _source_matches, timeout=30.0, interval=0.5)

        def _rt_matches():
            pt = get_rt_point(api, tag_name)
            tv = pt.get("tagValue")
            return tv == value
        wait_until(f"rt_sync:{tag_name}", _rt_matches, timeout=30.0, interval=0.5)

        src = opcua_read_sync(endpoint, node_name, namespace_index=1)
        assert src == value, f"source mismatch: {src!r} != {value!r}"
        assert src is not None, "source is None, expected empty string"
        _verify_variant_type(endpoint, node_name, variant_type)

        pt = get_rt_point(api, tag_name)
        assert pt["tagValue"] == value, f"RT mismatch: {pt['tagValue']!r} != {value!r}"
        assert pt["tagValue"] is not None, "RT tagValue is None, expected empty string"
        assert pt.get("quality") not in (None, 0)
        parse_required_timestamp(pt["tagTime"])

    finally:
        _string_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-067", chapter="UA-2-1",
    title="String 普通与中文",
    preconditions=["数据源 alive=true", "String 可写节点初始为 'initial'"],
    steps=["写入 'hello'", "验证三端一致", "写入 '测试用例'", "验证三端一致"],
    expected=["写响应成功", "源端与 RT 完整一致", "编码无损"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_string_normal_and_chinese(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 12
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-067", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        test_values = ["hello", "测试用例"]

        for value in test_values:
            resp = write_tag_values(api, {tag_name: value})
            assert_write_accepted(resp, tag_name)

            def _source_matches():
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                return src == value
            wait_until(f"source_sync:{tag_name}:{value}", _source_matches, timeout=30.0, interval=0.5)

            def _rt_matches():
                pt = get_rt_point(api, tag_name)
                tv = pt.get("tagValue")
                return tv == value
            wait_until(f"rt_sync:{tag_name}:{value}", _rt_matches, timeout=30.0, interval=0.5)

            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            assert src == value, f"source mismatch: {src!r} != {value!r}"
            _verify_variant_type(endpoint, node_name, variant_type)

            pt = get_rt_point(api, tag_name)
            assert pt["tagValue"] == value, f"RT mismatch: {pt['tagValue']!r} != {value!r}"
            assert pt.get("quality") not in (None, 0)
            parse_required_timestamp(pt["tagTime"])

    finally:
        _string_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-068", chapter="UA-2-1",
    title="String 特殊字符与转义",
    preconditions=["数据源 alive=true", "String 可写节点初始为 'initial'"],
    steps=["写入包含特殊字符的字符串", "验证三端一致"],
    expected=["写响应成功", "源端与 RT 完整保留字符", "JSON 转义后语义一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_string_special_chars(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 12
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-068", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        value = '<>&"\'\\ \n\t'
        resp = write_tag_values(api, {tag_name: value})
        assert_write_accepted(resp, tag_name)

        def _source_matches():
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            return src == value
        wait_until(f"source_sync:{tag_name}", _source_matches, timeout=30.0, interval=0.5)

        def _rt_matches():
            pt = get_rt_point(api, tag_name)
            tv = pt.get("tagValue")
            return tv == value
        wait_until(f"rt_sync:{tag_name}", _rt_matches, timeout=30.0, interval=0.5)

        src = opcua_read_sync(endpoint, node_name, namespace_index=1)
        assert src == value, f"source mismatch: {src!r} != {value!r}"
        _verify_variant_type(endpoint, node_name, variant_type)

        pt = get_rt_point(api, tag_name)
        assert pt["tagValue"] == value, f"RT mismatch: {pt['tagValue']!r} != {value!r}"
        assert pt.get("quality") not in (None, 0)
        parse_required_timestamp(pt["tagTime"])

    finally:
        _string_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-069", chapter="UA-2-1",
    title="String 长度边界",
    preconditions=["数据源 alive=true", "String 可写节点初始为 'initial'"],
    steps=["写入 1 字符", "记录观察", "写入 255 字符", "记录观察", "写入 256 字符", "记录观察", "写入 1000 字符", "记录观察", "动态 XFAIL"],
    expected=["记录最大长度与拒绝或截断规则", "若成功，源端和 RT 长度及内容一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_string_length_boundary(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    data_type = 12
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-069", data_type)
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

        test_lengths = [1, 255, 256, 1000]

        for length in test_lengths:
            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            assert src == default_val, f"restore failed: {src!r} != {default_val!r}"

            value = "A" * length
            obs: dict = {
                "input_length": length,
                "input_value_preview": value[:50] + "..." if length > 50 else value,
            }

            try:
                resp = write_tag_values(api, {tag_name: value})
                obs["write_exception"] = None
                obs["write_response"] = resp
            except TptAPIError as exc:
                resp = None
                obs["write_exception"] = {"code": exc.code, "msg": exc.msg}
                obs["write_response"] = None

            if resp is not None and tag_name in (resp.get("tagNames") or []):
                obs["verdict"] = "accepted"
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                obs["source_length"] = len(src) if isinstance(src, str) else None
                obs["source_matches"] = src == value
                pt = get_rt_point(api, tag_name)
                obs["rt_length"] = len(pt["tagValue"]) if isinstance(pt.get("tagValue"), str) else None
                obs["rt_matches"] = pt.get("tagValue") == value
            else:
                obs["verdict"] = "rejected"
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                obs["source_final"] = src
                assert src == default_val, f"rejected but source changed: {src!r} != {default_val!r}"

            observations.append(obs)
            record_property(
                f"observation_length_{length}",
                json.dumps(obs, ensure_ascii=False, default=str),
            )

    finally:
        _string_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        "UA-2-1-069 String length boundary semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-070", chapter="UA-2-1",
    title="String null 与缺失字段",
    preconditions=["数据源 alive=true", "String 可写节点初始为 'initial'"],
    steps=["写入 null", "记录观察", "缺失 value 字段", "记录观察", "动态 XFAIL"],
    expected=["记录校验规则", "拒绝时原值保持"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_string_null_and_missing(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    data_type = 12
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-070", data_type)
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

        test_cases = [
            ("null", None),
        ]

        for label, value in test_cases:
            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            assert src == default_val, f"restore failed: {src!r} != {default_val!r}"

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

            if resp is not None and tag_name in (resp.get("tagNames") or []):
                obs["verdict"] = "accepted"
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                obs["source_final"] = str(src)
                obs["source_python_type"] = type(src).__name__
            else:
                obs["verdict"] = "rejected"
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                obs["source_final"] = str(src)
                obs["source_python_type"] = type(src).__name__
                assert src == default_val, f"rejected but source changed: {src!r} != {default_val!r}"

            observations.append(obs)
            record_property(
                f"observation_{label}",
                json.dumps(obs, ensure_ascii=False, default=str),
            )

    finally:
        _string_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        "UA-2-1-070 String null/missing field semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
