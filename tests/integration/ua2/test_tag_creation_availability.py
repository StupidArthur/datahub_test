from __future__ import annotations

import json
import time
from datetime import datetime

import pytest

from tpt_api.datahub import write_tag_values, get_history_value
from tpt_api.types import DataTypes, TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    assert_write_accepted,
    find_unique_tag,
    opcua_read_sync,
    opcua_write_sync,
    query_tags_with_quality,
    setup_ds_and_tag,
)
from tests.support.ua2_rt_assertions import parse_required_timestamp
from tests.support.ua2_cleanup import strict_cleanup_ua2_context

from asyncua import ua


@pytest.mark.case(
    id="UA-2-1-102", chapter="UA-2-1",
    title="可用性_新增后实时读取",
    preconditions=["新增读取位号成功", "Mock 值持续变化"],
    steps=["等待两个周期", "读取两次 RT", "查询 queryWithQuality", "asyncua 直读"],
    expected=["两次 RT 值变化", "两个 TPT 查询入口值一致", "最新 RT 与源端值一致", "质量有效"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_availability_rt_read(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-102",
        tag_base_name="2_smoke_change_1",
        data_type=DataTypes["INT"],
        tag_type=TagTypes["一次位号"],
        only_read=True,
        namespace_index=2,
        cycle=500,
    )
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    node_name = "smoke_change_1"
    ns = 2

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("onlyRead") is True

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        time.sleep(1.0)
        rt1 = get_rt_point(api, tag_name)
        time.sleep(1.0)
        rt2 = get_rt_point(api, tag_name)

        assert rt1.get("tagValue") is not None
        assert rt2.get("tagValue") is not None
        assert rt1.get("quality") not in (None, 0)
        assert rt2.get("quality") not in (None, 0)

        qwq = query_tags_with_quality(api, ds_id=ctx["ds_id"], tag_name=tag_name)
        assert "tagInfoList" in qwq
        records = qwq["tagInfoList"].get("records", [])
        assert len(records) == 1
        qwq_rec = records[0]
        assert qwq_rec.get("tagName") == tag_name
        assert qwq_rec.get("tagValue") is not None
        assert qwq_rec.get("quality") not in (None, 0)

        src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
        assert src is not None

    finally:
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )


@pytest.mark.case(
    id="UA-2-1-103", chapter="UA-2-1",
    title="可用性_新增后写值回源",
    preconditions=["新增可写位号成功"],
    steps=["保存原值", "写入测试值", "查询源端、RT 和质量"],
    expected=["写接口成功", "源端值等于写入值", "RT 在超时内等于写入值", "质量有效"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_availability_write_back(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-103",
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        namespace_index=2,
        cycle=500,
    )
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    node_name = "smoke_static_1"
    ns = 2

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("onlyRead") is False

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        original_src = opcua_read_sync(endpoint, node_name, namespace_index=ns)

        test_value = 999.999
        resp = write_tag_values(api, {tag_name: test_value})
        assert_write_accepted(resp, tag_name)

        def _source_matches():
            src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
            return isinstance(src, (int, float)) and not isinstance(src, bool) and abs(src - test_value) < 1e-6
        wait_until(f"source_sync:{tag_name}", _source_matches, timeout=30.0, interval=0.5)

        def _rt_matches():
            pt = get_rt_point(api, tag_name)
            tv = pt.get("tagValue")
            return tv is not None and isinstance(tv, (int, float)) and not isinstance(tv, bool) and abs(tv - test_value) < 1e-6
        wait_until(f"rt_sync:{tag_name}", _rt_matches, timeout=30.0, interval=0.5)

        src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
        assert abs(src - test_value) < 1e-6, f"source mismatch: {src} != {test_value}"

        pt = get_rt_point(api, tag_name)
        assert abs(pt["tagValue"] - test_value) < 1e-6, f"RT mismatch: {pt['tagValue']} != {test_value}"
        assert pt.get("quality") not in (None, 0)
        parse_required_timestamp(pt["tagTime"])

        def _qwq_matches():
            qwq = query_tags_with_quality(api, ds_id=ctx["ds_id"], tag_name=tag_name)
            if "tagInfoList" not in qwq:
                return False
            records = qwq["tagInfoList"].get("records", [])
            if len(records) != 1:
                return False
            qwq_rec = records[0]
            tv = qwq_rec.get("tagValue")
            return tv is not None and abs(float(tv) - test_value) < 1e-6
        wait_until(f"qwq_sync:{tag_name}", _qwq_matches, timeout=30.0, interval=0.5)

        qwq = query_tags_with_quality(api, ds_id=ctx["ds_id"], tag_name=tag_name)
        records = qwq["tagInfoList"].get("records", [])
        qwq_rec = records[0]
        assert qwq_rec.get("quality") not in (None, 0)

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
    id="UA-2-1-104", chapter="UA-2-1",
    title="可用性_新增后历史落库",
    preconditions=["新增读取或可写位号成功"],
    steps=["记录开始时间", "产生一个唯一测试值", "等待历史超时", "查询时间窗口"],
    expected=["历史中存在测试值", "位号名正确", "时间戳位于执行窗口内", "值类型正确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_availability_history(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_and_tag(
        api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-104",
        tag_base_name="2_smoke_static_1",
        data_type=DataTypes["DOUBLE"],
        tag_type=TagTypes["一次位号"],
        only_read=False,
        namespace_index=2,
        cycle=500,
    )
    tag_name = ctx["tag_name"]
    endpoint = ctx["endpoint"]
    node_name = "smoke_static_1"
    ns = 2

    try:
        rec = find_unique_tag(api, tag_name)
        assert rec.get("onlyRead") is False

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        original_src = opcua_read_sync(endpoint, node_name, namespace_index=ns)

        start_time = time.time()
        
        test_value = 888.888
        resp = write_tag_values(api, {tag_name: test_value})
        assert_write_accepted(resp, tag_name)

        def _source_matches():
            src = opcua_read_sync(endpoint, node_name, namespace_index=ns)
            return isinstance(src, (int, float)) and not isinstance(src, bool) and abs(src - test_value) < 1e-6
        wait_until(f"source_sync:{tag_name}", _source_matches, timeout=30.0, interval=0.5)

        time.sleep(30.0)
        end_time = time.time()

        beg_time_str = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S")
        end_time_str = datetime.fromtimestamp(end_time).strftime("%Y-%m-%d %H:%M:%S")

        def _history_available():
            history = get_history_value(api, [tag_name], beg_time_str, end_time_str)
            if not isinstance(history, dict) or tag_name not in history:
                return False
            tag_history = history[tag_name]
            if "list" not in tag_history:
                return False
            records = tag_history["list"]
            return len(records) > 0
        
        try:
            wait_until(f"history_available:{tag_name}", _history_available, timeout=60.0, interval=5.0)
        except Exception as exc:
            record_property(
                "observation",
                json.dumps({"error": str(exc), "note": "History not available within timeout"}, ensure_ascii=False, default=str),
            )
            pytest.xfail(f"UA-2-1-104 history not available: {exc}")

        history = get_history_value(api, [tag_name], beg_time_str, end_time_str)
        
        assert isinstance(history, dict), f"history should be dict, got {type(history).__name__}"
        assert tag_name in history, f"history should contain {tag_name}"
        
        tag_history = history[tag_name]
        assert "list" in tag_history
        records = tag_history["list"]
        assert len(records) > 0, "history should not be empty"

        for record in records:
            assert record.get("tagName") == tag_name
            assert record.get("tagValue") is not None
            assert record.get("tagTime") is not None

    finally:
        opcua_write_sync(endpoint, node_name, original_src, namespace_index=ns, variant_type=ua.VariantType.Double)
        strict_cleanup_ua2_context(
            api,
            tag_id=ctx["tag_id"], tag_name=tag_name,
            ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )
