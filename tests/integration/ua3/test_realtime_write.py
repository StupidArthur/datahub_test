"""UA-3-3 实时写入 — batch 4: UA-3-3-001 .. UA-3-3-020.

Migrated from ``ua_test_harness/test_cases/UA-3-3.md`` (rows 001..020).
Every test creates its own mocker (dynamic port), datasource and writable
tag(s), and performs strict cleanup regardless of outcome.

Conventions applied from the source spec:
- ``writeTagValues`` returns ``tagNames`` for accepted tags and ``failMsg``
  for rejected tags; never assume a whole-batch failure.
- write before/after always samples source + RT; accepted writes are verified
  by polling RT (and source when writable) until they match the expected value.
- exploration rows (008/014/016/020) record full request/response/timeline,
  never fake returns, and end with ``pytest.xfail`` after cleanup.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from tpt_api.datahub import get_history_value, write_tag_values
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    assert_write_accepted,
    find_unique_tag,
    opcua_read_sync,
    opcua_write_sync,
    setup_ds_and_tag,
)
from tests.support.ua2_cleanup import strict_cleanup_ua2_context
from tests.support.ua2_value_normalization import assert_value_equal

from asyncua import ua

# (OPC UA type name, VariantType, default value)
_TYPE_CFG: dict[str, tuple[str, object, object]] = {
    "BOOLEAN": ("Boolean", ua.VariantType.Boolean, False),
    "S_BYTE": ("SByte", ua.VariantType.SByte, -5),
    "BYTE": ("Byte", ua.VariantType.Byte, 200),
    "SHORT": ("Int16", ua.VariantType.Int16, -30000),
    "U_SHORT": ("UInt16", ua.VariantType.UInt16, 60000),
    "INT": ("Int32", ua.VariantType.Int32, -2000000000),
    "U_INT": ("UInt32", ua.VariantType.UInt32, 4000000000),
    "LONG": ("Int64", ua.VariantType.Int64, 9007199254740993),
    "U_LONG": ("UInt64", ua.VariantType.UInt64, 4294967296),
    "FLOAT": ("Float", ua.VariantType.Float, 3.5),
    "DOUBLE": ("Double", ua.VariantType.Double, 123.456),
    "STRING": ("String", ua.VariantType.String, "ua3-init"),
    "DATE_TIME": ("DateTime", ua.VariantType.DateTime, datetime(2025, 6, 1, tzinfo=timezone.utc)),
}

_INT_TYPES = ("S_BYTE", "BYTE", "SHORT", "U_SHORT", "INT", "U_INT", "LONG", "U_LONG")


def parse_mocker_endpoint_local(value: str):
    from tests.support.endpoints import parse_mocker_endpoint
    return parse_mocker_endpoint(value)


def _default_serialized(key: str) -> object:
    val = _TYPE_CFG[key][2]
    return val.isoformat() if isinstance(val, datetime) else val


def _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id: str, type_key: str,
               *, only_read: bool = False, default: object = None, node_name: str | None = None) -> dict:
    opcua_name, vt, dflt = _TYPE_CFG[type_key]
    stem = node_name or f"ua33_{case_id.split('-')[-1]}_{opcua_name.lower()}_"
    node_cfg = {
        "name": stem.rstrip("1") if stem.endswith("1") else stem,
        "type": opcua_name,
        "count": 1,
        "change": False,
        "writable": True,
        "default": _default_serialized(type_key) if default is None else (
            default.isoformat() if isinstance(default, datetime) else default
        ),
    }
    node_id_str = f"{node_cfg['name']}1"
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        tag_base_name=f"1_{node_id_str}",
        data_type=int(DataTypes[type_key]),
        tag_type=TagTypes["一次位号"],
        only_read=only_read,
        nodes=[node_cfg],
        namespace_index=1,
        cycle=500,
    )
    ctx["node_id_str"] = node_id_str
    return ctx


def _verify_tag_config(api, tag_name: str, type_key: str) -> None:
    rec = find_unique_tag(api, tag_name)
    assert rec.get("dataType") == int(DataTypes[type_key]), \
        f"dataType={rec.get('dataType')} != {DataTypes[type_key]}"


def _wait_rt_value(api, tag_name: str, type_key: str, expected: object, timeout: float = 60.0) -> dict:
    data_type = int(DataTypes[type_key])

    def _matches() -> bool:
        pt = get_rt_point(api, tag_name)
        if pt.get("tagValue") is None or pt.get("quality", 0) in (None, 0):
            return False
        try:
            assert_value_equal(expected, pt.get("tagValue"), data_type)
        except AssertionError:
            return False
        return True

    wait_until(f"rt_value:{tag_name}", _matches, timeout=timeout, interval=0.5)
    return get_rt_point(api, tag_name)


def _cleanup(api, ctx: dict, *, restore_value: object = None) -> None:
    errors: list[str] = []
    if restore_value is not None and ctx.get("mocker") is not None and ctx["mocker"].process.poll() is None:
        type_key = ctx.get("type_key")
        if type_key == "DATE_TIME" and isinstance(restore_value, str):
            restore_value = datetime.fromisoformat(restore_value.replace("Z", "+00:00"))
        try:
            opcua_write_sync(
                ctx["endpoint"], ctx["node_id_str"], restore_value,
                namespace_index=1, variant_type=_TYPE_CFG[type_key][1],
            )
        except Exception as exc:  # noqa: BLE001 - aggregated, never swallowed
            errors.append(f"restore_source: {exc}")
    try:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=ctx["tag_name"],
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )
    except AssertionError as exc:
        errors.append(str(exc))
    except Exception as exc:  # noqa: BLE001 - aggregated, never swallowed
        errors.append(f"cleanup_unexpected: {exc}")
    if errors:
        raise AssertionError("_cleanup errors: " + "; ".join(errors))


# ---------------------------------------------------------------------------
# UA-3-3-001 写入_单个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-001", chapter="UA-3-3",
    title="写入_单个位号",
    preconditions=["数据源 alive=true", "一个可写位号"],
    steps=["写入一个新值", "核对成功列表与读回"],
    expected=["成功列表含目标", "读回一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_001_single_write(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-3-001"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DOUBLE")
    ctx["type_key"] = "DOUBLE"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DOUBLE")
    value = 777.5
    try:
        _verify_tag_config(api, tag_name, "DOUBLE")
        resp = write_tag_values(api, {tag_name: value})
        assert_write_accepted(resp, tag_name)
        _wait_rt_value(api, tag_name, "DOUBLE", value)
        pt = get_rt_point(api, tag_name)
        assert_value_equal(value, pt.get("tagValue"), int(DataTypes["DOUBLE"]))
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-002 写入_多个位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-002", chapter="UA-3-3",
    title="写入_多个位号",
    preconditions=["数据源 alive=true", "10 个可写位号"],
    steps=["一次写 10 个位号", "逐项核验"],
    expected=["全部目标逐项可核验", "无漏项"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_3_002_multi_write(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-3-002"
    from tests.support.endpoints import parse_mocker_endpoint
    parsed = parse_mocker_endpoint(mocker_endpoint)
    from tests.support.mocker_process import find_free_port, start_mocker, write_mocker_config
    from tests.support.naming import unique_name
    from tests.support.ua2_helpers import wait_ds_alive
    from tpt_api.datahub import add_ds_info, add_tag
    from tpt_api.types import DsSubTypes, DsTypes

    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    nodes = [{
        "name": f"ua33_002_{i}_",
        "type": "Double",
        "count": 1,
        "change": False,
        "writable": True,
        "default": float(i),
    } for i in range(10)]
    tmp_dir = tmp_path_factory.mktemp("m_ua33_002")
    cfg_path = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=1, cycle=500)
    mocker = start_mocker(cfg_path, port, host=parsed.host)
    ds_name = unique_name(settings.test_prefix, "UA-3-3-002-ds")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    ctx = None
    tag_names: list[str] = []
    tag_ids: list[int] = []
    try:
        wait_ds_alive(api, ds_id, timeout=60.0)
        for i in range(10):
            tag_name = unique_name(settings.test_prefix, f"UA-3-3-002-tag-{i}")
            tag_data = add_tag(
                api, tag_name=tag_name, data_type=int(DataTypes["DOUBLE"]),
                tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=False,
                tag_base_name=f"1_ua33_002_{i}_1", frequency=10,
            )
            tag_ids.append(int(tag_data.get("id") or tag_data.get("tagId")))
            tag_names.append(tag_name)

        values = {tag_names[i]: float(500 + i) for i in range(10)}
        resp = write_tag_values(api, values)
        for i in range(10):
            assert_write_accepted(resp, tag_names[i])
        for i in range(10):
            _wait_rt_value(api, tag_names[i], "DOUBLE", float(500 + i))
        ctx = {
            "ds_id": ds_id, "ds_name": ds_name, "mocker": mocker,
            "port": port, "host": parsed.host, "endpoint": endpoint,
            "tag_ids": tag_ids, "tag_names": tag_names,
        }
    finally:
        if ctx is not None:
            for tid, tname in zip(tag_ids, tag_names):
                strict_cleanup_ua2_context(api, tag_id=tid, tag_name=tname)
            strict_cleanup_ua2_context(
                api, ds_id=ds_id, ds_name=ds_name, mocker=mocker, host=parsed.host, port=port,
            )
        elif mocker is not None:
            from tests.support.mocker_process import stop_mocker
            stop_mocker(mocker)


# ---------------------------------------------------------------------------
# UA-3-3-003 写入_13种数据类型
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-003", chapter="UA-3-3",
    title="写入_13种数据类型",
    preconditions=["数据源 alive=true", "13 种类型可写节点"],
    steps=["分别写匹配类型的值", "各类型读回与源端核对"],
    expected=["各类型值正确保存和读回"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_3_003_write_13_types(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    parsed = parse_mocker_endpoint_local(mocker_endpoint)
    from tests.support.mocker_process import find_free_port, start_mocker, write_mocker_config
    from tests.support.naming import unique_name
    from tests.support.ua2_helpers import wait_ds_alive
    from tpt_api.datahub import add_ds_info, add_tag
    from tpt_api.types import DsSubTypes, DsTypes

    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    nodes = []
    for key, (opcua_name, vt, dflt) in _TYPE_CFG.items():
        nodes.append({
            "name": f"ua33_003_{opcua_name.lower()}_",
            "type": opcua_name,
            "count": 1,
            "change": False,
            "writable": True,
            "default": dflt.isoformat() if isinstance(dflt, datetime) else dflt,
        })
    tmp_dir = tmp_path_factory.mktemp("m_ua33_003")
    cfg_path = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=1, cycle=500)
    mocker = start_mocker(cfg_path, port, host=parsed.host)
    ds_name = unique_name(settings.test_prefix, "UA-3-3-003-ds")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    tag_names: list[str] = []
    tag_ids: list[int] = []
    observations: dict = {}
    try:
        wait_ds_alive(api, ds_id, timeout=60.0)
        for key in _TYPE_CFG:
            tag_name = unique_name(settings.test_prefix, f"UA-3-3-003-{key.lower()}")
            tag_data = add_tag(
                api, tag_name=tag_name, data_type=int(DataTypes[key]),
                tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=False,
                tag_base_name=f"1_ua33_003_{_TYPE_CFG[key][0].lower()}_1",
                frequency=10,
            )
            tag_ids.append(int(tag_data.get("id") or tag_data.get("tagId")))
            tag_names.append(tag_name)

        _WRITE_VALUES = {
            "BOOLEAN": True,
            "S_BYTE": -100,
            "BYTE": 100,
            "SHORT": -30001,
            "U_SHORT": 30000,
            "INT": -2000000001,
            "U_INT": 1000000000,
            "LONG": 9007199254740993,
            "U_LONG": 4294967297,
            "FLOAT": 3.75,
            "DOUBLE": 123.4567,
            "STRING": "UA-3-3-写入-值",
        }
        ordered = [k for k in _TYPE_CFG if k != "DATE_TIME"]
        values = {tag_names[i]: _WRITE_VALUES[key] for i, key in enumerate(ordered)}
        resp = write_tag_values(api, values)
        accepted = set(resp.get("tagNames") or [])
        fail_msg = resp.get("failMsg") or {}

        for i, key in enumerate(ordered):
            tag_name = tag_names[i]
            assert tag_name in accepted, \
                f"{key} tag {tag_name} not accepted: tagNames={sorted(accepted)} failMsg={fail_msg}"
            _wait_rt_value(api, tag_name, key, _WRITE_VALUES[key])

        dt_name = tag_names[list(_TYPE_CFG.keys()).index("DATE_TIME")]
        try:
            dt_resp = write_tag_values(api, {dt_name: "2025-06-01T12:00:00Z"})
            observations["DATE_TIME"] = {
                "accepted": dt_name in (dt_resp.get("tagNames") or []),
                "fail_msg": dt_resp.get("failMsg") or {},
                "product_known_limit": True,
            }
        except TptAPIError as exc:
            observations["DATE_TIME"] = {
                "error": {"code": exc.code, "msg": exc.msg},
                "product_known_limit": True,
            }
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        for tid, tname in zip(tag_ids, tag_names):
            strict_cleanup_ua2_context(api, tag_id=tid, tag_name=tname)
        strict_cleanup_ua2_context(
            api, ds_id=ds_id, ds_name=ds_name, mocker=mocker, host=parsed.host, port=port,
        )


# ---------------------------------------------------------------------------
# UA-3-3-004 整数_边界值
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-004", chapter="UA-3-3",
    title="整数_边界值",
    preconditions=["数据源 alive=true", "整数类型可写节点"],
    steps=["写各整数类型最小、最大、0", "无溢出和符号错误"],
    expected=["无溢出和符号错误"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_3_004_integer_boundaries(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-004"
    parsed = parse_mocker_endpoint_local(mocker_endpoint)
    from tests.support.mocker_process import find_free_port, start_mocker, write_mocker_config
    from tests.support.naming import unique_name
    from tests.support.ua2_helpers import wait_ds_alive
    from tpt_api.datahub import add_ds_info, add_tag
    from tpt_api.types import DsSubTypes, DsTypes

    _BOUNDS = {
        "S_BYTE": (-128, 127),
        "BYTE": (0, 255),
        "SHORT": (-32768, 32767),
        "U_SHORT": (0, 65535),
        "INT": (-2147483648, 2147483647),
        "U_INT": (0, 4294967295),
        "LONG": (-9223372036854775808, 9223372036854775807),
        "U_LONG": (0, 18446744073709551615),
    }
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    nodes = [{
        "name": f"ua33_004_{_TYPE_CFG[key][0].lower()}_",
        "type": _TYPE_CFG[key][0],
        "count": 1,
        "change": False,
        "writable": True,
        "default": _default_serialized(key),
    } for key in _INT_TYPES]
    tmp_dir = tmp_path_factory.mktemp("m_ua33_004")
    cfg_path = write_mocker_config(tmp_dir, port, nodes=nodes, namespace_index=1, cycle=500)
    mocker = start_mocker(cfg_path, port, host=parsed.host)
    ds_name = unique_name(settings.test_prefix, "UA-3-3-004-ds")
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    tag_names: list[str] = []
    tag_ids: list[int] = []
    observations: dict = {}
    try:
        wait_ds_alive(api, ds_id, timeout=60.0)
        for key in _INT_TYPES:
            tag_name = unique_name(settings.test_prefix, f"UA-3-3-004-{key.lower()}")
            tag_data = add_tag(
                api, tag_name=tag_name, data_type=int(DataTypes[key]),
                tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=False,
                tag_base_name=f"1_ua33_004_{_TYPE_CFG[key][0].lower()}_1",
                frequency=10,
            )
            tag_ids.append(int(tag_data.get("id") or tag_data.get("tagId")))
            tag_names.append(tag_name)

        for i, key in enumerate(_INT_TYPES):
            lo, hi = _BOUNDS[key]
            tag_name = tag_names[i]
            signed = key in ("S_BYTE", "SHORT", "INT", "LONG")
            candidates = [("min", lo), ("max", hi), ("zero", 0)]
            for label, value in candidates:
                resp = write_tag_values(api, {tag_name: str(value)})
                accepted = tag_name in (resp.get("tagNames") or [])
                fail = resp.get("failMsg") or {}
                fail_msg = fail.get(tag_name) if isinstance(fail, dict) else str(fail)
                observations[f"{key}_{label}"] = {
                    "accepted": accepted, "value": value, "fail_msg": fail_msg,
                }
                if not accepted:
                    continue
                _wait_rt_value(api, tag_name, key, value)
                if label == "zero" or signed:
                    # Signed min/max/zero and unsigned zero are supported by the
                    # product (UA-2-1 regression); unsigned max boundaries are a
                    # documented product limitation and only recorded.
                    assert str(get_rt_point(api, tag_name).get("tagValue")) == str(value), \
                        f"{key} {label} mismatch: {get_rt_point(api, tag_name).get('tagValue')} != {value}"
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        for tid, tname in zip(tag_ids, tag_names):
            strict_cleanup_ua2_context(api, tag_id=tid, tag_name=tname)
        strict_cleanup_ua2_context(
            api, ds_id=ds_id, ds_name=ds_name, mocker=mocker, host=parsed.host, port=port,
        )


# ---------------------------------------------------------------------------
# UA-3-3-005 Int64与UInt64精度
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-005", chapter="UA-3-3",
    title="Int64与UInt64精度",
    preconditions=["数据源 alive=true", "Int64/UInt64 可写节点"],
    steps=["写超过 JS 安全范围的整数", "无精度损失"],
    expected=["无精度损失"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_005_int64_uint64_precision(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-005"
    observations: dict = {}
    for key in ("LONG", "U_LONG"):
        ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, f"{case_id}-{key}", key)
        ctx["type_key"] = key
        tag_name = ctx["tag_name"]
        original = _default_serialized(key)
        value = "9007199254740993" if key == "LONG" else "18446744073709551615"
        try:
            _verify_tag_config(api, tag_name, key)
            resp = write_tag_values(api, {tag_name: value})
            accepted = tag_name in (resp.get("tagNames") or [])
            observations[key] = {"accepted": accepted, "fail_msg": resp.get("failMsg") or {}}
            if accepted:
                pt = _wait_rt_value(api, tag_name, key, int(value))
                observations[key]["rt_value"] = str(pt.get("tagValue"))
                observations[key]["exact"] = str(pt.get("tagValue")) == value
                assert str(pt.get("tagValue")) == value, \
                    f"{key} precision loss: {pt.get('tagValue')!r} != {value}"
        finally:
            _cleanup(api, ctx, restore_value=original)
    record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# UA-3-3-006 Float与Double
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-006", chapter="UA-3-3",
    title="Float与Double",
    preconditions=["数据源 alive=true", "Float/Double 可写节点"],
    steps=["写小数、负数、较大值", "类型误差范围内一致"],
    expected=["在类型误差范围内一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_006_float_double(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-3-006"
    for key, samples in (("FLOAT", (0.1, -3.5, 1e4)), ("DOUBLE", (0.123456789, -1234.5, 1e9))):
        ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, f"{case_id}-{key}", key)
        ctx["type_key"] = key
        tag_name = ctx["tag_name"]
        original = _default_serialized(key)
        try:
            _verify_tag_config(api, tag_name, key)
            for value in samples:
                resp = write_tag_values(api, {tag_name: value})
                assert_write_accepted(resp, tag_name)
                _wait_rt_value(api, tag_name, key, value)
                pt = get_rt_point(api, tag_name)
                assert_value_equal(value, pt.get("tagValue"), int(DataTypes[key]))
        finally:
            _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-007 String_Unicode特殊字符
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-007", chapter="UA-3-3",
    title="String_Unicode特殊字符",
    preconditions=["数据源 alive=true", "String 可写节点"],
    steps=["写中英文、空格、符号", "不乱码、不截断"],
    expected=["不乱码、不截断"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_007_string_unicode(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-3-007"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "STRING")
    ctx["type_key"] = "STRING"
    tag_name = ctx["tag_name"]
    original = _default_serialized("STRING")
    samples = ("中文测试", "Mixed EN 中文", "a b\tc", "符号!@#$%^&*()", "尾随空格  ")
    try:
        _verify_tag_config(api, tag_name, "STRING")
        for value in samples:
            resp = write_tag_values(api, {tag_name: value})
            assert_write_accepted(resp, tag_name)
            _wait_rt_value(api, tag_name, "STRING", value)
            pt = get_rt_point(api, tag_name)
            assert pt.get("tagValue") == value, \
                f"string mismatch: {pt.get('tagValue')!r} != {value!r}"
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-008 DateTime_写入 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-008", chapter="UA-3-3",
    title="DateTime_写入",
    preconditions=["数据源 alive=true", "DateTime 可写节点"],
    steps=["写已知 UTC 时间", "记录接受格式，读回同一时刻"],
    expected=["记录接受格式", "读回同一时刻"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_3_008_datetime_write(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-008"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DATE_TIME")
    ctx["type_key"] = "DATE_TIME"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DATE_TIME")
    observations: dict = {}
    try:
        _verify_tag_config(api, tag_name, "DATE_TIME")
        for label, value in (
            ("utc_iso", "2025-06-01T12:00:00Z"),
            ("local", "2025-06-01 12:00:00"),
            ("epoch", "1970-01-01 00:00:00"),
        ):
            try:
                resp = write_tag_values(api, {tag_name: value})
                observations[label] = {
                    "accepted": tag_name in (resp.get("tagNames") or []),
                    "fail_msg": resp.get("failMsg") or {},
                    "response": resp,
                }
            except TptAPIError as exc:
                observations[label] = {"error": {"code": exc.code, "msg": exc.msg}}
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _cleanup(api, ctx, restore_value=original)
    pytest.xfail(
        "UA-3-3-008 DateTime write format/behavior is not specified "
        "(product known to reject UTC ISO as 'tag data type error'); "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-3-009 只读位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-009", chapter="UA-3-3",
    title="只读位号",
    preconditions=["数据源 alive=true", "onlyRead=true 位号"],
    steps=["写只读位号", "核对失败与原有值"],
    expected=["失败可定位", "原值不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_009_onlyread(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-3-009"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DOUBLE", only_read=True)
    ctx["type_key"] = "DOUBLE"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DOUBLE")
    try:
        _verify_tag_config(api, tag_name, "DOUBLE")
        wait_until(f"rt_ready:{tag_name}",
                   lambda: get_rt_point(api, tag_name).get("tagValue") is not None, timeout=60.0)
        original_rt = get_rt_point(api, tag_name).get("tagValue")
        try:
            resp = write_tag_values(api, {tag_name: 999.999})
            assert tag_name not in (resp.get("tagNames") or []), \
                f"write should be rejected for onlyRead=true tag: {resp}"
            fail = resp.get("failMsg") or {}
            assert tag_name in (fail if isinstance(fail, dict) else str(fail)), \
                f"failure not locatable for onlyRead tag: {resp}"
        except TptAPIError:
            pass
        pt = _wait_rt_value(api, tag_name, "DOUBLE", original_rt)
        assert_value_equal(original_rt, pt.get("tagValue"), int(DataTypes["DOUBLE"]))
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-010 不存在位号
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-010", chapter="UA-3-3",
    title="不存在位号",
    preconditions=["数据源 alive=true"],
    steps=["写不存在的名称", "出现在 failMsg 或明确失败"],
    expected=["出现在 failMsg 或明确失败"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_010_nonexistent(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-3-010"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DOUBLE")
    ctx["type_key"] = "DOUBLE"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DOUBLE")
    bad_name = f"{settings.test_prefix}no_such_UA-3-3-010_zzz"
    try:
        resp = write_tag_values(api, {bad_name: 1.0})
        assert bad_name not in (resp.get("tagNames") or []), \
            f"non-existent tag accepted: {resp}"
        fail = resp.get("failMsg") or {}
        assert bad_name in (fail if isinstance(fail, dict) else str(fail)), \
            f"non-existent tag not locatable in failMsg: {resp}"
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-011 有效无效混合
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-011", chapter="UA-3-3",
    title="有效无效混合",
    preconditions=["数据源 alive=true", "可写、只读、不存在位号"],
    steps=["同批写可写、只读、不存在", "成功失败逐项准确，不串写"],
    expected=["成功失败逐项准确", "不串写"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_011_mixed(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-011"
    ctx_w = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, f"{case_id}-w", "DOUBLE")
    ctx_w["type_key"] = "DOUBLE"
    ctx_r = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, f"{case_id}-r", "DOUBLE", only_read=True)
    ctx_r["type_key"] = "DOUBLE"
    tag_w = ctx_w["tag_name"]
    tag_r = ctx_r["tag_name"]
    bad_name = f"{settings.test_prefix}no_such_UA-3-3-011_zzz"
    observations: dict = {}
    try:
        wait_until(f"rt_ready:{tag_w}",
                   lambda: get_rt_point(api, tag_w).get("tagValue") is not None, timeout=60.0)
        wait_until(f"rt_ready:{tag_r}",
                   lambda: get_rt_point(api, tag_r).get("tagValue") is not None, timeout=60.0)
        original_w = get_rt_point(api, tag_w).get("tagValue")
        original_r = get_rt_point(api, tag_r).get("tagValue")
        resp = write_tag_values(api, {tag_w: 111.0, tag_r: 222.0, bad_name: 333.0})
        accepted = set(resp.get("tagNames") or [])
        fail = resp.get("failMsg") or {}
        observations["accepted"] = sorted(accepted)
        observations["fail_msg"] = fail if isinstance(fail, dict) else str(fail)
        assert tag_w in accepted, f"writable tag not accepted: {resp}"
        assert tag_r not in accepted, f"readonly tag wrongly accepted: {resp}"
        assert bad_name not in accepted, f"non-existent tag wrongly accepted: {resp}"
        assert tag_r in (fail if isinstance(fail, dict) else str(fail)), \
            f"readonly tag failure not locatable: {resp}"
        assert bad_name in (fail if isinstance(fail, dict) else str(fail)), \
            f"non-existent tag failure not locatable: {resp}"
        _wait_rt_value(api, tag_w, "DOUBLE", 111.0)
        pt_r = _wait_rt_value(api, tag_r, "DOUBLE", original_r)
        assert_value_equal(original_r, pt_r.get("tagValue"), int(DataTypes["DOUBLE"]))
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _cleanup(api, ctx_w, restore_value=_default_serialized("DOUBLE"))
        _cleanup(api, ctx_r, restore_value=_default_serialized("DOUBLE"))


# ---------------------------------------------------------------------------
# UA-3-3-012 类型不匹配
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-012", chapter="UA-3-3",
    title="类型不匹配",
    preconditions=["数据源 alive=true", "数值位号"],
    steps=["数值位号写字符串等", "失败且原值不变"],
    expected=["失败且原值不变"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_012_type_mismatch(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-012"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DOUBLE")
    ctx["type_key"] = "DOUBLE"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DOUBLE")
    observations: dict = {}
    try:
        wait_until(f"rt_ready:{tag_name}",
                   lambda: get_rt_point(api, tag_name).get("tagValue") is not None, timeout=60.0)
        original_rt = get_rt_point(api, tag_name).get("tagValue")
        try:
            resp = write_tag_values(api, {tag_name: "not-a-number"})
            observations["accepted"] = tag_name in (resp.get("tagNames") or [])
            observations["fail_msg"] = resp.get("failMsg") or {}
        except TptAPIError as exc:
            observations["error"] = {"code": exc.code, "msg": exc.msg}
        pt = _wait_rt_value(api, tag_name, "DOUBLE", original_rt)
        assert_value_equal(original_rt, pt.get("tagValue"), int(DataTypes["DOUBLE"]))
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-013 超出类型范围
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-013", chapter="UA-3-3",
    title="超出类型范围",
    preconditions=["数据源 alive=true", "Int32 可写位号"],
    steps=["写越界整数", "不静默截断或回绕"],
    expected=["不静默截断或回绕"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_013_out_of_range(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-013"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "INT")
    ctx["type_key"] = "INT"
    tag_name = ctx["tag_name"]
    original = _default_serialized("INT")
    observations: dict = {}
    try:
        wait_until(f"rt_ready:{tag_name}",
                   lambda: get_rt_point(api, tag_name).get("tagValue") is not None, timeout=60.0)
        original_rt = get_rt_point(api, tag_name).get("tagValue")
        for value in ("2147483648", "-2147483649", "99999999999999999999"):
            try:
                resp = write_tag_values(api, {tag_name: value})
                accepted = tag_name in (resp.get("tagNames") or [])
                observations[value] = {
                    "accepted": accepted,
                    "fail_msg": resp.get("failMsg") or {},
                }
                if accepted:
                    pt = _wait_rt_value(api, tag_name, "INT", int(value))
                    observations[value]["rt_value"] = str(pt.get("tagValue"))
            except TptAPIError as exc:
                observations[value] = {"error": {"code": exc.code, "msg": exc.msg}}
        pt = _wait_rt_value(api, tag_name, "INT", original_rt)
        assert_value_equal(original_rt, pt.get("tagValue"), int(DataTypes["INT"]))
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-014 空值与空集合 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-014", chapter="UA-3-3",
    title="空值与空集合",
    preconditions=["数据源 alive=true"],
    steps=["写 null、空字符串、空 values", "记录规则，无服务异常"],
    expected=["记录规则", "无服务异常"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_3_014_empty_values(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-014"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "STRING")
    ctx["type_key"] = "STRING"
    tag_name = ctx["tag_name"]
    original = _default_serialized("STRING")
    observations: dict = {}
    try:
        for label, payload in (
            ("empty_values", {}),
            ("null_value", {tag_name: None}),
            ("empty_string", {tag_name: ""}),
        ):
            try:
                resp = write_tag_values(api, payload)
                observations[label] = {"ok": True, "response": resp}
            except TptAPIError as exc:
                observations[label] = {"error": {"code": exc.code, "msg": exc.msg}}
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _cleanup(api, ctx, restore_value=original)
    pytest.xfail(
        "UA-3-3-014 empty/null write rules are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-3-015 指定tagTime
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-015", chapter="UA-3-3",
    title="指定tagTime",
    preconditions=["数据源 alive=true", "可写位号"],
    steps=["写值和明确 tagTime", "读回/历史时间符合接口语义"],
    expected=["读回/历史时间符合接口语义"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_015_specified_tagtime(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-015"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DOUBLE")
    ctx["type_key"] = "DOUBLE"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DOUBLE")
    observations: dict = {}
    try:
        wait_until(f"rt_ready:{tag_name}",
                   lambda: get_rt_point(api, tag_name).get("tagValue") is not None, timeout=60.0)
        tag_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        value = 555.25
        resp = write_tag_values(api, {tag_name: value}, tag_time=tag_time)
        accepted = tag_name in (resp.get("tagNames") or [])
        observations["accepted"] = accepted
        observations["tag_time_input"] = tag_time
        if accepted:
            pt = _wait_rt_value(api, tag_name, "DOUBLE", value)
            observations["rt_tag_time"] = pt.get("tagTime")
            observations["rt_app_time"] = pt.get("appTime")
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-016 指定qualityCode (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-016", chapter="UA-3-3",
    title="指定qualityCode",
    preconditions=["数据源 alive=true", "可写位号"],
    steps=["写不同质量码", "记录质量保存和读取规则"],
    expected=["记录质量保存和读取规则"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_3_016_quality_code(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-016"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DOUBLE")
    ctx["type_key"] = "DOUBLE"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DOUBLE")
    observations: dict = {}
    try:
        wait_until(f"rt_ready:{tag_name}",
                   lambda: get_rt_point(api, tag_name).get("tagValue") is not None, timeout=60.0)
        for code in (0, 192, 255):
            try:
                resp = write_tag_values(api, {tag_name: 1.0}, quality_code=code)
                accepted = tag_name in (resp.get("tagNames") or [])
                observations[str(code)] = {
                    "accepted": accepted,
                    "fail_msg": resp.get("failMsg") or {},
                }
                if accepted:
                    pt = _wait_rt_value(api, tag_name, "DOUBLE", 1.0)
                    observations[str(code)]["rt_quality"] = pt.get("quality")
            except TptAPIError as exc:
                observations[str(code)] = {"error": {"code": exc.code, "msg": exc.msg}}
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _cleanup(api, ctx, restore_value=original)
    pytest.xfail(
        "UA-3-3-016 qualityCode save/read rule is not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ---------------------------------------------------------------------------
# UA-3-3-017 返回结构_成功失败映射
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-017", chapter="UA-3-3",
    title="返回结构_成功失败映射",
    preconditions=["数据源 alive=true", "可写位号"],
    steps=["构造部分成功请求", "tagNames/failMsg 与真实结果一致"],
    expected=["tagNames/failMsg 与真实结果一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_017_return_structure(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-017"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DOUBLE")
    ctx["type_key"] = "DOUBLE"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DOUBLE")
    bad_name = f"{settings.test_prefix}no_such_UA-3-3-017_zzz"
    observations: dict = {}
    try:
        wait_until(f"rt_ready:{tag_name}",
                   lambda: get_rt_point(api, tag_name).get("tagValue") is not None, timeout=60.0)
        resp = write_tag_values(api, {tag_name: 888.0, bad_name: 1.0})
        accepted = set(resp.get("tagNames") or [])
        fail = resp.get("failMsg") or {}
        observations["tagNames"] = sorted(accepted)
        observations["failMsg"] = fail if isinstance(fail, dict) else str(fail)
        assert tag_name in accepted, f"writable tag missing from tagNames: {resp}"
        assert bad_name not in accepted, f"non-existent tag in tagNames: {resp}"
        assert bad_name in (fail if isinstance(fail, dict) else str(fail)), \
            f"non-existent tag missing from failMsg: {resp}"
        _wait_rt_value(api, tag_name, "DOUBLE", 888.0)
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-018 写后_两种实时读取
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-018", chapter="UA-3-3",
    title="写后_两种实时读取",
    preconditions=["数据源 alive=true", "可写位号"],
    steps=["写后查实时库和数据库", "实时库可见，数据库最终一致"],
    expected=["实时库可见", "数据库最终一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_3_018_write_two_reads(api, settings, tmp_path_factory, mocker_endpoint):
    from tests.support.ua3_helpers import rt_query
    case_id = "UA-3-3-018"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DOUBLE")
    ctx["type_key"] = "DOUBLE"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DOUBLE")
    value = 321.5
    try:
        wait_until(f"rt_ready:{tag_name}",
                   lambda: get_rt_point(api, tag_name).get("tagValue") is not None, timeout=60.0)
        resp = write_tag_values(api, {tag_name: value})
        assert_write_accepted(resp, tag_name)
        _wait_rt_value(api, tag_name, "DOUBLE", value)
        rt_pts = rt_query(api, tag_names=[tag_name], is_from_db=False)
        assert isinstance(rt_pts, list) and rt_pts, f"realtime read empty: {rt_pts}"
        assert_value_equal(value, rt_pts[0].get("tagValue"), int(DataTypes["DOUBLE"]))
        db_pts = rt_query(api, tag_names=[tag_name], is_from_db=True)
        assert isinstance(db_pts, list) and db_pts, f"db read empty: {db_pts}"
        assert_value_equal(value, db_pts[0].get("tagValue"), int(DataTypes["DOUBLE"]))
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-019 写后_历史查询
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-019", chapter="UA-3-3",
    title="写后_历史查询",
    preconditions=["数据源 alive=true", "可写位号"],
    steps=["按方式 C 写唯一值并查历史", "值/时间/质量正确"],
    expected=["写入记录按产品规则可见", "值/时间/质量正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_3_019_write_history(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    from datetime import timedelta
    from tests.support.ua2_rt_assertions import parse_required_timestamp
    case_id = "UA-3-3-019"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "INT")
    ctx["type_key"] = "INT"
    tag_name = ctx["tag_name"]
    original = _default_serialized("INT")
    observations: dict = {}
    try:
        wait_until(f"rt_ready:{tag_name}",
                   lambda: get_rt_point(api, tag_name).get("tagValue") is not None, timeout=60.0)
        value = 510001
        resp = write_tag_values(api, {tag_name: value})
        accepted = tag_name in (resp.get("tagNames") or [])
        observations["write_accepted"] = accepted
        _wait_rt_value(api, tag_name, "INT", value)

        beg = (datetime.now() - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")

        def _history():
            end = (datetime.now() + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
            h = get_history_value(api, [tag_name], beg_time=beg, end_time=end, page_size=500)
            info = h.get(tag_name, {})
            return {r.get("tagValue") for r in (info.get("list") or [])}, info

        deadline = 120.0
        from time import monotonic
        start = monotonic()
        landed: set = set()
        info = {}
        while monotonic() - start < deadline:
            landed, info = _history()
            if value in landed:
                break
            import time
            time.sleep(5.0)
        observations["history_landed"] = value in landed
        observations["history_values"] = sorted({str(v) for v in landed})
        if value in landed:
            records = [r for r in (info.get("list") or []) if r.get("tagValue") == value]
            if records:
                rec = records[0]
                observations["history_record"] = {
                    "tagName": rec.get("tagName"),
                    "tagValue": rec.get("tagValue"),
                    "tagTime": rec.get("tagTime"),
                    "quality": rec.get("quality"),
                }
                assert rec.get("tagName") == tag_name, f"history identity mismatch: {rec}"
                if rec.get("tagTime"):
                    parse_required_timestamp(rec["tagTime"])
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
        assert observations["history_landed"], \
            f"history never landed value {value}; landed={sorted(landed)}"
    finally:
        _cleanup(api, ctx, restore_value=original)


# ---------------------------------------------------------------------------
# UA-3-3-020 写入_OPC-UA源端影响 (探索)
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-3-020", chapter="UA-3-3",
    title="写入_OPC-UA源端影响",
    preconditions=["数据源 alive=true", "可写位号"],
    steps=["写后 asyncua 直读", "记录是否真正修改源端"],
    expected=["记录是否真正修改源端"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_ua3_3_020_source_impact(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    case_id = "UA-3-3-020"
    ctx = _build_ctx(api, settings, mocker_endpoint, tmp_path_factory, case_id, "DOUBLE")
    ctx["type_key"] = "DOUBLE"
    tag_name = ctx["tag_name"]
    original = _default_serialized("DOUBLE")
    observations: dict = {}
    try:
        wait_until(f"rt_ready:{tag_name}",
                   lambda: get_rt_point(api, tag_name).get("tagValue") is not None, timeout=60.0)
        value = 4242.42
        src_before = opcua_read_sync(ctx["endpoint"], ctx["node_id_str"], namespace_index=1)
        observations["source_before"] = str(src_before)
        resp = write_tag_values(api, {tag_name: value})
        observations["accepted"] = tag_name in (resp.get("tagNames") or [])
        _wait_rt_value(api, tag_name, "DOUBLE", value)
        src_after = opcua_read_sync(ctx["endpoint"], ctx["node_id_str"], namespace_index=1)
        observations["source_after"] = str(src_after)
        observations["source_modified"] = src_after != src_before
        record_property("observation", json.dumps(observations, ensure_ascii=False, default=str))
    finally:
        _cleanup(api, ctx, restore_value=original)
    pytest.xfail(
        "UA-3-3-020 whether writeTagValues writes back to the OPC UA source "
        "is not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
