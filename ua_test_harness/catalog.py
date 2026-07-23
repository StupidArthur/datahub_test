"""catalog.py:用例装饰器 + catalog JSON 导出。"""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .models import CaseDef, StepDef

_REGISTRY: list[CaseDef] = []


def case(
    id: str,
    title: str,
    chapter: str,
    kind: str = "regression",
    tags: list[str] | None = None,
    timeout_sec: int = 600,
    exclusive_resources: list[str] | None = None,
    destructive: bool = False,
    doc_path: str = "",
    description: str = "",
    steps: list[StepDef] | None = None,
    assertions: list[str] | None = None,
) -> Callable[[Callable], Callable]:
    """用例装饰器。"""

    def deco(fn: Callable) -> Callable:
        try:
            file_path = os.path.relpath(fn.__code__.co_filename)
        except Exception:
            file_path = ""
        cd = CaseDef(
            id=id,
            title=title,
            chapter=chapter,
            kind=kind,
            tags=list(tags or []),
            timeout_sec=int(timeout_sec),
            exclusive_resources=list(exclusive_resources or []),
            destructive=bool(destructive),
            doc_path=doc_path,
            description=description,
            steps=list(steps or []),
            assertions=list(assertions or []),
            impl_func=fn,
            file_path=file_path,
            lineno=int(fn.__code__.co_firstlineno),
        )
        _REGISTRY.append(cd)
        fn.__ua_case_def__ = cd  # type: ignore[attr-defined]
        return fn

    return deco


def step(step_id: str, title: str = "") -> Callable[[Callable], Callable]:
    def deco(fn: Callable) -> Callable:
        return fn
    return deco


def all_defs() -> list[CaseDef]:
    return sorted(_REGISTRY, key=lambda c: (c.chapter, c.id))


def reset() -> None:
    _REGISTRY.clear()


def discover(package: str = "ua_test_harness.tests") -> int:
    """导入手写 Case 后，最后导入 Markdown 全量补齐注册器。"""
    before = len(_REGISTRY)
    try:
        mod = importlib.import_module(package)
    except ModuleNotFoundError:
        return 0
    if not hasattr(mod, "__path__"):
        return 0

    normal: list[str] = []
    deferred: list[str] = []
    for _finder, name, _ispkg in pkgutil.walk_packages(mod.__path__, prefix=f"{package}."):
        if name.endswith(".zz_documented_cases"):
            deferred.append(name)
        else:
            normal.append(name)

    failures: list[tuple[str, Exception]] = []
    for name in sorted(normal) + sorted(deferred):
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures.append((name, exc))

    if failures:
        details = "; ".join(f"{name}: {type(exc).__name__}: {exc}" for name, exc in failures)
        raise RuntimeError(f"case discovery failed: {details}")
    return len(_REGISTRY) - before


def export_catalog(
    out_path: str | Path,
    *,
    package: str = "ua_test_harness.tests",
    version: int = 1,
) -> dict:
    discover(package)
    chapters_map: dict[str, dict] = {}
    for c in all_defs():
        ch = chapters_map.setdefault(c.chapter, {"id": c.chapter, "title": c.chapter, "cases": []})
        ch["cases"].append(
            {
                "id": c.id,
                "title": c.title,
                "kind": c.kind,
                "implemented": True,
                "tags": c.tags,
                "timeoutSec": c.timeout_sec,
                "destructive": c.destructive,
                "exclusiveResources": c.exclusive_resources,
                "docPath": c.doc_path,
                "description": c.description,
                "steps": [{"stepId": s.step_id, "title": s.title} for s in c.steps],
                "assertions": c.assertions,
                "filePath": c.file_path,
                "lineno": c.lineno,
            }
        )
    chapters = [chapters_map[k] for k in sorted(chapters_map.keys())]
    catalog = {
        "version": version,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "chapters": chapters,
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalog
