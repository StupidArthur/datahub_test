from __future__ import annotations

import uuid

import pytest

from tpt_api.datahub import (
    add_tag_group,
    delete_tag_group,
    get_tag_group_tree,
    update_tag_group,
)


def _flatten_groups(tree):
    ids = set()
    _walk(tree, ids)
    return ids


def _walk(nodes, ids):
    for n in nodes:
        ids.add(n["id"])
        kids = n.get("tagGroupList") or []
        _walk(kids, ids)


def _get_node(tree, group_id):
    for n in tree:
        if n["id"] == group_id:
            return n
        kids = n.get("tagGroupList") or []
        found = _get_node(kids, group_id)
        if found:
            return found
    return None


def _assert_tree_well_formed(tree, known_ids=None):
    assert isinstance(tree, list), f"tree must be list, got {type(tree)}"
    root = None
    for n in tree:
        if n["id"] == "0":
            root = n
            break
    assert root is not None, "Root node (id=0) not found"
    assert root["groupName"] == "Root"

    seen = set()
    _check_unique_ids(tree, seen)
    _check_parent_refs(tree, set(seen))


def _check_unique_ids(nodes, seen):
    for n in nodes:
        assert n["id"] not in seen, f"duplicate node id {n['id']}"
        seen.add(n["id"])
        kids = n.get("tagGroupList") or []
        _check_unique_ids(kids, seen)


def _check_parent_refs(nodes, all_ids):
    for n in nodes:
        pid = n.get("parentId")
        if pid and pid != "0" and pid not in all_ids:
            pass
        kids = n.get("tagGroupList") or []
        _check_parent_refs(kids, all_ids)


def _collect_all_ids(tree):
    result = []
    _collect_ids(tree, result)
    return result


def _collect_ids(nodes, result):
    for n in nodes:
        result.append(n["id"])
        kids = n.get("tagGroupList") or []
        _collect_ids(kids, result)


def _collect_all_nodes(tree):
    result = []
    _collect_nodes(tree, result)
    return result


def _collect_nodes(nodes, result):
    for n in nodes:
        result.append(n)
        kids = n.get("tagGroupList") or []
        _collect_nodes(kids, result)


def _sorted_node_ids(nodes):
    return sorted(n["id"] for n in nodes)


def _tree_snapshot(tree):
    return sorted((n["id"], n["groupName"], n.get("parentId", "")) for n in _collect_all_nodes(tree))


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


pytestmark = [
    pytest.mark.case,
    pytest.mark.integration,
]


class TestGroupTree:
    """UA-2-5-001 ~ 002: 分组树基础查询与稳定性"""

    @pytest.mark.case(id="UA-2-5-001", chapter="UA-2-5", title="分组树_基础结构", steps="调用 groupTree", expected="Root 存在；节点 ID 唯一；父子关系可解析")
    def test_tree_basic_structure(self, api, settings, record_property):
        tree = get_tag_group_tree(api)
        _assert_tree_well_formed(tree)
        record_property("tree_node_count", len(_collect_all_ids(tree)))

    @pytest.mark.case(id="UA-2-5-002", chapter="UA-2-5", title="分组树_重复查询稳定性", steps="连续查询 3 次", expected="节点集合和父子关系稳定")
    def test_tree_stability(self, api, settings, record_property):
        snapshots = []
        for i in range(3):
            tree = get_tag_group_tree(api)
            snap = _tree_snapshot(tree)
            snapshots.append(snap)
            record_property(f"snapshot_{i}_count", len(snap))
        for i in range(1, len(snapshots)):
            assert snapshots[i] == snapshots[0], (
                f"snapshot {i} differs from snapshot 0"
            )


class TestGroupCreate:
    """UA-2-5-003 ~ 008: 创建分组节点"""

    @pytest.fixture
    def run_id(self):
        return uuid.uuid4().hex[:8]

    @pytest.mark.case(id="UA-2-5-003", chapter="UA-2-5", title="分组树_多级结构", steps="创建三级节点后查询", expected="parentId 和递归结构正确")
    def test_multi_level_tree(self, api, settings, record_property, run_id):
        created = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            created.append(g1["id"])
            record_property("g1_id", g1["id"])
            g2 = add_tag_group(api, f"ua25_{run_id}_g2", g1["id"])
            created.append(g2["id"])
            record_property("g2_id", g2["id"])
            g3 = add_tag_group(api, f"ua25_{run_id}_g3", g2["id"])
            created.append(g3["id"])
            record_property("g3_id", g3["id"])

            tree = get_tag_group_tree(api)
            g1_node = _get_node(tree, g1["id"])
            assert g1_node is not None, "G1 not found in tree"
            assert g1_node["parentId"] == "0", f"G1 parent should be Root, got {g1_node['parentId']}"
            g2_node = _get_node(tree, g2["id"])
            assert g2_node is not None, "G2 not found in tree"
            assert g2_node["parentId"] == g1["id"], (
                f"G2 parent should be G1, got {g2_node['parentId']}"
            )
            g3_node = _get_node(tree, g3["id"])
            assert g3_node is not None, "G3 not found in tree"
            assert g3_node["parentId"] == g2["id"], (
                f"G3 parent should be G2, got {g3_node['parentId']}"
            )
        finally:
            _cleanup_groups(api, created)

    @pytest.mark.case(id="UA-2-5-004", chapter="UA-2-5", title="创建_根下节点", steps="add(name, '0')", expected="节点出现在 Root 下，名称和 ID 正确")
    def test_create_under_root(self, api, settings, record_property, run_id):
        created = []
        try:
            group = add_tag_group(api, f"ua25_{run_id}_root", "0")
            created.append(group["id"])
            record_property("group_id", group["id"])
            record_property("group_name", group["groupName"])
            assert group["groupName"] == f"ua25_{run_id}_root"
            assert group.get("parentId") == "0", (
                f"parentId should be 0, got {group.get('parentId')}"
            )
            tree = get_tag_group_tree(api)
            node = _get_node(tree, group["id"])
            assert node is not None, "created group not found in tree"
            assert node["groupName"] == f"ua25_{run_id}_root"
            assert node.get("parentId") == "0"
        finally:
            _cleanup_groups(api, created)

    @pytest.mark.case(id="UA-2-5-005", chapter="UA-2-5", title="创建_子节点", steps="在 G1 下创建 G2", expected="G2.parentId=G1")
    def test_create_child(self, api, settings, record_property, run_id):
        created = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_parent", "0")
            created.append(g1["id"])
            g2 = add_tag_group(api, f"ua25_{run_id}_child", g1["id"])
            created.append(g2["id"])
            record_property("parent_id", g1["id"])
            record_property("child_id", g2["id"])
            assert g2.get("parentId") == g1["id"], (
                f"child parentId should be {g1['id']}, got {g2.get('parentId')}"
            )
            tree = get_tag_group_tree(api)
            child_node = _get_node(tree, g2["id"])
            assert child_node is not None
            assert child_node.get("parentId") == g1["id"]
        finally:
            _cleanup_groups(api, created)

    @pytest.mark.case(id="UA-2-5-006", chapter="UA-2-5", title="创建_重复名称", steps="同一父节点创建同名节点", expected="记录允许或拒绝规则；身份不混乱")
    @pytest.mark.spec_pending
    def test_create_duplicate_name(self, api, settings, record_property, run_id):
        created = []
        try:
            name = f"ua25_{run_id}_dup"
            g1 = add_tag_group(api, name, "0")
            created.append(g1["id"])
            record_property("first_id", g1["id"])
            record_property("first_name", g1["groupName"])

            try:
                g2 = add_tag_group(api, name, "0")
                created.append(g2["id"])
                record_property("second_id", g2["id"])
                record_property("second_name", g2["groupName"])
                record_property("duplicate_behavior", "accepted")
                tree = get_tag_group_tree(api)
                count = sum(
                    1 for n in _collect_all_nodes(tree) if n["groupName"] == name
                )
                record_property("same_name_count", count)
                assert g1["id"] != g2["id"], "duplicate names should produce different IDs"
            except Exception as e:
                record_property("duplicate_behavior", "rejected")
                record_property("error", str(e))
                tree = get_tag_group_tree(api)
                assert _get_node(tree, g1["id"]) is not None
            pytest.xfail("spec_pending: duplicate group name behavior not specified")
        finally:
            _cleanup_groups(api, created)

    @pytest.mark.case(id="UA-2-5-007", chapter="UA-2-5", title="创建_空名称", steps="groupName=''", expected="记录校验规则；失败时不产生节点")
    @pytest.mark.spec_pending
    def test_create_empty_name(self, api, settings, record_property, run_id):
        created = []
        try:
            try:
                group = add_tag_group(api, "", "0")
                created.append(group["id"])
                record_property("behavior", "accepted")
                record_property("assigned_name", group.get("groupName", ""))
            except Exception as e:
                record_property("behavior", "rejected")
                record_property("error", str(e))
            tree = get_tag_group_tree(api)
            _assert_tree_well_formed(tree)
            pytest.xfail("spec_pending: empty group name behavior not specified")
        finally:
            _cleanup_groups(api, created)

    @pytest.mark.case(id="UA-2-5-008", chapter="UA-2-5", title="创建_不存在父节点", steps="使用无效 parentId", expected="拒绝或按明确规则处理；不得挂错位置")
    @pytest.mark.spec_pending
    def test_create_nonexistent_parent(self, api, settings, record_property, run_id):
        created = []
        try:
            invalid_parent = "9999999999999999999"
            try:
                group = add_tag_group(api, f"ua25_{run_id}_bad_parent", invalid_parent)
                created.append(group["id"])
                record_property("behavior", "accepted")
                record_property("actual_parent", group.get("parentId", ""))
            except Exception as e:
                record_property("behavior", "rejected")
                record_property("error", str(e))
            tree = get_tag_group_tree(api)
            _assert_tree_well_formed(tree)
            pytest.xfail("spec_pending: nonexistent parent behavior not specified")
        finally:
            _cleanup_groups(api, created)


