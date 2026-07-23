"""Local env.json loader for UA-2 automation (replaces environment variables).

TPT connection credentials live in <repo_root>/env.json (gitignored). The
UA-2 automation runner and its child scripts read from there instead of
DATAHUB_* environment variables. The legacy config.py env fallback is
kept for UA-1 / fixtures and is NOT modified here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parent.parent  # ua_test_harness/ -> repo root
_ENV_JSON = _REPO_ROOT / "env.json"


def load_env_json() -> dict[str, Any]:
    """Read <repo_root>/env.json. Returns {} if missing or invalid."""
    try:
        return json.loads(_ENV_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_env(key: str, default: str = "") -> str:
    """Typed accessor with a string default."""
    return str(load_env_json().get(key, default))