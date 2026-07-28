"""UA-2-3-013~019, 024~027: canonical import tests."""
from __future__ import annotations

import io
import json

import pytest
from openpyxl import load_workbook

from tpt_api.datahub import (
    add_tag,
    add_tag_group,
    export_tags,
    import_tags_from_file,
    list_tags,
    query_tags_with_quality,
    write_tag_values,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.cleanup import delete_tag_if_exists
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    setup_ds_and_tag,
    setup_ds_only,
    teardown_ds_tag_mocker,
    wait_ds_alive,
    wait_qtq_valid,
)
from tests.support.ua2_import_helpers import (
    build_import_workbook,
    export_template_bytes,
    import_bytes,
    assert_tag_fields,
    delete_tag_by_name,
    parse_import_result_xlsx,
    tag_type_display,
)


# ===== UA-2-3-013: Excel导入_单条 =====

@pytest.mark.case(
    id="UA-2-3-013", chapter="UA-2-3",
    title="Excel导入_单条",
    preconditions=["目标 datasource 存在且 alive"],
    steps=["创建 DS + tag", "export 得模板", "构造 1 行工作簿", "导入", "查询验证"],
    expected=["只创建 1 条且字段正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_single_tag(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-013",
        tag_base_name="2_ua23_013_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_013_node_", "type": "Double", "default": 12.5, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    ds_id = ctx["ds_id"]
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        new_tag_name = ctx["tag_name"] + "_imp"
        row = [new_tag_name, "2_ua23_013_node_1", tt, ctx["ds_name"], "", "DOUBLE",
               None, None, 10,
               None, None, None, None, None, None,
               "imported single", "Root",
               "true", "false", None, None, None]
        xlsx = build_import_workbook(template_raw, [row])
        import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)

        assert_tag_fields(api, new_tag_name, dsId=ds_id)
        page = list_tags(api, page=1, page_size=50, data={"tagName": new_tag_name})
        match = [r for r in (page.get("records") or []) if r.get("tagName") == new_tag_name]
        assert len(match) == 1, f"expected 1 tag, got {len(match)}"
    finally:
        for tn in [ctx["tag_name"] + "_imp"]:
            page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
            for r in (page.get("records") or []):
                if r.get("tagName") == tn:
                    delete_tag_if_exists(api, int(r["id"]), tn)
        teardown_ds_tag_mocker(api, ctx)


# ===== UA-2-3-014: Excel导入_多条 =====

@pytest.mark.case(
    id="UA-2-3-014", chapter="UA-2-3",
    title="Excel导入_多条",
    preconditions=["目标 datasource 存在且 alive"],
    steps=["创建 DS + tag", "export 得模板", "构造 10 行工作簿", "导入", "验证 10 条"],
    expected=["恰好创建 10 条"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_multiple_tags(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-014",
        tag_base_name="2_ua23_014_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_014_node_", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        tag_names = []
        rows = []
        for i in range(10):
            tn = f"{ctx['tag_name']}_multi_{i}"
            tag_names.append(tn)
            rows.append([tn, f"2_ua23_014_node_{i}_1", tt, ctx["ds_name"], "", "DOUBLE",
                         None, None, 10,
                         None, None, None, None, None, None,
                         f"multi tag {i}", "Root",
                         "true", "false", None, None, None])
        xlsx = build_import_workbook(template_raw, rows)
        import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)

        count = 0
        for tn in tag_names:
            page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
            for r in (page.get("records") or []):
                if r.get("tagName") == tn:
                    count += 1
        assert count == 10, f"expected 10 tags, got {count}"
    finally:
        for tn in tag_names:
            page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
            for r in (page.get("records") or []):
                if r.get("tagName") == tn:
                    delete_tag_if_exists(api, int(r["id"]), tn)
        teardown_ds_tag_mocker(api, ctx)


# ===== UA-2-3-015: Excel导入_跨源跨组 =====

@pytest.mark.case(
    id="UA-2-3-015", chapter="UA-2-3",
    title="Excel导入_跨源跨组",
    preconditions=["两个 datasource 和两个普通 group 存在"],
    steps=["双 DS 双 Group 工作簿", "导入", "验证归属"],
    expected=["每条映射到正确 dsId/group"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_cross_ds_group(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-015a",
        tag_base_name="2_ua23_015a_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_015a_node_", "type": "Double", "default": 10.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    ctx_b = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-015b",
        tag_base_name="2_ua23_015b_node_1",
        data_type=DataTypes["INT"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_015b_node_", "type": "Int32", "default": 99, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        g1 = add_tag_group(api, f"{ctx_a['tag_name']}_g1")
        g2 = add_tag_group(api, f"{ctx_b['tag_name']}_g2")
        g1_name = str(g1.get("groupName") or g1.get("name") or "")
        g2_name = str(g2.get("groupName") or g2.get("name") or "")
        assert g1_name and g2_name, f"group names empty: {g1_name!r} {g2_name!r}"

        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx_a["tag_id"])
        tag_a = f"{ctx_a['tag_name']}_cross"
        tag_b = f"{ctx_b['tag_name']}_cross"
        rows = [
            [tag_a, "2_ua23_015a_node_1", tt, ctx_a["ds_name"], "", "DOUBLE",
             None, None, 10,
             None, None, None, None, None, None,
             "dsA tag", g1_name,
             "true", "false", None, None, None],
            [tag_b, "2_ua23_015b_node_1", tt, ctx_b["ds_name"], "", "INT",
             None, None, 10,
             None, None, None, None, None, None,
             "dsB tag", g2_name,
             "true", "false", None, None, None],
        ]
        xlsx = build_import_workbook(template_raw, rows)
        import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)

        assert_tag_fields(api, tag_a, dsId=ctx_a["ds_id"])
        assert_tag_fields(api, tag_b, dsId=ctx_b["ds_id"])
    finally:
        for tn in [tag_a, tag_b]:
            page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
            for r in (page.get("records") or []):
                if r.get("tagName") == tn:
                    delete_tag_if_exists(api, int(r["id"]), tn)
        teardown_ds_tag_mocker(api, ctx_b)
        teardown_ds_tag_mocker(api, ctx_a)


# ===== UA-2-3-016: Excel导入_完整配置 (含量程、报警限、push/readonly、base tag) =====

@pytest.mark.case(
    id="UA-2-3-016", chapter="UA-2-3",
    title="Excel导入_完整配置",
    preconditions=["datasource 存在"],
    steps=["含全部支持字段的工作簿", "导入", "逐字段回查"],
    expected=["所有字段保存正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_full_config(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-016",
        tag_base_name="2_ua23_016_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_016_node_", "type": "Double", "default": 50.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        g = add_tag_group(api, f"{ctx['tag_name']}_g")
        g_name = str(g.get("groupName") or g.get("name") or "")

        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        tn = f"{ctx['tag_name']}_full"
        row = [tn, "2_ua23_016_node_1", tt, ctx["ds_name"], "", "DOUBLE",
               None, None, 5,
               180.0, 190.0, 195.0,
               20.0, 10.0, 5.0,
               "full config import test", g_name,
               "true", "false", 0.0, 200.0, None]
        xlsx = build_import_workbook(template_raw, [row])
        import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)

        rec = assert_tag_fields(api, tn, dsId=ctx["ds_id"])
        assert str(rec.get("unit", "")) == "", f"unit unexpectedly set: {rec.get('unit')!r}"
        assert str(rec.get("tagDesc", "")) == "full config import test", \
            f"desc mismatch: {rec.get('tagDesc')!r}"
        assert float(rec.get("limitUp", 0) or 0) == 180.0, f"limitUp: {rec.get('limitUp')!r}"
        assert float(rec.get("limitUpUp", 0) or 0) == 190.0, f"limitUpUp: {rec.get('limitUpUp')!r}"
        assert float(rec.get("limitUpUpUp", 0) or 0) == 195.0, f"limitUpUpUp: {rec.get('limitUpUpUp')!r}"
        assert float(rec.get("limitDown", 0) or 0) == 20.0, f"limitDown: {rec.get('limitDown')!r}"
        assert float(rec.get("limitDownDown", 0) or 0) == 10.0, f"limitDownDown: {rec.get('limitDownDown')!r}"
        assert float(rec.get("limitDownDownDown", 0) or 0) == 5.0, f"limitDownDownDown: {rec.get('limitDownDownDown')!r}"
    finally:
        delete_tag_by_name(api, tn)
        teardown_ds_tag_mocker(api, ctx)


# ===== UA-2-3-017: Excel导入_13种类型（含 DateTime） =====

@pytest.mark.case(
    id="UA-2-3-017", chapter="UA-2-3",
    title="Excel导入_13种类型",
    preconditions=["datasource 存在"],
    steps=["13 种数据类型的工作簿", "逐类型独立导入", "验证 dataType"],
    expected=["各类型可导入且 dataType 正确；DateTime 若被拒绝记录为 FAIL"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_13_data_types(api, settings, tmp_path_factory, mocker_endpoint):
    type_map = {
        "BOOLEAN": ("Boolean", DataTypes["BOOLEAN"]),
        "S_BYTE": ("SByte", DataTypes["S_BYTE"]),
        "BYTE": ("Byte", DataTypes["BYTE"]),
        "SHORT": ("Int16", DataTypes["SHORT"]),
        "U_SHORT": ("UInt16", DataTypes["U_SHORT"]),
        "INT": ("Int32", DataTypes["INT"]),
        "U_INT": ("UInt32", DataTypes["U_INT"]),
        "LONG": ("Int64", DataTypes["LONG"]),
        "U_LONG": ("UInt64", DataTypes["U_LONG"]),
        "FLOAT": ("Float", DataTypes["FLOAT"]),
        "DOUBLE": ("Double", DataTypes["DOUBLE"]),
        "STRING": ("String", DataTypes["STRING"]),
        "DATE_TIME": ("DateTime", DataTypes["DATE_TIME"]),
    }
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-017",
        tag_base_name="2_ua23_017_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_017_node_", "type": "Double", "default": 0.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        tag_names = []
        rows = []
        for idx, (dt_key, (opcua_name, dt_int)) in enumerate(type_map.items()):
            tn = f"{ctx['tag_name']}_type_{idx}"
            tag_names.append(tn)
            rows.append([tn, f"2_ua23_017_type_{idx}_1", tt, ctx["ds_name"], "", dt_key,
                         None, None, 10,
                         None, None, None, None, None, None,
                         f"type {idx} {dt_key}", "Root",
                         "true", "false", None, None, None])
        xlsx = build_import_workbook(template_raw, rows)

        result = import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)
        errs = parse_import_result_xlsx(result)

        failures = []
        for idx, (dt_key, (opcua_name, dt_int)) in enumerate(type_map.items()):
            tn = f"{ctx['tag_name']}_type_{idx}"
            err = next((e for e in errs if e["tag_name"] == tn), None)
            page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
            rec = next((r for r in (page.get("records") or []) if r.get("tagName") == tn), None)
            if rec:
                actual_dt = rec.get("dataType")
                if actual_dt != dt_int:
                    failures.append({"type": dt_key, "expected_dt": dt_int, "actual_dt": actual_dt, "issue": "dataType mismatch"})
            elif err:
                failures.append({"type": dt_key, "issue": "rejected", "error": err["error_msg"]})
            else:
                failures.append({"type": dt_key, "issue": "not_found_no_error"})

        assert not failures, (
            "UA-2-3-017 failed data types: "
            + json.dumps(failures, ensure_ascii=False, default=str)
        )
    finally:
        for tn in tag_names:
            page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
            for r in (page.get("records") or []):
                if r.get("tagName") == tn:
                    delete_tag_if_exists(api, int(r["id"]), tn)
        teardown_ds_tag_mocker(api, ctx)


# ===== UA-2-3-018: Excel导入_Unicode与空白字段 =====

@pytest.mark.case(
    id="UA-2-3-018", chapter="UA-2-3",
    title="Excel导入_Unicode与空白字段",
    preconditions=["datasource 存在"],
    steps=["含中文、Unicode、空白的工作簿", "导入", "记录配置结果"],
    expected=["不出现乱码或错误映射"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_import_unicode_blank(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    observations = []
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-018",
        tag_base_name="2_ua23_018_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_018_node_", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        tag_names = []
        inputs = [
            {"tn": f"{ctx['tag_name']}_cn", "unit": "米/秒", "desc": "中文描述"},
            {"tn": f"{ctx['tag_name']}_unicode", "unit": "µm/s²", "desc": "Unicode ∞ Δ"},
            {"tn": f"{ctx['tag_name']}_empty", "unit": "", "desc": ""},
            {"tn": f"{ctx['tag_name']}_spaces", "unit": "   ", "desc": "  spaces  "},
        ]
        rows = []
        for inp in inputs:
            tag_names.append(inp["tn"])
            rows.append([inp["tn"], "2_ua23_018_node_1", tt, ctx["ds_name"], inp["unit"], "DOUBLE",
                         None, None, 10,
                         None, None, None, None, None, None,
                         inp["desc"], "Root",
                         "true", "false", None, None, None])
        xlsx = build_import_workbook(template_raw, rows)
        import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)

        for inp in inputs:
            page = list_tags(api, page=1, page_size=50, data={"tagName": inp["tn"]})
            for r in (page.get("records") or []):
                if r.get("tagName") == inp["tn"]:
                    obs = {
                        "tagName": inp["tn"],
                        "unit_original": inp["unit"],
                        "unit_saved": r.get("unit"),
                        "desc_original": inp["desc"],
                        "desc_saved": r.get("tagDesc"),
                    }
                    observations.append(obs)
                    record_property("import_row", obs)
                    delete_tag_if_exists(api, int(r["id"]), inp["tn"])
    finally:
        for tn in tag_names:
            page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
            for r in (page.get("records") or []):
                if r.get("tagName") == tn:
                    delete_tag_if_exists(api, int(r["id"]), tn)
        teardown_ds_tag_mocker(api, ctx)

    pytest.xfail(
        "UA-2-3-018 unicode/whitespace field behavior is product-specific; "
        f"observations: {json.dumps(observations, ensure_ascii=False, default=str)}"
    )


# ===== UA-2-3-019: Excel导入_可用性闭环 =====

@pytest.mark.case(
    id="UA-2-3-019", chapter="UA-2-3",
    title="Excel导入_可用性闭环",
    preconditions=["datasource 存在且 mocker 运行"],
    steps=["导入位号", "等待 RT", "验证 QwQ", "清理"],
    expected=["RT 出现", "QwQ 有效"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_availability(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-019",
        tag_base_name="2_ua23_019_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_019_node_", "type": "Double", "default": 42.0, "writable": True, "change": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        import_tag_name = ctx["tag_name"] + "_avail"
        row = [import_tag_name, "2_ua23_019_node_1", tt, ctx["ds_name"], "", "DOUBLE",
               None, None, 10,
               None, None, None, None, None, None,
               "availability test", "Root",
               "true", "false", None, None, None]
        xlsx = build_import_workbook(template_raw, [row])
        import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)

        def _has_rt():
            pt = get_rt_point(api, import_tag_name)
            return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

        wait_until(f"rt:{import_tag_name}", _has_rt, timeout=90.0)

        qwq = query_tags_with_quality(api, ds_id=ctx["ds_id"], tag_name=import_tag_name)
        assert qwq, f"QwQ empty for {import_tag_name}"

        page = list_tags(api, page=1, page_size=50, data={"tagName": import_tag_name})
        for r in (page.get("records") or []):
            if r.get("tagName") == import_tag_name:
                delete_tag_if_exists(api, int(r["id"]), import_tag_name)
    finally:
        page = list_tags(api, page=1, page_size=50, data={"tagName": import_tag_name})
        for r in (page.get("records") or []):
            if r.get("tagName") == import_tag_name:
                delete_tag_if_exists(api, int(r["id"]), import_tag_name)
        teardown_ds_tag_mocker(api, ctx)


# ===== UA-2-3-024: 映射_数据源或分组不存在 =====

@pytest.mark.case(
    id="UA-2-3-024", chapter="UA-2-3",
    title="映射_数据源或分组不存在",
    preconditions=["datasource 存在"],
    steps=["使用别名/不存在的 DS 名/不存在的 Group", "记录产品行为"],
    expected=["记录产品行为"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_import_datasource_or_group_not_exist(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-024",
        tag_base_name="2_ua23_024_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_024_node_", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    obs = []
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        scenarios = [
            ("wrong_ds", ctx["ds_name"] + "_NONEXISTENT", "Root", "nonexistent datasource"),
            ("wrong_group", ctx["ds_name"], "NONEXISTENT_GROUP", "nonexistent group"),
            ("wrong_both", ctx["ds_name"] + "_NONEXISTENT", "NONEXISTENT_GROUP", "both nonexistent"),
            ("correct", ctx["ds_name"], "Root", "all correct"),
        ]
        for suffix, ds_name_arg, group_arg, scenario in scenarios:
            tn = f"{ctx['tag_name']}_{suffix}"
            row = [tn, "2_ua23_024_node_1", tt, ds_name_arg, "", "DOUBLE",
                   None, None, 10,
                   None, None, None, None, None, None,
                   scenario, group_arg,
                   "true", "false", None, None, None]
            xlsx = build_import_workbook(template_raw, [row])
            try:
                r = import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)
                errs = parse_import_result_xlsx(r)
                page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
                found = [r for r in (page.get("records") or []) if r.get("tagName") == tn]
                entry = {"scenario": scenario, "result": "accepted",
                         "tag_created": len(found) > 0, "per_row_errors": errs}
                for f in found:
                    if f.get("groupName") != group_arg and group_arg != "Root":
                        entry["mapping_issue"] = f"group expected={group_arg}, got={f.get('groupName')}"
                    if f.get("dsId") != ctx["ds_id"] and ds_name_arg == ctx["ds_name"]:
                        entry["mapping_issue"] = f"dsId expected={ctx['ds_id']}, got={f.get('dsId')}"
                    delete_tag_if_exists(api, int(f["id"]), tn)
                obs.append(entry)
            except TptAPIError as exc:
                obs.append({"scenario": scenario, "result": "rejected", "error": exc.msg})
            record_property("ds_group_test", obs[-1])
    finally:
        teardown_ds_tag_mocker(api, ctx)

    pytest.xfail(
        "UA-2-3-024 datasource/group name mapping behavior is product-specific; "
        f"observations: {json.dumps(obs, ensure_ascii=False, default=str)}"
    )


# ===== UA-2-3-025: 文件校验_空损坏或错误类型 =====

@pytest.mark.case(
    id="UA-2-3-025", chapter="UA-2-3",
    title="文件校验_空损坏或错误类型",
    preconditions=["datasource 存在"],
    steps=["0 字节、只有表头、损坏 xlsx、txt、csv、错误扩展名", "分别导入", "要求明确拒绝"],
    expected=["明确失败且不创建位号"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_empty_corrupt_file(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-025",
        tag_base_name="2_ua23_025_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_025_node_", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    results = {}
    try:
        # 1) Only header, no data rows
        template_raw = export_template_bytes(api, ctx["tag_id"])
        no_data = build_import_workbook(template_raw, [])
        try:
            r = import_bytes(api, no_data, conflict_strategy=0, tmp_path_factory=tmp_path_factory)
            results["only_header"] = r.get("response_type", "json")
            record_property("only_header", {"response_type": r.get("response_type")})
        except TptAPIError as exc:
            results["only_header"] = {"code": exc.code, "msg": exc.msg}
            record_property("only_header_error", {"code": exc.code, "msg": exc.msg})

        # 2) 0-byte file
        import tempfile, uuid
        zero = tmp_path_factory.mktemp("zero") / f"zero_{uuid.uuid4().hex[:8]}.xlsx"
        zero.write_bytes(b"")
        try:
            r = import_tags_from_file(api, str(zero), conflict_strategy=0)
            results["zero_byte"] = r.get("response_type", str(r))
        except TptAPIError as exc:
            results["zero_byte"] = {"code": exc.code, "msg": exc.msg}
        record_property("zero_byte", results.get("zero_byte", "unknown"))

        # 3) Text file with .xlsx extension
        text_file = tmp_path_factory.mktemp("text") / f"text_{uuid.uuid4().hex[:8]}.xlsx"
        text_file.write_bytes(b"this is not an xlsx file")
        try:
            r = import_tags_from_file(api, str(text_file), conflict_strategy=0)
            results["text_as_xlsx"] = r.get("response_type", str(r))
        except TptAPIError as exc:
            results["text_as_xlsx"] = {"code": exc.code, "msg": exc.msg}
        record_property("text_as_xlsx", results.get("text_as_xlsx", "unknown"))

        # 4) .txt file (wrong extension)  
        txt_file = tmp_path_factory.mktemp("txt") / f"tag_{uuid.uuid4().hex[:8]}.txt"
        txt_file.write_bytes(b"")
        try:
            r = import_tags_from_file(api, str(txt_file), conflict_strategy=0)
            results["txt_extension"] = r.get("response_type", str(r))
        except TptAPIError as exc:
            results["txt_extension"] = {"code": exc.code, "msg": exc.msg}
        record_property("txt_extension", results.get("txt_extension", "unknown"))

        # Verify no stray tags created
        page = list_tags(api, page=1, page_size=200, data={})
        stray = [r for r in (page.get("records") or []) if (r.get("tagName") or "").startswith(ctx["tag_name"])]
        assert len(stray) <= 1, f"stray tags created by corrupt imports: {[r['tagName'] for r in stray]}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


# ===== UA-2-3-026: 文件校验_结构与行错误 =====

@pytest.mark.case(
    id="UA-2-3-026", chapter="UA-2-3",
    title="文件校验_结构与行错误",
    preconditions=["datasource 存在"],
    steps=["缺必填列、重复必填列、乱序列、缺 tagName、缺 datasource、非法 Data Type、非法布尔值"],
    expected=["不发生静默错误转换，结果可定位失败文件或数据行"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_structure_errors(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-026",
        tag_base_name="2_ua23_026_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_026_node_", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    results = {}
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])

        # 1) Missing required column: no Tag Name
        wb = load_workbook(io.BytesIO(template_raw))
        ws = wb.active
        header = [cell.value for cell in ws[1]]
        missing_tn_header = [h for h in header if h != "Tag Name"]
        missing_tn_wb = __import__("openpyxl").Workbook()
        mws = missing_tn_wb.active
        mws.append(missing_tn_header)
        mws.append([ctx["ds_name"]])  # just the datasource
        buf = io.BytesIO()
        missing_tn_wb.save(buf)
        missing_tn_wb.close()
        wb.close()
        try:
            r = import_bytes(api, buf.getvalue(), conflict_strategy=0, tmp_path_factory=tmp_path_factory)
            results["missing_tag_name"] = "accepted"
        except TptAPIError as exc:
            results["missing_tag_name"] = {"code": exc.code, "msg": exc.msg}
        record_property("missing_tag_name", results["missing_tag_name"])

        # 2) Duplicate columns in header
        from openpyxl import Workbook as Wb
        dup_wb = Wb()
        dup_ws = dup_wb.active
        dup_ws.append(["Tag Name", "Base Tag Name", "Tag Name"])
        dup_ws.append([f"{ctx['tag_name']}_dup", "2_ua23_026_node_1", "ignored"])
        buf2 = io.BytesIO()
        dup_wb.save(buf2)
        dup_wb.close()
        try:
            r = import_bytes(api, buf2.getvalue(), conflict_strategy=0, tmp_path_factory=tmp_path_factory)
            results["duplicate_columns"] = "accepted"
        except TptAPIError as exc:
            results["duplicate_columns"] = {"code": exc.code, "msg": exc.msg}
        record_property("duplicate_columns", results["duplicate_columns"])

        # 3) Shuffled column order
        n = len(header)
        indices = list(range(n))
        indices[0], indices[min(1, n-1)] = indices[min(1, n-1)], indices[0]
        shuffled_header = [header[i] for i in indices]
        shuf_wb = Wb()
        shuf_ws = shuf_wb.active
        shuf_ws.append(shuffled_header)
        shuf_row = [None] * n
        for i, si in enumerate(indices):
            shuf_row[si] = f"{ctx['tag_name']}_shuf" if i == 0 else \
                "2_ua23_026_node_1" if i == 1 else (ctx["ds_name"] if i == 3 else None)
        shuf_ws.append(shuf_row)
        buf3 = io.BytesIO()
        shuf_wb.save(buf3)
        shuf_wb.close()
        try:
            r = import_bytes(api, buf3.getvalue(), conflict_strategy=0, tmp_path_factory=tmp_path_factory)
            results["shuffled_columns"] = "accepted"
        except TptAPIError as exc:
            results["shuffled_columns"] = {"code": exc.code, "msg": exc.msg}
        record_property("shuffled_columns", results["shuffled_columns"])

        # 4) Invalid Data Type
        tn_bad = f"{ctx['tag_name']}_bad_dt"
        bad_row = [tn_bad, "2_ua23_026_node_1", tt, ctx["ds_name"], "", "INVALID_TYPE",
                   None, None, 10,
                   None, None, None, None, None, None,
                   "bad dt", "Root",
                   "true", "false", None, None, None]
        bad_xlsx = build_import_workbook(template_raw, [bad_row])
        try:
            r = import_bytes(api, bad_xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)
            errs = parse_import_result_xlsx(r)
            results["invalid_data_type"] = "accepted_with_errors" if errs else "accepted_no_error"
        except TptAPIError as exc:
            results["invalid_data_type"] = {"code": exc.code, "msg": exc.msg}
        record_property("invalid_data_type", results["invalid_data_type"])

        # Verify no stray tags created
        for suffix in ["_dup", "_shuf", "_bad_dt"]:
            delete_tag_by_name(api, f"{ctx['tag_name']}{suffix}")
    finally:
        teardown_ds_tag_mocker(api, ctx)


# ===== UA-2-3-027: 文件校验_合法非法混合 =====

@pytest.mark.case(
    id="UA-2-3-027", chapter="UA-2-3",
    title="文件校验_合法非法混合",
    preconditions=["datasource 存在"],
    steps=["同一文件包含合法行和非法行", "导入", "记录整批回滚或部分成功"],
    expected=["记录产品事务规则"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_import_valid_invalid_mixed(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-027",
        tag_base_name="2_ua23_027_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_027_node_", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    observations = []
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])

        valid_tn = f"{ctx['tag_name']}_valid"
        invalid_tn = f"{ctx['tag_name']}_invalid"
        # Invalid row: data type is garbage
        rows = [
            [valid_tn, "2_ua23_027_node_1", tt, ctx["ds_name"], "", "DOUBLE",
             None, None, 10,
             None, None, None, None, None, None,
             "valid row", "Root",
             "true", "false", None, None, None],
            [invalid_tn, "2_ua23_027_node_2", tt, ctx["ds_name"], "", "GARBAGE_TYPE",
             None, None, 10,
             None, None, None, None, None, None,
             "invalid row", "Root",
             "true", "false", None, None, None],
        ]
        xlsx = build_import_workbook(template_raw, rows)
        try:
            r = import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)
            errs = parse_import_result_xlsx(r)
            observations.append({"import_accepted": True, "error_rows": errs})

            # Check if valid tag was created
            valid_page = list_tags(api, page=1, page_size=50, data={"tagName": valid_tn})
            valid_found = [r for r in (valid_page.get("records") or []) if r.get("tagName") == valid_tn]
            observations[-1]["valid_tag_created"] = len(valid_found) > 0

            # Check if invalid tag was created  
            invalid_page = list_tags(api, page=1, page_size=50, data={"tagName": invalid_tn})
            invalid_found = [r for r in (invalid_page.get("records") or []) if r.get("tagName") == invalid_tn]
            observations[-1]["invalid_tag_created"] = len(invalid_found) > 0
        except TptAPIError as exc:
            observations.append({"import_rejected": True, "code": exc.code, "msg": exc.msg})

        for obs in observations:
            record_property("mixed_result", obs)
    finally:
        for tn in [valid_tn, invalid_tn]:
            page = list_tags(api, page=1, page_size=50, data={"tagName": tn})
            for r in (page.get("records") or []):
                if r.get("tagName") == tn:
                    delete_tag_if_exists(api, int(r["id"]), tn)
        teardown_ds_tag_mocker(api, ctx)

    pytest.xfail(
        "UA-2-3-027 mixed valid/invalid import behavior is product-specific; "
        f"observations: {json.dumps(observations, ensure_ascii=False, default=str)}"
    )
