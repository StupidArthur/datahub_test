from __future__ import annotations

import json
import socket
import time

from asyncua import ua

from tpt_api.datahub import (
    delete_ds_info,
    delete_tags_physical,
    get_rt_value,
    list_recycle_tags,
    list_tags,
    query_tags_with_quality,
)
from tests.support.ua2_helpers import is_ds_alive
from tpt_api.errors import TptAPIError
from tests.support.ua2_helpers import opcua_read_sync, opcua_read_variant_type_sync
from tests.support.ua2_rt_assertions import parse_required_timestamp
from tests.support.ua2_value_normalization import normalize_int, normalize_int64_as_str


INTEGER_RANGES: dict[int, tuple] = {
    2: ("SByte", -128, 127),
    3: ("Byte", 0, 255),
    4: ("Int16", -32768, 32767),
    5: ("UInt16", 0, 65535),
    6: ("Int32", -2147483648, 2147483647),
    7: ("UInt32", 0, 4294967295),
    8: ("Int64", -9223372036854775808, 9223372036854775807),
}

WRAP_MAP: dict[tuple, int] = {
    (2, -129): 127,
    (2, 128): -128,
    (3, -1): 255,
    (3, 256): 0,
    (4, -32769): 32767,
    (4, 32768): -32768,
    (5, -1): 65535,
    (5, 65536): 0,
    (6, -2147483649): 2147483647,
    (6, 2147483648): -2147483648,
    (7, -1): 4294967295,
    (7, 4294967296): 0,
    (8, -9223372036854775809): 9223372036854775807,
    (8, 9223372036854775808): -9223372036854775808,
}


def normalize_integer_decimal(raw: object, data_type: int) -> str:
    if isinstance(raw, bool):
        raise TypeError(f"boolean {raw!r} must not be accepted as integer (dataType={data_type})")
    if isinstance(raw, float):
        raise TypeError(f"float must not be used for integer normalization (dataType={data_type})")
    if data_type in (2, 3, 4, 5, 6, 7):
        return str(normalize_int(raw))
    if data_type == 8:
        return normalize_int64_as_str(raw, unsigned=False)
    raise ValueError(f"unsupported dataType {data_type} for normalize_integer_decimal")


def is_wrap_behaviour(data_type: int, value: int) -> bool:
    return (data_type, value) in WRAP_MAP


def expected_wrap_value(data_type: int, value: int) -> int:
    return WRAP_MAP[(data_type, value)]


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


def classify_outcome_value(data_type: int, final_value: int, baseline_value: int) -> str:
    name, lo, hi = INTEGER_RANGES[data_type]
    if final_value == baseline_value:
        return "kept_original"
    if final_value == lo or final_value == hi:
        return "clamped"
    if lo <= final_value <= hi:
        return "converted"
    return "out_of_range"


def _sample_trio(
    api, endpoint: str, node_name: str, namespace_index: int, ds_id: int, tag_name: str,
) -> dict:
    source = opcua_read_sync(endpoint, node_name, namespace_index=namespace_index)
    sf_val, sf_vt = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=namespace_index)
    rt_list = get_rt_value(api, tag_names=[tag_name])
    rt = rt_list[0] if isinstance(rt_list, list) and rt_list else {}
    qwq_all = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
    qrecs = (qwq_all.get("tagInfoList") or {}).get("records") or []
    qmatch = [r for r in qrecs if r.get("tagName") == tag_name]
    qwq = qmatch[0] if qmatch else {}
    da = is_ds_alive(api, ds_id)
    return {"source": source, "variant_type": sf_vt, "rt": rt, "qwq": qwq, "datasource_alive": da}


def _assert_mocker_alive(mocker, tag_name: str, context: str = "") -> None:
    if mocker is not None and mocker.process.poll() is not None:
        raise AssertionError(
            f"mocker exited during {context} for {tag_name}: "
            f"returncode={mocker.process.poll()}"
        )


def _assert_source_ok(src, vt, tag_name: str, expected_variant_type) -> int:
    if isinstance(src, bool):
        raise AssertionError(f"source is bool for {tag_name}: {src!r}")
    if vt != expected_variant_type:
        raise AssertionError(
            f"VariantType mismatch for {tag_name}: "
            f"{vt} != {expected_variant_type} (expected {expected_variant_type.name})"
        )
    try:
        return normalize_int(src)
    except (TypeError, ValueError) as exc:
        raise AssertionError(
            f"source value cannot be normalized for {tag_name}: {src!r} ({exc})"
        )