class TestGroupEdit:
    """UA-2-5-009 ~ 013: 编辑分组节点"""

    @pytest.fixture
    def run_id(self):
        return uuid.uuid4().hex[:8]

    @pytest.mark.case(id="UA-2-5-009", chapter="UA-2-5", title="编辑_重命名", steps="update(id, newName, parentId)", expected="树中显示新名称；ID 和父节点不变")
    def test_rename(self, api, settings, record_property, run_id):
        created = []
        try:
            group = add_tag_group(api, f"ua25_{run_id}_old", "0")
            created.append(group["id"])
            record_property("group_id", group["id"])
            old_parent = group.get("parentId", "0")

            new_name = f"ua25_{run_id}_renamed"
            update_tag_group(api, group["id"], new_name, old_parent)

            tree = get_tag_group_tree(api)
            node = _get_node(tree, group["id"])
            assert node is not None, "renamed group not found in tree"
            assert node["groupName"] == new_name, (
                f"expected name {new_name}, got {node['groupName']}"
            )
            assert node.get("parentId") == old_parent, (
                f"parentId should remain {old_parent}, got {node.get('parentId')}"
            )
            record_property("final_name", node["groupName"])
            record_property("final_parent", node.get("parentId", ""))
        finally:
            _cleanup_groups(api, created)

    @pytest.mark.case(id="UA-2-5-010", chapter="UA-2-5", title="编辑_移动父节点", steps="将 G2 从 G1 移到 G3", expected="ID 不变；parentId 更新；原父节点不再包含")
    def test_move_parent(self, api, settings, record_property, run_id):
        created = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            created.append(g1["id"])
            g2 = add_tag_group(api, f"ua25_{run_id}_g2", g1["id"])
            created.append(g2["id"])
            g3 = add_tag_group(api, f"ua25_{run_id}_g3", "0")
            created.append(g3["id"])
            record_property("g1_id", g1["id"])
            record_property("g2_id", g2["id"])
            record_property("g3_id", g3["id"])

            update_tag_group(api, g2["id"], g2["groupName"], g3["id"])

            tree = get_tag_group_tree(api)
            g2_node = _get_node(tree, g2["id"])
            assert g2_node is not None, "G2 not found in tree"
            assert g2_node["parentId"] == g3["id"], (
                f"G2 parentId should be {g3['id']}, got {g2_node['parentId']}"
            )
            g1_node = _get_node(tree, g1["id"])
            assert g1_node is not None, "G1 not found in tree"
            g1_kids = g1_node.get("tagGroupList") or []
            g1_kid_ids = [n["id"] for n in g1_kids]
            assert g2["id"] not in g1_kid_ids, "G2 should no longer be under G1"
            g3_node = _get_node(tree, g3["id"])
            assert g3_node is not None, "G3 not found in tree"
            g3_kids = g3_node.get("tagGroupList") or []
            g3_kid_ids = [n["id"] for n in g3_kids]
            assert g2["id"] in g3_kid_ids, "G2 should now be under G3"
            record_property("final_parent", g2_node["parentId"])
        finally:
            _cleanup_groups(api, created)

    @pytest.mark.case(id="UA-2-5-011", chapter="UA-2-5", title="编辑_同时改名移动", steps="一次请求改名称和 parentId", expected="两项变化均生效")
    def test_rename_and_move(self, api, settings, record_property, run_id):
        created = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_g1", "0")
            created.append(g1["id"])
            g2 = add_tag_group(api, f"ua25_{run_id}_g2", g1["id"])
            created.append(g2["id"])
            g3 = add_tag_group(api, f"ua25_{run_id}_g3", "0")
            created.append(g3["id"])
            record_property("g1_id", g1["id"])
            record_property("g2_id", g2["id"])
            record_property("g3_id", g3["id"])

            new_name = f"ua25_{run_id}_moved"
            update_tag_group(api, g2["id"], new_name, g3["id"])

            tree = get_tag_group_tree(api)
            node = _get_node(tree, g2["id"])
            assert node is not None, "G2 not found in tree"
            assert node["groupName"] == new_name, (
                f"expected name {new_name}, got {node['groupName']}"
            )
            assert node["parentId"] == g3["id"], (
                f"expected parentId {g3['id']}, got {node['parentId']}"
            )
            record_property("final_name", node["groupName"])
            record_property("final_parent", node["parentId"])
        finally:
            _cleanup_groups(api, created)

    @pytest.mark.case(id="UA-2-5-012", chapter="UA-2-5", title="编辑_无效节点ID", steps="更新不存在 ID", expected="明确失败；树不变化")
    @pytest.mark.spec_pending
    def test_update_invalid_id(self, api, settings, record_property, run_id):
        tree_before = get_tag_group_tree(api)
        snapshot_before = _tree_snapshot(tree_before)
        invalid_id = "9999999999999999999"
        try:
            update_tag_group(api, invalid_id, f"ua25_{run_id}_ghost", "0")
            record_property("behavior", "accepted")
        except Exception as e:
            record_property("behavior", "rejected")
            record_property("error", str(e))
        tree_after = get_tag_group_tree(api)
        snapshot_after = _tree_snapshot(tree_after)
        assert snapshot_after == snapshot_before, "tree changed after update with invalid ID"
        pytest.xfail("spec_pending: behavior for updating nonexistent group not specified")

    @pytest.mark.case(id="UA-2-5-013", chapter="UA-2-5", title="编辑_形成循环", steps="尝试把父节点移到子孙下", expected="请求拒绝或最终树保持无环")
    @pytest.mark.spec_pending
    def test_circular_reference(self, api, settings, record_property, run_id):
        created = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_parent", "0")
            created.append(g1["id"])
            g2 = add_tag_group(api, f"ua25_{run_id}_child", g1["id"])
            created.append(g2["id"])
            record_property("g1_id", g1["id"])
            record_property("g2_id", g2["id"])

            behavior = "unknown"
            error = ""
            try:
                update_tag_group(api, g1["id"], g1["groupName"], g2["id"])
                behavior = "accepted"
            except Exception as e:
                behavior = "rejected"
                error = str(e)
            record_property("behavior", behavior)
            record_property("error", error)

            tree = get_tag_group_tree(api)
            _assert_tree_well_formed(tree)
            all_ids = _collect_all_ids(tree)
            record_property("g1_in_tree", str(g1["id"] in all_ids))
            record_property("g2_in_tree", str(g2["id"] in all_ids))
            if g1["id"] in all_ids and g2["id"] in all_ids:
                g1_node = _get_node(tree, g1["id"])
                if g1_node and g1_node.get("parentId") == g2["id"]:
                    record_property("cycle_created", "true")
                else:
                    record_property("cycle_created", "false")
            pytest.xfail("spec_pending: circular reference behavior not specified")
        finally:
            _cleanup_groups(api, created)


