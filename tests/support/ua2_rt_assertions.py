from __future__ import annotations

import time
from datetime import datetime, timezone

from tpt_api.datahub import get_rt_value, query_tags_with_quality

from tests.support.ua2_value_normalization import assert_value_equal


def has_valid_tag_value(record: dict) -> bool:
    return "tagValue" in record and record["tagValue"] is not None


def parse_required_timestamp(raw: object) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise AssertionError(f"timestamp missing: {raw!r}")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssertionError(f"invalid timestamp: {raw!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def wait_consistent_rt_and_qwq(
    api,
    *,
    ds_id: int,
    tag_name: str,
    data_type: int,
    expected_value: object | None = None,
    timeout: float = 30.0,
    interval: float = 0.5,
) -> dict:
    deadline = time.monotonic() + timeout
    last_rt: dict = {}
    last_qwq_rec: dict = {}
    while time.monotonic() < deadline:
        rt_list = get_rt_value(api, tag_names=[tag_name])
        last_rt = rt_list[0] if isinstance(rt_list, list) and rt_list else {}
        qwq = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
        qrecs = (qwq.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == tag_name]
        last_qwq_rec = qmatch[0] if qmatch else {}

        if not has_valid_tag_value(last_rt):
            time.sleep(interval)
            continue
        if not has_valid_tag_value(last_qwq_rec):
            time.sleep(interval)
            continue
        if last_rt.get("quality") in (None, 0) or last_qwq_rec.get("quality") in (None, 0):
            time.sleep(interval)
            continue
        if not last_rt.get("tagTime") or not last_qwq_rec.get("tagTime"):
            time.sleep(interval)
            continue
        try:
            parse_required_timestamp(last_rt["tagTime"])
            parse_required_timestamp(last_qwq_rec["tagTime"])
        except AssertionError:
            time.sleep(interval)
            continue
        if expected_value is not None:
            try:
                assert_value_equal(expected_value, last_rt["tagValue"], data_type)
                assert_value_equal(expected_value, last_qwq_rec["tagValue"], data_type)
            except AssertionError:
                time.sleep(interval)
                continue
        else:
            try:
                assert_value_equal(last_rt["tagValue"], last_qwq_rec["tagValue"], data_type)
            except AssertionError:
                time.sleep(interval)
                continue
        return {
            "rt": last_rt,
            "qwq": last_qwq_rec,
        }
    raise AssertionError(
        f"RT/QwQ consistency timeout for {tag_name} (dt={data_type})\n"
        f"last getRTValue: {last_rt}\n"
        f"last queryWithQuality record: {last_qwq_rec}"
    )
