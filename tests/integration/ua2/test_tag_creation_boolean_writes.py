from __future__ import annotations

import json
import time

import pytest

from tpt_api.datahub import add_tag, write_tag_values
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.cleanup import delete_tag_if_exists
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    assert_write_accepted,
    find_unique_tag,
    opcua_read_sync,
    opcua_write_sync,
    setup_ds_and_tag,
    teardown_ds_tag_mocker,
)
from tests.support.ua2_rt_assertions import parse_required_timestamp, wait_consistent_rt_and_qwq


_BOOLEAN_NODE = {
    "name": "boolean_w_",
    "type": "Boolean",
    "count": 1,
    "change": False,
    "writable": True,
}
_NODE_NAME = "boolean_w_1"
_TAG_BASE_NAME = "1_boolean_w_1"
_DATA_TYPE = 1


def _build_context(api, settings, tmp_path_factory, mocker_endpoint, case_id: str, default: bool) -> dict:
    node = dict(_BOOLEAN_NODE)
    node["default"] = default
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        tag_base_name=_TAG_BASE_NAME,
        data_type=_DATA_TYPE,
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[node],
        namespace_index=1,
        cycle=500,
    )
    return ctx


def _verify_tag_config(api, tag_name: str) -> dict:
    rec = find_unique_tag(api, tag_name)
    assert rec.get("tagBaseName") == _TAG_BASE_NAME, \
        f"tagBaseName={rec.get('tagBaseName')!r}"
    assert rec.get("dataType") == _DATA_TYPE, \
        f"dataType={rec.get('dataType')} != {_DATA_TYPE}"
    assert rec.get("onlyRead") is False, \
        f"onlyRead should be False, got {rec.get('onlyRead')}"
    return rec


def _wait_rt_ready(api, tag_name: str, expected_value: object | None = None, timeout: float = 30.0) -> dict:
    def _has_val():
        pt = get_rt_point(api, tag_name)
        if pt.get("tagValue") is None or pt.get("quality") in (None, 0):
            return False
        if expected_value is not None:
            actual_bool = bool(pt["tagValue"])
            return actual_bool == expected_value
        return True
    wait_until(f"rt_ready:{tag_name}", _has_val, timeout=timeout, interval=0.5)
    return get_rt_point(api, tag_name)


def _verify_source_bool(endpoint: str, *, expected: bool) -> None:
    raw = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)
    assert isinstance(raw, bool), \
        f"source value type is {type(raw).__name__}, expected bool"
    assert raw is expected, f"source value is {raw}, expected {expected}"


def _verify_three_way_boolean(
    api, ds_id: int, tag_name: str, endpoint: str,
    *, expected: bool, timeout: float = 30.0,
) -> dict:
    def _all_match():
        raw = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)
        if not isinstance(raw, bool):
            return False
        if raw is not expected:
            return False
        rt = get_rt_point(api, tag_name)
        if rt.get("tagValue") is None or rt.get("quality") in (None, 0):
            return False
        rt_bool = bool(rt["tagValue"])
        if rt_bool is not expected:
            return False
        return True

    wait_until(f"three_way:{tag_name}", _all_match, timeout=timeout, interval=0.5)
    rt_final = get_rt_point(api, tag_name)
    return rt_final


def _write_and_verify(
    api, ds_id: int, tag_name: str,
    value: object, *, expected_result: bool | None = None,
) -> dict:
    resp = write_tag_values(api, {tag_name: value})
    assert_write_accepted(resp, tag_name)
    return resp


