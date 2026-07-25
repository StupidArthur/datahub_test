from __future__ import annotations

import time

from tpt_api.datahub import delete_ds_info, delete_tags_physical, list_ds_info, list_tags, list_recycle_tags
from tpt_api.errors import TptAPIError


def delete_datasource_if_exists(api, ds_id: int, name: str = "") -> None:
    try:
        delete_ds_info(api, [ds_id])
    except TptAPIError as exc:
        if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
            raise
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
        rows = page.get("records") or []
        if not any(int(r.get("id", -1)) == ds_id for r in rows):
            return
        time.sleep(1.0)
    raise AssertionError(
        f"datasource id={ds_id} name={name!r} still exists after delete timeout"
    )


def delete_tag_if_exists(api, tag_id: int, tag_name: str = "") -> None:
    try:
        delete_tags_physical(api, [tag_id])
    except TptAPIError as exc:
        if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
            raise
    page = list_tags(api, page=1, page_size=50, data={"tagName": tag_name})
    remaining = [r for r in (page.get("records") or []) if r.get("tagName") == tag_name]
    if remaining:
        raise AssertionError(
            f"tag id={tag_id} name={tag_name!r} still in active list after delete"
        )
    rec = list_recycle_tags(api, page=1, page_size=200)
    rec_records = ((rec or {}).get("tagInfoList") or {}).get("records") or []
    in_recycle = [r for r in rec_records if r.get("tagName") == tag_name]
    if in_recycle:
        rec_ids = [int(r["id"]) for r in in_recycle]
        delete_tags_physical(api, rec_ids)
