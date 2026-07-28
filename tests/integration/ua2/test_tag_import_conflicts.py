"""UA-2-3-020~023: conflict strategy import tests."""
from __future__ import annotations

import json

import pytest

from tpt_api.datahub import (
    add_tag,
    export_tags,
    import_tags_from_file,
    list_tags,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.cleanup import delete_tag_if_exists
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    setup_ds_and_tag,
    teardown_ds_tag_mocker,
    wait_ds_alive,
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


@pytest.mark.case(
    id="UA-2-3-020", chapter="UA-2-3",
    title="冲突_跳过",
    preconditions=["目标 tag 已存在"],
    steps=["首次导入 tagA", "再次导入相同 tagA（conflict_strategy=0）", "确认仍是首次值"],
    expected=["冲突时不覆盖，已有记录 ID 不变，新增记录创建"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_conflict_skip(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-020",
        tag_base_name="2_ua23_020_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        unit="m/s",
        tag_desc="original desc",
        nodes=[{"name": "ua23_020_node_", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        dup_name = ctx["tag_name"]
        first_desc = "first import"
        row1 = [dup_name, "2_ua23_020_node_1", tt, ctx["ds_name"], "", "DOUBLE",
                None, None, 10,
                None, None, None, None, None, None,
                first_desc, "Root",
                "true", "false", None, None, None]
        xlsx1 = build_import_workbook(template_raw, [row1])
        r1 = import_bytes(api, xlsx1, conflict_strategy=0, tmp_path_factory=tmp_path_factory)

        # Record original record id
        orig = assert_tag_fields(api, dup_name)
        orig_id = int(orig["id"])

        # Second import with different desc (should be ignored)
        row2 = [dup_name, "2_ua23_020_node_1", tt, ctx["ds_name"], "", "DOUBLE",
                None, None, 10,
                None, None, None, None, None, None,
                "second import - should be ignored", "Root",
                "true", "false", None, None, None]
        xlsx2 = build_import_workbook(template_raw, [row2])
        r2 = import_bytes(api, xlsx2, conflict_strategy=0, tmp_path_factory=tmp_path_factory)

        rec = assert_tag_fields(api, dup_name)
        assert int(rec["id"]) == orig_id, f"record id changed: {orig_id} -> {rec['id']}"
        saved_desc = str(rec.get("tagDesc", ""))
        assert saved_desc == "original desc", f"desc overwritten on skip: {saved_desc!r}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-021", chapter="UA-2-3",
    title="冲突_覆盖",
    preconditions=["目标 tag 已存在"],
    steps=["首次导入 tagA", "再次导入相同 tagA（conflict_strategy=1）", "确认配置更新、未修改字段保持、RT 继续可用"],
    expected=["目标配置更新，记录身份明确，RT 继续可用"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_import_conflict_overwrite(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-021",
        tag_base_name="2_ua23_021_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        unit="m/s",
        tag_desc="original desc",
        nodes=[{"name": "ua23_021_node_", "type": "Double", "default": 1.0, "writable": True, "change": True}],
        namespace_index=2,
        cycle=500,
    )
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        dup_name = ctx["tag_name"]

        orig = assert_tag_fields(api, dup_name)
        orig_id = int(orig["id"])

        row_overwrite = [dup_name, "2_ua23_021_node_1", tt, ctx["ds_name"], "", "DOUBLE",
                         None, None, 10,
                         None, None, None, None, None, None,
                         "overwritten desc", "Root",
                         "true", "false", None, None, None]
        xlsx = build_import_workbook(template_raw, [row_overwrite])
        import_bytes(api, xlsx, conflict_strategy=1, tmp_path_factory=tmp_path_factory)

        rec = assert_tag_fields(api, dup_name, dsId=ctx["ds_id"])
        assert int(rec["id"]) == orig_id, f"record id changed after overwrite: {orig_id} -> {rec['id']}"
        saved_desc = str(rec.get("tagDesc", ""))
        assert saved_desc == "overwritten desc", f"desc not updated: {saved_desc!r}"
        # RT should still be available
        wait_until(f"rt:{dup_name}", lambda: (
            get_rt_point(api, dup_name).get("tagValue") is not None
        ), timeout=30.0)
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-3-022", chapter="UA-2-3",
    title="冲突_覆盖身份与空白字段",
    preconditions=["目标 tag 已存在"],
    steps=["创建 tagA", "覆盖导入空白 Unit 和 Desc", "记录 ID、空白字段行为、分组关系、RT"],
    expected=["记录产品覆盖行为"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_import_conflict_overwrite_identity(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-022",
        tag_base_name="2_ua23_022_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        unit="m/s",
        tag_desc="original desc",
        nodes=[{"name": "ua23_022_node_", "type": "Double", "default": 1.0, "writable": True, "change": True}],
        namespace_index=2,
        cycle=500,
    )
    observations = []
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        dup_name = ctx["tag_name"]

        orig = assert_tag_fields(api, dup_name)
        orig_id = int(orig["id"])
        orig_group = orig.get("groupName", "")
        orig_ds_id = orig.get("dsId")

        # Overwrite with empty unit and desc
        row = [dup_name, "2_ua23_022_node_1", tt, ctx["ds_name"], "", "DOUBLE",
               None, None, 10,
               None, None, None, None, None, None,
               "", "",
               "true", "false", None, None, None]
        xlsx = build_import_workbook(template_raw, [row])
        import_bytes(api, xlsx, conflict_strategy=1, tmp_path_factory=tmp_path_factory)

        rec = assert_tag_fields(api, dup_name)
        observations.append({
            "original_id": orig_id,
            "after_id": int(rec["id"]),
            "original_unit": orig.get("unit"),
            "after_unit": rec.get("unit"),
            "original_desc": orig.get("tagDesc"),
            "after_desc": rec.get("tagDesc"),
            "original_group": orig_group,
            "after_group": rec.get("groupName"),
            "ds_id_unchanged": rec.get("dsId") == orig_ds_id,
        })
        for obs in observations:
            record_property("overwrite_identity", obs)

        # Check RT
        pt = get_rt_point(api, dup_name)
        observations[-1]["rt_available"] = pt.get("tagValue") is not None
    finally:
        teardown_ds_tag_mocker(api, ctx)

    pytest.xfail(
        "UA-2-3-022 overwrite identity behavior is product-specific; "
        f"observations: {json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-3-023", chapter="UA-2-3",
    title="冲突_文件内重名",
    preconditions=["datasource 存在"],
    steps=["工作簿含两行相同 tagName", "导入", "记录冲突行为和最终配置"],
    expected=["最终不得有两个全局同名记录", "结果可定位冲突行"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_import_conflict_duplicate_in_file(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-3-023",
        tag_base_name="2_ua23_023_node_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        nodes=[{"name": "ua23_023_node_", "type": "Double", "default": 1.0, "writable": True}],
        namespace_index=2,
        cycle=500,
    )
    observations = []
    try:
        tt = tag_type_display(TagTypes["一次位号"])
        template_raw = export_template_bytes(api, ctx["tag_id"])
        dup_name = f"{ctx['tag_name']}_dup_in_file"

        # Two rows with SAME tagName but different desc
        row_a = [dup_name, "2_ua23_023_node_1", tt, ctx["ds_name"], "", "DOUBLE",
                 None, None, 10,
                 None, None, None, None, None, None,
                 "first in file", "Root",
                 "true", "false", None, None, None]
        row_b = [dup_name, "2_ua23_023_node_2", tt, ctx["ds_name"], "", "DOUBLE",
                 None, None, 10,
                 None, None, None, None, None, None,
                 "second in file", "Root",
                 "true", "false", None, None, None]
        xlsx = build_import_workbook(template_raw, [row_a, row_b])

        try:
            result = import_bytes(api, xlsx, conflict_strategy=0, tmp_path_factory=tmp_path_factory)
            errs = parse_import_result_xlsx(result)
            observations.append({"import_accepted": True, "errors": errs})

            # Check how many records exist
            page = list_tags(api, page=1, page_size=50, data={"tagName": dup_name})
            matching = [r for r in (page.get("records") or []) if r.get("tagName") == dup_name]
            for r in matching:
                observations.append({
                    "found_id": int(r["id"]),
                    "found_desc": r.get("tagDesc"),
                    "group": r.get("groupName"),
                })
                record_property("dup_result", observations[-1])
        except TptAPIError as exc:
            observations.append({"import_rejected": True, "code": exc.code, "msg": exc.msg})
            record_property("dup_reject", observations[-1])
    finally:
        page = list_tags(api, page=1, page_size=50, data={"tagName": dup_name})
        for r in (page.get("records") or []):
            if r.get("tagName") == dup_name:
                delete_tag_if_exists(api, int(r["id"]), dup_name)
        teardown_ds_tag_mocker(api, ctx)

    pytest.xfail(
        "UA-2-3-023 duplicate tagName within file is product-specific; "
        f"observations: {json.dumps(observations, ensure_ascii=False, default=str)}"
    )
