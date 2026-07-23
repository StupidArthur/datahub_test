"""Shared helpers for precise UA-2 tag-management scenarios."""
from __future__ import annotations

import time
from typing import Any, Callable

from ua_test_harness.assertions import AssertFail, check_true
from ua_test_harness.type_mapping import tpt_tag_base_name

NAMESPACE_INDEX = 2
READ_NODE = "ua2_int32_r_1"
READ_DATA_TYPE = "INT"


def api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


def unique(ctx, prefix: str) -> str:
    run_id = (ctx.config.run_id or "run").replace("-", "_")
    return f"{prefix}_{run_id[:12]}_{time.time_ns() % 1_000_000}"


def endpoint(ctx) -> str:
    value = ctx.config.mock.endpoints.functional
    if not value:
        from ua_test_harness.clients.tpt_client import endpoint_for
        value = endpoint_for("functional", ctx)
    if not value:
        raise AssertFail("UA-2 functional mock endpoint is empty")
    return value


def wait_for(name: str, fn: Callable[[], Any], timeout: float = 60.0, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertFail(f"{name} timeout after {timeout}s; last={last!r}")


def row_value(row: dict[str, Any] | None):
    row = row or {}
    return row.get("tagValue", row.get("value"))


def prepare_datasource(ctx, cc, *, enabled: bool = True, endpoint_value: str | None = None,
                       endpoint: str | None = None, registry=None):
    from ua_test_harness.fixtures import datasource
    from ua_test_harness.fixtures.environment import ensure_logged_in, ensure_mock_ready

    ensure_mock_ready(ctx, "functional")
    ensure_logged_in(ctx)
    final_endpoint = endpoint_value if endpoint_value is not None else (endpoint or endpoint(ctx))
    ds = datasource.create_datasource(
        ctx,
        unique(ctx, "ua_auto_ua2_ds"),
        final_endpoint,
        registry=registry or cc.registry,
    )
    if enabled:
        datasource.change_state(ctx, ds["id"], True)
        check_true(
            "ua2_datasource_alive",
            datasource.wait_alive(ctx, ds["id"], timeout=ctx.config.timeouts.ds_connect_sec),
        )
    return ds


def create_read_tag(ctx, cc, ds_id: int, *, name: str | None = None, base_name: str | None = None):
    from ua_test_harness.fixtures import tag

    tag_name = name or unique(ctx, "ua_auto_ua2_tag")
    tg = tag.create_tag(
        ctx,
        tag_name,
        ds_id=ds_id,
        data_type=READ_DATA_TYPE,
        writable=False,
        frequency=1,
        tag_base_name=base_name or tpt_tag_base_name(NAMESPACE_INDEX, READ_NODE),
        registry=cc.registry,
    )
    row = tag.wait_tag_present(ctx, tag_name, timeout=30.0)
    return tg, row


def wait_rt(ctx, name: str, timeout: float | None = None):
    from ua_test_harness.fixtures import tag

    return wait_for(
        f"rt:{name}",
        lambda: (lambda row: row if row and row_value(row) is not None else None)(tag.read_rt(ctx, name)),
        timeout=timeout or ctx.config.timeouts.rt_visibility_sec,
    )


def active_rows(ctx, **filters) -> list[dict[str, Any]]:
    from tpt_api.datahub import list_tags
    return list_tags(api(ctx), page=1, page_size=500, data=filters).get("records") or []


def recycle_rows(ctx) -> list[dict[str, Any]]:
    from tpt_api.datahub import list_recycle_tags
    raw = list_recycle_tags(api(ctx), page=1, page_size=500)
    return ((raw or {}).get("tagInfoList") or {}).get("records") or []


def exact(rows: list[dict[str, Any]], field: str, value: Any) -> list[dict[str, Any]]:
    return [row for row in rows if row.get(field) == value]