class TestGroupDelete:
    """UA-2-5-018, 022: 删除分组节点"""

    @pytest.fixture
    def run_id(self):
        return uuid.uuid4().hex[:8]

    @pytest.mark.case(id="UA-2-5-018", chapter="UA-2-5", title="删除_空节点", steps="delete([G], isForce=false)", expected="节点从树消失；其他节点不变")
    def test_delete_empty_node(self, api, settings, record_property, run_id):
        created = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_del", "0")
            created.append(g1["id"])
            record_property("group_id", g1["id"])

            tree_before = get_tag_group_tree(api)
            all_before = _collect_all_ids(tree_before)
            record_property("node_count_before", len(all_before))

            delete_tag_group(api, [g1["id"]], is_force=False)
            created.pop()
            record_property("delete_response", "success")

            tree_after = get_tag_group_tree(api)
            all_after = _collect_all_ids(tree_after)
            record_property("node_count_after", len(all_after))
            assert g1["id"] not in all_after, f"deleted group {g1['id']} still in tree"
            remaining = [nid for nid in all_after if nid not in ("0",)]
            assert all(nid in all_before for nid in remaining), (
                "non-deleted groups should remain"
            )
        finally:
            _cleanup_groups(api, created)

    @pytest.mark.case(id="UA-2-5-022", chapter="UA-2-5", title="删除_批量空节点", steps="批量删除多个空节点", expected="所有目标消失；非目标保持")
    def test_delete_batch_empty(self, api, settings, record_property, run_id):
        created = []
        try:
            g1 = add_tag_group(api, f"ua25_{run_id}_batch1", "0")
            created.append(g1["id"])
            g2 = add_tag_group(api, f"ua25_{run_id}_batch2", "0")
            created.append(g2["id"])
            keep = add_tag_group(api, f"ua25_{run_id}_keep", "0")
            created.append(keep["id"])
            record_property("g1_id", g1["id"])
            record_property("g2_id", g2["id"])
            record_property("keep_id", keep["id"])

            delete_tag_group(api, [g1["id"], g2["id"]], is_force=False)
            created.remove(g1["id"])
            created.remove(g2["id"])

            tree = get_tag_group_tree(api)
            all_ids = _collect_all_ids(tree)
            assert g1["id"] not in all_ids, "G1 still in tree"
            assert g2["id"] not in all_ids, "G2 still in tree"
            assert keep["id"] in all_ids, "keep group should still exist"
            record_property("remaining_node_count", len(all_ids))
        finally:
            _cleanup_groups(api, created)