@pytest.mark.case(
    id="UA-2-1-039", chapter="UA-2-1",
    title="Boolean 写入 true",
    preconditions=["数据源 alive=true", "Boolean 可写节点初始为 false"],
    steps=[
        "创建 Boolean 可写节点，初始 false",
        "新增位号 onlyRead=false",
        "确认 dataType=1, onlyRead=false",
        "保存 asyncua 源端原值",
        "调用 write_tag_values 写入 True",
        "轮询 asyncua 源端变为 True",
        "联合轮询 RT 与 queryWithQuality 均为 True",
        "验证两个入口 quality 有效、tagTime 可解析",
        "finally 恢复源端为 False",
    ],
    expected=[
        "写接口响应成功",
        "源端 Python 类型为 bool",
        "源端值 is True",
        "RT 规范值 is True",
        "QwQ 规范值 is True",
        "quality 有效",
        "tagTime 可解析",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_boolean_write_true(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-039", default=False)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    try:
        _verify_tag_config(api, tag_name)
        _verify_source_bool(endpoint, expected=False)
        _wait_rt_ready(api, tag_name)

        original_source = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)

        _write_and_verify(api, ctx["ds_id"], tag_name, True)
        _verify_three_way_boolean(api, ctx["ds_id"], tag_name, endpoint, expected=True)

        result = wait_consistent_rt_and_qwq(
            api, ds_id=ctx["ds_id"], tag_name=tag_name, data_type=_DATA_TYPE,
            expected_value=True,
        )
        rt_rec = result["rt"]
        qwq_rec = result["qwq"]

        raw = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)
        assert isinstance(raw, bool), f"source type is {type(raw).__name__}, expected bool"
        assert raw is True, f"source is {raw}, expected True"

        rt_val = rt_rec.get("tagValue")
        qwq_val = qwq_rec.get("tagValue")

        from tests.support.ua2_value_normalization import normalize_boolean
        assert normalize_boolean(rt_val) is True, f"RT value is {rt_val!r}"
        assert normalize_boolean(qwq_val) is True, f"QwQ value is {qwq_val!r}"

        assert rt_rec.get("quality") not in (None, 0), f"RT quality invalid: {rt_rec.get('quality')}"
        assert qwq_rec.get("quality") not in (None, 0), f"QwQ quality invalid: {qwq_rec.get('quality')}"
        parse_required_timestamp(rt_rec.get("tagTime", ""))
        parse_required_timestamp(qwq_rec.get("tagTime", ""))
    finally:
        try:
            current = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)
            if current is not False:
                opcua_write_sync(endpoint, _NODE_NAME, False, namespace_index=1)
                _verify_source_bool(endpoint, expected=False)
        except Exception:
            pass
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-040", chapter="UA-2-1",
    title="Boolean 写入 false",
    preconditions=["数据源 alive=true", "Boolean 可写节点初始为 true"],
    steps=[
        "创建 Boolean 可写节点，初始 true",
        "新增位号 onlyRead=false",
        "确认 dataType=1, onlyRead=false",
        "保存 asyncua 源端原值",
        "调用 write_tag_values 写入 False",
        "轮询 asyncua 源端变为 False",
        "联合轮询 RT 与 queryWithQuality 均为 False",
        "验证两个入口 quality 有效、tagTime 可解析",
        "finally 恢复源端为 True",
    ],
    expected=[
        "写接口响应成功",
        "源端 Python 类型为 bool",
        "源端值 is False",
        "RT 规范值 is False",
        "QwQ 规范值 is False",
        "quality 有效",
        "tagTime 可解析",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_boolean_write_false(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-040", default=True)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    try:
        _verify_tag_config(api, tag_name)
        _verify_source_bool(endpoint, expected=True)
        _wait_rt_ready(api, tag_name)

        original_source = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)

        _write_and_verify(api, ctx["ds_id"], tag_name, False)
        _verify_three_way_boolean(api, ctx["ds_id"], tag_name, endpoint, expected=False)

        result = wait_consistent_rt_and_qwq(
            api, ds_id=ctx["ds_id"], tag_name=tag_name, data_type=_DATA_TYPE,
            expected_value=False,
        )
        rt_rec = result["rt"]
        qwq_rec = result["qwq"]

        raw = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)
        assert isinstance(raw, bool), f"source type is {type(raw).__name__}, expected bool"
        assert raw is False, f"source is {raw}, expected False"

        rt_val = rt_rec.get("tagValue")
        qwq_val = qwq_rec.get("tagValue")

        from tests.support.ua2_value_normalization import normalize_boolean
        assert normalize_boolean(rt_val) is False, f"RT value is {rt_val!r}"
        assert normalize_boolean(qwq_val) is False, f"QwQ value is {qwq_val!r}"

        assert rt_rec.get("quality") not in (None, 0), f"RT quality invalid: {rt_rec.get('quality')}"
        assert qwq_rec.get("quality") not in (None, 0), f"QwQ quality invalid: {qwq_rec.get('quality')}"
        parse_required_timestamp(rt_rec.get("tagTime", ""))
        parse_required_timestamp(qwq_rec.get("tagTime", ""))
    finally:
        try:
            current = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)
            if current is not True:
                opcua_write_sync(endpoint, _NODE_NAME, True, namespace_index=1)
                _verify_source_bool(endpoint, expected=True)
        except Exception:
            pass
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-041", chapter="UA-2-1",
    title="Boolean 写入非布尔值",
    preconditions=["数据源 alive=true", "Boolean 可写节点初始为 false"],
    steps=[
        "创建 Boolean 可写节点，初始 false",
        "分别写入 1、0、\"true\"",
        "每个写入后记录完整 observation",
        "所有输入完成并清理后动态 xfail",
    ],
    expected=[
        "记录每个输入的被拒绝或转换行为",
        "被拒绝时源端保持 False",
        "被接受时源端仍为 bool",
        "quality 有效",
        "tagTime 可解析",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_boolean_write_non_boolean_values(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-041", default=False)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    observations: list[dict] = []

    try:
        _verify_tag_config(api, tag_name)
        _verify_source_bool(endpoint, expected=False)
        _wait_rt_ready(api, tag_name)

        inputs = [1, 0, "true"]

        for val in inputs:
            _verify_source_bool(endpoint, expected=False)
            rt_before = get_rt_point(api, tag_name)
            source_before = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)

            obs: dict = {
                "input_value": val,
                "input_type": type(val).__name__,
            }

            try:
                resp = write_tag_values(api, {tag_name: val})
                obs["write_exception"] = None
                obs["write_response"] = resp
                obs["write_tagNames"] = resp.get("tagNames", [])
                obs["write_failMsg"] = resp.get("failMsg", "")
                obs["write_msg"] = resp.get("msg", "")
            except TptAPIError as exc:
                obs["write_exception"] = {"code": exc.code, "msg": exc.msg}
                obs["write_response"] = None
                obs["write_tagNames"] = []
                obs["write_failMsg"] = ""
                obs["write_msg"] = exc.msg

            time.sleep(2.0)

            source_final = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)
            obs["source_final"] = source_final
            obs["source_final_type"] = type(source_final).__name__

            rt_final = get_rt_point(api, tag_name)
            obs["rt_final"] = rt_final.get("tagValue")
            obs["rt_final_type"] = type(rt_final.get("tagValue")).__name__ if rt_final.get("tagValue") is not None else "NoneType"
            obs["rt_quality"] = rt_final.get("quality")
            obs["rt_tagTime"] = rt_final.get("tagTime")

            try:
                qwq_all = __import__("tpt_api.datahub", fromlist=["query_tags_with_quality"]).query_tags_with_quality(
                    api, ds_id=ctx["ds_id"], tag_name=tag_name,
                )
                qrecs = (qwq_all.get("tagInfoList") or {}).get("records") or []
                qmatch = [r for r in qrecs if r.get("tagName") == tag_name]
                qwq_rec = qmatch[0] if qmatch else {}
                obs["qwq_final"] = qwq_rec.get("tagValue")
                obs["qwq_final_type"] = type(qwq_rec.get("tagValue")).__name__ if qwq_rec.get("tagValue") is not None else "NoneType"
                obs["qwq_quality"] = qwq_rec.get("quality")
                obs["qwq_tagTime"] = qwq_rec.get("tagTime")
            except Exception as exc:
                obs["qwq_error"] = str(exc)

            if obs["write_exception"] is not None:
                assert isinstance(source_final, bool), \
                    f"source type after rejection: {type(source_final).__name__}"
                assert source_final is False, \
                    f"source changed after rejection: {source_final}"
                assert rt_final.get("tagValue") is not None, \
                    "RT value missing after rejection"
                rt_bool_final = bool(rt_final["tagValue"])
                assert rt_bool_final is False, \
                    f"RT changed after rejection: {rt_final['tagValue']!r}"
                assert rt_final.get("quality") not in (None, 0), \
                    f"quality invalid after rejection: {rt_final.get('quality')}"
            else:
                assert isinstance(source_final, bool), \
                    f"source type after acceptance: {type(source_final).__name__}, expected bool"
                assert rt_final.get("quality") not in (None, 0), \
                    f"quality invalid after acceptance: {rt_final.get('quality')}"
                if rt_final.get("tagTime"):
                    parse_required_timestamp(rt_final["tagTime"])

            observations.append(obs)

            opcua_write_sync(endpoint, _NODE_NAME, False, namespace_index=1)
            _verify_source_bool(endpoint, expected=False)

        for obs in observations:
            record_property("observation", obs)

    finally:
        try:
            current = opcua_read_sync(endpoint, _NODE_NAME, namespace_index=1)
            if current is not False:
                opcua_write_sync(endpoint, _NODE_NAME, False, namespace_index=1)
        except Exception:
            pass
        teardown_ds_tag_mocker(api, ctx)

    pytest.xfail(
        "UA-2-1-041 Boolean coercion semantics are not specified; "
        f"observed: {json.dumps(observations, ensure_ascii=False, default=str)}"
    )