def wait_three_way_sync(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    ds_id: int,
    tag_name: str,
    data_type: int,
    expected_value: int,
    expected_variant_type,
    mocker=None,
    timeout: float = 30.0,
    interval: float = 0.5,
) -> dict:
    deadline = time.monotonic() + timeout
    last_trio: dict = {}
    while time.monotonic() < deadline:
        _assert_mocker_alive(mocker, tag_name, "wait_three_way_sync")
        trio = _sample_trio(api, endpoint, node_name, namespace_index, ds_id, tag_name)
        last_trio = trio
        src = trio["source"]
        vt = trio["variant_type"]
        _assert_source_ok(src, vt, tag_name, expected_variant_type)
        sv = normalize_int(src)
        if sv != expected_value:
            time.sleep(interval)
            continue
        rt = trio["rt"]
        qwq = trio["qwq"]
        if "tagValue" not in rt or rt["tagValue"] is None:
            time.sleep(interval)
            continue
        if "tagValue" not in qwq or qwq["tagValue"] is None:
            time.sleep(interval)
            continue
        if rt.get("quality") in (None, 0) or qwq.get("quality") in (None, 0):
            time.sleep(interval)
            continue
        if not rt.get("tagTime") or not qwq.get("tagTime"):
            time.sleep(interval)
            continue
        try:
            parse_required_timestamp(rt["tagTime"])
            parse_required_timestamp(qwq["tagTime"])
        except AssertionError:
            time.sleep(interval)
            continue
        try:
            rv = normalize_int(rt["tagValue"])
            qv = normalize_int(qwq["tagValue"])
        except (TypeError, ValueError):
            time.sleep(interval)
            continue
        if rv != expected_value or qv != expected_value:
            time.sleep(interval)
            continue
        if not trio.get("datasource_alive"):
            time.sleep(interval)
            continue
        return trio

    raise AssertionError(
        f"three-way sync timeout for {tag_name} (expected={expected_value})\n"
        f"last sample: {json.dumps(_serialize_trio(last_trio), ensure_ascii=False, default=str)}"
    )


def wait_three_way_integer_decimal_sync(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    ds_id: int,
    tag_name: str,
    data_type: int,
    expected_decimal: str,
    expected_variant_type,
    mocker=None,
    timeout: float = 30.0,
    interval: float = 0.5,
) -> dict:
    deadline = time.monotonic() + timeout
    last_trio: dict = {}
    while time.monotonic() < deadline:
        _assert_mocker_alive(mocker, tag_name, "wait_three_way_integer_decimal_sync")
        trio = _sample_trio(api, endpoint, node_name, namespace_index, ds_id, tag_name)
        last_trio = trio
        src = trio["source"]
        vt = trio["variant_type"]
        sv_str = normalize_integer_decimal(src, data_type)
        if sv_str != expected_decimal:
            time.sleep(interval)
            continue
        if vt != expected_variant_type:
            raise AssertionError(
                f"VariantType mismatch for {tag_name}: "
                f"{vt} != {expected_variant_type} (expected {expected_variant_type.name})"
            )
        if isinstance(src, bool):
            raise AssertionError(f"source is bool for {tag_name}: {src!r}")
        if not isinstance(src, int):
            raise AssertionError(f"source Python type is not int for {tag_name}: {type(src).__name__} {src!r}")
        rt = trio["rt"]
        qwq = trio["qwq"]
        if "tagValue" not in rt or rt["tagValue"] is None:
            time.sleep(interval)
            continue
        if "tagValue" not in qwq or qwq["tagValue"] is None:
            time.sleep(interval)
            continue
        if rt.get("quality") in (None, 0) or qwq.get("quality") in (None, 0):
            time.sleep(interval)
            continue
        if not rt.get("tagTime") or not qwq.get("tagTime"):
            time.sleep(interval)
            continue
        try:
            parse_required_timestamp(rt["tagTime"])
            parse_required_timestamp(qwq["tagTime"])
        except AssertionError:
            time.sleep(interval)
            continue
        rv_str = normalize_integer_decimal(rt["tagValue"], data_type)
        qv_str = normalize_integer_decimal(qwq["tagValue"], data_type)
        if rv_str != expected_decimal or qv_str != expected_decimal:
            time.sleep(interval)
            continue
        if not trio.get("datasource_alive"):
            time.sleep(interval)
            continue
        return trio

    raise AssertionError(
        f"three-way integer decimal sync timeout for {tag_name} "
        f"(data_type={data_type}, expected={expected_decimal})\n"
        f"last sample: {json.dumps(_serialize_trio(last_trio), ensure_ascii=False, default=str)}"
    )


