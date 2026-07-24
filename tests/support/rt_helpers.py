"""Real-time value helpers for native pytest tests.

Three helpers with clearly separated responsibilities:

- ``get_rt_point(api, tag_name)``: the canonical read. Propagates
  ``TptAPIError`` (including "Tag Dose/Does Not Exist") so tests see the
  real product behavior.

- ``try_get_rt_point(api, tag_name)``: tolerates only the explicit
  "tag does not exist" error and returns ``{}``; raises everything else.
  Suitable for polling probes that need to wait for a tag to appear.

- ``assert_rt_unavailable(api, tag_name, ...)``: asserts that reading the
  tag throws ``TptAPIError``. Used by cases like UA-1-2-02 where the
  expected behavior after disable is "RT no longer available".

Historical note: ``tests/integration/ua1/test_lifecycle_control.py``
previously swallowed ``TptAPIError("Tag Dose Not Exist")`` and returned
``{"tagName": ..., "tagValue": None, "quality": 0}``. That masked real
product behavior. These helpers do not perform that conversion.
"""
from __future__ import annotations

from tpt_api.datahub import get_rt_value
from tpt_api.errors import TptAPIError


_TAG_MISSING_SUBSTRINGS = ("tag dose not exist", "tag does not exist")


def _is_tag_missing(exc: TptAPIError) -> bool:
    msg = (exc.msg or "").lower()
    return any(sub in msg for sub in _TAG_MISSING_SUBSTRINGS)


def get_rt_point(api, tag_name: str) -> dict:
    """Read a tag's real-time point.

    Returns the first element of the ``get_rt_value`` response list, or
    ``{}`` if the list is empty.

    Does NOT swallow any error. ``TptAPIError`` (including "Tag Dose/Does
    Not Exist") propagates so callers see the real product behavior.
    """
    points = get_rt_value(api, tag_names=[tag_name])
    if isinstance(points, list) and points:
        return points[0]
    return {}


def try_get_rt_point(api, tag_name: str) -> dict:
    """Read a tag's real-time point, tolerating only "tag does not exist".

    Returns ``{}`` if the tag does not exist. Other ``TptAPIError`` codes
    (network, auth, server-side) propagate.

    Use this for polling probes such as "wait until the tag appears".
    """
    try:
        return get_rt_point(api, tag_name)
    except TptAPIError as exc:
        if _is_tag_missing(exc):
            return {}
        raise


def assert_rt_unavailable(api, tag_name: str, timeout: float = 0.0) -> None:
    """Assert that reading the tag raises ``TptAPIError``.

    With ``timeout == 0`` (default), reads once and asserts. With a
    positive ``timeout``, polls until the read raises (or the timeout
    elapses). Useful when the platform needs a few seconds to react to
    a datasource disable.
    """
    if timeout <= 0:
        try:
            get_rt_point(api, tag_name)
        except TptAPIError:
            return
        raise AssertionError(
            f"expected TptAPIError reading RT for tag {tag_name!r}, but read succeeded"
        )

    from tests.support.polling import wait_until

    def _cond() -> bool:
        try:
            get_rt_point(api, tag_name)
            return False
        except TptAPIError:
            return True

    wait_until(f"rt_unavailable:{tag_name}", _cond, timeout=timeout)