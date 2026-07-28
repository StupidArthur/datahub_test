from __future__ import annotations

import uuid

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    add_tag_group,
    add_tag_group_relation,
    batch_update_tags,
    change_ds_state,
    delete_ds_info,
    delete_tag_group,
    delete_tags_physical,
    get_tag_group_tree,
    list_favorite_tags,
    list_ds_info,
    list_tags,
    query_tags_with_quality,
    remove_tag_group_relation,
    update_tag_group,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, DsSubTypes, DsTypes, TagTypes

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


pytestmark = [
    pytest.mark.case,
    pytest.mark.integration,
    pytest.mark.destructive,
]


def _walk(nodes, ids):
    for n in nodes:
        ids.add(n["id"])
        kids = n.get("tagGroupList") or []
        _walk(kids, ids)


def _collect_all_ids(tree):
    result = []
    _collect_ids(tree, result)
    return result


def _collect_ids(nodes, result):
    for n in nodes:
        result.append(n["id"])
        kids = n.get("tagGroupList") or []
        _collect_ids(kids, result)


def _get_node(tree, group_id):
    for n in tree:
        if n["id"] == group_id:
            return n
        kids = n.get("tagGroupList") or []
        found = _get_node(kids, group_id)
        if found:
            return found
    return None


def _collect_tag_ids_from_group(api, group_id):
    result = query_tags_with_quality(api, group_id=str(group_id), page_size=999)
    records = (result.get("tagInfoList") or {}).get("records") or []
    return [int(r["id"]) for r in records]


def _collect_tag_names_from_group(api, group_id):
    result = query_tags_with_quality(api, group_id=str(group_id), page_size=999)
    records = (result.get("tagInfoList") or {}).get("records") or []
    return [r["tagName"] for r in records]


def _assert_tree_well_formed(tree):
    assert isinstance(tree, list), f"tree must be list, got {type(tree)}"
    root = None
    for n in tree:
        if n["id"] == "0":
            root = n
            break
    assert root is not None, "Root node (id=0) not found"


def _ds_tar_url(parsed, port):
    return f"opc.tcp://{parsed.host}:{port}/ua_mocker/"