def _assert_not_float(raw: object, label: str, tag_name: str) -> None:
    if isinstance(raw, float):
        raise AssertionError(f"{label} is float for {tag_name}: {raw!r}")


def _assert_no_float_in_trio(trio: dict, tag_name: str) -> None:
    _assert_not_float(trio["source"], "source", tag_name)
    rt_v = trio["rt"].get("tagValue")
    qwq_v = trio["qwq"].get("tagValue")
    if rt_v is not None:
        _assert_not_float(rt_v, "RT tagValue", tag_name)
    if qwq_v is not None:
        _assert_not_float(qwq_v, "QwQ tagValue", tag_name)


def wait_accepted_integer_decimal_outcome(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    ds_id: int,
    tag_name: str,
    data_type: int,
    expected_variant_type,
    mocker,
    timeout: float = 30.0,
    interval: float = 0.5,
    stable_samples: int = 2,
) -> dict:
    name, lo, hi = INTEGER_RANGES[data_type]
    baseline_vt_name = expected_variant_type.name
    deadline = time.monotonic() + timeout
    all_samples: list[dict] = []

    while time.monotonic() < deadline:
        _assert_mocker_alive(mocker, tag_name, "wait_accepted_integer_decimal_outcome")

        trio = _sample_trio(api, endpoint, node_name, namespace_index, ds_id, tag_name)
        src = trio["source"]
        vt = trio["variant_type"]
        rt = trio["rt"]
        qwq = trio["qwq"]

        if isinstance(src, bool):
            raise AssertionError(f"source is bool for {tag_name}: {src!r}")
        if not isinstance(src, int):
            raise AssertionError(f"source Python type is not int for {tag_name}: {type(src).__name__} {src!r}")
        _assert_no_float_in_trio(trio, tag_name)
        if vt != expected_variant_type:
            raise AssertionError(
                f"VariantType mismatch for {tag_name}: "
                f"{vt} != {expected_variant_type} (expected {baseline_vt_name})"
            )

        try:
            sv_str = normalize_integer_decimal(src, data_type)
        except (TypeError, ValueError) as exc:
            raise AssertionError(f"source decimal normalization failed for {tag_name}: {exc}")

        sv = int(sv_str)
        if not (lo <= sv <= hi):
            time.sleep(interval)
            continue

        if "tagValue" not in rt or rt["tagValue"] is None:
            time.sleep(interval)
            continue
        if "tagValue" not in qwq or qwq["tagValue"] is None:
            time.sleep(interval)
            continue
        if rt.get("quality") in (None, 0) or qwq.get("quality") in (None, 0):
            time.sleep(interval)
            continue
        if not rt.get("tagTime") or not qwq.get("tagTime"):
            time.sleep(interval)
            continue
        try:
            parse_required_timestamp(rt["tagTime"])
            parse_required_timestamp(qwq["tagTime"])
        except AssertionError:
            time.sleep(interval)
            continue

        try:
            rv_str = normalize_integer_decimal(rt["tagValue"], data_type)
            qv_str = normalize_integer_decimal(qwq["tagValue"], data_type)
        except (TypeError, ValueError):
            time.sleep(interval)
            continue
        if rv_str != sv_str or qv_str != sv_str:
            time.sleep(interval)
            continue
        if not trio.get("datasource_alive"):
            time.sleep(interval)
            continue

        sample = {
            "source": src,
            "source_decimal": sv_str,
            "variant_type": vt,
            "rt": rt,
            "rt_decimal": rv_str,
            "qwq": qwq,
            "qwq_decimal": qv_str,
            "datasource_alive": True,
            "mocker_alive": mocker is not None and mocker.process.poll() is None,
        }
        all_samples.append(sample)

        if len(all_samples) >= stable_samples:
            recent = all_samples[-stable_samples:]
            if len(set(s["source_decimal"] for s in recent)) == 1:
                last = recent[-1]
                return {
                    "source": last["source"],
                    "source_decimal": last["source_decimal"],
                    "variant_type": last["variant_type"],
                    "rt": last["rt"],
                    "rt_decimal": last["rt_decimal"],
                    "qwq": last["qwq"],
                    "qwq_decimal": last["qwq_decimal"],
                    "datasource_alive": last["datasource_alive"],
                    "mocker_alive": last["mocker_alive"],
                    "samples": all_samples,
                }

        time.sleep(interval)

    last = all_samples[-1] if all_samples else {}
    raise AssertionError(
        f"wait_accepted_integer_decimal_outcome timeout for {tag_name} "
        f"(data_type={data_type}, stable_samples={stable_samples})\n"
        f"last sample: {json.dumps(_serialize_trio(last) if last else {}, ensure_ascii=False, default=str)}"
    )


