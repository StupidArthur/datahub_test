"""Regression tests for the test_cases migration from ua_test_gui to ua_test_harness."""
from __future__ import annotations

from pathlib import Path

from ua_test_harness.case_inventory import (
    build_inventory,
    default_test_cases_dir,
    load_documented_cases,
    parse_case_doc,
)


def test_default_test_cases_dir_points_to_harness() -> None:
    """default_test_cases_dir() 不带参数时应指向 ua_test_harness/test_cases。"""
    result = default_test_cases_dir()
    assert result.name == "test_cases"
    assert result.parent.name == "ua_test_harness"
    assert result.is_dir(), f"expected directory to exist: {result}"


def test_default_test_cases_dir_with_repo_root(tmp_path: Path) -> None:
    """传入 repo_root 时应返回 <repo_root>/ua_test_harness/test_cases。"""
    result = default_test_cases_dir(tmp_path)
    assert result == tmp_path.resolve() / "ua_test_harness" / "test_cases"


def test_load_documented_cases_from_tmp_repo(tmp_path: Path) -> None:
    """构造临时仓库结构，验证 load_documented_cases 能正常读取。"""
    doc_dir = tmp_path / "ua_test_harness" / "test_cases"
    doc_dir.mkdir(parents=True)
    (doc_dir / "UA-1-1.md").write_text(
        "# UA-1-1 连接建立\n"
        "\n"
        "| 编号 | 三级点 | 前置条件 | 测试步骤 | 预期结果 | 验证手段 |\n"
        "|---|---|---|---|---|---|\n"
        "| UA-1-1-01 | 正常连接 | mock ready | create | alive=true | list |\n",
        encoding="utf-8",
    )
    rows, malformed = load_documented_cases(tmp_path)
    assert malformed == []
    assert len(rows) == 1
    assert rows[0]["id"] == "UA-1-1-01"


def test_inventory_works_without_gui_directory(tmp_path: Path) -> None:
    """构造不包含 ua_test_gui 的临时仓库，验证 inventory 可正常生成。"""
    doc_dir = tmp_path / "ua_test_harness" / "test_cases"
    doc_dir.mkdir(parents=True)
    (doc_dir / "UA-1-1.md").write_text(
        "# UA-1-1 连接建立\n"
        "\n"
        "| 编号 | 三级点 | 前置条件 | 测试步骤 | 预期结果 | 验证手段 |\n"
        "|---|---|---|---|---|---|\n"
        "| UA-1-1-01 | A | P | S | E | V |\n"
        "| UA-1-1-02 | B | P | S | E | V |\n",
        encoding="utf-8",
    )
    # 确认没有 ua_test_gui 目录
    assert not (tmp_path / "ua_test_gui").exists()

    report = build_inventory(
        tmp_path,
        implemented={"UA-1-1-01": {"filePath": "test.py", "lineno": 1}},
        expected_total=2,
    )
    assert report["summary"]["documented"] == 2
    assert report["summary"]["implemented"] == 1
    assert report["summary"]["structureOk"] is True


def test_doc_path_uses_harness_directory(tmp_path: Path) -> None:
    """验证 docPath 字段使用 ua_test_harness/test_cases/ 前缀。"""
    doc_dir = tmp_path / "ua_test_harness" / "test_cases"
    doc_dir.mkdir(parents=True)
    (doc_dir / "UA-2-1.md").write_text(
        "# UA-2-1 位号新增\n"
        "\n"
        "| 编号 | 三级点 | 类型 | 前置条件 | 测试步骤 | 预期结果 / 断言 | 验证手段 | 清理 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| UA-2-1-001 | 一次位号 | 回归 | ds alive | add | saved | page | delete |\n",
        encoding="utf-8",
    )
    rows, malformed = load_documented_cases(tmp_path)
    assert malformed == []
    assert rows[0]["docPath"] == "ua_test_harness/test_cases/UA-2-1.md"
    assert "ua_test_gui" not in rows[0]["docPath"]


def test_real_repo_cases_are_unique_and_complete() -> None:
    """验证真实仓库中所有 Markdown Case 能注册，Case ID 无重复。"""
    # 使用真实仓库路径
    repo_root = default_test_cases_dir().parents[1]  # ua_test_harness/test_cases -> ua_test_harness -> repo
    rows, malformed = load_documented_cases(repo_root)
    assert malformed == [], f"malformed rows: {malformed[:5]}"
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), f"duplicate IDs: {[x for x in ids if ids.count(x) > 1]}"
    assert len(ids) == 419, f"expected 419 cases, got {len(ids)}"
    # 验证所有 docPath 使用新路径
    for row in rows:
        assert row["docPath"].startswith("ua_test_harness/test_cases/"), f"bad docPath: {row['docPath']}"
        assert "ua_test_gui" not in row["docPath"], f"old path in docPath: {row['docPath']}"
