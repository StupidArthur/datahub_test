from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from tpt_api.datahub import add_tag, get_rt_value, query_tags_with_quality
from tpt_api.types import DataTypes, TagTypes

from tests.support.cleanup import delete_tag_if_exists
from tests.support.polling import wait_until, WaitTimeout
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    find_unique_tag,
    opcua_read_sync,
    setup_ds_only,
    teardown_ds_tag_mocker,
)
from tests.support.ua2_value_normalization import assert_value_equal, normalize_datetime


def _build_node(name: str, type_name: str, default_val: object) -> dict:
    return {
        "name": name,
        "type": type_name,
        "default": default_val,
        "writable": False,
        "change": True,
        "count": 1,
    }


def parse_required_timestamp(raw: object) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise AssertionError(f"timestamp missing: {raw!r}")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssertionError(f"invalid timestamp: {raw!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clamped_rt_snapshot(api, tag_name: str, source_fn) -> dict:
    source_before = source_fn()
    rt_raw = get_rt_point(api, tag_name)
    source_after = source_fn()
    return {
        "source_before": source_before,
        "source_before_ts": time.monotonic(),
        "rt": rt_raw,
        "rt_ts": time.monotonic(),
        "source_after": source_after,
        "source_after_ts": time.monotonic(),
    }


def _assert_clamped_match(snap: dict, data_type: int, tag_name: str) -> None:
    rt_val = snap["rt"].get("tagValue")
    sb = snap["source_before"]
    sa = snap["source_after"]
    assert rt_val is not None, f"RT value is None for {tag_name}"
    assert snap["rt"].get("quality", 0) != 0, f"quality 0 for {tag_name}"
    assert sb is not None, f"source_before is None for {tag_name}"
    assert sa is not None, f"source_after is None for {tag_name}"
    if sb == sa:
        assert_value_equal(sb, rt_val, data_type)
    else:
        try:
            assert_value_equal(sb, rt_val, data_type)
        except AssertionError:
            assert_value_equal(sa, rt_val, data_type)


def _wait_rt_value(api, tag_name: str, timeout: float = 20.0) -> dict:
    def _has_val():
        pt = get_rt_point(api, tag_name)
        return pt.get("tagValue") is not None and pt.get("quality", 0) != 0
    wait_until(f"rt_val:{tag_name}", _has_val, timeout=timeout, interval=0.5)
    return get_rt_point(api, tag_name)


def _wait_second_value(api, tag_name: str, first_val: object, timeout: float = 30.0) -> dict:
    def _diff():
        pt = get_rt_point(api, tag_name)
        v = pt.get("tagValue")
        return v is not None and pt.get("quality", 0) != 0 and v != first_val
    wait_until(f"rt_diff:{tag_name}", _diff, timeout=timeout, interval=0.5)
    return get_rt_point(api, tag_name)


def wait_consistent_rt_and_qwq(
    api, ds_id: int, tag_name: str, data_type: int, timeout: float = 20.0
) -> dict:
    deadline = time.monotonic() + timeout
    last_rt = {}
    last_qwq_rec = {}
    while time.monotonic() < deadline:
        rt_list = get_rt_value(api, tag_names=[tag_name])
        last_rt = rt_list[0] if isinstance(rt_list, list) and rt_list else {}
        qwq = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
        qrecs = (qwq.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == tag_name]
        last_qwq_rec = qmatch[0] if qmatch else {}
        if not last_rt.get("tagValue") or not last_qwq_rec.get("tagValue"):
            time.sleep(0.5)
            continue
        if last_rt.get("quality") in (None, 0) or last_qwq_rec.get("quality") in (None, 0):
            time.sleep(0.5)
            continue
        if not last_rt.get("tagTime") or not last_qwq_rec.get("tagTime"):
            time.sleep(0.5)
            continue
        try:
            parse_required_timestamp(last_rt["tagTime"])
            parse_required_timestamp(last_qwq_rec["tagTime"])
        except AssertionError:
            time.sleep(0.5)
            continue
        try:
            assert_value_equal(
                last_rt["tagValue"], last_qwq_rec["tagValue"], data_type
            )
        except AssertionError:
            time.sleep(0.5)
            continue
        return last_qwq_rec
    raise AssertionError(
        f"RT/QwQ consistency timeout for {tag_name} (dt={data_type})\n"
        f"last getRTValue: {last_rt}\n"
        f"last queryWithQuality record: {last_qwq_rec}"
    )


def _run_default_read_case(
    api, settings, tmp_path_factory, mocker_endpoint,
    case_id: str,
    data_type: int,
    node_type: str,
    default_val: object,
) -> None:
    type_name = node_type.lower()
    node_name = f"{type_name}_r_"
    tag_base_name = f"1_{type_name}_r_1"
    nodes = [_build_node(node_name, node_type, default_val)]
    cycle_ms = 1000

    ctx = setup_ds_only(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        nodes=nodes, namespace_index=1, cycle=cycle_ms,
    )
    tag_name = None
    tag_id = None
    try:
        tag_data = add_tag(
            api, tag_name=f"{settings.test_prefix}{case_id}-tag",
            data_type=data_type, tag_type=TagTypes["一次位号"],
            ds_id=ctx["ds_id"], only_read=True,
            tag_base_name=tag_base_name,
        )
        tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
        tag_name = tag_data.get("tagName") or f"{settings.test_prefix}{case_id}-tag"

        rec = find_unique_tag(api, tag_name)
        assert rec.get("tagBaseName") == tag_base_name, \
            f"tagBaseName={rec.get('tagBaseName')!r}"
        assert rec.get("dataType") == data_type, \
            f"dataType={rec.get('dataType')} != {data_type}"
        assert rec.get("tagName") == tag_name
        assert rec.get("onlyRead") is not None

        pt1 = _wait_rt_value(api, tag_name, timeout=20.0)
        rt_ts1 = pt1.get("tagTime")
        assert rt_ts1, f"first RT tagTime is empty: {pt1}"
        ts1 = parse_required_timestamp(rt_ts1)

        source_fn = lambda: opcua_read_sync(ctx["endpoint"], f"{type_name}_r_1", namespace_index=1)
        snap1 = _clamped_rt_snapshot(api, tag_name, source_fn)

        pt2 = _wait_second_value(api, tag_name, snap1["rt"].get("tagValue"), timeout=30.0)
        rt_ts2 = pt2.get("tagTime")
        assert rt_ts2, f"second RT tagTime is empty: {pt2}"
        ts2 = parse_required_timestamp(rt_ts2)

        snap2 = _clamped_rt_snapshot(api, tag_name, source_fn)

        _assert_clamped_match(snap1, data_type, tag_name)
        _assert_clamped_match(snap2, data_type, tag_name)

        assert snap1["rt"].get("tagValue") != snap2["rt"].get("tagValue"), \
            "two RT values must differ"

        assert ts2 >= ts1, f"second timestamp {ts2} < first {ts1}"

        qr = wait_consistent_rt_and_qwq(api, ctx["ds_id"], tag_name, data_type)

        q_quality = qr["quality"]
        assert q_quality not in (None, 0), \
            f"queryWithQuality quality invalid: {q_quality}"

        qt_ts_str = qr.get("tagTime")
        assert qt_ts_str, f"queryWithQuality tagTime missing: {qr}"
        parse_required_timestamp(qt_ts_str)

        snap_q = _clamped_rt_snapshot(api, tag_name, source_fn)
        _assert_clamped_match(snap_q, data_type, tag_name)

    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-026", chapter="UA-2-1",
    title="默认读取类型_Boolean",
    preconditions=["数据源 alive=true"],
    steps=["创建 Boolean 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_boolean(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-026", 1, "Boolean", True)


@pytest.mark.case(
    id="UA-2-1-027", chapter="UA-2-1",
    title="默认读取类型_SByte",
    preconditions=["数据源 alive=true"],
    steps=["创建 SByte 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_sbyte(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-027", 2, "SByte", 0)


@pytest.mark.case(
    id="UA-2-1-028", chapter="UA-2-1",
    title="默认读取类型_Byte",
    preconditions=["数据源 alive=true"],
    steps=["创建 Byte 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_byte(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-028", 3, "Byte", 0)


@pytest.mark.case(
    id="UA-2-1-029", chapter="UA-2-1",
    title="默认读取类型_Int16",
    preconditions=["数据源 alive=true"],
    steps=["创建 Int16 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_int16(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-029", 4, "Int16", 0)


@pytest.mark.case(
    id="UA-2-1-030", chapter="UA-2-1",
    title="默认读取类型_UInt16",
    preconditions=["数据源 alive=true"],
    steps=["创建 UInt16 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_uint16(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-030", 5, "UInt16", 0)


@pytest.mark.case(
    id="UA-2-1-031", chapter="UA-2-1",
    title="默认读取类型_Int32",
    preconditions=["数据源 alive=true"],
    steps=["创建 Int32 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_int32(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-031", 6, "Int32", 0)


@pytest.mark.case(
    id="UA-2-1-032", chapter="UA-2-1",
    title="默认读取类型_UInt32",
    preconditions=["数据源 alive=true"],
    steps=["创建 UInt32 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_uint32(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-032", 7, "UInt32", 0)


@pytest.mark.case(
    id="UA-2-1-033", chapter="UA-2-1",
    title="默认读取类型_Int64",
    preconditions=["数据源 alive=true"],
    steps=["创建 Int64 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_int64(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-033", 8, "Int64", 0)


@pytest.mark.case(
    id="UA-2-1-034", chapter="UA-2-1",
    title="默认读取类型_UInt64",
    preconditions=["数据源 alive=true"],
    steps=["创建 UInt64 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_uint64(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-034", 9, "UInt64", 0)


@pytest.mark.case(
    id="UA-2-1-035", chapter="UA-2-1",
    title="默认读取类型_Float",
    preconditions=["数据源 alive=true"],
    steps=["创建 Float 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_float(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-035", 10, "Float", 0.0)


@pytest.mark.case(
    id="UA-2-1-036", chapter="UA-2-1",
    title="默认读取类型_Double",
    preconditions=["数据源 alive=true"],
    steps=["创建 Double 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_double(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-036", 11, "Double", 0.0)


@pytest.mark.case(
    id="UA-2-1-037", chapter="UA-2-1",
    title="默认读取类型_String",
    preconditions=["数据源 alive=true"],
    steps=["创建 String 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_string(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-037", 12, "String", "init")


@pytest.mark.case(
    id="UA-2-1-038", chapter="UA-2-1",
    title="默认读取类型_DateTime",
    preconditions=["数据源 alive=true"],
    steps=["创建 DateTime 节点并新增位号", "等待第一次 RT 值", "等待第二次 RT 值发生变化", "联合轮询 RT 与 queryWithQuality 直到一致"],
    expected=[
        "dataType 与请求一致",
        "tagBaseName 与请求一致",
        "两次 RT 值发生变化",
        "两次 RT quality 有效",
        "两次 RT tagTime 可严格解析",
        "第二次 RT 时间不早于第一次",
        "queryWithQuality 返回唯一目标记录",
        "queryWithQuality quality 存在且有效",
        "queryWithQuality tagTime 存在且可解析",
        "queryWithQuality tagValue 存在",
        "queryWithQuality 与 getRTValue 值一致",
        "RT 与 asyncua 源端夹逼值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_default_read_datetime(api, settings, tmp_path_factory, mocker_endpoint):
    _run_default_read_case(api, settings, tmp_path_factory, mocker_endpoint, "UA-2-1-038", 13, "DateTime", "2025-01-01T00:00:00Z")
