"""UA-3-2 实时读取 — batch 2: UA-3-2-001 .. UA-3-2-004.

Migrated from ``ua_test_harness/test_cases/UA-3-2.md``.  Each test creates
its own mocker (dynamic port), datasource and tag, and performs strict
cleanup regardless of outcome.

Conventions applied from the source spec:
- real-time library: ``isFromDB=false``
- query by ``tagNames`` / ``tagInfoIds`` / ``groupId``
- dynamic values compared within an allowed time window, not same-ms equal
"""
from __future__ import annotations

import time

import pytest

from tpt_api.types import DataTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.naming import unique_name
from tests.support.ua2_helpers import opcua_read_sync, opcua_write_sync
from tests.support.ua3_helpers import (
    add_collection_tag,
    build_node,
    cleanup_ua3_context,
    cleanup_ua3_multi_context,
    node_id_from_cfg,
    rt_query,
    wait_rt_valid,
)
from tests.support.ua2_helpers import setup_ds_only
from tests.support.ua2_value_normalization import assert_value_equal


def _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id: str, nodes: list[dict]) -> dict:
    ctx = setup_ds_only(
        api, settings, mocker_endpoint, tmp_path_factory, case_id,
        nodes=nodes, namespace_index=1, cycle=500,
    )
    ctx["nodes"] = nodes
    return ctx


def _teardown(api, ctx: dict, tags: list[dict]) -> None:
    cleanup_ua3_context(
        api,
        tag_ids=[t["tag_id"] for t in tags],
        tag_names=[t["tag_name"] for t in tags],
        ds_id=ctx["ds_id"], ds_name=ctx["ds_name"],
        mocker=ctx.get("mocker"), host=ctx["host"], port=ctx["port"],
    )


def _by_name(points: list[dict], tag_name: str) -> dict:
    return next((p for p in points if p.get("tagName") == tag_name), {})


