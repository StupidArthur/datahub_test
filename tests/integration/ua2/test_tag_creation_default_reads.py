from __future__ import annotations

import time

import pytest
from asyncua import ua

from tpt_api.datahub import add_tag
from tpt_api.types import DataTypes, TagTypes

from tests.support.cleanup import delete_tag_if_exists
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    find_unique_tag,
    opcua_read_sync,
    opcua_read_variant_type_sync,
    setup_ds_only,
    teardown_ds_tag_mocker,
)
from tests.support.ua2_rt_assertions import parse_required_timestamp, wait_consistent_rt_and_qwq
from tests.support.ua2_value_normalization import assert_value_equal

_CHANGE_CLAMP_TIMEOUT_S = 5.0
_CHANGE_CLAMP_INTERVAL_S = 0.25


def _build_node(name: str, type_name: str, default_val: object, *, change: bool = True) -> dict:
    return {
        "name": name,
        "type": type_name,
        "default": default_val,
        "writable": False,
        "change": change,
        "count": 1,
    }


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


def _read_source_variant_type(endpoint: str, node_name: str, namespace_index: int) -> ua.VariantType:
    _, vt = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=namespace_index)
    return vt


def _expected_variant_type(node_type: str) -> ua.VariantType:
    return getattr(ua.VariantType, node_type)


def _assert_source_variant_type(endpoint: str, node_name: str, namespace_index: int, node_type: str) -> None:
    observed = _read_source_variant_type(endpoint, node_name, namespace_index)
    expected = _expected_variant_type(node_type)
    assert observed == expected, \
        f"OPC UA VariantType mismatch for {node_name}: observed={observed} expected={expected}"


def _snapshot_matches_rt(snap: dict, data_type: int, tag_name: str, source_samples: list, *, differ_from: object = None) -> bool:
    rt_val = snap["rt"].get("tagValue")
    if rt_val is None or snap["rt"].get("quality", 0) == 0:
        return False
    if differ_from is not None and rt_val == differ_from:
        return False
    for src in source_samples:
        try:
            assert_value_equal(src, rt_val, data_type)
        except AssertionError:
            continue
        return True
    return False


def _wait_clamped_match(
    api, tag_name: str, source_fn, data_type: int,
    *,
    node_name: str,
    node_type: str,
    endpoint: str,
    namespace_index: int,
    is_change: bool,
    differ_from: object = None,
    timeout: float = _CHANGE_CLAMP_TIMEOUT_S,
    interval: float = _CHANGE_CLAMP_INTERVAL_S,
) -> dict:
    """Return a clamped snapshot whose RT value matches the OPC UA source.

    静态节点（change=false）：单次严格相等。
    change 节点：有界轮询 ≤timeout（monotonic deadline），每轮采集源值窗口，
    RT 与窗口内任一实际观察到的同类型源值一致即可（若提供 differ_from，
    还需与 differ_from 不同）；同时独立校验 OPC UA VariantType 与 dataType。
    超时仍未一致则真实 FAIL，并输出源值序列、RT 序列和时间戳。
    """
    if not is_change:
        snap = _clamped_rt_snapshot(api, tag_name, source_fn)
        _assert_clamped_match(snap, data_type, tag_name)
        return snap

    deadline = time.monotonic() + timeout
    source_samples: list = []
    rt_samples: list = []
    last_snap: dict = {}

    while time.monotonic() < deadline:
        snap = _clamped_rt_snapshot(api, tag_name, source_fn)
        last_snap = snap
        sb = snap["source_before"]
        sa = snap["source_after"]
        rt = snap["rt"]
        for src in (sb, sa):
            if src is not None and src not in source_samples:
                source_samples.append(src)
        rt_samples.append((snap["rt_ts"], rt.get("tagValue"), rt.get("quality"), rt.get("tagTime")))
        source_samples = source_samples[-8:]

        if _snapshot_matches_rt(snap, data_type, tag_name, source_samples, differ_from=differ_from):
            _assert_source_variant_type(endpoint, node_name, namespace_index, node_type)
            return snap
        time.sleep(interval)

    detail = "\n".join(
        f"  rt[{i}] ts={ts:.3f} tagValue={rv!r} quality={q} tagTime={tt!r}"
        for i, (ts, rv, q, tt) in enumerate(rt_samples)
    )
    src_detail = ", ".join(repr(s) for s in source_samples)
    raise AssertionError(
        f"RT never matched any observed source value within {timeout:.1f}s for {tag_name} "
        f"(data_type={data_type}, node_type={node_type})\n"
        f"source samples observed: [{src_detail}]\n"
        f"RT samples:\n{detail}"
    )


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
    is_change = any(n.get("change") is True for n in nodes)
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
        snap1 = _wait_clamped_match(
            api, tag_name, source_fn, data_type,
            node_name=f"{type_name}_r_1", node_type=node_type,
            endpoint=ctx["endpoint"], namespace_index=1,
            is_change=is_change,
        )

        pt2 = _wait_second_value(api, tag_name, snap1["rt"].get("tagValue"), timeout=30.0)
        rt_ts2 = pt2.get("tagTime")
        assert rt_ts2, f"second RT tagTime is empty: {pt2}"
        ts2 = parse_required_timestamp(rt_ts2)

        snap2 = _wait_clamped_match(
            api, tag_name, source_fn, data_type,
            node_name=f"{type_name}_r_1", node_type=node_type,
            endpoint=ctx["endpoint"], namespace_index=1,
            is_change=is_change,
            differ_from=snap1["rt"].get("tagValue"),
        )

        assert snap1["rt"].get("tagValue") != snap2["rt"].get("tagValue"), \
            "two RT values must differ"

        assert ts2 >= ts1, f"second timestamp {ts2} < first {ts1}"

        result = wait_consistent_rt_and_qwq(api, ds_id=ctx["ds_id"], tag_name=tag_name, data_type=data_type)
        qr = result["qwq"]

        q_quality = qr["quality"]
        assert q_quality not in (None, 0), \
            f"queryWithQuality quality invalid: {q_quality}"

        qt_ts_str = qr.get("tagTime")
        assert qt_ts_str, f"queryWithQuality tagTime missing: {qr}"
        parse_required_timestamp(qt_ts_str)

        snap_q = _wait_clamped_match(
            api, tag_name, source_fn, data_type,
            node_name=f"{type_name}_r_1", node_type=node_type,
            endpoint=ctx["endpoint"], namespace_index=1,
            is_change=is_change,
        )

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
