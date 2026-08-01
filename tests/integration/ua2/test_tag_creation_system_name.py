from __future__ import annotations

import pytest

from tpt_api.datahub import add_tag, change_ds_state
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    delete_tags_safe,
    find_all_tags,
    find_unique_tag,
    opcua_read_sync,
    setup_ds_and_tag,
    setup_ds_only,
    teardown_ds_tag_mocker,
    try_add_tag,
)

_DOUBLE_CH = [
    {"name": "double_ch_", "type": "Double", "default": 3.14, "writable": True, "change": False, "count": 1},
]


def _named_tag(api, ctx: dict, *, tag_name: str, tag_base_name: str = "2_smoke_static_1",
               data_type: int = DataTypes["DOUBLE"]) -> dict:
    return add_tag(
        api, tag_name=tag_name, data_type=data_type,
        tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
        tag_base_name=tag_base_name,
    )


def _wait_rt(api, tag_name: str, timeout: float = 60.0) -> dict:
    def _has_rt():
        pt = get_rt_point(api, tag_name)
        return pt.get("tagValue") is not None and pt.get("quality", 0) != 0
    wait_until(f"rt:{tag_name}", _has_rt, timeout=timeout)
    return get_rt_point(api, tag_name)


@pytest.mark.case(
    id="UA-2-1-016",
    chapter="UA-2-1",
    title="系统位号名_与底层名独立",
    preconditions=["数据源 alive=true"],
    steps=[
        "新增 tagName=<unique>, tagBaseName=1_double_ch_1",
        "查询记录并读取 RT",
    ],
    expected=[
        "tagName 与 tagBaseName 分别按请求保存",
        "RT 来自 double_ch_1",
        "两字段互不覆盖",
        "RT 与 asyncua 源端值一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_system_name_independent_from_base(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-016",
        tag_base_name="1_double_ch_1",
        data_type=DataTypes["DOUBLE"],
        nodes=_DOUBLE_CH,
        namespace_index=1,
    )
    try:
        rec = find_unique_tag(api, ctx["tag_name"])
        assert rec.get("tagName") == ctx["tag_name"]
        assert rec.get("tagBaseName") == "1_double_ch_1"

        pt = _wait_rt(api, ctx["tag_name"], timeout=60.0)
        assert pt.get("tagValue") is not None
        assert pt.get("quality", 0) != 0

        src = opcua_read_sync(ctx["endpoint"], "double_ch_1", namespace_index=1)
        assert float(pt["tagValue"]) == pytest.approx(float(src))
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-017",
    chapter="UA-2-1",
    title="系统位号名_同数据源重复",
    preconditions=["同一数据源已存在 tagName"],
    steps=[
        "再次新增相同 tagName",
        "查询该名称全部记录",
    ],
    expected=[
        "第二次请求被拒绝",
        "仅保留原记录",
        "原记录字段未被覆盖",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_system_name_duplicate_same_ds(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-017")
    tag_name = unique_name(settings.test_prefix, "UA-2-1-017-tag")
    try:
        tag1 = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag1_id = int(tag1.get("id") or tag1.get("tagId"))

        with pytest.raises(TptAPIError) as exc_info:
            add_tag(
                api, tag_name=tag_name, data_type=DataTypes["INT"],
                tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
                tag_base_name="2_smoke_change_1",
            )
        assert exc_info.value.msg, "error message should not be empty"

        recs = find_all_tags(api, tag_name)
        assert len(recs) == 1, f"expected 1 record, got {len(recs)}"
        assert int(recs[0].get("id", -1)) == tag1_id, "original tag id changed"
        assert recs[0].get("dataType") is not None, "original fields should be intact"

        pt = _wait_rt(api, tag_name, timeout=60.0)
        assert pt.get("tagValue") is not None, "original tag RT should still work"
        assert pt.get("quality", 0) != 0
    finally:
        delete_tag_if_exists(api, tag1_id, tag_name)
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-018",
    chapter="UA-2-1",
    title="系统位号名_跨数据源重复",
    preconditions=["ds-A 已存在 tagName"],
    steps=[
        "ds-B 新增相同 tagName",
        "查询全局记录",
    ],
    expected=[
        "请求被拒绝",
        "全局仅存在 ds-A 原记录",
        "原记录不变",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_system_name_duplicate_cross_ds(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-018-a")
    tag_name = unique_name(settings.test_prefix, "UA-2-1-018-tag")
    try:
        tag_a = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx_a["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        tag_a_id = int(tag_a.get("id") or tag_a.get("tagId"))

        ctx_b = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-018-b")
        try:
            with pytest.raises(TptAPIError) as exc_info:
                add_tag(
                    api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                    tag_type=TagTypes["一次位号"], ds_id=ctx_b["ds_id"], only_read=True,
                    tag_base_name="2_smoke_static_1",
                )
            assert exc_info.value.msg, "error message should not be empty"

            recs = find_all_tags(api, tag_name)
            assert len(recs) == 1, f"expected 1 global record, got {len(recs)}"
            assert int(recs[0].get("id", -1)) == tag_a_id, "ds-A tag id changed"

            pt = get_rt_point(api, tag_name)
            assert pt.get("tagValue") is not None, "ds-A RT should still work"
        finally:
            teardown_ds_tag_mocker(api, ctx_b)
    finally:
        delete_tag_if_exists(api, tag_a_id, tag_name)
        teardown_ds_tag_mocker(api, ctx_a)


@pytest.mark.case(
    id="UA-2-1-019",
    chapter="UA-2-1",
    title="系统位号名_空字符串",
    preconditions=["数据源 alive=true"],
    steps=[
        "tagName=\"\" 调用 add_tag",
        "查询空名和测试前缀",
    ],
    expected=[
        "请求失败",
        "错误信息明确",
        "不生成残留位号",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_system_name_empty(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-019")
    residual_tag_id = None
    residual_tag_name = None
    try:
        result = try_add_tag(
            api, tag_name="", data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        if result["ok"]:
            residual_tag_id = int(result["data"].get("id") or result["data"].get("tagId"))
            residual_tag_name = result["data"].get("tagName", "")
            pytest.fail(f"product accepted empty tagName; saved as '{residual_tag_name}' (id={residual_tag_id})")

        recs = find_all_tags(api, "")
        assert len(recs) == 0, f"empty-tag-name records found: {len(recs)}"

        residual_recs = find_all_tags(api, settings.test_prefix + "UA-2-1-019")
        assert len(residual_recs) == 0, f"unexpected residual records: {len(residual_recs)}"
    finally:
        if residual_tag_id:
            delete_tag_if_exists(api, residual_tag_id, residual_tag_name)
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-020",
    chapter="UA-2-1",
    title="系统位号名_纯空白",
    preconditions=["数据源 alive=true"],
    steps=[
        "分别使用一个空格、多个空格、Tab 新增",
        "查询实际保存名称",
    ],
    expected=[
        "记录是否 trim 或拒绝",
        "不得生成多个不可区分的空白名称",
        "失败时不产生残留",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_system_name_whitespace(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-020")
    created: list[tuple[int, str]] = []
    observations: dict[str, dict] = {}
    try:
        inputs = [" ", "   ", "\t"]
        for inp in inputs:
            result = try_add_tag(
                api, tag_name=inp, data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
                tag_base_name="2_smoke_static_1",
            )
            entry: dict = {"accepted": result["ok"]}
            if result.get("error"):
                entry["error_msg"] = result["error"].msg
            if result["ok"]:
                tag_id = int(result["data"].get("id") or result["data"].get("tagId"))
                created.append((tag_id, inp))
                recs = find_all_tags(api, inp)
                entry["saved_name"] = recs[0].get("tagName", "") if recs else None
            observations[repr(inp)] = entry

        unique_saved = set()
        for _, tname in created:
            recs = find_all_tags(api, tname)
            if recs:
                unique_saved.add(recs[0].get("tagName", ""))
        assert len(created) == len(unique_saved), (
            "whitespace inputs must not produce indistinguishable names"
        )
    finally:
        delete_tags_safe(api, [tid for tid, _ in created])
        teardown_ds_tag_mocker(api, ctx)

    obs_str = "; ".join(f"{k}: accepted={v['accepted']}" for k, v in observations.items())
    pytest.xfail(
        f"UA-2-1-020 whitespace tagName semantics not specified; observed: {obs_str}"
    )


def _fixed_length_name(prefix: str, case_id: str, length: int) -> str:
    base = unique_name(prefix, case_id)
    if len(base) >= length:
        raise ValueError(f"base {base!r} ({len(base)}) already >= {length}")
    return base + "x" * (length - len(base))


@pytest.mark.case(
    id="UA-2-1-021",
    chapter="UA-2-1",
    title="系统位号名_长度边界127",
    preconditions=["数据源 alive=true"],
    steps=[
        "使用 127 字符名称新增",
        "查询名称与长度",
    ],
    expected=[
        "请求结果明确",
        "若成功，名称完整保存且长度为 127",
        "不得静默产生乱码",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_system_name_length_127(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-021")
    tag_name = _fixed_length_name(settings.test_prefix, "UA-2-1-021-tag", 127)
    tag_id = None
    try:
        result = try_add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        if result["ok"]:
            tag_id = int(result["data"].get("id") or result["data"].get("tagId"))
            rec = find_unique_tag(api, tag_name)
            assert rec, "tag should exist"
            assert rec.get("tagName") == tag_name, "name must match exactly"
            assert len(rec.get("tagName", "")) == 127, f"length={len(rec.get('tagName', ''))}"

            pt = _wait_rt(api, tag_name, timeout=60.0)
            assert pt.get("tagValue") is not None
            assert pt.get("quality", 0) != 0
        else:
            assert result["error"].msg, "error message should not be empty"
            recs = find_all_tags(api, tag_name)
            assert len(recs) == 0, "tag should not exist after rejection"
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-022",
    chapter="UA-2-1",
    title="系统位号名_长度边界128",
    preconditions=["数据源 alive=true"],
    steps=[
        "使用 128 字符名称新增",
        "查询名称与长度",
    ],
    expected=[
        "请求结果明确",
        "若成功，名称完整保存且长度为 128",
        "若拒绝，不生成记录",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_system_name_length_128(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-022")
    tag_name = _fixed_length_name(settings.test_prefix, "UA-2-1-022-tag", 128)
    tag_id = None
    try:
        result = try_add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        if result["ok"]:
            tag_id = int(result["data"].get("id") or result["data"].get("tagId"))
            rec = find_unique_tag(api, tag_name)
            assert rec, "tag should exist"
            assert rec.get("tagName") == tag_name, "name must match exactly"
            assert len(rec.get("tagName", "")) == 128, f"length={len(rec.get('tagName', ''))}"

            pt = _wait_rt(api, tag_name, timeout=60.0)
            assert pt.get("tagValue") is not None
            assert pt.get("quality", 0) != 0
        else:
            assert result["error"].msg, "error message should not be empty"
            recs = find_all_tags(api, tag_name)
            assert len(recs) == 0, "tag should not exist after rejection"
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-023",
    chapter="UA-2-1",
    title="系统位号名_长度边界129",
    preconditions=["数据源 alive=true"],
    steps=[
        "使用 129 字符名称新增",
        "查询名称与长度",
        "检查与 128 对照是否冲突",
    ],
    expected=[
        "记录拒绝、截断或接受行为",
        "不得静默截断后与已有名称冲突",
        "不影响其他位号",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_system_name_length_129(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-023")
    ref_name = _fixed_length_name(settings.test_prefix, "UA-2-1-023-ref", 128)
    test_name = _fixed_length_name(settings.test_prefix, "UA-2-1-023-tag", 129)
    ref_id = None
    test_id = None
    observations: dict[str, object] = {}
    try:
        ref_result = add_tag(
            api, tag_name=ref_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        ref_id = int(ref_result.get("id") or ref_result.get("tagId"))

        result = try_add_tag(
            api, tag_name=test_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        observations["accepted"] = result["ok"]
        if result.get("error"):
            observations["error_msg"] = result["error"].msg
        if result["ok"]:
            test_id = int(result["data"].get("id") or result["data"].get("tagId"))
            rec = find_unique_tag(api, test_name)
            observations["saved_name"] = rec.get("tagName", "") if rec else None
            observations["saved_length"] = len(rec.get("tagName", "")) if rec else 0

        ref_rec = find_unique_tag(api, ref_name)
        assert ref_rec, "reference tag should remain"
        assert int(ref_rec.get("id", -1)) == ref_id, "reference tag id changed"
        assert ref_rec.get("tagName") == ref_name, "reference tag name unchanged"

        ref_recs = find_all_tags(api, ref_name)
        test_recs = find_all_tags(api, test_name) if test_name != ref_name else []
        assert len(ref_recs) == 1, "reference tag should be unique"
        if test_id:
            assert len(test_recs) == 1, "test tag should be unique"
            assert ref_recs[0].get("tagName") != test_recs[0].get("tagName"), (
                "129-char tag must not collide with 128-char tag"
            )
    finally:
        if test_id:
            delete_tag_if_exists(api, test_id, test_name)
        if ref_id:
            delete_tag_if_exists(api, ref_id, ref_name)
        teardown_ds_tag_mocker(api, ctx)

    obs_str = "; ".join(f"{k}={v}" for k, v in observations.items())
    pytest.xfail(
        f"UA-2-1-023 length 129 behavior not specified; observed: {obs_str}"
    )


@pytest.mark.case(
    id="UA-2-1-024",
    chapter="UA-2-1",
    title="系统位号名_特殊字符",
    preconditions=["数据源 alive=true"],
    steps=[
        "使用 a/b\\c.d@e#f 新增",
        "查询实际保存名称并读取 RT",
    ],
    expected=[
        "记录允许字符范围",
        "若成功，名称原样保存且可查询、可读取",
        "若拒绝，不生成残留",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_system_name_special_chars(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-024")
    suffix = unique_name("", "UA-2-1-024-sfx")[-8:]
    tag_name = f"a/b\\c.d@e#{suffix}"
    tag_id = None
    observations: dict[str, object] = {}
    try:
        result = try_add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        observations["accepted"] = result["ok"]
        if result.get("error"):
            observations["error_msg"] = result["error"].msg
        if result["ok"]:
            tag_id = int(result["data"].get("id") or result["data"].get("tagId"))
            recs = find_all_tags(api, tag_name)
            observations["records_found"] = len(recs)
            if recs:
                observations["saved_name"] = recs[0].get("tagName", "")
                saved = recs[0].get("tagName", "")
                assert saved == tag_name, f"saved name {saved!r} != input {tag_name!r}"

                pt = _wait_rt(api, tag_name, timeout=60.0)
                observations["rt_available"] = pt.get("tagValue") is not None
                if pt.get("tagValue") is not None:
                    assert pt.get("quality", 0) != 0
        else:
            recs = find_all_tags(api, tag_name)
            observations["records_found"] = len(recs)
            assert len(recs) == 0, "no residual when rejected"
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        teardown_ds_tag_mocker(api, ctx)

    obs_str = "; ".join(f"{k}={v}" for k, v in observations.items())
    pytest.xfail(
        f"UA-2-1-024 special chars tagName behavior not specified; observed: {obs_str}"
    )


@pytest.mark.case(
    id="UA-2-1-025",
    chapter="UA-2-1",
    title="系统位号名_Unicode与大小写",
    preconditions=["数据源 alive=true"],
    steps=[
        "分别新增中文、Emoji、Tag_A、tag_a",
        "查询全部记录",
    ],
    expected=[
        "记录 Unicode 支持情况",
        "记录大小写唯一性",
        "查询结果与实际保存一致",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_system_name_unicode_and_case(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-025")
    suffix = unique_name("", "UA-2-1-025-sfx")[-6:]
    inputs = [
        f"中文测试_{suffix}",
        f"emoji_test_{chr(0x1F600)}_{suffix}",
        f"Tag_A_{suffix}",
        f"tag_a_{suffix}",
    ]
    created: list[tuple[int, str]] = []
    observations: dict[str, dict] = {}
    try:
        for inp in inputs:
            result = try_add_tag(
                api, tag_name=inp, data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
                tag_base_name="2_smoke_static_1",
            )
            entry: dict = {"accepted": result["ok"]}
            if result.get("error"):
                entry["error_msg"] = result["error"].msg
            if result["ok"]:
                tag_id = int(result["data"].get("id") or result["data"].get("tagId"))
                created.append((tag_id, inp))
                recs = find_all_tags(api, inp)
                entry["saved_name"] = recs[0].get("tagName", "") if recs else None
                entry["records_found"] = len(recs)
            else:
                entry["records_found"] = 0
            observations[inp] = entry

        tag_a_input = f"Tag_A_{suffix}"
        tag_a_lower = f"tag_a_{suffix}"
        case_unique = False
        if tag_a_lower != tag_a_input and tag_a_input in [inp for _, inp in created]:
            a_recs = find_all_tags(api, tag_a_input)
            lower_recs = find_all_tags(api, tag_a_lower)
            lower_saved = [r.get("tagName", "") for r in lower_recs] if lower_recs else []
            case_unique = (
                len(a_recs) == 1 and (tag_a_lower not in [r.get("tagName", "") for r in a_recs])
            )
        observations["case_sensitive_unique"] = {"accepted": case_unique}

        all_saved = set()
        for _, tname in created:
            recs = find_all_tags(api, tname)
            if recs:
                all_saved.add(recs[0].get("tagName", ""))
        assert len(created) == len(all_saved), "all created tags must have distinct saved names"

        for inp in inputs:
            found_after = find_all_tags(api, inp)
            assert len(found_after) <= 1, f"duplicate records for {inp!r}"
    finally:
        for tid, tname in created:
            delete_tag_if_exists(api, tid, tname)
        teardown_ds_tag_mocker(api, ctx)

    obs_str = "; ".join(
        f"{k}: accepted={v.get('accepted')}, saved={v.get('saved_name')!r}"
        for k, v in observations.items()
    )
    pytest.xfail(
        f"UA-2-1-025 Unicode/case tagName behavior not specified; observed: {obs_str}"
    )