def observe_integer_decimal_rejection(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    ds_id: int,
    tag_name: str,
    data_type: int,
    baseline_decimal: str,
    expected_variant_type,
    mocker,
    timeout: float = 30.0,
    interval: float = 0.5,
    min_observation_period: float = 4.0,
) -> dict:
    samples: list[dict] = []
    baseline_vt_name = expected_variant_type.name
    deadline = time.monotonic() + timeout
    sampling_deadline = time.monotonic() + min_observation_period

    while time.monotonic() < deadline:
        _assert_mocker_alive(mocker, tag_name, "observe_integer_decimal_rejection")
        try:
            source = opcua_read_sync(endpoint, node_name, namespace_index=namespace_index)
        except Exception as exc:
            raise AssertionError(f"OPC UA source read failed during observation: {exc}")
        try:
            sf_val, sf_vt = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=namespace_index)
            vt_name = sf_vt.name
        except Exception as exc:
            raise AssertionError(f"OPC UA variant type read failed during observation: {exc}")

        if isinstance(source, bool):
            raise AssertionError(f"source is bool during rejection observation for {tag_name}: {source!r}")
        if not isinstance(source, int):
            raise AssertionError(
                f"source Python type is not int during rejection observation for {tag_name}: "
                f"{type(source).__name__} {source!r}"
            )
        if isinstance(source, float):
            raise AssertionError(f"source is float during rejection observation for {tag_name}: {source!r}")

        try:
            src_str = normalize_integer_decimal(source, data_type)
        except (TypeError, ValueError) as exc:
            raise AssertionError(f"source decimal normalization failed during rejection observation: {exc}")

        if src_str != baseline_decimal:
            raise AssertionError(
                f"source changed during rejection observation for {tag_name}: "
                f"{src_str} != {baseline_decimal}"
            )
        if vt_name != baseline_vt_name:
            raise AssertionError(
                f"VariantType changed during rejection observation for {tag_name}: "
                f"{vt_name} != {baseline_vt_name}"
            )

        try:
            rt_list = get_rt_value(api, tag_names=[tag_name])
        except TptAPIError:
            rt = {}
        except Exception as exc:
            raise AssertionError(f"getRTValue failed during observation: {exc}")
        else:
            rt = rt_list[0] if isinstance(rt_list, list) and rt_list else {}

        try:
            qwq_all = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
        except TptAPIError:
            qwq_all = {}
        except Exception as exc:
            raise AssertionError(f"queryWithQuality failed during observation: {exc}")
        qrecs = (qwq_all.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == tag_name]
        qwq = qmatch[0] if qmatch else {}

        rt_v = rt.get("tagValue")
        qwq_v = qwq.get("tagValue")
        if rt_v is not None and isinstance(rt_v, float):
            raise AssertionError(f"RT tagValue is float during rejection observation for {tag_name}: {rt_v!r}")
        if qwq_v is not None and isinstance(qwq_v, float):
            raise AssertionError(f"QwQ tagValue is float during rejection observation for {tag_name}: {qwq_v!r}")

        da = is_ds_alive(api, ds_id)
        mocker_alive = mocker is not None and mocker.process.poll() is None

        sample = {
            "source": source,
            "source_decimal": src_str,
            "variant_type": vt_name,
            "rt": rt,
            "qwq": qwq,
            "datasource_alive": da,
            "mocker_alive": mocker_alive,
        }
        samples.append(sample)

        if time.monotonic() >= sampling_deadline and len(samples) >= 2:
            break
        time.sleep(interval)

    if not samples:
        raise AssertionError("observe_integer_decimal_rejection collected zero samples")

    issues: list[str] = []
    all_stable = True
    for i, s in enumerate(samples):
        if s["source_decimal"] != baseline_decimal:
            all_stable = False
            issues.append(f"sample[{i}] source {s['source_decimal']} != baseline {baseline_decimal}")
        if s["variant_type"] != baseline_vt_name:
            all_stable = False
            issues.append(f"sample[{i}] VT {s['variant_type']} != {baseline_vt_name}")
        if not s["datasource_alive"]:
            all_stable = False
            issues.append(f"sample[{i}] datasource not alive")
        if not s["mocker_alive"]:
            all_stable = False
            issues.append(f"sample[{i}] mocker not alive")
        rt_q = s["rt"].get("quality")
        qwq_q = s["qwq"].get("quality")
        if rt_q in (None, 0) or qwq_q in (None, 0):
            all_stable = False
            issues.append(f"sample[{i}] quality RT={rt_q} QwQ={qwq_q}")
        if not s["rt"].get("tagTime") or not s["qwq"].get("tagTime"):
            all_stable = False
            issues.append(f"sample[{i}] tagTime missing")

    return {
        "samples": samples,
        "stable": all_stable,
        "issues": issues,
    }