class TestTagMove:
    """UA-2-5-014 ~ 017: 位号移动"""

    @pytest.fixture
    def run_id(self):
        return uuid.uuid4().hex[:8]

    def _setup_mocker_ds(self, api, settings, tmp_path_factory, mocker_endpoint, run_id):
        parsed = parse_mocker_endpoint(mocker_endpoint)
        port = find_free_port()
        endpoint = _ds_tar_url(parsed, port)
        ds_name = unique_name(settings.test_prefix, f"UA-2-5-014_{run_id}")
        tmp_dir = tmp_path_factory.mktemp(f"m_ua25_{run_id}")
        cfg_path = write_mocker_config(tmp_dir, port)
        mocker = start_mocker(cfg_path, port, host=parsed.host)
        data = add_ds_info(api, ds_name=ds_name,
                           ds_type=DsTypes["REAL_TIME_DB"],
                           ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
                           ds_tar_url=endpoint)
        ds_id = int(data.get("id") or data.get("dsId"))
        wait_until(f"ds_alive:{ds_id}",
                   lambda: _is_ds_alive(api, ds_id), timeout=60.0)
        return {"mocker": mocker, "ds_id": ds_id, "ds_name": ds_name,
                "endpoint": endpoint, "port": port, "host": parsed.host}

    def _teardown_mocker_ds(self, api, ctx):
        errors = []
        if ctx.get("mocker"):
            try:
                stop_mocker(ctx["mocker"])
            except Exception as e:
                errors.append(f"stop_mocker: {e}")
        if errors:
            raise AssertionError("; ".join(errors))

    @pytest.mark.case(id="UA-2-5-014", chapter="UA-2-5", title="位号移动_单个", steps="batchUpdate([id],groupId=G2)", expected="从原组消失，在 G2 出现；其他配置不变")
    def test_move_single_tag(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_id = None
        tag_name = None
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])
            g2 = add_tag_group(api, f"ua25_{run_id}_g2", "0")
            groups_created.append(g2["id"])
            record_property("g1_id", g1["id"])
            record_property("g2_id", g2["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            tag_name = unique_name(settings.test_prefix, f"UA-2-5-014_{run_id}")
            tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               ds_id=ds_id, group_id=g1["id"],
                               tag_base_name="2_smoke_static_1", only_read=True)
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
            record_property("tag_id", tag_id)
            record_property("tag_name", tag_name)
            wait_until(f"rt:{tag_name}",
                       lambda: get_rt_point(api, tag_name).get("tagValue") is not None,
                       timeout=30.0)

            before_g1_names = _collect_tag_names_from_group(api, g1["id"])
            assert tag_name in before_g1_names, f"tag should be in G1 before move"

            batch_update_tags(api, [tag_id], group_id=g2["id"])

            after_g1_names = _collect_tag_names_from_group(api, g1["id"])
            after_g2_names = _collect_tag_names_from_group(api, g2["id"])
            assert tag_name not in after_g1_names, f"tag should no longer be in G1"
            assert tag_name in after_g2_names, f"tag should now be in G2"
            record_property("g1_after", after_g1_names)
            record_property("g2_after", after_g2_names)
        finally:
            if tag_id is not None:
                try:
                    delete_tags_physical(api, [tag_id])
                except TptAPIError:
                    pass
            if tag_name:
                try:
                    recycle = list_tags(api, page=1, page_size=999)
                    for rec in recycle.get("records") or []:
                        if rec.get("tagName") == tag_name:
                            delete_tags_physical(api, [int(rec["id"])])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)

    @pytest.mark.case(id="UA-2-5-015", chapter="UA-2-5", title="位号移动_多个", steps="批量移动 10 个位号", expected="目标全部移动；未选位号保持")
    def test_move_multiple_tags(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        moved_ids = []
        kept_ids = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_src", "0")
            groups_created.append(g1["id"])
            g2 = add_tag_group(api, f"ua25_{run_id}_dst", "0")
            groups_created.append(g2["id"])
            record_property("g1_id", g1["id"])
            record_property("g2_id", g2["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            moved_names = []
            kept_names = []
            for i in range(10):
                tn = unique_name(settings.test_prefix, f"UA-2-5-015_m{i}_{run_id}")
                td = add_tag(api, tag_name=tn, data_type=DataTypes["DOUBLE"],
                             ds_id=ds_id, group_id=g1["id"],
                             tag_base_name="2_smoke_static_1", only_read=True)
                moved_ids.append(int(td.get("id") or td.get("tagId")))
                moved_names.append(tn)
            for i in range(3):
                tn = unique_name(settings.test_prefix, f"UA-2-5-015_k{i}_{run_id}")
                td = add_tag(api, tag_name=tn, data_type=DataTypes["DOUBLE"],
                             ds_id=ds_id, group_id=g1["id"],
                             tag_base_name="2_smoke_static_1", only_read=True)
                kept_ids.append(int(td.get("id") or td.get("tagId")))
                kept_names.append(tn)
            record_property("moved_count", len(moved_ids))
            record_property("kept_count", len(kept_ids))

            batch_update_tags(api, moved_ids, group_id=g2["id"])

            after_g1_names = _collect_tag_names_from_group(api, g1["id"])
            after_g2_names = _collect_tag_names_from_group(api, g2["id"])
            for n in moved_names:
                assert n not in after_g1_names, f"{n} should not be in G1 after move"
                assert n in after_g2_names, f"{n} should be in G2 after move"
            for n in kept_names:
                assert n in after_g1_names, f"{n} should remain in G1"
                assert n not in after_g2_names, f"{n} should not be in G2"
            record_property("g1_after_count", len(after_g1_names))
            record_property("g2_after_count", len(after_g2_names))
        finally:
            all_tag_ids = moved_ids + kept_ids
            for tid in all_tag_ids:
                try:
                    delete_tags_physical(api, [tid])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)

    @pytest.mark.case(id="UA-2-5-016", chapter="UA-2-5", title="位号移动_Root", steps="移动到 groupId=0", expected="位号进入 Root 范围；配置和采集不变")
    def test_move_to_root(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_id = None
        tag_name = None
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])
            record_property("g1_id", g1["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            tag_name = unique_name(settings.test_prefix, f"UA-2-5-016_{run_id}")
            tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               ds_id=ds_id, group_id=g1["id"],
                               tag_base_name="2_smoke_static_1", only_read=True)
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
            record_property("tag_id", tag_id)
            wait_until(f"rt:{tag_name}",
                       lambda: get_rt_point(api, tag_name).get("tagValue") is not None,
                       timeout=30.0)

            rt_before = get_rt_point(api, tag_name)
            record_property("rt_before", rt_before.get("tagValue"))

            batch_update_tags(api, [tag_id], group_id="0")

            after_g1_names = _collect_tag_names_from_group(api, g1["id"])
            after_root_names = _collect_tag_names_from_group(api, "0")
            assert tag_name not in after_g1_names, "tag should no longer be in G1"
            assert tag_name in after_root_names, "tag should be in Root"

            rt_after = get_rt_point(api, tag_name)
            record_property("rt_after", rt_after.get("tagValue"))
            record_property("rt_after_quality", rt_after.get("quality"))
        finally:
            if tag_id is not None:
                try:
                    delete_tags_physical(api, [tag_id])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)

    @pytest.mark.case(id="UA-2-5-017", chapter="UA-2-5", title="位号移动_无效分组", steps="使用不存在 groupId", expected="失败或按明确规则处理；原关系保持")
    @pytest.mark.spec_pending
    def test_move_invalid_group(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_id = None
        tag_name = None
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])
            record_property("g1_id", g1["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            tag_name = unique_name(settings.test_prefix, f"UA-2-5-017_{run_id}")
            tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               ds_id=ds_id, group_id=g1["id"],
                               tag_base_name="2_smoke_static_1", only_read=True)
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
            record_property("tag_id", tag_id)
            wait_until(f"rt:{tag_name}",
                       lambda: get_rt_point(api, tag_name).get("tagValue") is not None,
                       timeout=30.0)

            before_g1_names = _collect_tag_names_from_group(api, g1["id"])

            invalid_group_id = "99999999999999999"
            try:
                batch_update_tags(api, [tag_id], group_id=invalid_group_id)
                record_property("behavior", "accepted")
            except Exception as e:
                record_property("behavior", "rejected")
                record_property("error", str(e))

            after_g1_names = _collect_tag_names_from_group(api, g1["id"])
            if tag_name not in after_g1_names:
                record_property("tag_disappeared", "true")
                after_all = _collect_tag_ids_from_group(api, "0")
                record_property("root_tag_ids", after_all)
            else:
                record_property("tag_relationship_preserved", "true")
            pytest.xfail("spec_pending: behavior for moving tag to invalid group not specified")
        finally:
            if tag_id is not None:
                try:
                    delete_tags_physical(api, [tag_id])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)


