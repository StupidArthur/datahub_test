from __future__ import annotations

import time

from tpt_api.datahub import get_rt_value, query_tags_with_quality
from tests.support.ua2_helpers import opcua_read_sync
from tests.support.ua2_rt_assertions import parse_required_timestamp
from tests.support.ua2_value_normalization import normalize_int


INTEGER_RANGES: dict[int, tuple] = {
    2: ("SByte", -128, 127),
    3: ("Byte", 0, 255),
    4: ("Int16", -32768, 32767),
    5: ("UInt16", 0, 65535),
}

WRAP_MAP: dict[tuple, tuple] = {
    (2, -129): 127,
    (2, 128): -128,
    (3, -1): 255,
    (3, 256): 0,
    (4, -32769): 32767,
    (4, 32768): -32768,
    (5, -1): 65535,
    (5, 65536): 0,
}


def is_wrap_behaviour(data_type: int, value: int) -> bool:
    return (data_type, value) in WRAP_MAP


def classify_write_result(response: dict | None, tag_name: str, *, exception: BaseException | None = None) -> str:
    if exception is not None:
        return "rejected"
    if response is None:
        return "rejected"
    if not isinstance(response, dict):
        return "rejected"
    tag_names = response.get("tagNames") or []
    if tag_name not in tag_names:
        return "rejected"
    fail_msg = response.get("failMsg") or ""
    if isinstance(fail_msg, dict):
        fail_msg = str(fail_msg)
    if tag_name in fail_msg:
        return "rejected"
    return "accepted"


def wait_integer_write_closed_loop(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    ds_id: int,
    tag_name: str,
    data_type: int,
    expected_value: int,
    timeout: float = 30.0,
    interval: float = 0.5,
) -> dict:
    deadline = time.monotonic() + timeout
    last_source = None
    last_rt: dict = {}
    last_qwq: dict = {}
    while time.monotonic() < deadline:
        try:
            last_source = opcua_read_sync(endpoint, node_name, namespace_index=namespace_index)
        except Exception:
            time.sleep(interval)
            continue
        if isinstance(last_source, bool) or last_source is None:
            time.sleep(interval)
            continue

        rt_list = get_rt_value(api, tag_names=[tag_name])
        last_rt = rt_list[0] if isinstance(rt_list, list) and rt_list else {}
        qwq_all = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
        qrecs = (qwq_all.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == tag_name]
        last_qwq = qmatch[0] if qmatch else {}

        if "tagValue" not in last_rt or last_rt["tagValue"] is None:
            time.sleep(interval)
            continue
        if "tagValue" not in last_qwq or last_qwq["tagValue"] is None:
            time.sleep(interval)
            continue
        if last_rt.get("quality") in (None, 0) or last_qwq.get("quality") in (None, 0):
            time.sleep(interval)
            continue
        if not last_rt.get("tagTime") or not last_qwq.get("tagTime"):
            time.sleep(interval)
            continue
        try:
            parse_required_timestamp(last_rt["tagTime"])
            parse_required_timestamp(last_qwq["tagTime"])
        except AssertionError:
            time.sleep(interval)
            continue

        try:
            sv = normalize_int(last_source)
            rv = normalize_int(last_rt["tagValue"])
            qv = normalize_int(last_qwq["tagValue"])
        except (TypeError, ValueError):
            time.sleep(interval)
            continue

        if sv != expected_value or rv != expected_value or qv != expected_value:
            time.sleep(interval)
            continue

        return {
            "source": last_source,
            "rt": last_rt,
            "qwq": last_qwq,
        }

    raise AssertionError(
        f"integer write closed-loop timeout for {tag_name} (dt={data_type}, expected={expected_value})\n"
        f"last source: {last_source!r}\n"
        f"last getRTValue: {last_rt}\n"
        f"last queryWithQuality: {last_qwq}"
    )


def strict_teardown(api, *, tag_id: int | None, tag_name: str, ds_id: int | None, ds_name: str, mocker) -> None:
    from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists

    errors: list[str] = []

    if mocker:
        from tests.support.mocker_process import stop_mocker
        try:
            stop_mocker(mocker)
        except Exception as exc:
            errors.append(f"stop_mocker: {exc}")

    if tag_id:
        try:
            delete_tag_if_exists(api, tag_id, tag_name)
        except Exception as exc:
            errors.append(f"delete_tag: {exc}")

    if ds_id:
        from tpt_api.datahub import change_ds_state
        try:
            change_ds_state(api, ds_id, False)
        except Exception as exc:
            errors.append(f"disable_ds: {exc}")
        try:
            delete_datasource_if_exists(api, ds_id, ds_name)
        except Exception as exc:
            errors.append(f"delete_ds: {exc}")

    if errors:
        raise AssertionError("strict_teardown errors: " + "; ".join(errors))
