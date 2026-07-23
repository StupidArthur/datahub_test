"""UA-2 精确执行器派发。

按章节 dispatcher 路由全部 UA-2 case;未挂接章节的 ID 保持 BLOCKED。
"""
from __future__ import annotations

import inspect
from typing import Any, Callable

from ua_test_harness.assertions import AssertFail
from ua_test_harness.models import CaseStatus
from ua_test_harness.provisioning import BaselineError
from ua_test_harness.ua2_registry import ua2_all_ids

from ua_test_harness import (
    ua2_create_runtime,
    ua2_group_runtime,
    ua2_import_runtime,
    ua2_query_runtime,
    ua2_recycle_runtime,
)

_CHAPTER_DISPATCH: dict[str, Callable] = {
    "UA-2-1": ua2_create_runtime.dispatch_ua2_1,
    "UA-2-2": ua2_query_runtime.dispatch_ua2_2,
    "UA-2-3": ua2_import_runtime.dispatch_ua2_3,
    "UA-2-4": ua2_recycle_runtime.dispatch_ua2_4,
    "UA-2-5": ua2_group_runtime.dispatch_ua2_5,
}

_EXECUTE_UA2: dict[str, Callable] = {}
for case_id in ua2_all_ids():
    parts = case_id.split("-")
    chapter = f"{parts[0]}-{parts[1]}-{parts[2]}"
    handler = _CHAPTER_DISPATCH.get(chapter)
    if handler is not None:
        _EXECUTE_UA2[case_id] = handler


def supported_ua2_ids() -> list[str]:
    return sorted(_EXECUTE_UA2.keys())


def is_supported_ua2(case_id: str) -> bool:
    return case_id in _EXECUTE_UA2


def execute_ua2_case(ctx, cc, meta) -> CaseStatus:
    case_id = meta["id"]
    handler = _EXECUTE_UA2.get(case_id)
    if handler is None:
        raise AssertFail(
            f"UA-2 precise runtime has no adapter for {case_id}; "
            "this case must remain BLOCKED until queryWithQuality / asyncua / batch / "
            "import-export / group adapter is added."
        )
    sig = inspect.signature(handler)
    kwargs: dict[str, Any] = {}
    accepted = ("ctx", "cc", "meta")
    for name in sig.parameters:
        if name in accepted:
            kwargs[name] = {"ctx": ctx, "cc": cc, "meta": meta}[name]
    try:
        return handler(**kwargs)
    except BaselineError:
        return CaseStatus.BLOCKED
