from __future__ import annotations

import pytest

from tools.generate_case_docs import (
    LIST_FIELDS,
    _coerce_list_field,
    _normalize_list_fields,
    generate,
    render_case,
    validate_cases,
)


def _make_case(cid="UA-X-1", chapter="UA-X", title="t", steps=None, expected=None, nodeid="tests/test_x.py::test_x", **kw):
    return {
        "id": cid,
        "chapter": chapter,
        "title": title,
        "steps": steps or ["step1"],
        "expected": expected or ["ok"],
        "nodeid": nodeid,
        **kw,
    }


def test_duplicate_id_fails():
    cases = [_make_case(cid="DUP"), _make_case(cid="DUP", nodeid="other")]
    with pytest.raises(ValueError, match="duplicate case id"):
        validate_cases(cases)


def test_missing_required_field_fails():
    c = _make_case()
    c["steps"] = []
    with pytest.raises(ValueError, match="missing required field"):
        validate_cases([c])


def test_missing_id_fails():
    c = _make_case()
    c["id"] = ""
    with pytest.raises(ValueError, match="missing id"):
        validate_cases([c])


def test_output_order_stable(tmp_path):
    cases = [_make_case(cid="B-2", chapter="B"), _make_case(cid="A-1", chapter="A")]
    r1 = generate(cases, output_dir=tmp_path)
    r2 = generate(cases, output_dir=tmp_path)
    assert r1 == r2


def test_markdown_contains_nodeid(tmp_path):
    cases = [_make_case(nodeid="tests/integration/test_x.py::test_foo")]
    written = generate(cases, output_dir=tmp_path)
    content = list(written.values())[0]
    assert "tests/integration/test_x.py::test_foo" in content


def test_idempotent(tmp_path):
    cases = [_make_case(cid="C-1", chapter="C"), _make_case(cid="C-2", chapter="C")]
    generate(cases, output_dir=tmp_path)
    first = {f.name: f.read_text(encoding="utf-8") for f in tmp_path.iterdir()}
    generate(cases, output_dir=tmp_path)
    second = {f.name: f.read_text(encoding="utf-8") for f in tmp_path.iterdir()}
    assert first == second


def test_coerce_list_field_str_single_entry():
    assert _coerce_list_field("将 A 写入") == ["将 A 写入"]


def test_coerce_list_field_list_preserved():
    assert _coerce_list_field(["s1", "s2"]) == ["s1", "s2"]


def test_coerce_list_field_tuple_preserved():
    assert _coerce_list_field(("s1", "s2")) == ["s1", "s2"]


def test_coerce_list_field_empty_list():
    assert _coerce_list_field([]) == []


def test_coerce_list_field_illegal_type_raises():
    with pytest.raises(TypeError):
        _coerce_list_field(42)


def test_normalize_str_steps_not_char_split(tmp_path):
    c = _make_case(cid="N-1", steps="将 G 写入 3")
    _normalize_list_fields(c)
    assert c["steps"] == ["将 G 写入 3"]
    rendered = render_case(c)
    assert "1. 将 G 写入 3" in rendered
    assert "2." not in rendered


def test_normalize_str_preconditions_and_expected(tmp_path):
    c = _make_case(cid="N-2", steps=["s"], expected="值为 3")
    c["preconditions"] = "DS 已连接"
    _normalize_list_fields(c)
    assert c["preconditions"] == ["DS 已连接"]
    assert c["expected"] == ["值为 3"]


def test_validate_normalizes_str_fields(tmp_path):
    cases = [_make_case(cid="N-3", steps="单步操作", expected="成功")]
    validate_cases(cases)
    assert cases[0]["steps"] == ["单步操作"]
    written = generate(cases, output_dir=tmp_path)
    content = list(written.values())[0]
    assert "1. 单步操作" in content


def test_all_list_fields_normalized(tmp_path):
    c = _make_case(cid="N-4")
    for field in LIST_FIELDS:
        c[field] = "单条"
    validate_cases([c])
    for field in LIST_FIELDS:
        assert c[field] == ["单条"]
