from __future__ import annotations

import json
from datetime import datetime, timezone

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
    13: ("DateTime", "datetime_w_1", ua.VariantType.DateTime, datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
}


def _build_context(api, settings, tmp_path_factory, mocker_endpoint, case_id: str, data_type: int) -> dict:
    cfg = _TYPE_CONFIG[data_type]
    node = {
        "name": cfg[1].rstrip("1"),
        "type": cfg[0],
        "count": 1,
        "change": False,
        "writable": True,
        "default": cfg[3].isoformat(),
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


def _datetime_restore_and_cleanup(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    original_value: datetime,
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
        raise AssertionError("_datetime_restore_and_cleanup errors: " + "; ".join(errors))


def _normalize_datetime_to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@pytest.mark.case(
    id="UA-2-1-071", chapter="UA-2-1",
    title="DateTime 写入 UTC ISO",
    preconditions=["数据源 alive=true", "DateTime 可写节点初始为 2025-01-01T00:00:00Z"],
    steps=["写入 2025-06-01T12:00:00Z", "验证三端一致"],
    expected=["写响应成功", "源端时刻等于输入 UTC", "RT utcTime 等于输入 UTC"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_datetime_utc_iso(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 13
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-071", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        value_str = "2025-06-01T12:00:00Z"
        value_dt = datetime.fromisoformat(value_str.replace("Z", "+00:00"))
        
        resp = write_tag_values(api, {tag_name: value_str})
        assert_write_accepted(resp, tag_name)

        def _source_matches():
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            if not isinstance(src, datetime):
                return False
            src_utc = _normalize_datetime_to_utc(src)
            return src_utc == value_dt
        wait_until(f"source_sync:{tag_name}", _source_matches, timeout=30.0, interval=0.5)

        def _rt_matches():
            pt = get_rt_point(api, tag_name)
            tv = pt.get("tagValue")
            if tv is None:
                return False
            try:
                tv_dt = datetime.fromisoformat(tv.replace("Z", "+00:00"))
                tv_utc = _normalize_datetime_to_utc(tv_dt)
                return tv_utc == value_dt
            except:
                return False
        wait_until(f"rt_sync:{tag_name}", _rt_matches, timeout=30.0, interval=0.5)

        src = opcua_read_sync(endpoint, node_name, namespace_index=1)
        assert isinstance(src, datetime), f"source is not datetime: {type(src).__name__}"
        src_utc = _normalize_datetime_to_utc(src)
        assert src_utc == value_dt, f"source mismatch: {src_utc} != {value_dt}"
        _verify_variant_type(endpoint, node_name, variant_type)

        pt = get_rt_point(api, tag_name)
        tv = pt["tagValue"]
        tv_dt = datetime.fromisoformat(tv.replace("Z", "+00:00"))
        tv_utc = _normalize_datetime_to_utc(tv_dt)
        assert tv_utc == value_dt, f"RT mismatch: {tv_utc} != {value_dt}"
        assert pt.get("quality") not in (None, 0)
        parse_required_timestamp(pt["tagTime"])

    finally:
        _datetime_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-072", chapter="UA-2-1",
    title="DateTime 写入带时区值",
    preconditions=["数据源 alive=true", "DateTime 可写节点初始为 2025-01-01T00:00:00Z"],
    steps=["写入 2025-06-01T20:00:00+08:00", "验证三端一致"],
    expected=["写响应成功", "源端和 RT 归一化后均等于 2025-06-01T12:00:00Z"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_datetime_with_timezone(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 13
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-072", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        value_str = "2025-06-01T20:00:00+08:00"
        value_dt = datetime.fromisoformat(value_str)
        expected_utc = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        resp = write_tag_values(api, {tag_name: value_str})
        assert_write_accepted(resp, tag_name)

        def _source_matches():
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            if not isinstance(src, datetime):
                return False
            src_utc = _normalize_datetime_to_utc(src)
            return src_utc == expected_utc
        wait_until(f"source_sync:{tag_name}", _source_matches, timeout=30.0, interval=0.5)

        def _rt_matches():
            pt = get_rt_point(api, tag_name)
            tv = pt.get("tagValue")
            if tv is None:
                return False
            try:
                tv_dt = datetime.fromisoformat(tv.replace("Z", "+00:00"))
                tv_utc = _normalize_datetime_to_utc(tv_dt)
                return tv_utc == expected_utc
            except:
                return False
        wait_until(f"rt_sync:{tag_name}", _rt_matches, timeout=30.0, interval=0.5)

        src = opcua_read_sync(endpoint, node_name, namespace_index=1)
        assert isinstance(src, datetime), f"source is not datetime: {type(src).__name__}"
        src_utc = _normalize_datetime_to_utc(src)
        assert src_utc == expected_utc, f"source mismatch: {src_utc} != {expected_utc}"
        _verify_variant_type(endpoint, node_name, variant_type)

        pt = get_rt_point(api, tag_name)
        tv = pt["tagValue"]
        tv_dt = datetime.fromisoformat(tv.replace("Z", "+00:00"))
        tv_utc = _normalize_datetime_to_utc(tv_dt)
        assert tv_utc == expected_utc, f"RT mismatch: {tv_utc} != {expected_utc}"
        assert pt.get("quality") not in (None, 0)
        parse_required_timestamp(pt["tagTime"])

    finally:
        _datetime_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-073", chapter="UA-2-1",
    title="DateTime 非法日期字符串",
    preconditions=["数据源 alive=true", "DateTime 可写节点初始为 2025-01-01T00:00:00Z"],
    steps=["写入 not-a-date", "验证拒绝", "写入 2025-02-30T00:00:00Z", "验证拒绝"],
    expected=["请求被拒绝", "原值保持不变", "不产生异常历史值"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_datetime_invalid(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 13
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-073", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        invalid_values = ["not-a-date", "2025-02-30T00:00:00Z"]

        for value in invalid_values:
            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            assert src == default_val, f"restore failed: {src!r} != {default_val!r}"

            try:
                resp = write_tag_values(api, {tag_name: value})
                if tag_name in (resp.get("tagNames") or []):
                    pytest.fail(f"invalid date {value!r} was accepted")
            except TptAPIError:
                pass

            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            assert src == default_val, f"source changed after rejected write: {src!r} != {default_val!r}"

    finally:
        _datetime_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-074", chapter="UA-2-1",
    title="DateTime 1601 与 1970 边界",
    preconditions=["数据源 alive=true", "DateTime 可写节点初始为 2025-01-01T00:00:00Z"],
    steps=["写入 1601-01-01T00:00:00Z", "验证三端一致", "写入 1970-01-01T00:00:00Z", "验证三端一致"],
    expected=["utcTime 按 1601 epoch 正确换算", "1970 不得被错误当作 UA epoch", "源端与 RT 归一化一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_datetime_epoch_boundaries(api, settings, tmp_path_factory, mocker_endpoint):
    data_type = 13
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-074", data_type)
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]

    try:
        _verify_tag_config(api, tag_name, data_type)
        _verify_variant_type(endpoint, node_name, variant_type)

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        test_values = [
            ("1601-01-01T00:00:00Z", datetime(1601, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
            ("1970-01-01T00:00:00Z", datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)),
        ]

        for value_str, value_dt in test_values:
            resp = write_tag_values(api, {tag_name: value_str})
            assert_write_accepted(resp, tag_name)

            def _source_matches():
                src = opcua_read_sync(endpoint, node_name, namespace_index=1)
                if not isinstance(src, datetime):
                    return False
                src_utc = _normalize_datetime_to_utc(src)
                return src_utc == value_dt
            wait_until(f"source_sync:{tag_name}:{value_str}", _source_matches, timeout=30.0, interval=0.5)

            def _rt_matches():
                pt = get_rt_point(api, tag_name)
                tv = pt.get("tagValue")
                if tv is None:
                    return False
                try:
                    tv_dt = datetime.fromisoformat(tv.replace("Z", "+00:00"))
                    tv_utc = _normalize_datetime_to_utc(tv_dt)
                    return tv_utc == value_dt
                except:
                    return False
            wait_until(f"rt_sync:{tag_name}:{value_str}", _rt_matches, timeout=30.0, interval=0.5)

            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            assert isinstance(src, datetime), f"source is not datetime: {type(src).__name__}"
            src_utc = _normalize_datetime_to_utc(src)
            assert src_utc == value_dt, f"source mismatch for {value_str}: {src_utc} != {value_dt}"
            _verify_variant_type(endpoint, node_name, variant_type)

            pt = get_rt_point(api, tag_name)
            tv = pt["tagValue"]
            tv_dt = datetime.fromisoformat(tv.replace("Z", "+00:00"))
            tv_utc = _normalize_datetime_to_utc(tv_dt)
            assert tv_utc == value_dt, f"RT mismatch for {value_str}: {tv_utc} != {value_dt}"
            assert pt.get("quality") not in (None, 0)
            parse_required_timestamp(pt["tagTime"])

    finally:
        _datetime_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-075", chapter="UA-2-1",
    title="DateTime 小数秒与无时区",
    preconditions=["数据源 alive=true", "DateTime 可写节点初始为 2025-01-01T00:00:00Z"],
    steps=["写入带毫秒值", "记录观察", "写入不带时区值", "记录观察", "动态 XFAIL"],
    expected=["记录支持的时间精度", "记录无时区输入按 UTC、本地时区或拒绝处理"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_datetime_fractional_and_no_timezone(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    data_type = 13
    cfg = _TYPE_CONFIG[data_type]
    node_name = cfg[1]
    variant_type = cfg[2]
    default_val = cfg[3]
    ctx = _build_context(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-075", data_type)
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
            ("fractional_seconds", "2025-06-01T12:00:00.123Z"),
            ("no_timezone", "2025-06-01T12:00:00"),
        ]

        for label, value_str in test_cases:
            opcua_write_sync(endpoint, node_name, default_val, namespace_index=1, variant_type=variant_type)
            src = opcua_read_sync(endpoint, node_name, namespace_index=1)
            assert src == default_val, f"restore failed: {src!r} != {default_val!r}"

            obs: dict = {
                "input_label": label,
                "input_value": value_str,
            }

            try:
                resp = write_tag_values(api, {tag_name: value_str})
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
                pt = get_rt_point(api, tag_name)
                obs["rt_final"] = str(pt.get("tagValue"))
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
        _datetime_restore_and_cleanup(
            api,
            endpoint=endpoint, node_name=node_name, namespace_index=1,
            original_value=default_val, original_variant_type=variant_type,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        "UA-2-1-075 DateTime fractional seconds and no timezone semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
