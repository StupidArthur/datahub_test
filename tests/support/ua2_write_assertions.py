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
from tests.support.ua2_value_normalization import normalize_int


INTEGER_RANGES: dict[int, tuple] = {
    2: ("SByte", -128, 127),
    3: ("Byte", 0, 255),
    4: ("Int16", -32768, 32767),
    5: ("UInt16", 0, 65535),
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
}


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
    timeout: float = 30.0,
    interval: float = 0.5,
) -> dict:
    deadline = time.monotonic() + timeout
    last_trio: dict = {}
    while time.monotonic() < deadline:
        trio = _sample_trio(api, endpoint, node_name, namespace_index, ds_id, tag_name)
        last_trio = trio
        src = trio["source"]
        if isinstance(src, bool) or src is None:
            time.sleep(interval)
            continue
        if trio["variant_type"] != expected_variant_type:
            time.sleep(interval)
            continue
        try:
            sv = normalize_int(src)
        except (TypeError, ValueError):
            time.sleep(interval)
            continue
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
    if port:
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(0.3)
                        s.connect(("127.0.0.1", port))
                        time.sleep(0.3)
                except OSError:
                    port_closed = True
                    break
            else:
                errors.append(f"port {port} still open after stop_mocker")
        except Exception as exc:
            errors.append(f"port_check: {exc}")

    if errors:
        raise AssertionError("strict_restore_and_teardown errors: " + "; ".join(errors))
