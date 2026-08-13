"""Infra-noise retry helper for real-environment test runs.

The shared integration backend (``DATAHUB_BASE_URL``) periodically reloads its
dataset into Redis and intermittently returns 404/5xx from the reverse proxy.
During those windows every endpoint can hang past the client timeout or answer
with ``code=500`` / 404.  Those are transient infrastructure noise, not test
bugs, so a bounded retry keeps a run from failing on them.

Only transport failures, HTTP 5xx, transient 404 routing, and business
``code=500``/Redis-loading/system-error messages are retried.  Genuine business
rejections (auth ``C0001``, ``A0001`` in-use, validation codes, HTTP 4xx other
than 404) are propagated immediately.
"""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from tpt_api.errors import TptAPIError


def is_infra_noise(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 404
    if isinstance(exc, TptAPIError):
        msg = exc.msg or ""
        return exc.code == "500" or "RedisLoading" in msg or "System error" in msg
    return False


def retry_infra_noise(fn: Callable[[], Any], *, retries: int = 8, delay: float = 10.0,
                      name: str = "call") -> Any:
    """Call ``fn``, retrying on infra noise only; propagate everything else.

    Raises the last observed infra error after ``retries`` attempts.
    """
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - retried only for infra noise
            last = exc
            if not is_infra_noise(exc):
                raise
            if attempt < retries:
                time.sleep(delay)
    raise last  # type: ignore[misc] - last is always set when we get here
