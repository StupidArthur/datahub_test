from __future__ import annotations

from pathlib import Path

from ua_test_harness.case_inventory import build_inventory, parse_case_doc, structural_failures


def _write_doc(repo: Path, body: str, name: str = "UA-1-1.md") -> Path:
    path = repo / "ua_test_harness" / "test_cases" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_parse_case_doc_reads_six_columns(tmp_path: Path) -> None:
    path = _write_doc(
        tmp_path,
        """# UA-1-1 连接建立

| 编号 | 三级点 | 前置条件 | 测试步骤 | 预期结果 | 验证手段 |
|---|---|---|---|---|---|
| UA-1-1-01 | 正常连接 | mock ready | create | alive=true | list |
""",
    )
    cases, malformed = parse_case_doc(path, tmp_path)
    assert malformed == []
    assert cases[0]["id"] == "UA-1-1-01"
    assert cases[0]["chapter"] == "UA-1-1"
    assert cases[0]["title"] == "正常连接"
    assert cases[0]["kind"] == ""
    assert cases[0]["cleanup"] == ""


def test_parse_case_doc_reads_eight_columns(tmp_path: Path) -> None:
    path = _write_doc(
        tmp_path,
        """# UA-2-1 位号新增
| 编号 | 三级点 | 类型 | 前置条件 | 测试步骤 | 预期结果 / 断言 | 验证手段 | 清理 |
|---|---|---|---|---|---|---|---|
| UA-2-1-001 | 一次位号 | 回归 | ds alive | add | saved | page | delete |
""",
        "UA-2-1.md",
    )
    cases, malformed = parse_case_doc(path, tmp_path)
    assert malformed == []
    assert cases[0]["id"] == "UA-2-1-001"
    assert cases[0]["kind"] == "回归"
    assert cases[0]["cleanup"] == "delete"


def test_parse_case_doc_reads_seven_column_test_data_table(tmp_path: Path) -> None:
    path = _write_doc(
        tmp_path,
        """# UA-2-1 位号新增
| 编号 | 三级点 | 类型 | 前置条件 | 测试数据 | 验证手段 | 清理 |
|---|---|---|---|---|---|---|
| UA-2-1-026 | Boolean 默认读取 | 回归 | Boolean node | dataType=1 | 公共读取断言 | 删除位号 |
""",
        "UA-2-1.md",
    )
    cases, malformed = parse_case_doc(path, tmp_path)
    assert malformed == []
    assert cases[0]["testData"] == "dataType=1"
    assert cases[0]["steps"] == "测试数据：dataType=1"
    assert cases[0]["verification"] == "公共读取断言"


def test_parse_case_doc_accepts_missing_trailing_cell_and_pipe(tmp_path: Path) -> None:
    path = _write_doc(
        tmp_path,
        """# UA-3-4 历史查询
| 编号 | 三级点 | 类型 | 造数/步骤 | 断言 | 验证 |
|---|---|---|---|---|---|
| UA-3-4-008 | 非法时间 | 回归 | begin>end | 明确失败
""",
        "UA-3-4.md",
    )
    cases, malformed = parse_case_doc(path, tmp_path)
    assert malformed == []
    assert [case["id"] for case in cases] == ["UA-3-4-008"]
    assert cases[0]["expected"] == "明确失败"
    assert cases[0]["verification"] == ""
    assert cases[0]["documentWarnings"]


def test_build_inventory_marks_implemented_and_missing(tmp_path: Path) -> None:
    _write_doc(
        tmp_path,
        """# UA-1-1 连接建立
| 编号 | 三级点 | 前置条件 | 测试步骤 | 预期结果 | 验证手段 |
|---|---|---|---|---|---|
| UA-1-1-01 | A | P | S | E | V |
| UA-1-1-02 | B | P | S | E | V |
""",
    )
    report = build_inventory(
        tmp_path,
        implemented={"UA-1-1-01": {"filePath": "test.py", "lineno": 1}},
        expected_total=2,
    )
    assert report["summary"]["documented"] == 2
    assert report["summary"]["implemented"] == 1
    assert report["summary"]["partial"] == 0
    assert report["summary"]["unimplemented"] == 1
    assert report["cases"][0]["implementationStatus"] == "IMPLEMENTED"
    assert report["cases"][1]["implementationStatus"] == "UNIMPLEMENTED"
    assert report["summary"]["structureOk"] is True
    assert structural_failures(report) == []