def strict_restore_source_and_cleanup(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    original_value: int,
    original_variant_type,
    tag_id: int | None,
    tag_name: str | None,
    ds_id: int | None,
    ds_name: str | None,
    mocker,
    host: str | None,
    port: int | None,
) -> None:
    errors: list[str] = []

    if mocker is not None and mocker.process.poll() is None:
        try:
            from asyncua import ua as ua_module
            dv = ua_module.DataValue(ua_module.Variant(original_value, original_variant_type))
            import asyncio
            from asyncua import Client
            async def _restore():
                async with Client(endpoint) as client:
                    nid = f"ns={namespace_index};s={node_name}"
                    node = client.get_node(nid)
                    await node.write_value(dv)
            asyncio.run(_restore())
        except Exception as exc:
            errors.append(f"restore_source: {exc}")
        else:
            try:
                check_val, check_vt = opcua_read_variant_type_sync(
                    endpoint, node_name, namespace_index=namespace_index
                )
                if check_vt != original_variant_type:
                    errors.append(
                        f"restore_vt_mismatch: got {check_vt.name} != {original_variant_type.name}"
                    )
                if check_val != original_value:
                    errors.append(
                        f"restore_value_mismatch: got {check_val} != {original_value}"
                    )
            except Exception as exc:
                errors.append(f"restore_verify: {exc}")

    cleanup_errors: list[str] = []
    try:
        from tests.support.ua2_cleanup import strict_cleanup_ua2_context
        strict_cleanup_ua2_context(
            api,
            tag_id=tag_id, tag_name=tag_name,
            ds_id=ds_id, ds_name=ds_name,
            mocker=mocker,
            host=host, port=port,
        )
    except AssertionError as exc:
        cleanup_errors.append(str(exc))
    except Exception as exc:
        cleanup_errors.append(f"cleanup_unexpected: {exc}")

    if cleanup_errors:
        errors.extend(cleanup_errors)

    if errors:
        raise AssertionError("strict_restore_source_and_cleanup errors: " + "; ".join(errors))


