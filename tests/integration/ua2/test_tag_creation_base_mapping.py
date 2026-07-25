from __future__ import annotations

import pytest

from tpt_api.datahub import add_tag, change_ds_state, list_tags, query_tags_with_quality
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, TagTypes

from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists
from tests.support.endpoints import parse_mocker_endpoint
from tests.support.mocker_process import (
    find_free_port,
    start_mocker,
    stop_mocker,
    write_mocker_config,
)
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    find_unique_tag,
    is_ds_alive,
    opcua_read_sync,
    setup_ds_and_tag,
    teardown_ds_tag_mocker,
    wait_ds_alive,
    wait_qtq_valid,
)

_DOUBLE_CH_1 = [
    {"name": "double_ch_", "type": "Double", "default": 3.14, "writable": True, "change": False, "count": 1},
]
_SHARED_NODE_100 = [
    {"name": "shared_node_", "type": "Int32", "default": 100, "writable": True, "change": False, "count": 1},
]
_SHARED_NODE_200 = [
    {"name": "shared_node_", "type": "Int32", "default": 200, "writable": True, "change": False, "count": 1},
]


@pytest.mark.case(
    id="UA-2-1-008",
    chapter="UA-2-1",
    title="底层位号_规范格式",
    preconditions=["数据源 alive=true；存在节点 ns=1, nodeId=double_ch_1"],
    steps=[
        "新增 tagBaseName=\"1_double_ch_1\"",
        "执行公共新增闭环",
    ],
    expected=[
        "tagBaseName 原样保存",
        "RT 值与 asyncua 直读同一节点一致",
        "质量有效",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_base_name_standard_format(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-008",
        tag_base_name="1_double_ch_1",
        data_type=DataTypes["DOUBLE"],
        nodes=_DOUBLE_CH_1,
        namespace_index=1,
    )
    try:
        rec = find_unique_tag(api, ctx["tag_name"])
        assert rec.get("tagBaseName") == "1_double_ch_1", (
            f"tagBaseName={rec.get('tagBaseName')!r}"
        )

        pt = get_rt_point(api, ctx["tag_name"])
        assert pt.get("tagValue") is not None
        assert pt.get("quality", 0) != 0

        source_val = opcua_read_sync(ctx["endpoint"], "double_ch_1", namespace_index=1)
        assert float(pt["tagValue"]) == pytest.approx(float(source_val)), (
            f"RT {pt['tagValue']} != source {source_val}"
        )

        qr = wait_qtq_valid(api, ctx["ds_id"], ctx["tag_name"], timeout=30.0)
        assert qr.get("tagValue") is not None
        assert qr.get("quality") not in (None, 0)
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-009",
    chapter="UA-2-1",
    title="底层位号_不存在节点",
    preconditions=["数据源 alive=true；源端不存在目标节点"],
    steps=[
        "新增 tagBaseName=\"1_nonexistent\"",
        "查询配置与实时值",
    ],
    expected=[
        "位号配置创建成功",
        "tagBaseName 正确保存",
        "RT 无有效值",
        "quality=0",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_base_name_nonexistent_node(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-009",
        tag_base_name="1_nonexistent",
        data_type=DataTypes["DOUBLE"],
        wait_for_rt=False,
    )
    try:
        rec = find_unique_tag(api, ctx["tag_name"])
        assert rec.get("tagBaseName") == "1_nonexistent"

        pt = get_rt_point(api, ctx["tag_name"])
        qval = pt.get("quality") if pt else 0
        assert qval is None or qval == 0, f"quality should be None/0, got {qval!r}"

        qwq = query_tags_with_quality(api, ds_id=ctx["ds_id"], tag_name=ctx["tag_name"])
        qrecs = (qwq.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == ctx["tag_name"]]
        assert len(qmatch) == 1
        qv = qmatch[0].get("quality")
        assert qv is None or qv == 0, f"quality should be None/0, got {qv!r}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-010",
    chapter="UA-2-1",
    title="底层位号_跨数据源相同节点名",
    preconditions=[
        "两个数据源均 alive=true",
        "各有 nodeId=shared_node_1，源端值不同",
    ],
    steps=[
        "ds-A 新增 tag_A 指向 1_shared_node_1",
        "ds-B 新增 tag_B 指向 1_shared_node_1",
        "分别读取 RT 和源端",
    ],
    expected=[
        "两个位号均创建成功",
        "各自 RT 值等于各自数据源的源端值",
        "两个位号不串值",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_base_name_cross_ds_same_node(api, settings, tmp_path_factory, mocker_endpoint):
    ctx_a = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-010-a",
        tag_base_name="1_shared_node_1",
        data_type=DataTypes["INT"],
        nodes=_SHARED_NODE_100,
        namespace_index=1,
    )
    try:
        ctx_b = setup_ds_and_tag(
            api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-010-b",
            tag_base_name="1_shared_node_1",
            data_type=DataTypes["INT"],
            nodes=_SHARED_NODE_200,
            namespace_index=1,
        )
        try:
            rec_a = find_unique_tag(api, ctx_a["tag_name"])
            assert rec_a.get("tagBaseName") == "1_shared_node_1"
            rec_b = find_unique_tag(api, ctx_b["tag_name"])
            assert rec_b.get("tagBaseName") == "1_shared_node_1"

            pt_a = get_rt_point(api, ctx_a["tag_name"])
            pt_b = get_rt_point(api, ctx_b["tag_name"])
            assert pt_a.get("tagValue") is not None
            assert pt_b.get("tagValue") is not None
            assert pt_a.get("tagValue") != pt_b.get("tagValue"), (
                "two DS should have different values"
            )

            src_a = opcua_read_sync(ctx_a["endpoint"], "shared_node_1", namespace_index=1)
            src_b = opcua_read_sync(ctx_b["endpoint"], "shared_node_1", namespace_index=1)
            assert int(pt_a["tagValue"]) == int(src_a), (
                f"RT A {pt_a['tagValue']} != source A {src_a}"
            )
            assert int(pt_b["tagValue"]) == int(src_b), (
                f"RT B {pt_b['tagValue']} != source B {src_b}"
            )
        finally:
            teardown_ds_tag_mocker(api, ctx_b)
    finally:
        teardown_ds_tag_mocker(api, ctx_a)


@pytest.mark.case(
    id="UA-2-1-011",
    chapter="UA-2-1",
    title="底层位号_同数据源重复映射",
    preconditions=["同一数据源 alive=true；存在节点 2_smoke_static_1"],
    steps=[
        "新增 tag_A 指向该节点",
        "新增 tag_B 也指向该节点",
        "读取两位号并确认独立",
    ],
    expected=[
        "第二次新增允许",
        "两个 tag 各自读取独立 RT 值",
        "原位号不受影响",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_base_name_duplicate_mapping(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-011-a",
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
    )
    second_tag_name = unique_name(settings.test_prefix, "UA-2-1-011-b")
    second_tag_id = None
    try:
        tag_data = add_tag(
            api, tag_name=second_tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ctx["ds_id"], only_read=True,
            tag_base_name="2_smoke_static_1",
        )
        second_tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
        pt_a = get_rt_point(api, ctx["tag_name"])
        pt_b = get_rt_point(api, second_tag_name)
        assert pt_a.get("tagValue") is not None
        assert pt_b.get("tagValue") is not None
    except Exception:
        page = list_tags(api, page=1, page_size=50, data={"tagName": second_tag_name})
        remaining = [r for r in (page.get("records") or []) if r.get("tagName") == second_tag_name]
        assert len(remaining) == 0, "second tag should not exist after rejection"
        pt_a = get_rt_point(api, ctx["tag_name"])
        assert pt_a.get("tagValue") is not None, "first tag should be unaffected"
    finally:
        if second_tag_id:
            delete_tag_if_exists(api, second_tag_id, second_tag_name)
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-012",
    chapter="UA-2-1",
    title="底层位号_格式异常",
    preconditions=["数据源 alive=true"],
    steps=[
        "使用 tagBaseName=\"invalid_format\" 新增",
        "查询配置与 RT",
    ],
    expected=[
        "记录接口是否拒绝",
        "若接受，记录字段保存值、RT 和质量",
        "不得影响其他位号",
    ],
)
@pytest.mark.xfail(strict=True, reason="spec_pending: invalid tagBaseName format behavior")
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_base_name_invalid_format(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-012",
        tag_base_name="invalid_format",
        data_type=DataTypes["DOUBLE"],
    )
    try:
        rec = find_unique_tag(api, ctx["tag_name"])
        saved_base_name = rec.get("tagBaseName")
        assert saved_base_name is not None, "tagBaseName should be saved"

        pt = get_rt_point(api, ctx["tag_name"])
        assert pt.get("tagValue") is not None or pt.get("quality", 0) == 0
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-013",
    chapter="UA-2-1",
    title="底层位号_Namespace不存在",
    preconditions=["数据源 alive=true；Namespace 99 不存在"],
    steps=[
        "新增 tagBaseName=\"99_double_ch_1\"",
        "查询配置与质量",
    ],
    expected=[
        "配置可创建",
        "RT 无有效值",
        "quality=0",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_base_name_nonexistent_namespace(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-013",
        tag_base_name="99_double_ch_1",
        data_type=DataTypes["DOUBLE"],
        wait_for_rt=False,
    )
    try:
        rec = find_unique_tag(api, ctx["tag_name"])
        assert rec.get("tagBaseName") == "99_double_ch_1"

        pt = get_rt_point(api, ctx["tag_name"])
        qval = pt.get("quality") if pt else 0
        assert qval is None or qval == 0, f"quality should be None/0, got {qval!r}"

        qwq = query_tags_with_quality(api, ds_id=ctx["ds_id"], tag_name=ctx["tag_name"])
        qrecs = (qwq.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == ctx["tag_name"]]
        assert len(qmatch) == 1
        qv = qmatch[0].get("quality")
        assert qv is None or qv == 0, f"quality should be None/0, got {qv!r}"
    finally:
        teardown_ds_tag_mocker(api, ctx)


@pytest.mark.case(
    id="UA-2-1-014",
    chapter="UA-2-1",
    title="底层位号_空值",
    preconditions=["数据源 alive=true"],
    steps=[
        "tagBaseName=\"\" 调用 add_tag",
        "按系统位号名查询",
    ],
    expected=[
        "请求被拒绝或按接口默认规则处理",
        "若拒绝，不生成位号",
        "若接受，记录行为",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_base_name_empty(api, settings, tmp_path_factory, mocker_endpoint):
    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    tag_name = unique_name(settings.test_prefix, "UA-2-1-014-tag")
    ds_name = unique_name(settings.test_prefix, "UA-2-1-014-ds")

    tmp_dir = tmp_path_factory.mktemp("m_ua_2_1_014")
    cfg_path = write_mocker_config(tmp_dir, port)
    mocker = start_mocker(cfg_path, port, host=parsed.host)

    from tpt_api.datahub import add_ds_info
    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=1, ds_sub_type=4,
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    tag_id = None

    try:
        wait_ds_alive(api, ds_id, timeout=60.0)

        try:
            tag_data = add_tag(
                api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
                tag_base_name="",
            )
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

            rec = find_unique_tag(api, tag_name)
            assert rec, "tag should exist when empty tagBaseName is accepted"
            saved_base_name = rec.get("tagBaseName")
        except TptAPIError:
            page = list_tags(api, page=1, page_size=50, data={"tagName": tag_name})
            remaining = [r for r in (page.get("records") or []) if r.get("tagName") == tag_name]
            assert len(remaining) == 0, (
                f"tag {tag_name} should not exist after rejection"
            )
    finally:
        if tag_id:
            delete_tag_if_exists(api, tag_id, tag_name)
        try:
            change_ds_state(api, ds_id, False)
        except Exception:
            pass
        delete_datasource_if_exists(api, ds_id, ds_name)
        if mocker:
            stop_mocker(mocker)


@pytest.mark.case(
    id="UA-2-1-015",
    chapter="UA-2-1",
    title="底层位号_配置类型与源端类型不一致",
    preconditions=["源端节点为 Double；数据源 alive=true"],
    steps=[
        "使用该节点新增 dataType=Boolean 位号",
        "查询配置、RT 和质量",
    ],
    expected=[
        "记录新增阶段是否拒绝",
        "若接受，记录最终 dataType、RT 值和质量",
        "不得产生进程异常",
    ],
)
@pytest.mark.xfail(strict=True, reason="spec_pending: dataType mismatch behavior")
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_base_name_data_type_mismatch(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-015",
        tag_base_name="1_double_ch_1",
        data_type=DataTypes["BOOLEAN"],
        nodes=_DOUBLE_CH_1,
        namespace_index=1,
    )
    try:
        rec = find_unique_tag(api, ctx["tag_name"])
        saved_dt = int(rec.get("dataType", -1))
        assert saved_dt != -1, "dataType should be present in config"
        if saved_dt == DataTypes["BOOLEAN"]:
            pt = get_rt_point(api, ctx["tag_name"])
            assert pt.get("quality", 0) == 0 or pt.get("tagValue") is None
        else:
            pt = get_rt_point(api, ctx["tag_name"])
            assert pt.get("tagValue") is not None
            assert pt.get("quality", 0) != 0

        qwq = query_tags_with_quality(api, ds_id=ctx["ds_id"], tag_name=ctx["tag_name"])
        qrecs = (qwq.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == ctx["tag_name"]]
        assert len(qmatch) == 1
    finally:
        teardown_ds_tag_mocker(api, ctx)