class TestGroupDeleteNonEmpty:
    """UA-2-5-019 ~ 021: 删除非空节点 / 含子节点"""

    @pytest.fixture
    def run_id(self):
        return uuid.uuid4().hex[:8]

    def _setup_mocker_ds(self, api, settings, tmp_path_factory, mocker_endpoint, run_id):
        parsed = parse_mocker_endpoint(mocker_endpoint)
        port = find_free_port()
        endpoint = _ds_tar_url(parsed, port)
        ds_name = unique_name(settings.test_prefix, f"UA-2-5-019_{run_id}")
        tmp_dir = tmp_path_factory.mktemp(f"m_ua25_{run_id}")
        cfg_path = write_mocker_config(tmp_dir, port)
        mocker = start_mocker(cfg_path, port, host=parsed.host)
        data = add_ds_info(api, ds_name=ds_name,
                           ds_type=DsTypes["REAL_TIME_DB"],
                           ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
                           ds_tar_url=endpoint)
        ds_id = int(data.get("id") or data.get("dsId"))
        wait_until(f"ds_alive:{ds_id}",
                   lambda: _is_ds_alive(api, ds_id), timeout=60.0)
        return {"mocker": mocker, "ds_id": ds_id, "ds_name": ds_name,
                "endpoint": endpoint, "port": port, "host": parsed.host}

    def _teardown_mocker_ds(self, api, ctx):
        errors = []
        if ctx.get("mocker"):
            try:
                stop_mocker(ctx["mocker"])
            except Exception as e:
                errors.append(f"stop_mocker: {e}")
        if errors:
            raise AssertionError("; ".join(errors))

    @pytest.mark.case(id="UA-2-5-019", chapter="UA-2-5", title="删除_非空不强制", steps="节点内有位号，isForce=false", expected="记录拒绝、位号迁移或保留规则；位号不得静默丢失")
    @pytest.mark.spec_pending
    def test_delete_nonempty_not_force(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_id = None
        tag_name = None
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])
            record_property("g1_id", g1["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            tag_name = unique_name(settings.test_prefix, f"UA-2-5-019_{run_id}")
            tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               ds_id=ds_id, group_id=g1["id"],
                               tag_base_name="2_smoke_static_1", only_read=True)
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
            record_property("tag_id", tag_id)
            wait_until(f"rt:{tag_name}",
                       lambda: get_rt_point(api, tag_name).get("tagValue") is not None,
                       timeout=30.0)

            record_property("tag_before_group", g1["id"])
            try:
                delete_tag_group(api, [g1["id"]], is_force=False)
                record_property("delete_behavior", "accepted")
            except Exception as e:
                record_property("delete_behavior", "rejected")
                record_property("delete_error", str(e))

            tree = get_tag_group_tree(api)
            g1_still_exists = _get_node(tree, g1["id"]) is not None
            record_property("g1_still_in_tree", str(g1_still_exists))

            tag_still_exists = True
            try:
                rt = get_rt_point(api, tag_name)
                record_property("tag_rt_value", rt.get("tagValue"))
            except TptAPIError:
                tag_still_exists = False
                record_property("tag_rt_value", "not_found")
            record_property("tag_still_exists", str(tag_still_exists))

            if tag_still_exists:
                current_group = _collect_tag_ids_from_group(api, g1["id"])
                root_ids = _collect_tag_ids_from_group(api, "0")
                record_property("tag_in_g1", str(tag_id in current_group))
                record_property("tag_in_root", str(tag_id in root_ids))

            pytest.xfail("spec_pending: delete non-empty not-force behavior not specified")
        finally:
            if tag_id is not None:
                try:
                    delete_tags_physical(api, [tag_id])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)

    @pytest.mark.case(id="UA-2-5-020", chapter="UA-2-5", title="删除_非空强制", steps="节点内有位号，isForce=true", expected="记录位号进入回收站或物理删除规则；最终状态可确认")
    @pytest.mark.spec_pending
    def test_delete_nonempty_force(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_id = None
        tag_name = None
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])
            record_property("g1_id", g1["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            tag_name = unique_name(settings.test_prefix, f"UA-2-5-020_{run_id}")
            tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               ds_id=ds_id, group_id=g1["id"],
                               tag_base_name="2_smoke_static_1", only_read=True)
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
            record_property("tag_id", tag_id)
            wait_until(f"rt:{tag_name}",
                       lambda: get_rt_point(api, tag_name).get("tagValue") is not None,
                       timeout=30.0)

            try:
                delete_tag_group(api, [g1["id"]], is_force=True)
                record_property("delete_behavior", "accepted")
                groups_created.pop()
            except Exception as e:
                record_property("delete_behavior", "rejected")
                record_property("delete_error", str(e))

            tree = get_tag_group_tree(api)
            g1_still_exists = _get_node(tree, g1["id"]) is not None
            record_property("g1_still_in_tree", str(g1_still_exists))

            try:
                rt = get_rt_point(api, tag_name)
                record_property("tag_rt_value", rt.get("tagValue"))
                record_property("tag_still_active", "true")
            except TptAPIError:
                record_property("tag_rt_value", "not_found")
                record_property("tag_still_active", "false")

            try:
                fav = list_favorite_tags(api, page_size=999)
                fav_records = (fav.get("tagInfoList") or {}).get("records") or []
                recycle_ids = [int(r["id"]) for r in fav_records if r.get("tagName") == tag_name]
                record_property("tag_in_favorites", str(tag_id in recycle_ids))
            except Exception as e:
                record_property("tag_in_favorites", f"error:{e}")

            pytest.xfail("spec_pending: delete non-empty force behavior not specified")
        finally:
            if tag_id is not None:
                try:
                    delete_tags_physical(api, [tag_id])
                except TptAPIError:
                    pass
            if tag_name:
                try:
                    recycle = list_tags(api, page=1, page_size=999)
                    for rec in recycle.get("records") or []:
                        if rec.get("tagName") == tag_name:
                            delete_tags_physical(api, [int(rec["id"])])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)

    @pytest.mark.case(id="UA-2-5-021", chapter="UA-2-5", title="删除_含子节点", steps="父节点含子树，分别测试 force=false/true", expected="记录子树处理规则；不得产生孤儿节点")
    @pytest.mark.spec_pending
    def test_delete_with_children(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_id = None
        tag_name = None
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_parent", "0")
            groups_created.append(g1["id"])
            g2 = add_tag_group(api, f"ua25_{run_id}_child", g1["id"])
            groups_created.append(g2["id"])
            record_property("g1_id", g1["id"])
            record_property("g2_id", g2["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            tag_name = unique_name(settings.test_prefix, f"UA-2-5-021_{run_id}")
            tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               ds_id=ds_id, group_id=g2["id"],
                               tag_base_name="2_smoke_static_1", only_read=True)
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
            record_property("tag_id", tag_id)
            wait_until(f"rt:{tag_name}",
                       lambda: get_rt_point(api, tag_name).get("tagValue") is not None,
                       timeout=30.0)

            for force_val in [False, True]:
                record_property(f"try_force_{force_val}", "")
                try:
                    delete_tag_group(api, [g1["id"]], is_force=force_val)
                    record_property(f"force_{force_val}_behavior", "accepted")
                except Exception as e:
                    record_property(f"force_{force_val}_behavior", "rejected")
                    record_property(f"force_{force_val}_error", str(e))

                tree = get_tag_group_tree(api)
                all_ids = _collect_all_ids(tree)
                record_property(f"force_{force_val}_g1_exists", str(g1["id"] in all_ids))
                record_property(f"force_{force_val}_g2_exists", str(g2["id"] in all_ids))
                _assert_tree_well_formed(tree)

            pytest.xfail("spec_pending: delete with children behavior not specified")
        finally:
            if tag_id is not None:
                try:
                    delete_tags_physical(api, [tag_id])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)


class TestFavorites:
    """UA-2-5-023 ~ 027: 收藏与取消收藏"""

    @pytest.fixture
    def run_id(self):
        return uuid.uuid4().hex[:8]

    def _setup_mocker_ds(self, api, settings, tmp_path_factory, mocker_endpoint, run_id):
        parsed = parse_mocker_endpoint(mocker_endpoint)
        port = find_free_port()
        endpoint = _ds_tar_url(parsed, port)
        ds_name = unique_name(settings.test_prefix, f"UA-2-5-023_{run_id}")
        tmp_dir = tmp_path_factory.mktemp(f"m_ua25_{run_id}")
        cfg_path = write_mocker_config(tmp_dir, port)
        mocker = start_mocker(cfg_path, port, host=parsed.host)
        data = add_ds_info(api, ds_name=ds_name,
                           ds_type=DsTypes["REAL_TIME_DB"],
                           ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
                           ds_tar_url=endpoint)
        ds_id = int(data.get("id") or data.get("dsId"))
        wait_until(f"ds_alive:{ds_id}",
                   lambda: _is_ds_alive(api, ds_id), timeout=60.0)
        return {"mocker": mocker, "ds_id": ds_id, "ds_name": ds_name,
                "endpoint": endpoint, "port": port, "host": parsed.host}

    def _teardown_mocker_ds(self, api, ctx):
        errors = []
        if ctx.get("mocker"):
            try:
                stop_mocker(ctx["mocker"])
            except Exception as e:
                errors.append(f"stop_mocker: {e}")
        if errors:
            raise AssertionError("; ".join(errors))

    def _favorite_tag_ids(self, api):
        fav = list_favorite_tags(api, page_size=999)
        records = (fav.get("tagInfoList") or {}).get("records") or []
        return [int(r["id"]) for r in records]

    @pytest.mark.case(id="UA-2-5-023", chapter="UA-2-5", title="收藏_单个位号", steps="addRelation('2',[id])", expected="收藏列表出现目标；普通分组关系不变")
    def test_favorite_single(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_id = None
        tag_name = None
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            tag_name = unique_name(settings.test_prefix, f"UA-2-5-023_{run_id}")
            tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               ds_id=ds_id, group_id=g1["id"],
                               tag_base_name="2_smoke_static_1", only_read=True)
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
            record_property("tag_id", tag_id)
            wait_until(f"rt:{tag_name}",
                       lambda: get_rt_point(api, tag_name).get("tagValue") is not None,
                       timeout=30.0)

            fav_before = self._favorite_tag_ids(api)
            record_property("fav_before_count", len(fav_before))

            add_tag_group_relation(api, "2", [tag_id])

            fav_after = self._favorite_tag_ids(api)
            record_property("fav_after_count", len(fav_after))
            assert tag_id in fav_after, "tag should be in favorites after add"

            g1_ids = _collect_tag_ids_from_group(api, g1["id"])
            assert tag_id in g1_ids, "tag should still be in its original group"
        finally:
            if tag_id is not None:
                try:
                    remove_tag_group_relation(api, "2", [tag_id])
                except TptAPIError:
                    pass
                try:
                    delete_tags_physical(api, [tag_id])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)

    @pytest.mark.case(id="UA-2-5-024", chapter="UA-2-5", title="收藏_多个位号", steps="批量收藏多个 ID", expected="所有目标出现且无重复")
    def test_favorite_multiple(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_ids = []
        tag_names = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            for i in range(5):
                tn = unique_name(settings.test_prefix, f"UA-2-5-024_{i}_{run_id}")
                td = add_tag(api, tag_name=tn, data_type=DataTypes["DOUBLE"],
                             ds_id=ds_id, group_id=g1["id"],
                             tag_base_name="2_smoke_static_1", only_read=True)
                tag_ids.append(int(td.get("id") or td.get("tagId")))
                tag_names.append(tn)
            record_property("tag_ids", tag_ids)

            fav_before = self._favorite_tag_ids(api)
            record_property("fav_before_count", len(fav_before))

            add_tag_group_relation(api, "2", tag_ids)

            fav_after = self._favorite_tag_ids(api)
            record_property("fav_after_count", len(fav_after))
            for tid in tag_ids:
                assert tid in fav_after, f"tag {tid} should be in favorites"
            assert len(fav_after) == len(set(fav_after)), "favorites should contain no duplicates"
        finally:
            if tag_ids:
                try:
                    remove_tag_group_relation(api, "2", tag_ids)
                except TptAPIError:
                    pass
                for tid in tag_ids:
                    try:
                        delete_tags_physical(api, [tid])
                    except TptAPIError:
                        pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)

    @pytest.mark.case(id="UA-2-5-025", chapter="UA-2-5", title="收藏_重复提交", steps="对已收藏 ID 再次收藏", expected="无重复；记录幂等或错误规则")
    @pytest.mark.spec_pending
    def test_favorite_duplicate(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_id = None
        tag_name = None
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            tag_name = unique_name(settings.test_prefix, f"UA-2-5-025_{run_id}")
            tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               ds_id=ds_id, group_id=g1["id"],
                               tag_base_name="2_smoke_static_1", only_read=True)
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
            record_property("tag_id", tag_id)
            wait_until(f"rt:{tag_name}",
                       lambda: get_rt_point(api, tag_name).get("tagValue") is not None,
                       timeout=30.0)

            add_tag_group_relation(api, "2", [tag_id])
            record_property("first_add_response", "done")

            try:
                add_tag_group_relation(api, "2", [tag_id])
                record_property("second_add_behavior", "accepted")
            except Exception as e:
                record_property("second_add_behavior", "rejected")
                record_property("second_add_error", str(e))

            fav_ids = self._favorite_tag_ids(api)
            count = fav_ids.count(tag_id)
            record_property("tag_id_count", count)
            assert count == 1, f"tag should appear exactly once in favorites, got {count}"
            pytest.xfail("spec_pending: duplicate favorite behavior not specified")
        finally:
            if tag_id is not None:
                try:
                    remove_tag_group_relation(api, "2", [tag_id])
                except TptAPIError:
                    pass
                try:
                    delete_tags_physical(api, [tag_id])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)

    @pytest.mark.case(id="UA-2-5-026", chapter="UA-2-5", title="取消收藏_单个与批量", steps="removeRelation('2',ids)", expected="收藏列表移除目标；正常查询仍存在")
    def test_unfavorite(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_ids = []
        tag_names = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            for i in range(3):
                tn = unique_name(settings.test_prefix, f"UA-2-5-026_{i}_{run_id}")
                td = add_tag(api, tag_name=tn, data_type=DataTypes["DOUBLE"],
                             ds_id=ds_id, group_id=g1["id"],
                             tag_base_name="2_smoke_static_1", only_read=True)
                tag_ids.append(int(td.get("id") or td.get("tagId")))
                tag_names.append(tn)
            record_property("tag_ids", tag_ids)

            add_tag_group_relation(api, "2", tag_ids)
            fav_before = self._favorite_tag_ids(api)
            record_property("fav_before_count", len(fav_before))

            remove_tag_group_relation(api, "2", [tag_ids[0]])
            record_property("remove_single_response", "done")

            fav_after_single = self._favorite_tag_ids(api)
            record_property("fav_after_single_count", len(fav_after_single))
            assert tag_ids[0] not in fav_after_single, "first tag should be removed from favorites"
            assert tag_ids[1] in fav_after_single, "second tag should still be in favorites"
            assert tag_ids[2] in fav_after_single, "third tag should still be in favorites"

            g1_ids = _collect_tag_ids_from_group(api, g1["id"])
            assert all(tid in g1_ids for tid in tag_ids), (
                "all tags should still exist in original group"
            )
            record_property("unfavorite_single_verified", True)

            remove_tag_group_relation(api, "2", tag_ids[1:])
            record_property("remove_batch_response", "done")

            fav_after_batch = self._favorite_tag_ids(api)
            record_property("fav_after_batch_count", len(fav_after_batch))
            for tid in tag_ids:
                assert tid not in fav_after_batch, f"tag {tid} should not be in favorites after all removals"
        finally:
            if tag_ids:
                try:
                    remove_tag_group_relation(api, "2", tag_ids)
                except TptAPIError:
                    pass
                for tid in tag_ids:
                    try:
                        delete_tags_physical(api, [tid])
                    except TptAPIError:
                        pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)

    @pytest.mark.case(id="UA-2-5-027", chapter="UA-2-5", title="取消收藏_返回false但生效", steps="记录返回值并查询收藏列表", expected="返回 false 时，以目标实际消失判定生效")
    def test_unfavorite_returns_false(self, api, settings, tmp_path_factory, mocker_endpoint, record_property, run_id):
        groups_created = []
        mocker_ctx = None
        tag_id = None
        tag_name = None
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            groups_created.append(g1["id"])

            mocker_ctx = self._setup_mocker_ds(api, settings, tmp_path_factory, mocker_endpoint, run_id)
            ds_id = mocker_ctx["ds_id"]
            tag_name = unique_name(settings.test_prefix, f"UA-2-5-027_{run_id}")
            tag_data = add_tag(api, tag_name=tag_name, data_type=DataTypes["DOUBLE"],
                               ds_id=ds_id, group_id=g1["id"],
                               tag_base_name="2_smoke_static_1", only_read=True)
            tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
            record_property("tag_id", tag_id)
            wait_until(f"rt:{tag_name}",
                       lambda: get_rt_point(api, tag_name).get("tagValue") is not None,
                       timeout=30.0)

            add_tag_group_relation(api, "2", [tag_id])
            fav_before = self._favorite_tag_ids(api)
            assert tag_id in fav_before, "tag should be favorited before test"

            response = remove_tag_group_relation(api, "2", [tag_id])
            record_property("remove_response", response)

            fav_after = self._favorite_tag_ids(api)
            record_property("fav_after_ids", fav_after)
            assert tag_id not in fav_after, (
                f"tag should be removed from favorites regardless of response. "
                f"response={response}, fav_after={fav_after}"
            )

            g1_ids = _collect_tag_ids_from_group(api, g1["id"])
            assert tag_id in g1_ids, "tag should still exist in its original group"
        finally:
            if tag_id is not None:
                try:
                    remove_tag_group_relation(api, "2", [tag_id])
                except TptAPIError:
                    pass
                try:
                    delete_tags_physical(api, [tag_id])
                except TptAPIError:
                    pass
            if mocker_ctx:
                try:
                    change_ds_state(api, mocker_ctx["ds_id"], False)
                except TptAPIError:
                    pass
                try:
                    delete_ds_info(api, [mocker_ctx["ds_id"]])
                except TptAPIError:
                    pass
                self._teardown_mocker_ds(api, mocker_ctx)
            _cleanup_groups(api, groups_created)


def _is_ds_alive(api, ds_id):
    page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", -1)) == ds_id:
            return bool(row.get("alive"))
    return False


def _cleanup_groups(api, group_ids):
    if not group_ids:
        return
    try:
        tree = get_tag_group_tree(api)
        current = _collect_all_ids(tree)
        to_delete = [gid for gid in reversed(group_ids) if gid in current]
        if to_delete:
            delete_tag_group(api, to_delete)
    except Exception:
        pass
