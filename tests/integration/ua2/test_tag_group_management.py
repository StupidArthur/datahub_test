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
        if pid and pid != "0":
            assert pid in all_ids, (
                f"node {n['id']} references parent {pid} which does not exist"
            )
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
    """UA-2-5-009: 编辑分组节点"""

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