# ---------------------------------------------------------------------------
# UA-3-2-001 实时库_按名称读取
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-001", chapter="UA-3-2",
    title="实时库_按名称读取",
    preconditions=["数据源 alive=true", "位号已创建"],
    steps=["传 tagNames 查询", "返回目标位号", "值与源端一致"],
    expected=["返回目标位号", "值与源端一致"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_001_rt_by_name(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-2-001"
    prefix = "ua32_001"
    node = build_node(f"{prefix}_val_", "Double", 12.5, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        points = rt_query(api, tag_names=[tags[0]["tag_name"]], is_from_db=False)
        assert isinstance(points, list) and len(points) == 1, f"expected 1 point, got {points}"
        pt = points[0]
        assert pt.get("tagName") == tags[0]["tag_name"]
        assert pt.get("quality", 0) != 0
        assert_value_equal(12.5, pt.get("tagValue"), DataTypes["DOUBLE"])
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-2-002 实时库_按ID读取
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-002", chapter="UA-3-2",
    title="实时库_按ID读取",
    preconditions=["数据源 alive=true", "位号已创建"],
    steps=["传 tagInfoIds 查询", "确认 ID 与返回位号正确对应"],
    expected=["ID 与返回位号正确对应"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_002_rt_by_id(api, settings, tmp_path_factory, mocker_endpoint):
    case_id = "UA-3-2-002"
    prefix = "ua32_002"
    node = build_node(f"{prefix}_val_", "Double", 3.14, change=False, writable=True)
    node_id = node_id_from_cfg(node)
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, [node])
    tags = []
    try:
        tags.append(add_collection_tag(api, settings, ctx, case_id, node_id_str=node_id, type_key="DOUBLE"))
        wait_rt_valid(api, tags[0]["tag_name"], timeout=60.0)

        points = rt_query(api, tag_info_ids=[tags[0]["tag_id"]], is_from_db=False)
        assert isinstance(points, list) and len(points) == 1, f"expected 1 point, got {points}"
        pt = points[0]
        assert pt.get("tagName") == tags[0]["tag_name"], \
            f"point tagName={pt.get('tagName')!r} != {tags[0]['tag_name']!r}"
        assert pt.get("quality", 0) != 0
    finally:
        _teardown(api, ctx, tags)


# ---------------------------------------------------------------------------
# UA-3-2-003 实时库_按分组读取
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-003", chapter="UA-3-2",
    title="实时库_按分组读取",
    preconditions=["数据源 alive=true", "位号已创建并分配分组"],
    steps=["传 groupId 查询", "确认只返回该组位号"],
    expected=["只返回该组位号"],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_ua3_2_003_rt_by_group(api, settings, tmp_path_factory, mocker_endpoint):
    from tpt_api.datahub import add_tag_group, add_tag_group_relation, delete_tag_group

    case_id = "UA-3-2-003"
    prefix = "ua32_003"
    nodes = [
        build_node(f"{prefix}_a_", "Int32", change=True),
        build_node(f"{prefix}_b_", "Int32", change=True),
    ]
    ctx = _setup(api, settings, mocker_endpoint, tmp_path_factory, case_id, nodes)
    tags = []
    group_id = None
    group_errors: list[str] = []
    try:
        for i, node in enumerate(nodes):
            tags.append(add_collection_tag(
                api, settings, ctx, case_id,
                node_id_str=node_id_from_cfg(node), type_key="INT",
            ))
            wait_rt_valid(api, tags[-1]["tag_name"], timeout=60.0)

        group_name = unique_name(settings.test_prefix, f"{case_id}-group")
        group_data = add_tag_group(api, group_name)
        group_id = int(group_data.get("id") or group_data.get("groupId"))
        add_tag_group_relation(api, group_id=str(group_id), tag_ids=[t["tag_id"] for t in tags])

        points = rt_query(api, group_id=group_id, is_from_db=False)
        assert isinstance(points, list), f"expected list, got {type(points)}"
        names = {p.get("tagName") for p in points}
        assert all(t["tag_name"] in names for t in tags), \
            f"group query missing expected tags: have={sorted(names)}"
        assert len(names) <= len(tags), \
            f"group query returned tags outside the group: {sorted(names - {t['tag_name'] for t in tags})}"

        ds_ids = {p.get("dsId") for p in points if p.get("dsId") is not None}
        assert ds_ids == {ctx["ds_id"]}, f"group query crossed datasources: {ds_ids}"
    finally:
        _teardown(api, ctx, tags)
        if group_id is not None:
            try:
                delete_tag_group(api, [str(group_id)])
            except Exception as exc:
                group_errors.append(f"delete group {group_id}: {exc}")
        if group_errors:
            raise AssertionError("; ".join(group_errors))


# ---------------------------------------------------------------------------
# UA-3-2-004 实时库_批量跨数据源
# ---------------------------------------------------------------------------
@pytest.mark.case(
    id="UA-3-2-004", chapter="UA-3-2",
    title="实时库_批量跨数据源",
    preconditions=["两个数据源 A/B", "数据源 alive=true"],
    steps=["查询 A、B 多个位号", "确认 dsId、tagName、值不串源"],
    expected=["dsId、tagName、值不串源"],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_ua3_2_004_rt_multi_ds(api, settings, tmp_path_factory, mocker_endpoint):
    from tests.support.endpoints import parse_mocker_endpoint
    from tests.support.mocker_process import find_free_port, start_mocker, write_mocker_config
    from tests.support.naming import unique_name
    from tpt_api.datahub import add_ds_info
    from tpt_api.types import DsSubTypes, DsTypes

    case_id = "UA-3-2-004"
    parsed = parse_mocker_endpoint(mocker_endpoint)

    def _build_ds(letter: str, node) -> dict:
        port = find_free_port()
        endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
        tmp_dir = tmp_path_factory.mktemp(f"m_{case_id.lower()}_{letter}")
        cfg_path = write_mocker_config(tmp_dir, port, nodes=[node], namespace_index=1, cycle=500)
        mocker = start_mocker(cfg_path, port, host=parsed.host)
        ds_name = unique_name(settings.test_prefix, f"{case_id}-ds-{letter}")
        data = add_ds_info(
            api, ds_name=ds_name,
            ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
            ds_tar_url=endpoint,
        )
        ds_id = int(data.get("id") or data.get("dsId"))
        from tests.support.ua2_helpers import is_ds_alive
        wait_until(f"ds_alive:{case_id}-{letter}", lambda: is_ds_alive(api, ds_id), timeout=60.0)
        return {
            "ds_id": ds_id, "ds_name": ds_name, "mocker": mocker,
            "port": port, "host": parsed.host, "endpoint": endpoint,
            "cfg_path": cfg_path, "namespace_index": 1,
        }

    ctx_a = _build_ds("A", build_node("ua32_004_a_", "Int32", change=True))
    ctx_b = _build_ds("B", build_node("ua32_004_b_", "Int32", change=True))
    tags = []
    ctxs = [ctx_a, ctx_b]
    try:
        tag_a = add_collection_tag(api, settings, ctx_a, case_id, node_id_str="ua32_004_a_1", type_key="INT")
        tag_b = add_collection_tag(api, settings, ctx_b, case_id, node_id_str="ua32_004_b_1", type_key="INT")
        tags = [tag_a, tag_b]
        wait_rt_valid(api, tag_a["tag_name"], timeout=60.0)
        wait_rt_valid(api, tag_b["tag_name"], timeout=60.0)

        points = rt_query(
            api,
            tag_names=[tag_a["tag_name"], tag_b["tag_name"]],
            is_from_db=False,
        )
        assert isinstance(points, list) and len(points) == 2, f"expected 2 points, got {points}"
        for pt in points:
            assert pt.get("quality", 0) != 0, f"quality 0 for {pt.get('tagName')}"
        pa = _by_name(points, tag_a["tag_name"])
        pb = _by_name(points, tag_b["tag_name"])
        assert pa and pb, f"missing a tag in response: {points}"
        assert int(pa.get("dsId", -1)) == ctx_a["ds_id"], f"A dsId={pa.get('dsId')}"
        assert int(pb.get("dsId", -1)) == ctx_b["ds_id"], f"B dsId={pb.get('dsId')}"
        # 值不串源：源值经 clamp 检查与各自 RT 一致
        for t, ctx in ((tag_a, ctx_a), (tag_b, ctx_b)):
            node_id = f"ua32_004_{'a' if t is tag_a else 'b'}_1"
            snap = None
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                src = opcua_read_sync(ctx["endpoint"], node_id, namespace_index=1)
                pt = get_rt_point(api, t["tag_name"])
                if pt.get("tagValue") is not None:
                    try:
                        assert_value_equal(src, pt["tagValue"], DataTypes["INT"])
                        snap = True
                        break
                    except AssertionError:
                        pass
                time.sleep(0.5)
            assert snap, f"tag {t['tag_name']} RT not consistent with its own source"
    finally:
        cleanup_ua3_multi_context(api, tags=tags, ds_contexts=ctxs)
