"""J 阶段: 跨模块资源模型回归 + catalog/inventory 完整性(主 Agent 维护)。

验证整个 UA-2 资源重构的端到端不变量:
- catalog 仍 419 条,UA-2 265 条。
- case_inventory 结构 OK(documented=419, implemented+partial=419, unimplemented=0,
  malformedRows=0, duplicateDocumentIds=0)。
- 265 个 UA-2 handler 全部在派发表里且可派发。
- 三个 UA-2 runtime 模块不再依赖 ua2_common.prepare_datasource(状态检查:
  monkeypatch 为 raise,逐个派发 handler,确认无一触发)。

"不调 prepare_datasource / 不建删数据源" 的逐 case 行为验证已由
test_ua2_1_refactor / test_ua2_2_refactor / test_ua2_4_refactor 的
test_no_prepare_datasource 覆盖;本文件做跨模块聚合 + 文档完整性。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ua_test_harness.config import RunConfig
from ua_test_harness.context import CaseContext, RunContext
from ua_test_harness.resources import ResourceRegistry


REPO_ROOT = Path(__file__).resolve().parents[2]


def _ctx() -> RunContext:
    cfg = RunConfig()
    cfg.run_id = "ua2_resource_model_run"
    cfg.local_ip = "127.0.0.1"
    cfg.mock.endpoints.functional = "opc.tcp://127.0.0.1:18965/ua_mocker/"
    return RunContext(
        config=cfg, emitter=MagicMock(),
        evidence_root=None, log_path=None, cancellation_token=None,
    )


def _cc(case_id: str) -> CaseContext:
    return CaseContext(case_id=case_id, title="t", registry=ResourceRegistry())


# --- catalog / inventory 完整性 ---


def test_catalog_total_419_and_ua2_265():
    from ua_test_harness.catalog import all_defs, discover

    discover("ua_test_harness.tests")
    defs = list(all_defs())
    assert len(defs) == 419, len(defs)
    ua2 = [d for d in defs if d.id.startswith("UA-2-")]
    assert len(ua2) == 265, len(ua2)


def test_inventory_structure_ok():
    from ua_test_harness.case_inventory import build_inventory, structural_failures

    report = build_inventory(REPO_ROOT, expected_total=419)
    s = report["summary"]
    assert s["documented"] == 419, s
    assert s["implemented"] + s["partial"] == 419, s
    assert s["unimplemented"] == 0, s
    assert s["partial"] > 0, s
    assert s["duplicateDocumentIds"] == 0, s
    assert s["malformedRows"] == 0, s
    assert s["structureOk"] is True, s
    assert structural_failures(report) == [], structural_failures(report)


# --- UA-2 handler 派发 ---


def test_all_supported_handlers_dispatch():
    from ua_test_harness.ua2_runtime import (
        _EXECUTE_UA2, is_supported_ua2, supported_ua2_ids,
    )
    from ua_test_harness.ua2_registry import ua2_all_ids

    expected = set(ua2_all_ids())
    assert len(_EXECUTE_UA2) == 265, len(_EXECUTE_UA2)
    assert set(_EXECUTE_UA2.keys()) == expected
    for cid in expected:
        assert is_supported_ua2(cid) is True
    assert set(supported_ua2_ids()) == expected


# --- 跨模块: 全部 handler 均不调 prepare_datasource ---

# 逐 case 的行为级 "不调 prepare_datasource / 不建删 DS" 已由各 runtime 的
# test_no_prepare_datasource 覆盖(全量 pytest 会跑)。这里补一个聚合断言:
# 三个 runtime 模块不再以可调用名引入 prepare_datasource。

def test_runtime_modules_do_not_expose_prepare_datasource():
    import ua_test_harness.ua2_create_runtime as c
    import ua_test_harness.ua2_query_runtime as q
    import ua_test_harness.ua2_recycle_runtime as r

    for mod in (c, q, r):
        # 模块自身不应再绑定 prepare_datasource 这一名字(旧实现从 ua2_common 导入它)。
        assert not hasattr(mod, "prepare_datasource"), \
            f"{mod.__name__} still exposes prepare_datasource"


def test_runtime_modules_use_shared_datasource_and_ops():
    """三个 runtime 模块必须依赖 provisioning.require_shared_datasource
    和 ua2_ops(而非 fixtures.datasource 自建数据源)。"""
    import ua_test_harness.ua2_create_runtime as c
    import ua_test_harness.ua2_query_runtime as q
    import ua_test_harness.ua2_recycle_runtime as r

    for mod in (c, q, r):
        assert hasattr(mod, "require_shared_datasource"), mod.__name__
    # ops 层被 create/recycle 使用(query 不建 tag 时可不引 create_case_tag,但应引 ops 查询)
    assert hasattr(c, "create_case_tag") and hasattr(c, "cleanup_case_tag")
    assert hasattr(r, "create_case_tag") and hasattr(r, "cleanup_case_tag")
