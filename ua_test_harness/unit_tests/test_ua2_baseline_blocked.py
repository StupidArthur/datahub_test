"""验收主 Agent 的接线: BaselineError -> CaseStatus.BLOCKED。

状态分类设计要求:
- 共享数据源/环境前置不可用 = BLOCKED(不是 ERROR)
- 产品断言失败(AssertFail)仍向上抛出,由 runner 归为 FAIL
- 正常 handler 返回值原样透传
"""
import pytest
from unittest.mock import MagicMock

from ua_test_harness.assertions import AssertFail
from ua_test_harness.config import RunConfig
from ua_test_harness.context import RunContext
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import BaselineError
from ua_test_harness.ua2_runtime import _EXECUTE_UA2, execute_ua2_case


def _meta(case_id="UA-2-1-017"):
    return {"id": case_id, "chapter": "UA-2-1", "title": "x", "kind": "regression"}


def _ctx_cc():
    ctx = RunContext(
        config=RunConfig(), emitter=MagicMock(),
        evidence_root=None, log_path=None, cancellation_token=None,
    )
    return ctx, MagicMock()


def test_baseline_error_maps_to_blocked(monkeypatch):
    def boom(ctx, cc):
        raise BaselineError("shared datasource missing")
    monkeypatch.setitem(_EXECUTE_UA2, "UA-2-1-017", boom)
    ctx, cc = _ctx_cc()
    assert execute_ua2_case(ctx, cc, _meta()) == CaseStatus.BLOCKED


def test_assertfail_still_propagates_as_fail(monkeypatch):
    def boom(ctx, cc):
        raise AssertFail("product assertion failed")
    monkeypatch.setitem(_EXECUTE_UA2, "UA-2-1-017", boom)
    ctx, cc = _ctx_cc()
    with pytest.raises(AssertFail):
        execute_ua2_case(ctx, cc, _meta())


def test_normal_handler_return_passes_through(monkeypatch):
    def ok(ctx, cc):
        return CaseStatus.PASS
    monkeypatch.setitem(_EXECUTE_UA2, "UA-2-1-017", ok)
    ctx, cc = _ctx_cc()
    assert execute_ua2_case(ctx, cc, _meta()) == CaseStatus.PASS
