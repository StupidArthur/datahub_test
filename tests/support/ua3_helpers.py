"""UA-3 collection / real-time read helpers for native pytest tests.

Shared infrastructure for the UA-3-1 (位号采集) and UA-3-2 (实时读取)
chapters.  Reuses the ua2 mocker/datasource helpers where the semantics are
identical and adds UA-3-specific clamped source matching, 13-type node
building and frequency timeline sampling.

Every helper propagates ``TptAPIError``.  None of them convert a business
error into a fake "valid" return.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from tpt_api.datahub import add_tag, get_rt_value, query_tags_with_quality
from tpt_api.types import DataTypes, TagTypes

from tests.support.polling import wait_until
from tests.support.rt_helpers import get_rt_point
from tests.support.ua2_helpers import (
    opcua_read_sync,
    opcua_read_variant_type_sync,
    opcua_write_sync,
    setup_ds_only,
)
from tests.support.ua2_cleanup import strict_cleanup_ua2_context
from tests.support.ua2_rt_assertions import parse_required_timestamp
from tests.support.ua2_value_normalization import assert_value_equal

# ---------------------------------------------------------------------------
# 13 OPC UA types (config type name, DataHub dataType key)
# ---------------------------------------------------------------------------
UA3_TYPES: list[tuple[str, str]] = [
    ("Boolean", "BOOLEAN"),
    ("SByte", "S_BYTE"),
    ("Byte", "BYTE"),
    ("Int16", "SHORT"),
    ("UInt16", "U_SHORT"),
    ("Int32", "INT"),
    ("UInt32", "U_INT"),
    ("Int64", "LONG"),
    ("UInt64", "U_LONG"),
    ("Float", "FLOAT"),
    ("Double", "DOUBLE"),
    ("String", "STRING"),
    ("DateTime", "DATE_TIME"),
]

_TYPE_DEFAULTS: dict[str, object] = {
    "Boolean": False,
    "SByte": -5,
    "Byte": 200,
    "Int16": -30000,
    "UInt16": 60000,
    "Int32": -2000000000,
    "UInt32": 4000000000,
    "Int64": 9007199254740993,
    "UInt64": 4294967296,
    "Float": 3.5,
    "Double": 123.456,
    "String": "ua3-init",
    "DateTime": "2025-06-01T12:00:00+00:00",
}


def build_node(name: str, type_name: str, default: object = None, *, change: bool = True, writable: bool = False) -> dict:
    """Build a mocker node config dict for the given OPC UA type."""
    return {
        "name": name,
        "type": type_name,
        "count": 1,
        "change": change,
        "writable": writable,
        "default": _TYPE_DEFAULTS[type_name] if default is None else default,
    }


def build_13_type_nodes(prefix: str) -> list[dict]:
    """Return one writable static node per OPC UA type.

    Nodes are writable (change=False) so tests can set explicit values via
    asyncua and verify RT reflects them with the correct dataType.
    """
    return [
        build_node(f"{prefix}_{type_name.lower()}_", type_name, change=False, writable=True)
        for type_name, _ in UA3_TYPES
    ]


def type_node_name(prefix: str, type_name: str, namespace_index: int = 1, count_index: int = 1) -> str:
    """Derive the generated node id string for a 13-type node config.

    The mocker expands ``name`` with count into ``name_1`` ... ``name_N``
    (see ua_mocker/server_main.py ``_node_id_string``).
    """
    return f"{prefix}_{type_name.lower()}_{count_index}"


def node_id_from_cfg(node_cfg: dict, count_index: int = 1) -> str:
    """Node id string generated from a raw mocker node config entry."""
    return f"{node_cfg['name']}{count_index}"


def tag_base_name(namespace_index: int, node_id_str: str) -> str:
    """Compose the tagBaseName DataHub expects: ``<ns>_<node_id>``."""
    return f"{namespace_index}_{node_id_str}"


def data_type_key_to_id(key: str) -> int:
    return int(DataTypes[key])


def add_collection_tag(
    api, settings, ctx: dict, case_id: str,
    *,
    node_id_str: str,
    type_key: str,
    frequency: int = 10,
    only_read: bool = True,
) -> dict:
    """Add one tag bound to ``node_id_str`` on the existing datasource.

    Returns a context entry with tag_id / tag_name / tag_base_name.
    """
    from tests.support.naming import unique_name

    tag_name = unique_name(settings.test_prefix, f"{case_id}-tag")
    base = tag_base_name(ctx["namespace_index"], node_id_str)
    tag_data = add_tag(
        api, tag_name=tag_name,
        data_type=data_type_key_to_id(type_key),
        tag_type=TagTypes["一次位号"],
        ds_id=ctx["ds_id"],
        only_read=only_read,
        tag_base_name=base,
        frequency=frequency,
    )
    tag_id = int(tag_data.get("id") or tag_data.get("tagId"))
    return {"tag_id": tag_id, "tag_name": tag_name, "tag_base_name": base}


def wait_rt_valid(api, tag_name: str, timeout: float = 60.0) -> dict:
    """Poll until RT has a value and non-zero quality; return the point."""
    def _has():
        pt = get_rt_point(api, tag_name)
        return pt.get("tagValue") is not None and pt.get("quality", 0) != 0
    wait_until(f"rt_valid:{tag_name}", _has, timeout=timeout, interval=0.5)
    return get_rt_point(api, tag_name)


def wait_rt_matches_source(
    api,
    ctx: dict,
    tag_name: str,
    node_id_str: str,
    type_key: str,
    *,
    timeout: float = 30.0,
    interval: float = 0.25,
    expected: object = None,
) -> dict:
    """Poll until RT value matches the OPC UA source (clamped).

    For each round the source is sampled before and after the RT read.  The
    RT value must equal at least one observed source value of the correct
    type.  When ``expected`` is given, the RT value must equal ``expected``
    AND ``expected`` must be what the source currently holds (used to verify
    an asyncua-written value landed on the source and was collected).
    """
    data_type = data_type_key_to_id(type_key)
    endpoint = ctx["endpoint"]
    ns = ctx["namespace_index"]

    deadline = time.monotonic() + timeout
    source_samples: list = []
    rt_samples: list = []

    while time.monotonic() < deadline:
        source_before = opcua_read_sync(endpoint, node_id_str, namespace_index=ns)
        pt = get_rt_point(api, tag_name)
        source_after = opcua_read_sync(endpoint, node_id_str, namespace_index=ns)
        for s in (source_before, source_after):
            if s is not None and s not in source_samples:
                source_samples.append(s)
        source_samples = source_samples[-12:]
        rt_samples.append((time.monotonic(), pt.get("tagValue"), pt.get("quality")))

        rt_val = pt.get("tagValue")
        rt_quality = pt.get("quality", 0)
        if rt_val is not None and rt_quality not in (None, 0):
            if expected is not None:
                if _value_in_source_samples(expected, data_type, source_samples) and _value_equals(rt_val, expected, data_type):
                    return pt
            else:
                for s in source_samples:
                    try:
                        assert_value_equal(s, rt_val, data_type)
                    except AssertionError:
                        continue
                    return pt
        time.sleep(interval)

    detail = "\n".join(
        f"  rt[{i}] ts={ts:.3f} tagValue={rv!r} quality={q}"
        for i, (ts, rv, q) in enumerate(rt_samples)
    )
    raise AssertionError(
        f"RT never matched source within {timeout:.1f}s for {tag_name} "
        f"(node={node_id_str}, type={type_key})\n"
        f"source samples: {source_samples}\n"
        f"RT samples:\n{detail}"
    )


def _value_equals(actual: object, expected: object, data_type: int) -> bool:
    try:
        assert_value_equal(expected, actual, data_type)
    except AssertionError:
        return False
    return True


def _value_in_source_samples(expected: object, data_type: int, samples: list) -> bool:
    for s in samples:
        try:
            assert_value_equal(expected, s, data_type)
        except AssertionError:
            continue
        return True
    return False


def wait_rt_changed(api, tag_name: str, old_value: object, timeout: float = 30.0) -> dict:
    """Wait until RT value differs from ``old_value`` (strict)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pt = get_rt_point(api, tag_name)
        if pt.get("tagValue") is not None and pt.get("tagValue") != old_value:
            return pt
        time.sleep(0.5)
    raise AssertionError(f"RT for {tag_name} did not change from {old_value!r} within {timeout:.1f}s")


