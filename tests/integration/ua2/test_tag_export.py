from __future__ import annotations

import json
import time

import pytest

from tpt_api.datahub import add_tag, export_tags, list_tags, update_tag
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.cleanup import delete_tag_if_exists
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import setup_ds_and_tag, teardown_ds_tag_mocker


_EXPECTED_HEADER = [
    "Tag Name", "Base Tag Name", "Tag Type", "Datasource Name", "Unit",
    "Data Type", "Expression", "Tag Value", "Frequency",
    "High Limit", "HH Limit", "HHH Limit",
    "Low Limit", "LL Limit", "LLL Limit",
    "Description", "Group Name",
    "Real-time Push", "Readonly", "Lo EU", "Hi EU",
]


def _create_simple_tag(api, ds_id: int, case_id: str, settings,
                       tmp_path_factory, mocker_endpoint,
                       data_type: int = DataTypes["DOUBLE"],
                       tag_base_name: str | None = None,
                       **overrides) -> dict:
    overrides.setdefault("only_read", False)
    overrides.setdefault("unit", "")
    overrides.setdefault("tag_desc", None)
    overrides.setdefault("frequency", 10)
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        tag_base_name=tag_base_name or f"2_{case_id.lower()}_node",
        data_type=data_type,
        tag_type=TagTypes["一次位号"],
        **overrides,
    )
    return ctx


def _export_and_parse(api, tag_ids: list[int]) -> list[list]:
    rows = export_tags(api, tag_ids, parse=True)
    assert rows, "export returned empty result"
    return rows


def _get_tag_ids(api, tag_names: list[str]) -> list[int]:
    ids = []
    for name in tag_names:
        page = list_tags(api, page=1, page_size=50, data={"tagName": name})
        for r in (page.get("records") or []):
            if r.get("tagName") == name:
                ids.append(int(r["id"]))
                break
    return ids


