from __future__ import annotations

import pytest

from tools.generate_case_docs import generate, validate_cases


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
