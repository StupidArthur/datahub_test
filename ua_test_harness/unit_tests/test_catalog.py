"""test_catalog.py:装饰器 + 导出 单测。"""
from __future__ import annotations

import json

from ua_test_harness.catalog import case, all_defs, reset, export_catalog
from ua_test_harness.models import StepDef


def setup_function(_fn):
    reset()


def test_case_decorator_registers():
    @case(id="UA-X-9-999", title="t", chapter="UA-X-9", kind="regression",
          tags=["t1"], timeout_sec=10, exclusive_resources=["res-A"],
          doc_path="doc/x.md", description="d",
          steps=[StepDef(step_id="s1", title="step1")],
          assertions=["a1"])
    def f(ctx, cc):  # pragma: no cover - impl not invoked
        return None

    defs = all_defs()
    assert len(defs) == 1
    cd = defs[0]
    assert cd.id == "UA-X-9-999"
    assert cd.chapter == "UA-X-9"
    assert cd.kind == "regression"
    assert cd.tags == ["t1"]
    assert cd.timeout_sec == 10
    assert cd.exclusive_resources == ["res-A"]
    assert cd.doc_path == "doc/x.md"
    assert cd.steps[0].step_id == "s1"
    assert cd.assertions == ["a1"]


def test_export_catalog_groups_by_chapter(tmp_path):
    @case(id="UA-A-1-001", title="a1", chapter="UA-A-1")
    def a(_c, _cc):  # pragma: no cover
        return None

    @case(id="UA-B-1-001", title="b1", chapter="UA-B-1")
    def b(_c, _cc):  # pragma: no cover
        return None

    @case(id="UA-A-1-002", title="a2", chapter="UA-A-1")
    def c(_c, _cc):  # pragma: no cover
        return None

    out = tmp_path / "catalog.json"
    cat = export_catalog(out, package="__not_a_pkg__")  # 用内存注册的
    assert out.is_file()
    assert cat["version"] == 1
    chapters = {ch["id"]: ch for ch in cat["chapters"]}
    assert set(chapters.keys()) == {"UA-A-1", "UA-B-1"}
    assert len(chapters["UA-A-1"]["cases"]) == 2
    assert len(chapters["UA-B-1"]["cases"]) == 1
    assert chapters["UA-A-1"]["cases"][0]["implemented"] is True