def wait_accepted_integer_outcome(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    ds_id: int,
    tag_name: str,
    data_type: int,
    expected_variant_type,
    mocker,
    timeout: float = 30.0,
    interval: float = 0.5,
    stable_samples: int = 2,
) -> dict:
    name, lo, hi = INTEGER_RANGES[data_type]
    deadline = time.monotonic() + timeout
    all_samples: list[dict] = []

    while time.monotonic() < deadline:
        _assert_mocker_alive(mocker, tag_name, "wait_accepted_integer_outcome")

        trio = _sample_trio(api, endpoint, node_name, namespace_index, ds_id, tag_name)
        src = trio["source"]
        vt = trio["variant_type"]
        rt = trio["rt"]
        qwq = trio["qwq"]

        sv = _assert_source_ok(src, vt, tag_name, expected_variant_type)

        if not (lo <= sv <= hi):
            time.sleep(interval)
            continue

        if "tagValue" not in rt or rt["tagValue"] is None:
            time.sleep(interval)
            continue
        if "tagValue" not in qwq or qwq["tagValue"] is None:
            time.sleep(interval)
            continue
        if rt.get("quality") in (None, 0) or qwq.get("quality") in (None, 0):
            time.sleep(interval)
            continue
        if not rt.get("tagTime") or not qwq.get("tagTime"):
            time.sleep(interval)
            continue
        try:
            parse_required_timestamp(rt["tagTime"])
            parse_required_timestamp(qwq["tagTime"])
        except AssertionError:
            time.sleep(interval)
            continue
        try:
            rv = normalize_int(rt["tagValue"])
            qv = normalize_int(qwq["tagValue"])
        except (TypeError, ValueError):
            time.sleep(interval)
            continue
        if rv != sv or qv != sv:
            time.sleep(interval)
            continue
        if not trio.get("datasource_alive"):
            time.sleep(interval)
            continue

        sample = {
            "source": sv,
            "variant_type": vt,
            "rt": rt,
            "qwq": qwq,
            "datasource_alive": True,
            "mocker_alive": mocker is not None and mocker.process.poll() is None,
        }
        all_samples.append(sample)

        if len(all_samples) >= stable_samples:
            recent = all_samples[-stable_samples:]
            if len(set(s["source"] for s in recent)) == 1:
                return {
                    "source": recent[-1]["source"],
                    "variant_type": recent[-1]["variant_type"],
                    "rt": recent[-1]["rt"],
                    "qwq": recent[-1]["qwq"],
                    "datasource_alive": recent[-1]["datasource_alive"],
                    "mocker_alive": recent[-1]["mocker_alive"],
                    "samples": all_samples,
                }

        time.sleep(interval)

    last = all_samples[-1] if all_samples else {}
    raise AssertionError(
        f"wait_accepted_integer_outcome timeout for {tag_name} "
        f"(data_type={data_type}, stable_samples={stable_samples})\n"
        f"last sample: {json.dumps(_serialize_trio(last) if last else {}, ensure_ascii=False, default=str)}"
    )


def _serialize_trio(trio: dict) -> dict:
    out = dict(trio)
    if "variant_type" in out and hasattr(out["variant_type"], "name"):
        out["variant_type"] = out["variant_type"].name
    return out


def observe_integer_write_outcome(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    ds_id: int,
    tag_name: str,
    data_type: int,
    input_value: int,
    baseline_value: int,
    expected_variant_type,
    mocker,
    timeout: float = 30.0,
    interval: float = 0.5,
    min_observation_period: float = 4.0,
) -> dict:
    samples: list[dict] = []
    baseline_vt_name = expected_variant_type.name
    deadline = time.monotonic() + timeout
    sampling_deadline = time.monotonic() + min_observation_period

    while time.monotonic() < deadline:
        try:
            source = opcua_read_sync(endpoint, node_name, namespace_index=namespace_index)
        except Exception as exc:
            raise AssertionError(
                f"OPC UA source read failed during observation: {exc}"
            )
        try:
            sf_val, sf_vt = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=namespace_index)
            vt_name = sf_vt.name
        except Exception as exc:
            raise AssertionError(
                f"OPC UA variant type read failed during observation: {exc}"
            )

        try:
            rt_list = get_rt_value(api, tag_names=[tag_name])
        except TptAPIError:
            rt = {}
        except Exception as exc:
            raise AssertionError(f"getRTValue failed during observation: {exc}")
        else:
            rt = rt_list[0] if isinstance(rt_list, list) and rt_list else {}

        try:
            qwq_all = query_tags_with_quality(api, ds_id=ds_id, tag_name=tag_name)
        except TptAPIError:
            qwq_all = {}
        except Exception as exc:
            raise AssertionError(f"queryWithQuality failed during observation: {exc}")
        qrecs = (qwq_all.get("tagInfoList") or {}).get("records") or []
        qmatch = [r for r in qrecs if r.get("tagName") == tag_name]
        qwq = qmatch[0] if qmatch else {}

        da = is_ds_alive(api, ds_id)
        mocker_alive = mocker is not None and mocker.process.poll() is None

        sample = {
            "source": source,
            "variant_type": vt_name,
            "rt": rt,
            "qwq": qwq,
            "datasource_alive": da,
            "mocker_alive": mocker_alive,
        }
        samples.append(sample)

        if time.monotonic() >= sampling_deadline and len(samples) >= 2:
            break
        time.sleep(interval)

    if not samples:
        raise AssertionError("observe_integer_write_outcome collected zero samples")

    stable = _check_stable(samples, baseline_value, data_type, baseline_vt_name)

    return {
        "samples": samples,
        "stable": stable,
    }


