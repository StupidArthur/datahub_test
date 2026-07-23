"""Thin single-action ops for UA-2 cases.

Every function does exactly one thing. None implicitly: delete same-name
resources, delete a datasource's tags, decide reuse, or register the primary
cleanup. Case-private tag lifecycle is owned by the case body; the registry
entry registered by create_case_tag is a FALLBACK only.
"""
from __future__ import annotations

import time
from typing import Any

CASE_TAG_PREFIX = "ua_case_ua2_"
CASE_DS_PREFIX = "ua_case_ua2_ds_"


def _api(ctx):
    from ua_test_harness.clients.tpt_client import get_api
    return get_api(ctx)


# ---------- datasource ops ----------

def create_datasource_raw(ctx, name: str, endpoint: str, *, sub_type: str = "OPC_UA_SERVER") -> dict:
    from tpt_api.datahub import add_ds_info
    from tpt_api.types import DsSubTypes
    created = add_ds_info(_api(ctx), ds_name=name, ds_tar_url=endpoint, ds_sub_type=DsSubTypes[sub_type])
    return {"id": int(created.get("id") or 0), "name": name, "endpoint": endpoint, "raw": created}


def find_datasource_by_name(ctx, name: str) -> dict[str, Any] | None:
    from tpt_api.datahub import list_ds_info
    page = list_ds_info(_api(ctx), page=1, page_size=500, data={"dsName": name})
    for r in (page or {}).get("records") or []:
        if str(r.get("dsName") or r.get("name") or "") == name:
            return r
    return None


def find_datasource_by_id(ctx, ds_id: int) -> dict[str, Any] | None:
    from tpt_api.datahub import list_ds_info
    page = list_ds_info(_api(ctx), page=1, page_size=500, data={"id": ds_id})
    for r in (page or {}).get("records") or []:
        if int(r.get("id", -1)) == int(ds_id):
            return r
    return None


def enable_datasource(ctx, ds_id: int) -> None:
    from tpt_api.datahub import change_ds_state
    change_ds_state(_api(ctx), ds_id, True)


def disable_datasource(ctx, ds_id: int) -> None:
    from tpt_api.datahub import change_ds_state
    change_ds_state(_api(ctx), ds_id, False)


