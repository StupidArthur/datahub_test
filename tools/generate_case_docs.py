"""Generate Markdown test case documents from pytest case markers.

Usage:
    python -m tools.generate_case_docs
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REQUIRED_FIELDS = ("id", "chapter", "title", "steps", "expected")

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "test_cases"

HEADER = """\
<!--
此文件由 pytest 测试代码自动生成。
禁止直接修改。
-->
"""


def collect_cases() -> list[dict]:
    import pytest

    class _Collector:
        def __init__(self):
            self.cases: list[dict] = []

        def pytest_collection_modifyitems(self, items):
            for item in items:
                marker = item.get_closest_marker("case")
                if marker is None:
                    continue
                kw = dict(marker.kwargs)
                kw["nodeid"] = item.nodeid
                self.cases.append(kw)

    collector = _Collector()
    pytest.main(
        ["--collect-only", "-q", "tests"],
        plugins=[collector],
    )
    return collector.cases


def validate_cases(cases: list[dict]) -> None:
    seen_ids: dict[str, str] = {}
    for c in cases:
        cid = c.get("id", "")
        if not cid:
            raise ValueError(f"case missing id: nodeid={c.get('nodeid')}")
        if cid in seen_ids:
            raise ValueError(
                f"duplicate case id {cid!r}: "
                f"{seen_ids[cid]} and {c.get('nodeid')}"
            )
        seen_ids[cid] = c.get("nodeid", "")
        for field in REQUIRED_FIELDS:
            val = c.get(field)
            if not val:
                raise ValueError(
                    f"case {cid!r} missing required field {field!r}"
                )


def render_case(c: dict) -> str:
    lines: list[str] = []
    lines.append(f"## {c['id']} {c['title']}")
    lines.append("")
    if c.get("preconditions"):
        lines.append("### 前置条件")
        lines.append("")
        for p in c["preconditions"]:
            lines.append(f"- {p}")
        lines.append("")
    lines.append("### 测试步骤")
    lines.append("")
    for i, s in enumerate(c["steps"], 1):
        lines.append(f"{i}. {s}")
    lines.append("")
    lines.append("### 预期结果")
    lines.append("")
    for e in c["expected"]:
        lines.append(f"- {e}")
    lines.append("")
    lines.append(f"**pytest nodeid**: `{c['nodeid']}`")
    lines.append("")
    return "\n".join(lines)


def generate(cases: list[dict], output_dir: Path | None = None) -> dict[str, str]:
    validate_cases(cases)
    out = output_dir or DOCS_DIR
    out.mkdir(parents=True, exist_ok=True)

    chapters: dict[str, list[dict]] = {}
    for c in cases:
        chapters.setdefault(c["chapter"], []).append(c)

    written: dict[str, str] = {}
    for chapter in sorted(chapters):
        chapter_cases = sorted(chapters[chapter], key=lambda x: x["id"])
        parts = [HEADER, f"# {chapter}", ""]
        for c in chapter_cases:
            parts.append(render_case(c))
        content = "\n".join(parts)
        filename = f"{chapter}.md"
        (out / filename).write_text(content, encoding="utf-8")
        written[filename] = content
    return written


def main() -> None:
    cases = collect_cases()
    if not cases:
        print("no cases found", file=sys.stderr)
        sys.exit(1)
    written = generate(cases)
    for name in sorted(written):
        print(f"  {DOCS_DIR / name}")
    print(f"generated {len(written)} file(s), {len(cases)} case(s)")


if __name__ == "__main__":
    main()
