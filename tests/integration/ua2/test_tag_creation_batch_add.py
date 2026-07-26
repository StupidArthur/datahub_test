from __future__ import annotations

import json

import pytest

from tpt_api.datahub import batch_add_tags, list_tags
from tpt_api.types import DataTypes, TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    find_unique_tag,
    setup_ds_only,
)
from tests.support.ua2_cleanup import strict_cleanup_ua2_context


def _get_available_base_tags(api, ds_id: int, count: int = 10) -> list[str]:
    """Get available base tag names from the datasource.
    
    Since the default mocker only has 2 nodes (2_smoke_static_1 and 2_smoke_change_1),
    we can only return up to 2 unique base names.
    """
    result = list_tags(api, data={"dsId": ds_id}, page_size=1000)
    existing_tags = result.get("records", [])
    existing_base_names = {t.get("tagBaseName") for t in existing_tags if t.get("tagBaseName")}
    
    # Default mocker nodes
    default_nodes = ["2_smoke_static_1", "2_smoke_change_1"]
    
    available = []
    # Add nodes that are not already registered
    for base_name in default_nodes:
        if base_name not in existing_base_names:
            available.append(base_name)
    
    # Return only unique base names (no duplicates)
    return available[:count]


@pytest.mark.case(
    id="UA-2-1-105", chapter="UA-2-1",
    title="批量新增_10个位号",
    preconditions=["数据源 alive=true", "至少 10 个未注册底层节点"],
    steps=["Browse 底层节点", "工具侧排除已注册项", "选择 10 个调用 batchAdd", "逐个查询并读取"],
    expected=["10 个位号均创建成功", "每个位号配置正确", "每个位号均可读取有效 RT"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_batch_add_10_tags(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-105")
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]
    
    created_tag_ids = []
    created_tag_names = []
    observations: dict = {}

    try:
        available_bases = _get_available_base_tags(api, ds_id, count=10)
        observations["available_bases_count"] = len(available_bases)
        observations["available_bases"] = available_bases[:10]
        
        if len(available_bases) < 10:
            observations["note"] = "Default mocker only has 2 nodes, need at least 10 for this test"
            record_property(
                "observation",
                json.dumps(observations, ensure_ascii=False, default=str),
            )
            pytest.xfail("UA-2-1-105 requires at least 10 unregistered base nodes, but default mocker only has 2")

        tag_infos = []
        for i, base_name in enumerate(available_bases[:10]):
            tag_name = f"{settings.test_prefix}UA-2-1-105-batch_{i}"
            tag_infos.append({
                "dsId": ds_id,
                "tagName": tag_name,
                "tagBaseName": base_name,
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
            })
            created_tag_names.append(tag_name)

        result = batch_add_tags(api, tag_infos, conflict_strategy=0)
        assert isinstance(result, list), f"batch_add_tags should return list, got {type(result).__name__}"
        assert len(result) == 10, f"Should create 10 tags, got {len(result)}"

        for record in result:
            tag_id = record.get("id")
            if tag_id:
                created_tag_ids.append(tag_id)

        for tag_name in created_tag_names:
            rec = find_unique_tag(api, tag_name)
            assert rec.get("tagName") == tag_name
            assert rec.get("dsId") == ds_id

            def _has_rt():
                pt = get_rt_point(api, tag_name)
                return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
            wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

            pt = get_rt_point(api, tag_name)
            assert pt.get("quality") not in (None, 0)

    finally:
        for tag_id, tag_name in zip(created_tag_ids, created_tag_names):
            try:
                strict_cleanup_ua2_context(
                    api,
                    tag_id=tag_id, tag_name=tag_name,
                    ds_id=ds_id, ds_name=ds_name,
                    mocker=ctx.get("mocker"),
                    host=ctx["host"], port=ctx["port"],
                )
            except Exception:
                pass


@pytest.mark.case(
    id="UA-2-1-106", chapter="UA-2-1",
    title="批量新增_冲突跳过",
    preconditions=["已存在 tagName", "conflictStrategy=0"],
    steps=["批次包含已有项和新项"],
    expected=["已有项未被修改", "新项创建成功", "返回结果可区分跳过项与成功项"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_batch_add_conflict_skip(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-106")
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]
    
    created_tag_ids = []
    created_tag_names = []

    try:
        available_bases = _get_available_base_tags(api, ds_id, count=2)
        assert len(available_bases) >= 2, f"Need at least 2 available base tags, got {len(available_bases)}"

        existing_tag_name = f"{settings.test_prefix}UA-2-1-106-existing"
        existing_base = available_bases[0]
        
        from tpt_api.datahub import add_tag
        existing_rec = add_tag(
            api, tag_name=existing_tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name=existing_base, unit="kW",
        )
        created_tag_ids.append(existing_rec.get("id"))
        created_tag_names.append(existing_tag_name)

        new_tag_name = f"{settings.test_prefix}UA-2-1-106-new"
        new_base = available_bases[1]

        tag_infos = [
            {
                "dsId": ds_id,
                "tagName": existing_tag_name,
                "tagBaseName": existing_base,
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
                "unit": "Hz",
            },
            {
                "dsId": ds_id,
                "tagName": new_tag_name,
                "tagBaseName": new_base,
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
            },
        ]

        result = batch_add_tags(api, tag_infos, conflict_strategy=0)
        assert isinstance(result, list), f"batch_add_tags should return list, got {type(result).__name__}"

        existing_after = find_unique_tag(api, existing_tag_name)
        assert existing_after.get("unit") == "kW", f"Existing tag should not be modified, unit={existing_after.get('unit')}"

        new_rec = find_unique_tag(api, new_tag_name)
        assert new_rec.get("tagName") == new_tag_name
        created_tag_ids.append(new_rec.get("id"))
        created_tag_names.append(new_tag_name)

    finally:
        for tag_id, tag_name in zip(created_tag_ids, created_tag_names):
            try:
                strict_cleanup_ua2_context(
                    api,
                    tag_id=tag_id, tag_name=tag_name,
                    ds_id=ds_id, ds_name=ds_name,
                    mocker=ctx.get("mocker"),
                    host=ctx["host"], port=ctx["port"],
                )
            except Exception:
                pass


@pytest.mark.case(
    id="UA-2-1-107", chapter="UA-2-1",
    title="批量新增_冲突覆盖",
    preconditions=["已存在位号 unit='kW'", "conflictStrategy=1"],
    steps=["批次提交同名位号 unit='Hz'"],
    expected=["原记录按接口覆盖规则更新", "unit='Hz'", "位号仍可采集"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_batch_add_conflict_overwrite(api, settings, tmp_path_factory, mocker_endpoint):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-107")
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]
    
    created_tag_ids = []
    created_tag_names = []

    try:
        available_bases = _get_available_base_tags(api, ds_id, count=1)
        assert len(available_bases) >= 1, f"Need at least 1 available base tag, got {len(available_bases)}"

        tag_name = f"{settings.test_prefix}UA-2-1-107-overwrite"
        base_name = available_bases[0]
        
        from tpt_api.datahub import add_tag
        rec = add_tag(
            api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
            tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
            tag_base_name=base_name, unit="kW",
        )
        created_tag_ids.append(rec.get("id"))
        created_tag_names.append(tag_name)

        tag_infos = [
            {
                "dsId": ds_id,
                "tagName": tag_name,
                "tagBaseName": base_name,
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
                "unit": "Hz",
            },
        ]

        result = batch_add_tags(api, tag_infos, conflict_strategy=1)
        assert isinstance(result, list), f"batch_add_tags should return list, got {type(result).__name__}"

        after = find_unique_tag(api, tag_name)
        assert after.get("unit") == "Hz", f"Tag should be overwritten with unit='Hz', got {after.get('unit')}"

        def _has_rt():
            pt = get_rt_point(api, tag_name)
            return pt.get("tagValue") is not None and pt.get("quality") not in (None, 0)
        wait_until(f"rt_ready:{tag_name}", _has_rt, timeout=30.0, interval=0.5)

        pt = get_rt_point(api, tag_name)
        assert pt.get("quality") not in (None, 0)

    finally:
        for tag_id, tag_name in zip(created_tag_ids, created_tag_names):
            try:
                strict_cleanup_ua2_context(
                    api,
                    tag_id=tag_id, tag_name=tag_name,
                    ds_id=ds_id, ds_name=ds_name,
                    mocker=ctx.get("mocker"),
                    host=ctx["host"], port=ctx["port"],
                )
            except Exception:
                pass


@pytest.mark.case(
    id="UA-2-1-108", chapter="UA-2-1",
    title="批量新增_空列表",
    preconditions=["无"],
    steps=["调用 batchAdd(tagInfos=[])"],
    expected=["记录成功无操作或明确参数错误", "系统状态不变化"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_batch_add_empty_list(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-108")
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]
    observations: dict = {}

    try:
        before_count = len(list_tags(api, data={"dsId": ds_id}, page_size=1000).get("records", []))

        try:
            result = batch_add_tags(api, [], conflict_strategy=0)
            observations["result"] = str(result)
            observations["verdict"] = "accepted"
        except Exception as exc:
            observations["error"] = str(exc)
            observations["verdict"] = "rejected"

        after_count = len(list_tags(api, data={"dsId": ds_id}, page_size=1000).get("records", []))
        observations["before_count"] = before_count
        observations["after_count"] = after_count
        observations["count_changed"] = before_count != after_count

        record_property(
            "observation",
            json.dumps(observations, ensure_ascii=False, default=str),
        )

    finally:
        strict_cleanup_ua2_context(
            api,
            ds_id=ds_id, ds_name=ds_name,
            mocker=ctx.get("mocker"),
            host=ctx["host"], port=ctx["port"],
        )

    pytest.xfail(
        "UA-2-1-108 batch add empty list semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-109", chapter="UA-2-1",
    title="批量新增_部分非法",
    preconditions=["批次含 8 个合法项、1 个重复名、1 个非法类型"],
    steps=["提交批次并查询所有目标名"],
    expected=["记录整批回滚或部分成功策略", "返回结果能定位失败项", "不产生不可识别的半成品记录"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_batch_add_partial_invalid(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-109")
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]
    
    created_tag_ids = []
    created_tag_names = []
    observations: dict = {}

    try:
        available_bases = _get_available_base_tags(api, ds_id, count=10)
        observations["available_bases_count"] = len(available_bases)
        observations["available_bases"] = available_bases
        
        if len(available_bases) < 10:
            observations["note"] = f"Default mocker only has {len(available_bases)} unique nodes, need at least 10 for this test"
            record_property(
                "observation",
                json.dumps(observations, ensure_ascii=False, default=str),
            )
            pytest.xfail(f"UA-2-1-109 requires at least 10 unique base nodes, but only {len(available_bases)} available")

        tag_infos = []
        for i in range(8):
            tag_name = f"{settings.test_prefix}UA-2-1-109-valid_{i}"
            tag_infos.append({
                "dsId": ds_id,
                "tagName": tag_name,
                "tagBaseName": available_bases[i],
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
            })
            created_tag_names.append(tag_name)

        tag_infos.append({
            "dsId": ds_id,
            "tagName": created_tag_names[0],
            "tagBaseName": available_bases[8],
            "dataType": DataTypes["DOUBLE"],
            "tagType": TagTypes["一次位号"],
            "frequency": 10,
            "isVector": True,
        })

        tag_infos.append({
            "dsId": ds_id,
            "tagName": f"{settings.test_prefix}UA-2-1-109-invalid_type",
            "tagBaseName": available_bases[9],
            "dataType": 999,
            "tagType": TagTypes["一次位号"],
            "frequency": 10,
            "isVector": True,
        })

        try:
            result = batch_add_tags(api, tag_infos, conflict_strategy=0)
            observations["result"] = str(result)
            observations["verdict"] = "accepted"
            
            if isinstance(result, list):
                for record in result:
                    tag_id = record.get("id")
                    if tag_id:
                        created_tag_ids.append(tag_id)
        except Exception as exc:
            observations["error"] = str(exc)
            observations["verdict"] = "rejected"

        record_property(
            "observation",
            json.dumps(observations, ensure_ascii=False, default=str),
        )

    finally:
        for tag_id, tag_name in zip(created_tag_ids, created_tag_names):
            try:
                strict_cleanup_ua2_context(
                    api,
                    tag_id=tag_id, tag_name=tag_name,
                    ds_id=ds_id, ds_name=ds_name,
                    mocker=ctx.get("mocker"),
                    host=ctx["host"], port=ctx["port"],
                )
            except Exception:
                pass
        
        try:
            strict_cleanup_ua2_context(
                api,
                ds_id=ds_id, ds_name=ds_name,
                mocker=ctx.get("mocker"),
                host=ctx["host"], port=ctx["port"],
            )
        except Exception:
            pass

    pytest.xfail(
        "UA-2-1-109 batch add partial invalid semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-110", chapter="UA-2-1",
    title="批量新增_批次内重名",
    preconditions=["同一批次包含两个相同 tagName"],
    steps=["提交批次并查询该名称"],
    expected=["记录冲突处理规则", "不得生成两个全局同名记录", "返回结果明确"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_batch_add_duplicate_in_batch(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-110")
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]
    
    created_tag_ids = []
    created_tag_names = []
    observations: dict = {}

    try:
        available_bases = _get_available_base_tags(api, ds_id, count=2)
        assert len(available_bases) >= 2, f"Need at least 2 available base tags, got {len(available_bases)}"

        tag_name = f"{settings.test_prefix}UA-2-1-110-dup"
        
        tag_infos = [
            {
                "dsId": ds_id,
                "tagName": tag_name,
                "tagBaseName": available_bases[0],
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
            },
            {
                "dsId": ds_id,
                "tagName": tag_name,
                "tagBaseName": available_bases[1],
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
            },
        ]

        try:
            result = batch_add_tags(api, tag_infos, conflict_strategy=0)
            observations["result"] = str(result)
            observations["verdict"] = "accepted"
            
            if isinstance(result, list):
                for record in result:
                    tag_id = record.get("id")
                    if tag_id:
                        created_tag_ids.append(tag_id)
        except Exception as exc:
            observations["error"] = str(exc)
            observations["verdict"] = "rejected"

        try:
            tags = list_tags(api, tag_name=tag_name)
            observations["duplicate_count"] = len(tags)
        except Exception as exc:
            observations["query_error"] = str(exc)

        record_property(
            "observation",
            json.dumps(observations, ensure_ascii=False, default=str),
        )

    finally:
        for tag_id in created_tag_ids:
            try:
                strict_cleanup_ua2_context(
                    api,
                    tag_id=tag_id, tag_name=tag_name,
                    ds_id=ds_id, ds_name=ds_name,
                    mocker=ctx.get("mocker"),
                    host=ctx["host"], port=ctx["port"],
                )
            except Exception:
                pass
        
        try:
            strict_cleanup_ua2_context(
                api,
                ds_id=ds_id, ds_name=ds_name,
                mocker=ctx.get("mocker"),
                host=ctx["host"], port=ctx["port"],
            )
        except Exception:
            pass

    pytest.xfail(
        "UA-2-1-110 batch add duplicate in batch semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-111", chapter="UA-2-1",
    title="批量新增_重复提交幂等性",
    preconditions=["已准备固定批次"],
    steps=["连续提交完全相同批次两次"],
    expected=["记录第二次跳过、覆盖或失败规则", "位号数量不异常增加", "已有配置不被意外重置"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_batch_add_idempotency(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-111")
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]
    
    created_tag_ids = []
    created_tag_names = []
    observations: dict = {}

    try:
        available_bases = _get_available_base_tags(api, ds_id, count=3)
        observations["available_bases_count"] = len(available_bases)
        observations["available_bases"] = available_bases
        
        if len(available_bases) < 3:
            observations["note"] = f"Default mocker only has {len(available_bases)} unique nodes, need at least 3 for this test"
            record_property(
                "observation",
                json.dumps(observations, ensure_ascii=False, default=str),
            )
            pytest.xfail(f"UA-2-1-111 requires at least 3 unique base nodes, but only {len(available_bases)} available")

        tag_infos = []
        for i in range(3):
            tag_name = f"{settings.test_prefix}UA-2-1-111-idem_{i}"
            tag_infos.append({
                "dsId": ds_id,
                "tagName": tag_name,
                "tagBaseName": available_bases[i],
                "dataType": DataTypes["DOUBLE"],
                "tagType": TagTypes["一次位号"],
                "frequency": 10,
                "isVector": True,
                "unit": "kW",
            })
            created_tag_names.append(tag_name)

        result1 = batch_add_tags(api, tag_infos, conflict_strategy=0)
        observations["result1"] = str(result1)
        
        if isinstance(result1, list):
            for record in result1:
                tag_id = record.get("id")
                if tag_id:
                    created_tag_ids.append(tag_id)

        before_count = len(list_tags(api, data={"dsId": ds_id}, page_size=1000).get("records", []))

        result2 = batch_add_tags(api, tag_infos, conflict_strategy=0)
        observations["result2"] = str(result2)

        after_count = len(list_tags(api, data={"dsId": ds_id}, page_size=1000).get("records", []))
        observations["before_count"] = before_count
        observations["after_count"] = after_count
        observations["count_changed"] = before_count != after_count

        for tag_name in created_tag_names:
            rec = find_unique_tag(api, tag_name)
            observations[f"{tag_name}_unit"] = rec.get("unit")

        record_property(
            "observation",
            json.dumps(observations, ensure_ascii=False, default=str),
        )

    finally:
        for tag_id, tag_name in zip(created_tag_ids, created_tag_names):
            try:
                strict_cleanup_ua2_context(
                    api,
                    tag_id=tag_id, tag_name=tag_name,
                    ds_id=ds_id, ds_name=ds_name,
                    mocker=ctx.get("mocker"),
                    host=ctx["host"], port=ctx["port"],
                )
            except Exception:
                pass
        
        try:
            strict_cleanup_ua2_context(
                api,
                ds_id=ds_id, ds_name=ds_name,
                mocker=ctx.get("mocker"),
                host=ctx["host"], port=ctx["port"],
            )
        except Exception:
            pass

    pytest.xfail(
        "UA-2-1-111 batch add idempotency semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )


@pytest.mark.case(
    id="UA-2-1-112", chapter="UA-2-1",
    title="批量新增_数量边界",
    preconditions=["准备 1、10、100、接口上限、上限+1 个节点"],
    steps=["分批提交并记录耗时和结果"],
    expected=["记录支持的批次上限", "超限时返回明确错误", "成功批次记录数完整", "不出现静默丢项"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.spec_pending
def test_batch_add_quantity_boundary(api, settings, tmp_path_factory, mocker_endpoint, record_property):
    ctx = setup_ds_only(api, settings, mocker_endpoint, tmp_path_factory, "UA-2-1-112")
    ds_id = ctx["ds_id"]
    ds_name = ctx["ds_name"]
    
    created_tag_ids = []
    created_tag_names = []
    observations: list[dict] = []

    try:
        test_sizes = [1, 10]

        for size in test_sizes:
            available_bases = _get_available_base_tags(api, ds_id, count=size)
            if len(available_bases) < size:
                observations.append({
                    "size": size,
                    "error": f"Not enough available base tags: need {size}, got {len(available_bases)}",
                })
                continue

            tag_infos = []
            batch_tag_names = []
            for i in range(size):
                tag_name = f"{settings.test_prefix}UA-2-1-112-size{size}_{i}"
                tag_infos.append({
                    "dsId": ds_id,
                    "tagName": tag_name,
                    "tagBaseName": available_bases[i],
                    "dataType": DataTypes["DOUBLE"],
                    "tagType": TagTypes["一次位号"],
                    "frequency": 10,
                    "isVector": True,
                })
                batch_tag_names.append(tag_name)
                created_tag_names.append(tag_name)

            import time
            start = time.time()
            try:
                result = batch_add_tags(api, tag_infos, conflict_strategy=0)
                elapsed = time.time() - start
                
                obs = {
                    "size": size,
                    "elapsed": elapsed,
                    "verdict": "accepted",
                    "result_count": len(result) if isinstance(result, list) else None,
                }
                
                if isinstance(result, list):
                    for record in result:
                        tag_id = record.get("id")
                        if tag_id:
                            created_tag_ids.append(tag_id)
                
                observations.append(obs)
            except Exception as exc:
                elapsed = time.time() - start
                observations.append({
                    "size": size,
                    "elapsed": elapsed,
                    "verdict": "rejected",
                    "error": str(exc),
                })

        record_property(
            "observation",
            json.dumps(observations, ensure_ascii=False, default=str),
        )

    finally:
        for tag_id, tag_name in zip(created_tag_ids, created_tag_names):
            try:
                strict_cleanup_ua2_context(
                    api,
                    tag_id=tag_id, tag_name=tag_name,
                    ds_id=ds_id, ds_name=ds_name,
                    mocker=ctx.get("mocker"),
                    host=ctx["host"], port=ctx["port"],
                )
            except Exception:
                pass
        
        try:
            strict_cleanup_ua2_context(
                api,
                ds_id=ds_id, ds_name=ds_name,
                mocker=ctx.get("mocker"),
                host=ctx["host"], port=ctx["port"],
            )
        except Exception:
            pass

    pytest.xfail(
        "UA-2-1-112 batch add quantity boundary semantics are not specified; "
        f"observed={json.dumps(observations, ensure_ascii=False, default=str)}"
    )
