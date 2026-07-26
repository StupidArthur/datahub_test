from __future__ import annotations

import json

import pytest

from tpt_api.datahub import write_tag_values
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

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


def _build_writable_context(api, settings, tmp_path_factory, mocker_endpoint, case_id: str, only_read: bool) -> dict:
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=only_read,
        namespace_index=2,
        cycle=500,
    )
    return ctx


def _build_readonly_context(api, settings, tmp_path_factory, mocker_endpoint, case_id: str, only_read: bool) -> dict:
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        tag_base_name="2_smoke_change_1",
        data_type=DataTypes["INT"],
        tag_type=TagTypes["一次位号"],
        only_read=only_read,
        namespace_index=2,
        cycle=500,
    )
    return ctx


@pytest.mark.case(
    id="UA-2-1-082", chapter="UA-2-1",
    title="只读_源可写_位号只读",
    preconditions=["源端 writable=true", "新增 onlyRead=true"],
    steps=["保存原值", "尝试写入新值", "查询源端与 RT"],
    expected=["写入被拒绝", "源端原值保持", "RT 不变", "错误信息明确"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_onlyread_source_writable_tag_readonly(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_writable_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-082", only_read=True)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    node_name = "smoke_static_1"
    ns = 2

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("onlyRead") is True, f"onlyRead should be True, got {rec.get('onlyRead')}"

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        original_src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
        original_rt = get_rt_point(api, tag_name)["tagValue"]

        try:
            resp = write_tag_values(api, {tag_name: 999.999})
            if tag_name in (resp.get("tagNames") or []):
                pytest.fail("write should be rejected for onlyRead=true tag")
        except TptAPIError:
            pass

        src_after = opcua_read_sync(endpoint, node_name, namespace_index=ns)
        assert src_after == original_src, f"source changed: {src_after} != {original_src}"

        rt_after = get_rt_point(api, tag_name)["tagValue"]
        assert rt_after == original_rt, f"RT changed: {rt_after} != {original_rt}"

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-083", chapter="UA-2-1",
    title="只读_源可写_位号可写",
    preconditions=["源端 writable=true", "新增 onlyRead=false"],
    steps=["写入新值并执行完整写入闭环"],
    expected=["写接口、源端、RT、质量和历史均按规则生效"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_onlyread_source_writable_tag_writable(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_writable_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-083", only_read=False)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    node_name = "smoke_static_1"
    ns = 2

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("onlyRead") is False, f"onlyRead should be False, got {rec.get('onlyRead')}"

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        original_src = opcua_read_sync(endpoint, node_name, namespace_index=ns)

        value = 999.999
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
    id="UA-2-1-084", chapter="UA-2-1",
    title="只读_源只读_位号只读",
    preconditions=["源端 writable=false", "新增 onlyRead=true"],
    steps=["尝试写入新值"],
    expected=["写入被拒绝", "源端与 RT 原值保持"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_onlyread_source_readonly_tag_readonly(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = _build_readonly_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-084", only_read=True)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    node_name = "smoke_change_1"
    ns = 2

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("onlyRead") is True, f"onlyRead should be True, got {rec.get('onlyRead')}"

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        original_src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
        original_rt = get_rt_point(api, tag_name)["tagValue"]

        try:
            resp = write_tag_values(api, {tag_name: 999.999})
            if tag_name in (resp.get("tagNames") or []):
                pytest.fail("write should be rejected for onlyRead=true tag")
        except TptAPIError:
            pass

        src_after = opcua_read_sync(endpoint, node_name, namespace_index=ns)
        assert src_after == original_src, f"source changed: {src_after} != {original_src}"

        rt_after = get_rt_point(api, tag_name)["tagValue"]
        assert rt_after == original_rt, f"RT changed: {rt_after} != {original_rt}"

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-085", chapter="UA-2-1",
    title="只读_源只读_位号配置可写",
    preconditions=["源端 writable=false", "新增 onlyRead=false"],
    steps=["新增位号", "尝试写入", "查询配置、源端和 RT", "记录观察", "动态 XFAIL"],
    expected=["记录新增时是否允许错误可写配置", "写入必须失败或不生效", "源端原值保持"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_onlyread_source_readonly_tag_writable(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = _build_readonly_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-085", only_read=False)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    node_name = "smoke_change_1"
    ns = 2
    observations: dict = {}

    try:
        rec = find_unique_tag(api, tag_name)
        observations["config_onlyRead"] = rec.get("onlyRead")
        observations["config_accepted"] = True

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        original_src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
        original_rt = get_rt_point(api, tag_name)["tagValue"]

        try:
            resp = write_tag_values(api, {tag_name: 999.999})
            observations["write_accepted"] = tag_name in (resp.get("tagNames") or [])
            observations["write_response"] = resp
        except TptAPIError as exc:
            observations["write_accepted"] = False
            observations["write_error"] = {"code": exc.code, "msg": exc.msg}

        src_after = opcua_read_sync(endpoint, node_name, namespace_index=ns)
        observations["source_changed"] = src_after != original_src
        observations["source_final"] = str(src_after)

        rt_after = get_rt_point(api, tag_name)["tagValue"]
        observations["rt_changed"] = rt_after != original_rt
        observations["rt_final"] = str(rt_after)

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
        "UA-2-1-085 onlyRead=false with source writable=false semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
