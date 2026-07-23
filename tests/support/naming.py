from __future__ import annotations

import uuid


def unique_name(prefix: str, case_id: str) -> str:
    return f"{prefix}{case_id}_{uuid.uuid4().hex[:8]}"