def wait_datasource_alive(ctx, ds_id: int, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = find_datasource_by_id(ctx, ds_id)
        if row and row.get("alive"):
            return True
        time.sleep(1.0)
    return False


def wait_datasource_offline(ctx, ds_id: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_datasource_by_id(ctx, ds_id) is None:
            return True
        time.sleep(1.0)
    return False


def delete_datasource_raw(ctx, ds_id: int, *, disable_first: bool = True) -> None:
    from tpt_api.datahub import delete_ds_info
    if disable_first:
        try:
            disable_datasource(ctx, ds_id)
        except Exception:
            pass
    delete_ds_info(_api(ctx), [ds_id])
    wait_datasource_offline(ctx, ds_id, timeout=15.0)


# ---------- tag ops ----------

def create_tag_raw(ctx, name: str, ds_id: int, *, data_type: str = "INT",
                   tag_base_name: str | None = None, tag_desc: str | None = None,
                   frequency: int = 1, only_read: bool = False, need_push: bool = True,
                   unit: str = "") -> dict:
    from tpt_api.datahub import add_tag
    from tpt_api.types import DataTypes, TagTypes
    kwargs: dict[str, Any] = {}
    if tag_desc is not None:
        kwargs["tag_desc"] = tag_desc
    result = add_tag(
        _api(ctx),
        tag_name=name,
        data_type=DataTypes[data_type],
        tag_type=TagTypes["一次位号"],
        ds_id=ds_id,
        group_id="0",
        unit=unit,
        only_read=only_read,
        frequency=frequency,
        need_push=need_push,
        is_vector=True,
        tag_base_name=tag_base_name or ("2_" + name),
        **kwargs,
    )
    return {"id": int(result.get("id") or 0), "name": name, "raw": result}


def _qtq_records(ctx, *, name: str = "", base_name: str = "", ds_id: int | None = None,
                group_id: str = "0", page: int = 1, page_size: int = 500) -> list[dict[str, Any]]:
    """Single page of `query_tags_with_quality (groupId=0/1)` flattened to records.

    groupId="0" → active view (excludes soft-deleted);
    groupId="1" → recycle bin view.
    See bugs.md Bug #1 for why we prefer this over `list_tags` for active queries.
    """
    from tpt_api.datahub import query_tags_with_quality
    res = query_tags_with_quality(
        _api(ctx),
        ds_id=ds_id,
        group_id=group_id,
        tag_name=name,
        tag_base_name=base_name,
        page=page,
        page_size=page_size,
    )
    return ((res or {}).get("tagInfoList") or {}).get("records") or []


def _qtq_all_pages(ctx, *, name: str = "", base_name: str = "", ds_id: int | None = None,
                  group_id: str = "0", page_size: int = 500) -> list[dict[str, Any]]:
    """Paginate `query_tags_with_quality` until page returns < page_size records."""
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        recs = _qtq_records(
            ctx, name=name, base_name=base_name, ds_id=ds_id,
            group_id=group_id, page=page, page_size=page_size,
        )
        if not recs:
            break
        out.extend(recs)
        if len(recs) < page_size:
            break
        page += 1
    return out


def find_tag_by_name(ctx, name: str) -> dict[str, Any] | None:
    """Active view lookup by exact tagName (post-filter for fuzzy match)."""
    for r in _qtq_records(ctx, name=name):
        if str(r.get("tagName") or "") == name:
            return r
    return None


def find_tag_by_id(ctx, tag_id: int) -> dict[str, Any] | None:
    rows = all_active_rows(ctx)
    for r in rows:
        if int(r.get("id", -1)) == int(tag_id):
            return r
    return None


def soft_delete_tag(ctx, tag_id: int) -> None:
    from tpt_api.datahub import delete_tags
    delete_tags(_api(ctx), [tag_id])


def restore_tag(ctx, tag_id: int) -> None:
    from tpt_api.datahub import remove_tag_group_relation
    remove_tag_group_relation(_api(ctx), group_id="1", tag_ids=[tag_id])


def physical_delete_tag(ctx, tag_id: int) -> None:
    from tpt_api.datahub import delete_tags_physical
    delete_tags_physical(_api(ctx), [tag_id])


def wait_tag_absent(ctx, name: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if find_tag_by_name(ctx, name) is None:
            return True
        time.sleep(1.0)
    return False


# ---------- case-tag helpers ----------

def case_tag_name(ctx, cc, suffix: str) -> str:
    run_id = (ctx.config.run_id or "run").replace("-", "_")
    case_id = str(getattr(cc, "case_id", "case")).replace("-", "_")
    return f"{CASE_TAG_PREFIX}{case_id}_{run_id[:12]}_{suffix}_{time.time_ns() % 1_000_000}"


def create_case_tag(ctx, cc, ds_id: int, *, suffix: str = "tag", data_type: str = "INT",
                    tag_base_name: str | None = None, tag_desc: str | None = None,
                    only_read: bool = False, frequency: int = 1, need_push: bool = True,
                    unit: str = "") -> dict:
    name = case_tag_name(ctx, cc, suffix)
    tg = create_tag_raw(
        ctx, name, ds_id, data_type=data_type, tag_base_name=tag_base_name,
        tag_desc=tag_desc, only_read=only_read, frequency=frequency,
        need_push=need_push, unit=unit,
    )
    tag_id = int(tg["id"])
    # FALLBACK only: runs if the case body did not explicitly clean up.
    cc.registry.register(
        f"tag:{name}", "tag",
        lambda: physical_delete_tag(ctx, tag_id),
        payload={"id": tag_id, "name": name, "source": "case_fallback"},
    )
    return {"id": tag_id, "name": name, "raw": tg["raw"]}


def cleanup_case_tag(ctx, cc, tag_id: int, tag_name: str) -> None:
    """Best-effort explicit cleanup. Swallows errors so cleanup never masks the
    case result; the registry fallback (still registered if pop didn't run) is
    retried by the runner's cleanup_all."""
    try:
        physical_delete_tag(ctx, tag_id)
        wait_tag_absent(ctx, tag_name)
        cc.registry.pop(f"tag:{tag_name}")
    except Exception:
        pass


# ---------- query helpers ----------
# These all use `query_tags_with_quality` (groupId="0") instead of `list_tags`,
# because `list_tags` does NOT filter out soft-deleted records (see bugs.md #1).

def active_rows(ctx, **filters) -> list[dict[str, Any]]:
    """Active view rows (groupId="0"), post-filtered to honor arbitrary filters.

    Supports the same **filters as before: tagName, dsId, tagBaseName, tagType.
    For tagName we post-filter to keep exact-match behavior (QTQ does fuzzy).
    """
    name = filters.get("tagName") or ""
    base = filters.get("tagBaseName") or ""
    ds_id = filters.get("dsId")
    recs = _qtq_records(ctx, name=name, base_name=base, ds_id=ds_id, group_id="0")
    # For exact tagName match: when filter explicitly says tagName=X, keep only X.
    if name:
        recs = [r for r in recs if str(r.get("tagName") or "") == str(name)]
    return recs


def all_active_rows(ctx, **filters) -> list[dict[str, Any]]:
    """Paginated active view (groupId="0"). Used by 016 for tagBaseName scan."""
    name = filters.get("tagName") or ""
    base = filters.get("tagBaseName") or ""
    ds_id = filters.get("dsId")
    return _qtq_all_pages(ctx, name=name, base_name=base, ds_id=ds_id, group_id="0")


def all_recycle_rows(ctx) -> list[dict[str, Any]]:
    from tpt_api.datahub import list_recycle_tags
    api = _api(ctx)
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        raw = list_recycle_tags(api, page=page, page_size=200)
        recs = ((raw or {}).get("tagInfoList") or {}).get("records") or []
        if not recs:
            break
        out.extend(recs)
        if len(recs) < 200:
            break
        page += 1
    return out


def exact(rows: list[dict[str, Any]], field: str, value: Any) -> list[dict[str, Any]]:
    return [r for r in rows if r.get(field) == value]