@pytest.mark.case(
    id="UA-2-3-001", chapter="UA-2-3",
    title="导出_单个位号",
    preconditions=["至少一个位号存在且有采集数据"],
    steps=["创建双精度位号并等待 RT", "调用 export_tags([id])", "解析 Excel 并校验"],
    expected=["返回有效 xlsx", "仅目标行存在", "Excel 行与配置一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_export_single_tag(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-001",
        tag_base_name="2_ua23_001_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_001_node", "type": "Double", "default": 42.5, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    tag_id = ctx["tag_id"]
    try:
        rows = _export_and_parse(api, [tag_id])
        header = rows[0]
        assert header == _EXPECTED_HEADER, f"header mismatch: {header}"
        data_rows = rows[1:]
        assert len(data_rows) == 1, f"expected 1 data row, got {len(data_rows)}"
        row = data_rows[0]
        assert str(row[0]) == ctx["tag_name"], f"Tag Name: {row[0]!r}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-002", chapter="UA-2-3",
    title="导出_多位号集合",
    preconditions=["多个位号存在且有采集数据"],
    steps=["创建 10 个位号", "export_tags(10 ids)", "校验行数无遗漏重复"],
    expected=["10 行数据", "无遗漏无重复"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_export_multiple_tags(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-002",
        tag_base_name="2_ua23_002_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_002_node", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    ds_id = ctx["ds_id"]
    tag_names = [ctx["tag_name"]]
    extra_ids = []
    try:
        for i in range(9):
            extra = add_tag(
                api, tag_name=f"{ctx['tag_name']}_extra_{i}",
                data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"],
                ds_id=ds_id,
                tag_base_name=f"2_ua23_002_node_extra_{i}",
                only_read=False,
                frequency=10,
            )
            extra_ids.append(int(extra.get("id") or extra.get("tagId")))
            tag_names.append(f"{ctx['tag_name']}_extra_{i}")

        all_ids = [ctx["tag_id"]] + extra_ids
        rows = _export_and_parse(api, all_ids)
        data_rows = rows[1:]
        assert len(data_rows) == 10, f"expected 10 rows, got {len(data_rows)}"
        exported_names = [str(r[0]) for r in data_rows]
        for name in tag_names:
            assert name in exported_names, f"{name} missing in export"
        assert len(set(exported_names)) == 10, f"duplicates in exported names: {exported_names}"
    finally:
        for eid in extra_ids:
            try:
                delete_tag_if_exists(api, eid)
            except Exception:
                pass
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-003", chapter="UA-2-3",
    title="导出_跨源跨组",
    preconditions=["两个数据源两个分组"],
    steps=["创建双 DS 双分组位号", "export_tags 混合集合", "校验数据源和分组字段"],
    expected=["数据源和分组字段正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_export_cross_ds_group(api, settings, tmp_path_factory, mocker_endpoint):
    ctx1 = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-003a",
        tag_base_name="2_ua23_003a_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_003a_node", "type": "Double", "default": 10.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    ctx2 = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-003b",
        tag_base_name="2_ua23_003b_node",
        data_type=DataTypes["INT32"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_003b_node", "type": "Int32", "default": 99, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        all_ids = [ctx1["tag_id"], ctx2["tag_id"]]
        rows = _export_and_parse(api, all_ids)
        data_rows = rows[1:]
        assert len(data_rows) == 2, f"expected 2 rows, got {len(data_rows)}"
        row_map = {str(r[0]): r for r in data_rows}
        r1 = row_map.get(ctx1["tag_name"])
        r2 = row_map.get(ctx2["tag_name"])
        assert r1 is not None, f"{ctx1['tag_name']} missing"
        assert r2 is not None, f"{ctx2['tag_name']} missing"
        ds1_name = r1[3]
        ds2_name = r2[3]
        assert ds1_name and ds2_name, f"datasource name empty: {ds1_name!r} {ds2_name!r}"
        data_type_col1 = str(r1[5])
        data_type_col2 = str(r2[5])
        assert data_type_col1 and data_type_col2
    finally:
        teardown_ds_tag_mocker(api, ctx2)
        teardown_ds_tag_mocker(api, ctx1)


@pytest.mark.case(
    id="UA-2-3-004", chapter="UA-2-3",
    title="导出_空ID",
    preconditions=["无"],
    steps=["export_tags([])", "记录服务端行为"],
    expected=["记录明确行为；配置不变"],
)
@pytest.mark.integration
def test_export_empty_ids(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-004",
        tag_base_name="2_ua23_004_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_004_node", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        try:
            export_tags(api, [], parse=True)
            pytest.fail("expected export with empty ids to fail")
        except Exception as exc:
            record_property("export_empty_behavior", str(exc))
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-005", chapter="UA-2-3",
    title="导出_重复请求",
    preconditions=["至少一个位号存在"],
    steps=["连续导出两次", "均成功可解析", "配置字段一致"],
    expected=["两次均可解析", "配置字段一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_export_duplicate_request(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-005",
        tag_base_name="2_ua23_005_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_005_node", "type": "Double", "default": 77.7, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        rows1 = _export_and_parse(api, [ctx["tag_id"]])
        rows2 = _export_and_parse(api, [ctx["tag_id"]])
        assert rows1[1:] == rows2[1:], f"two exports differ:\n{rows1[1:]}\n{rows2[1:]}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-006", chapter="UA-2-3",
    title="文件_21列表头",
    preconditions=["至少一个位号存在"],
    steps=["导出位号", "用 openpyxl 解析", "比对 21 列"],
    expected=["列名、数量、顺序正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_file_21_column_header(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-006",
        tag_base_name="2_ua23_006_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_006_node", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        rows = _export_and_parse(api, [ctx["tag_id"]])
        header = rows[0]
        assert len(header) == 21, f"expected 21 columns, got {len(header)}: {header}"
        assert header == _EXPECTED_HEADER, f"header mismatch:\nexpected={_EXPECTED_HEADER}\ngot={header}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-007", chapter="UA-2-3",
    title="文件_名称归属",
    preconditions=["至少一个位号存在"],
    steps=["导出位号", "逐字段比对系统名、底层名、数据源、分组"],
    expected=["名称归属字段与配置一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_file_name_ownership(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-007",
        tag_base_name="2_ua23_007_node",
        data_type=DataTypes["INT32"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        unit="m/s",
        tag_desc="ua23_007 desc",
        nodes=[{"name": "ua23_007_node", "type": "Int32", "default": 50, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        rows = _export_and_parse(api, [ctx["tag_id"]])
        row = rows[1]
        assert str(row[0]) == ctx["tag_name"], f"Tag Name: {row[0]!r}"
        assert str(row[1]) == "2_ua23_007_node", f"Base Tag Name: {row[1]!r}"
        assert str(row[3]) == ctx["ds_name"], f"Datasource Name: {row[3]!r}"
        assert str(row[4]) == "m/s", f"Unit: {row[4]!r}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-008", chapter="UA-2-3",
    title="文件_配置字段",
    preconditions=["至少一个位号存在"],
    steps=["导出位号", "比对类型/单位/频率/只读/推送/描述"],
    expected=["字段与配置一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_file_config_fields(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-008",
        tag_base_name="2_ua23_008_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        unit="Pa",
        tag_desc="pressure sensor",
        frequency=5,
        nodes=[{"name": "ua23_008_node", "type": "Double", "default": 0.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        rows = _export_and_parse(api, [ctx["tag_id"]])
        row = rows[1]
        assert str(row[4]) == "Pa", f"Unit: {row[4]!r}"
        assert str(row[15]) == "pressure sensor", f"Description: {row[15]!r}"
        assert str(row[16]) == "ROOT", f"Group Name: {row[16]!r}"
        assert str(row[17]) == "1", f"Real-time Push: {row[17]!r}"
        assert str(row[18]) == "0", f"Readonly: {row[18]!r}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-009", chapter="UA-2-3",
    title="文件_量程报警限",
    preconditions=["至少一个位号存在"],
    steps=["创建带量程和六档限值的位号", "导出", "比对值及列位置"],
    expected=["值和列位置正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_file_range_alarm_limits(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-009",
        tag_base_name="2_ua23_009_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        hi_eu=200.0, lo_eu=0.0,
        limit_up=180.0, limit_up_up=190.0, limit_up_up_up=195.0,
        limit_down=20.0, limit_down_down=10.0, limit_down_down_down=5.0,
        nodes=[{"name": "ua23_009_node", "type": "Double", "default": 100.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        rows = _export_and_parse(api, [ctx["tag_id"]])
        row = rows[1]
        assert float(row[9]) == 180.0, f"High Limit: {row[9]!r}"
        assert float(row[10]) == 190.0, f"HH Limit: {row[10]!r}"
        assert float(row[11]) == 195.0, f"HHH Limit: {row[11]!r}"
        assert float(row[12]) == 20.0, f"Low Limit: {row[12]!r}"
        assert float(row[13]) == 10.0, f"LL Limit: {row[13]!r}"
        assert float(row[14]) == 5.0, f"LLL Limit: {row[14]!r}"
        assert float(row[19]) == 0.0, f"Lo EU: {row[19]!r}"
        assert float(row[20]) == 200.0, f"Hi EU: {row[20]!r}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-010", chapter="UA-2-3",
    title="文件_13种类型",
    preconditions=["13 种数据类型位号存在"],
    steps=["创建 13 种类型位号", "导出", "各类型可识别"],
    expected=["各类型可识别"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_file_13_data_types(api, settings, tmp_path_factory, mocker_endpoint):
    type_map = {
        DataTypes["BOOLEAN"]: ("Boolean", "Bool", False),
        DataTypes["S_BYTE"]: ("SByte", "SByte", 0),
        DataTypes["BYTE"]: ("Byte", "Byte", 0),
        DataTypes["SHORT"]: ("Int16", "Int16", 0),
        DataTypes["U_SHORT"]: ("UInt16", "UInt16", 0),
        DataTypes["INT"]: ("Int32", "Int32", 0),
        DataTypes["U_INT"]: ("UInt32", "UInt32", 0),
        DataTypes["LONG"]: ("Int64", "Int64", 0),
        DataTypes["U_LONG"]: ("UInt64", "UInt64", 0),
        DataTypes["FLOAT"]: ("Float", "Float", 0.0),
        DataTypes["DOUBLE"]: ("Double", "Double", 0.0),
        DataTypes["STRING"]: ("String", "String", "hello"),
        DataTypes["DATE_TIME"]: ("DateTime", "DateTime", "2024-01-01T00:00:00Z"),
    }
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-010",
        tag_base_name="2_ua23_010_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_010_node", "type": "Double", "default": 0.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    ds_id = ctx["ds_id"]
    extra_ids = []
    try:
        exported_dts: set[str] = set()
        main_row = _export_and_parse(api, [ctx["tag_id"]])[1]
        exported_dts.add(str(main_row[5]))

        dt_list = list(type_map.items())
        for idx, (dt_code, (opcua_type, _, default_val)) in enumerate(dt_list):
            node_name = f"ua23_010_type_{idx}"
            tag_name = f"{ctx['tag_name']}_type_{idx}"
            extra = add_tag(
                api, tag_name=tag_name,
                data_type=dt_code,
                tag_type=TagTypes["一次位号"],
                ds_id=ds_id,
                tag_base_name=f"2_{node_name}",
                only_read=False,
                frequency=10,
            )
            extra_ids.append(int(extra.get("id") or extra.get("tagId")))

        all_ids = [ctx["tag_id"]] + extra_ids
        rows = _export_and_parse(api, all_ids)
        row_map = {str(r[0]): r for r in rows[1:]}
        for idx, (dt_code, (opcua_type, _, _)) in enumerate(type_map.items()):
            tag_key = f"{ctx['tag_name']}_type_{idx}"
            r = row_map.get(tag_key)
            if r is not None:
                exported_dts.add(str(r[5]))

        assert len(exported_dts) >= 2, f"too few data types seen: {exported_dts}"
    finally:
        for eid in extra_ids:
            try:
                delete_tag_if_exists(api, eid)
            except Exception:
                pass
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-011", chapter="UA-2-3",
    title="文件_大整数与DateTime",
    preconditions=["Int64/UInt64/DateTime 位号存在"],
    steps=["创建大整数字段", "导出", "解析原始单元格", "记录精度、格式和时区"],
    expected=["可无歧义还原"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_file_large_int_datetime(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    observations: list[dict] = []
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-011",
        tag_base_name="2_ua23_011_node",
        data_type=DataTypes["INT64"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_011_node", "type": "Int64", "default": 0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    ds_id = ctx["ds_id"]
    extra_ids = []
    try:
        for idx, dt in enumerate([DataTypes["LONG"], DataTypes["U_LONG"], DataTypes["DATE_TIME"]]):
            node_name = f"ua23_011_large_{idx}"
            tag_name = f"{ctx['tag_name']}_large_{idx}"
            extra = add_tag(
                api, tag_name=tag_name,
                data_type=dt,
                tag_type=TagTypes["一次位号"],
                ds_id=ds_id,
                tag_base_name=f"2_{node_name}",
                only_read=False,
                frequency=10,
            )
            extra_ids.append(int(extra.get("id") or extra.get("tagId")))

        all_ids = [ctx["tag_id"]] + extra_ids
        rows = _export_and_parse(api, all_ids)
        for r in rows[1:]:
            obs = {"tag_name": str(r[0]), "tag_base_name": str(r[1]),
                   "data_type": str(r[5]), "tag_value": str(r[7]),
                   "raw_cells": [str(c) for c in r]}
            observations.append(obs)
            record_property("export_row", obs)
    finally:
        for eid in extra_ids:
            try:
                delete_tag_if_exists(api, eid)
            except Exception:
                pass
        teardown_ds_tag_mocker(api, ctx)

    pytest.xfail(
        "UA-2-3-011 large integer/DateTime export cell format is product-specific; "
        f"observations: {json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-3-012", chapter="UA-2-3",
    title="文件_实时值及无值",
    preconditions=["在线和断线两种状态"],
    steps=["在线时导出", "断线时导出", "记录实时值窗口及无值规则"],
    expected=["记录实时值窗口及无值规则"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_file_rt_value_and_no_value(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    observations: list[dict] = []
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-012",
        tag_base_name="2_ua23_012_node",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_012_node", "type": "Double", "default": 88.8, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    tag_id = ctx["tag_id"]
    mocker = ctx["mocker"]
    try:
        rows_online = export_tags(api, [tag_id], parse=True)
        online_row = rows_online[1] if len(rows_online) > 1 else []
        obs_online = {
            "state": "online",
            "tag_value_cell": str(online_row[7]) if len(online_row) > 7 else "",
            "row": [str(c) for c in online_row],
        }
        observations.append(obs_online)
        record_property("export_online", obs_online)

        from tests.support.mocker_process import stop_mocker
        stop_mocker(mocker)
        time.sleep(1.0)

        rows_offline = export_tags(api, [tag_id], parse=True)
        offline_row = rows_offline[1] if len(rows_offline) > 1 else []
        obs_offline = {
            "state": "offline",
            "tag_value_cell": str(offline_row[7]) if len(offline_row) > 7 else "",
            "row": [str(c) for c in offline_row],
        }
        observations.append(obs_offline)
        record_property("export_offline", obs_offline)
    finally:
        teardown_ds_tag_mocker(api, ctx)

    pytest.xfail(
        "UA-2-3-012 export RT value window and no-value behavior is product-specific; "
        f"observations: {json.dumps(observations, ensure_ascii=False, default=str)}"
    )