def _check_stable(
    samples: list[dict], baseline_value: int, data_type: int, baseline_vt_name: str,
) -> dict:
    issues: list[str] = []
    all_same_value: bool = True
    source_values: list = []
    rt_values: list = []
    qwq_values: list = []
    all_vt_same: bool = True
    all_ds_alive: bool = True
    all_mocker_alive: bool = True

    for i, s in enumerate(samples):
        src = s["source"]
        if isinstance(src, bool) or src is None:
            all_same_value = False
            issues.append(f"sample[{i}] source is bool/None: {src!r}")
        else:
            source_values.append(src)
        vt_ok = s.get("variant_type") == baseline_vt_name
        if not vt_ok:
            all_vt_same = False
            issues.append(
                f"sample[{i}] variant_type {s.get('variant_type')} != {baseline_vt_name}"
            )
        if not s.get("datasource_alive"):
            all_ds_alive = False
            issues.append(f"sample[{i}] datasource not alive")
        if not s.get("mocker_alive"):
            all_mocker_alive = False
            issues.append(f"sample[{i}] mocker not alive")

        rv_raw = s["rt"].get("tagValue")
        qv_raw = s["qwq"].get("tagValue")
        rv = None
        qv = None
        if rv_raw is not None:
            try:
                rv = normalize_int(rv_raw)
            except (TypeError, ValueError):
                rv = None
        if qv_raw is not None:
            try:
                qv = normalize_int(qv_raw)
            except (TypeError, ValueError):
                qv = None

        rt_values.append(rv)
        qwq_values.append(qv)

        if rv is None:
            issues.append(f"sample[{i}] RT tagValue missing/unparseable: {rv_raw!r}")
        if qv is None:
            issues.append(f"sample[{i}] QwQ tagValue missing/unparseable: {qv_raw!r}")
        quality_ok = s["rt"].get("quality") not in (None, 0) and s["qwq"].get("quality") not in (None, 0)
        if not quality_ok:
            issues.append(
                f"sample[{i}] quality RT={s['rt'].get('quality')} QwQ={s['qwq'].get('quality')}"
            )
        t_ok = bool(s["rt"].get("tagTime")) and bool(s["qwq"].get("tagTime"))
        if not t_ok:
            issues.append(
                f"sample[{i}] tagTime RT={s['rt'].get('tagTime')!r} QwQ={s['qwq'].get('tagTime')!r}"
            )
        else:
            try:
                parse_required_timestamp(s["rt"]["tagTime"])
                parse_required_timestamp(s["qwq"]["tagTime"])
            except AssertionError:
                issues.append(f"sample[{i}] tagTime unparsable")

        if rv is not None and rv != baseline_value:
            all_same_value = False
        if qv is not None and qv != baseline_value:
            all_same_value = False
        try:
            sv = normalize_int(src)
        except (TypeError, ValueError):
            sv = None
        if sv is not None and sv != baseline_value:
            all_same_value = False
            issues.append(f"sample[{i}] source value {sv} != baseline {baseline_value}")

    return {
        "stable": all_same_value and all_vt_same and all_ds_alive and all_mocker_alive and not issues,
        "issues": issues,
        "all_same_value": all_same_value,
        "all_vt_same": all_vt_same,
        "all_ds_alive": all_ds_alive,
        "all_mocker_alive": all_mocker_alive,
        "final_source": source_values[-1] if source_values else None,
        "final_rt": rt_values[-1] if rt_values else None,
        "final_qwq": qwq_values[-1] if qwq_values else None,
    }


