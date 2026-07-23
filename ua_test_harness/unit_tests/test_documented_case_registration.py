from __future__ import annotations

from ua_test_harness.catalog import all_defs, case, reset


def setup_function(_fn):
    reset()


def test_all_documented_cases_register_with_metadata() -> None:
    from ua_test_harness.tests.zz_documented_cases import register_documented_cases

    register_documented_cases()
    defs = all_defs()
    assert len(defs) == 419
    ids = [item.id for item in defs]
    assert len(ids) == len(set(ids))
    assert all(item.title for item in defs)
    assert all(item.chapter for item in defs)
    assert all(item.doc_path for item in defs)
    assert all(item.steps for item in defs)
    assert all(item.assertions for item in defs)
    assert all(callable(item.impl_func) for item in defs)


def test_handwritten_case_wins_without_duplicate_registration() -> None:
    from ua_test_harness.tests.zz_documented_cases import register_documented_cases

    @case(id="UA-1-1-01", title="handwritten", chapter="UA-1-1")
    def handwritten(_ctx, _cc):
        return None

    added = register_documented_cases()
    defs = all_defs()
    assert added == 418
    assert len(defs) == 419
    matched = [item for item in defs if item.id == "UA-1-1-01"]
    assert len(matched) == 1
    assert matched[0].title == "handwritten"
