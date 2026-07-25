from __future__ import annotations

import time
from typing import Callable


class WaitTimeout(AssertionError):
    pass


def wait_until(
    name: str,
    condition: Callable[[], bool],
    timeout: float,
    interval: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if condition():
                return
        except Exception:
            pass
        time.sleep(interval)
    raise WaitTimeout(f"{name}: timed out after {timeout:.1f}s")
