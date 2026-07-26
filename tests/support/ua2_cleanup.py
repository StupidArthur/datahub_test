from __future__ import annotations

import socket
import time

from tpt_api.datahub import (
    change_ds_state,
    delete_ds_info,
    delete_tags_physical,
    list_ds_info,
    list_tags,
    list_recycle_tags,
)
from tpt_api.errors import TptAPIError

from tests.support.mocker_process import stop_mocker


def _check_port_closed(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return False
    except (OSError, socket.error):
        return True


def strict_cleanup_ua2_context(
    api,
    *,
    tag_id: int | None = None,
    tag_name: str | None = None,
    ds_id: int | None = None,
    ds_name: str | None = None,
    mocker=None,
    host: str | None = None,
    port: int | None = None,
) -> None:
    errors: list[str] = []

    # 1. Delete active tag by physical delete
    if tag_id:
        try:
            delete_tags_physical(api, [tag_id])
        except TptAPIError as exc:
            if "not exist" not in exc.msg.lower() and "不存在" not in exc.msg:
                errors.append(f"delete active tag id={tag_id}: {exc.msg}")

    # 2. Query recycle and clean tag_name residuals
    if tag_name:
        try:
            r = list_recycle_tags(api, page=1, page_size=999)
        except Exception as exc:
            errors.append(f"list_recycle_tags: {exc}")
            r = {}
        rec_records = (r.get("tagInfoList") or {}).get("records") or []
        recycle_hits = [t for t in rec_records if t.get("tagName") == tag_name]
        if recycle_hits:
            rec_ids = [int(t["id"]) for t in recycle_hits]
            try:
                delete_tags_physical(api, rec_ids)
            except TptAPIError as exc:
                errors.append(f"delete recycle tag ids={rec_ids}: {exc.msg}")

        # 3. Confirm active/recycle no longer have tag_name
        try:
            active = list_tags(api, page=1, page_size=999)
        except Exception as exc:
            errors.append(f"list_tags: {exc}")
            active = {}
        active_records = active.get("records") or []
        if any(t.get("tagName") == tag_name for t in active_records):
            errors.append(f"active tag {tag_name!r} still present after cleanup")

        try:
            recycle2 = list_recycle_tags(api, page=1, page_size=999)
        except Exception as exc:
            errors.append(f"list_recycle_tags: {exc}")
            recycle2 = {}
        recycle2_records = (recycle2.get("tagInfoList") or {}).get("records") or []
        if any(t.get("tagName") == tag_name for t in recycle2_records):
            errors.append(f"recycle tag {tag_name!r} still present after cleanup")

    # 4. Disable datasource
    disable_errors: list[str] = []
    if ds_id:
        try:
            change_ds_state(api, ds_id, False)
        except Exception as exc:
            disable_errors.append(f"disable ds id={ds_id}: {exc}")

        # 5. Delete datasource (always try even if disable failed)
        try:
            delete_ds_info(api, [ds_id])
        except TptAPIError as exc:
            errors.append(f"delete ds id={ds_id}: {exc.msg}")

        # 6. Confirm datasource deleted by id and name
        ds_deleted = False
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                page = list_ds_info(api, page=1, page_size=999)
                rows = page.get("records") or []
                found_by_id = any(int(r.get("id", -1)) == ds_id for r in rows)
                found_by_name = False
                if ds_name:
                    found_by_name = any(
                        (r.get("name") or r.get("dsName", "")) == ds_name
                        for r in rows
                    )
                if not found_by_id and not found_by_name:
                    ds_deleted = True
                    break
            except Exception as exc:
                errors.append(f"query ds id={ds_id}: {exc}")
                break
            time.sleep(1.0)
        if not ds_deleted:
            errors.append(
                f"datasource id={ds_id} name={ds_name!r} still exists after delete timeout"
            )

        # If DS was deleted despite disable error, ignore the disable error
        if ds_deleted:
            disable_errors.clear()

    errors.extend(disable_errors)

    # 7. Stop mocker
    if mocker is not None:
        try:
            stop_mocker(mocker)
        except Exception as exc:
            errors.append(f"stop_mocker: {exc}")

    # 8. Confirm mocker process exited (by port check)
    if port is not None:
        actual_host = host or "127.0.0.1"
        try:
            if not _check_port_closed(actual_host, port, timeout=5.0):
                errors.append(
                    f"port {actual_host}:{port} still listening after mocker stop"
                )
        except Exception as exc:
            errors.append(f"port check {actual_host}:{port}: {exc}")

    if errors:
        raise AssertionError("; ".join(errors))
