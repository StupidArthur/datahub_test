from __future__ import annotations

from pathlib import Path


def test_tpt_api_resolves_to_this_repo():
    import tpt_api.client

    resolved = Path(tpt_api.client.__file__).resolve()
    repo_root = Path(__file__).resolve().parents[2]
    expected_dir = repo_root / "tpt_api" / "python" / "tpt_api"
    assert str(resolved).startswith(str(expected_dir)), (
        f"tpt_api.client resolved to {resolved}, "
        f"expected under {expected_dir}"
    )
