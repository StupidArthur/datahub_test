from __future__ import annotations

"""Static regression: verify mocker node names use correct convention.

Mocker nodes must NOT embed namespace index in their `name` field.
The namespace is passed separately via `namespace_index`.
"""

import ast
from pathlib import Path

FIXTURE_FILES = [
    Path("tests/integration/ua2/test_tag_queries.py"),
    Path("tests/integration/ua2/test_tag_query_runtime.py"),
]


def _extract_node_names_from_node_configs(filepath: Path) -> list[str]:
    """Parse mocker node config dicts and extract all `name` field values."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            name_val = None
            for key, val in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "name":
                    if isinstance(val, ast.Constant):
                        name_val = val.value
                    break
            if name_val is not None:
                names.append(name_val)

    return names


def _has_digit_underscore_prefix(name: str) -> bool:
    """Check if a name starts with <digits>_ e.g. 1_foo, 22_bar."""
    import re
    return bool(re.match(r"^\d+_", name))


class TestMockerNodeNamesNoNamespacePrefix:
    def test_all_node_names_have_no_ns_prefix(self):
        failures: list[str] = []
        for fp in FIXTURE_FILES:
            if not fp.exists():
                failures.append(f"file not found: {fp}")
                continue
            names = _extract_node_names_from_node_configs(fp)
            for name in names:
                if _has_digit_underscore_prefix(name):
                    failures.append(f"{fp}: node name {name!r} starts with digit_ prefix")
        assert not failures, "\n".join(failures)