def strict_restore_and_teardown(
    api,
    *,
    endpoint: str,
    node_name: str,
    namespace_index: int,
    original_value: int,
    original_variant_type,
    tag_id: int,
    tag_name: str,
    ds_id: int,
    ds_name: str,
    mocker,
    port: int,
    host: str,
) -> None:
    errors: list[str] = []

    # 1. restore source value (mocker must still be alive)
    if mocker is not None and mocker.process.poll() is None:
        try:
            from asyncua import ua as ua_module
            dv = ua_module.DataValue(ua_module.Variant(original_value, original_variant_type))
            import asyncio
            from asyncua import Client
            async def _restore():
                async with Client(endpoint) as client:
                    nid = f"ns={namespace_index};s={node_name}"
                    node = client.get_node(nid)
                    await node.write_value(dv)
            asyncio.run(_restore())
        except Exception as exc:
            errors.append(f"restore_source: {exc}")
        else:
            try:
                check = opcua_read_variant_type_sync(endpoint, node_name, namespace_index=namespace_index)
                if check[1] != original_variant_type:
                    errors.append(
                        f"restore_vt_mismatch: got {check[1].name} != {original_variant_type.name}"
                    )
                if check[0] != original_value:
                    errors.append(
                        f"restore_value_mismatch: got {check[0]} != {original_value}"
                    )
            except Exception as exc:
                errors.append(f"restore_verify: {exc}")

    # 2. delete active tag
    if tag_id:
        try:
            delete_tags_physical(api, [tag_id])
        except TptAPIError as exc:
            if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                errors.append(f"delete_tag: {exc}")
        except Exception as exc:
            errors.append(f"delete_tag: {exc}")

    # 3. verify active list is clean
    if tag_name:
        try:
            page = list_tags(api, page=1, page_size=50, data={"tagName": tag_name})
            remaining = [r for r in (page.get("records") or []) if r.get("tagName") == tag_name]
            if remaining:
                errors.append(
                    f"tag {tag_name!r} still in active list after delete: ids={[r.get('id') for r in remaining]}"
                )
        except Exception as exc:
            errors.append(f"verify_active_list: {exc}")

    # 4. verify and clean recycle tag
    if tag_name:
        try:
            rec = list_recycle_tags(api, page=1, page_size=200)
            rec_records = ((rec or {}).get("tagInfoList") or {}).get("records") or []
            in_recycle = [r for r in rec_records if r.get("tagName") == tag_name]
            if in_recycle:
                rec_ids = [int(r["id"]) for r in in_recycle]
                delete_tags_physical(api, rec_ids)
        except Exception as exc:
            errors.append(f"recycle_cleanup: {exc}")

    # 5. disable datasource
    if ds_id:
        try:
            from tpt_api.datahub import change_ds_state
            change_ds_state(api, ds_id, False)
        except Exception as exc:
            errors.append(f"disable_ds: {exc}")

    # 6. delete datasource
    if ds_id:
        try:
            delete_ds_info(api, [ds_id])
        except TptAPIError as exc:
            if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                errors.append(f"delete_ds: {exc}")
        except Exception as exc:
            errors.append(f"delete_ds: {exc}")

    # 7. stop mocker
    if mocker is not None and mocker.process.poll() is None:
        try:
            mocker.process.terminate()
            mocker.process.wait(timeout=10.0)
        except Exception as exc:
            errors.append(f"stop_mocker: {exc}")

    # 8. verify port closed
    if port and host:
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.3)
                        s.connect((host, port))
                        time.sleep(0.3)
                except OSError:
                    break
            else:
                errors.append(f"listener residual: {host}:{port}")
        except Exception as exc:
            errors.append(f"port_check: {exc}")

    if errors:
        raise AssertionError("strict_restore_and_teardown errors: " + "; ".join(errors))
