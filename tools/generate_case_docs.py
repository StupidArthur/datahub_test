"""Generate Markdown test case documents from pytest case markers.

Usage:
    python -m tools.generate_case_docs
    python -m tools.generate_case_docs --check
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REQUIRED_FIELDS = ("id", "chapter", "title", "steps", "expected")

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "test_cases"

HEADER = """\
<!--
此文件由 pytest 测试代码自动生成。
禁止直接修改。
-->
"""


LIST_FIELDS = ("preconditions", "steps", "expected")


def _coerce_list_field(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    raise TypeError(f"expected str/list/tuple, got {type(value).__name__}")


def _normalize_list_fields(c: dict, strict: bool = False) -> None:
    for field in LIST_FIELDS:
        val = c.get(field)
        if val is None:
            continue
        if isinstance(val, str) and strict:
            print(
                f"warning: case {c.get('id', '?')} field {field!r} "
                f"is a str (nodeid={c.get('nodeid', '?')}); "
                f"wrapping as single entry",
                file=sys.stderr,
            )
        c[field] = _coerce_list_field(val)


def collect_cases(strict: bool = False) -> list[dict]:
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
                kw["markers"] = [
                    m.name for m in item.iter_markers()
                    if m.name in ("integration", "destructive", "spec_pending")
                ]
                _normalize_list_fields(kw, strict=strict)
                self.cases.append(kw)

    collector = _Collector()
    exit_code = pytest.main(
        ["--collect-only", "-q", "tests"],
        plugins=[collector],
    )
    if exit_code != 0:
        raise RuntimeError(f"pytest collection failed with exit code {exit_code}")
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
        _normalize_list_fields(c)
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


def build_manifest(cases: list[dict]) -> dict:
    manifest_cases = []
    for c in sorted(cases, key=lambda x: x["id"]):
        manifest_cases.append({
            "id": c["id"],
            "chapter": c["chapter"],
            "title": c["title"],
            "nodeid": c["nodeid"],
            "preconditions": c.get("preconditions") or [],
            "steps": c["steps"],
            "expected": c["expected"],
            "markers": c.get("markers") or [],
        })
    return {"schemaVersion": 1, "cases": manifest_cases}


def generate(cases: list[dict], output_dir: Path | None = None) -> dict[str, str]:
    validate_cases(cases)
    out = output_dir or DOCS_DIR
    out.mkdir(parents=True, exist_ok=True)

    _remove_stale(cases, out)

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

    manifest = build_manifest(cases)
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (out / "case-manifest.json").write_text(manifest_json, encoding="utf-8")
    written["case-manifest.json"] = manifest_json

    return written


def _remove_stale(cases: list[dict], out: Path) -> None:
    active_chapters = {c["chapter"] for c in cases}
    for f in out.iterdir():
        if not f.is_file():
            continue
        if f.name == "case-manifest.json":
            continue
        if not f.suffix == ".md":
            continue
        content = f.read_text(encoding="utf-8")
        if not content.startswith(HEADER.split("\n")[0]):
            continue
        chapter = f.stem
        if chapter not in active_chapters:
            f.unlink()


def check(cases: list[dict]) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        generated = generate(cases, output_dir=tmp_path)

    diffs: list[str] = []
    for name, content in sorted(generated.items()):
        target = DOCS_DIR / name
        if not target.exists():
            diffs.append(f"missing: {name}")
        elif target.read_text(encoding="utf-8") != content:
            diffs.append(f"changed: {name}")

    if DOCS_DIR.exists():
        for f in sorted(DOCS_DIR.iterdir()):
            if f.name not in generated and f.suffix in (".md", ".json"):
                content = f.read_text(encoding="utf-8")
                if content.startswith(HEADER.split("\n")[0]) or f.name == "case-manifest.json":
                    diffs.append(f"stale: {f.name}")

    if diffs:
        for d in diffs:
            print(f"  {d}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    check_mode = "--check" in sys.argv
    cases = collect_cases(strict=check_mode)
    if not cases:
        print("no cases found", file=sys.stderr)
        sys.exit(1)

    if check_mode:
        rc = check(cases)
        if rc != 0:
            print("docs out of date", file=sys.stderr)
        sys.exit(rc)

    written = generate(cases)
    for name in sorted(written):
        print(f"  {DOCS_DIR / name}")
    print(f"generated {len(written)} file(s), {len(cases)} case(s)")


if __name__ == "__main__":
    main()