def sample_rt_timeline(api, tag_name: str, duration: float, interval: float = 0.5) -> list[dict]:
    """Sample RT repeatedly; return a list of {ts, tagTime, tagValue, quality}."""
    timeline: list[dict] = []
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        pt = get_rt_point(api, tag_name)
        timeline.append({
            "ts": time.monotonic(),
            "tagTime": pt.get("tagTime"),
            "tagValue": pt.get("tagValue"),
            "quality": pt.get("quality", 0),
        })
        time.sleep(interval)
    return timeline


def distinct_update_times(timeline: list[dict]) -> list[str]:
    """Unique non-empty tagTime values in observation order."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for rec in timeline:
        tt = rec.get("tagTime")
        if tt and tt not in seen_set:
            seen_set.add(tt)
            seen.append(tt)
    return seen


def assert_times_parsable(records: list[dict]) -> list[datetime]:
    parsed: list[datetime] = []
    for rec in records:
        tag_time = rec.get("tagTime") or rec.get("appTime")
        if not tag_time:
            raise AssertionError(f"timestamp missing in record: {rec}")
        parsed.append(parse_required_timestamp(tag_time))
    return parsed


def now_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def rt_query(api, *, tag_names: list[str] | None = None, tag_info_ids: list[int] | None = None,
             group_id: int | None = None, is_from_db: bool = False,
             option: int | None = None, query_time: str | None = None) -> list[dict]:
    """Thin passthrough to getRTValue (UA-3-2 keeps the call explicit)."""
    return get_rt_value(
        api, tag_names=tag_names, tag_info_ids=tag_info_ids, group_id=group_id,
        is_from_db=is_from_db, option=option, query_time=query_time,
    )


def cleanup_ua3_context(api, *, tag_ids: list[int] | None = None, tag_names: list[str] | None = None,
                        ds_id: int | None = None, ds_name: str | None = None,
                        mocker=None, host: str | None = None, port: int | None = None) -> None:
    """Strict UA-3 cleanup: physical-delete tags, then strict DS/mocker cleanup."""
    errors: list[str] = []
    tag_ids = tag_ids or []
    tag_names = tag_names or []
    for tid, tname in zip(tag_ids, tag_names):
        try:
            strict_cleanup_ua2_context(
                api, tag_id=tid, tag_name=tname,
                ds_id=None, mocker=None, host=None, port=None,
            )
        except AssertionError as exc:
            errors.append(str(exc))
    if errors:
        raise AssertionError("; ".join(errors))
    strict_cleanup_ua2_context(
        api, ds_id=ds_id, ds_name=ds_name, mocker=mocker, host=host, port=port,
    )


def cleanup_ua3_multi_context(api, *, tags: list[dict] | None = None,
                              ds_contexts: list[dict] | None = None) -> None:
    """Strict cleanup for multi-datasource UA-3 tests.

    Physically deletes every tag (active + recycle residual), then for each
    datasource runs the full strict DS/mocker cleanup.  All errors are
    aggregated; any failure raises AssertionError (never swallowed).
    """
    errors: list[str] = []
    for tag in tags or []:
        try:
            strict_cleanup_ua2_context(
                api, tag_id=tag.get("tag_id"), tag_name=tag.get("tag_name"),
                ds_id=None, mocker=None, host=None, port=None,
            )
        except AssertionError as exc:
            errors.append(str(exc))
    for c in ds_contexts or []:
        try:
            strict_cleanup_ua2_context(
                api, ds_id=c.get("ds_id"), ds_name=c.get("ds_name"),
                mocker=c.get("mocker"), host=c.get("host"), port=c.get("port"),
            )
        except AssertionError as exc:
            errors.append(str(exc))
    if errors:
        raise AssertionError("; ".join(errors))
