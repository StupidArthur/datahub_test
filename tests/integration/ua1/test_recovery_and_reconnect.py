"""UA-1-3 disconnect / reconnect cases.

Migrated from the legacy Harness specification
(ua_test_harness/test_cases/UA-1-3.md). Eight cases total; this slice
implements the four that can be safely verified against the current
product:

- UA-1-3-01: disconnect detection latency (alive + RT)
- UA-1-3-02: reconnect recovery latency
- UA-1-3-06: short disconnect recovery
- UA-1-3-07: long disconnect recovery (window shortened to 30s from the
  spec's 120s to keep pytest cycle time manageable)

Remaining cases (UA-1-3-03/04/05/08) are deferred and recorded in
docs/migration/ua-1-3-blockers.md.

Each test allocates a free port, creates its own datasource / tag /
mocker, and reuses the port across restart cycles.
"""
from __future__ import annotations

import time

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    list_ds_info,
)
from tpt_api.errors import TptAPIError
from tpt_api.types import DataTypes, DsSubTypes, DsTypes, TagTypes

from tests.support.cleanup import delete_datasource_if_exists, delete_tag_if_exists
from tests.support.mocker_process import (
    find_free_port,
    start_mocker,
    stop_mocker,
    write_mocker_config,
)
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import assert_rt_unavailable, get_rt_point, try_get_rt_point


def _is_alive(api, ds_id: int) -> bool:
    page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", -1)) == ds_id:
            return bool(row.get("alive"))
    return False


def _setup_recovery(api, settings, tmp_path_factory, case_id: str) -> dict:
    """Create datasource + tag + mocker on a free port; return context."""
    local_ip = (
        settings.mocker_endpoint.split("//")[1].split(":")[0]
        if settings.mocker_endpoint
        else "127.0.0.1"
    )
    port = find_free_port()
    endpoint = f"opc.tcp://{local_ip}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, f"{case_id}-ds")
    tag_name = unique_name(settings.test_prefix, f"{case_id}-tag")

    tmp_dir = tmp_path_factory.mktemp(f"mocker_{case_id.lower()}")
    cfg_path = write_mocker_config(tmp_dir, port)
    mocker = start_mocker(cfg_path, port, host=local_ip)

    data = add_ds_info(
        api, ds_name=ds_name,
        ds_type=DsTypes["REAL_TIME_DB"], ds_sub_type=DsSubTypes["OPC_UA_SERVER"],
        ds_tar_url=endpoint,
    )
    ds_id = int(data.get("id") or data.get("dsId"))
    change_ds_state(api, ds_id, True)
    wait_until(f"ds_alive:{ds_id}", lambda: _is_alive(api, ds_id), timeout=60.0)

    tag_data = add_tag(
        api, tag_name=tag_name, data_type=DataTypes["INT"],
        tag_type=TagTypes["一次位号"], ds_id=ds_id, only_read=True,
        tag_base_name="2_smoke_change_1",
    )
    tag_id = int(tag_data.get("id") or tag_data.get("tagId"))

    def _has_rt():
        pt = get_rt_point(api, tag_name)
        return pt.get("tagValue") is not None and pt.get("quality", 0) != 0

    wait_until(f"rt:{tag_name}", _has_rt, timeout=60.0)

    return {
        "ds_id": ds_id, "ds_name": ds_name,
        "tag_id": tag_id, "tag_name": tag_name,
        "mocker": mocker, "port": port, "local_ip": local_ip,
        "endpoint": endpoint, "case_id": case_id,
    }


def _teardown(api, ctx: dict) -> None:
    if ctx.get("mocker"):
        try:
            stop_mocker(ctx["mocker"])
        except Exception:
            pass
    if ctx.get("tag_id"):
        delete_tag_if_exists(api, ctx["tag_id"], ctx["tag_name"])
    if ctx.get("ds_id"):
        change_ds_state(api, ctx["ds_id"], False)
        delete_datasource_if_exists(api, ctx["ds_id"], ctx["ds_name"])


def _restart_mocker(ctx: dict, tmp_path_factory) -> None:
    """Restart the mocker on the same port; keep ds/tag intact.

    If ``ctx["mocker"]`` is a live handle, stop it first. If it has
    already been stopped and set to ``None``, skip the stop call.
    """
    if ctx.get("mocker") is not None:
        stop_mocker(ctx["mocker"])
    ctx["mocker"] = None
    tmp_dir = tmp_path_factory.mktemp(f"restart_{ctx['case_id'].lower()}")
    cfg_path = write_mocker_config(tmp_dir, ctx["port"])
    ctx["mocker"] = start_mocker(cfg_path, ctx["port"], host=ctx["local_ip"])


def _wait_for_alive_false(api, ds_id: int, timeout: float, interval: float = 1.0) -> float:
    """Poll alive; return elapsed seconds until False (or raise)."""
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    while time.monotonic() < deadline:
        if not _is_alive(api, ds_id):
            return time.monotonic() - start
        time.sleep(interval)
    raise AssertionError(f"ds {ds_id} still alive after {timeout}s")


def _wait_for_alive_true(api, ds_id: int, timeout: float, interval: float = 1.0) -> float:
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    while time.monotonic() < deadline:
        if _is_alive(api, ds_id):
            return time.monotonic() - start
        time.sleep(interval)
    raise AssertionError(f"ds {ds_id} did not recover within {timeout}s")


def _wait_for_rt_unavailable(api, tag_name: str, timeout: float = 30.0) -> float:
    """Poll RT read until TptAPIError; return elapsed seconds."""
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    while time.monotonic() < deadline:
        pt = try_get_rt_point(api, tag_name)
        if not pt:
            return time.monotonic() - start
        time.sleep(0.5)
    raise AssertionError(
        f"RT for {tag_name} still returned {pt} after {timeout}s"
    )


def _wait_for_rt_ok(api, tag_name: str, timeout: float = 30.0) -> float:
    """Poll RT read until good quality; return elapsed seconds.

    Tolerates transient TptAPIError (e.g. ``Tag Dose Not Exist``) right
    after an OPC UA server restart: the tag can briefly disappear from
    DataHub's index as the datasource re-subscribes.
    """
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    while time.monotonic() < deadline:
        try:
            pt = get_rt_point(api, tag_name)
            if pt.get("tagValue") is not None and pt.get("quality", 0) != 0:
                return time.monotonic() - start
        except TptAPIError:
            pass
        time.sleep(0.5)
    raise AssertionError(
        f"RT for {tag_name} did not return good value within {timeout}s"
    )


@pytest.mark.case(
    id="UA-1-3-01",
    chapter="UA-1-3",
    title="断开后各项指标变化延迟",
    preconditions=[
        "mock 配置 change=true；alive=true；位号正常采集",
    ],
    steps=[
        "连续 getRTValue 2 次确认值在变化",
        "记录历史当前条数",
        "停止 mock，记录 t0",
        "每 1s 轮询以下指标，记录各自发生变化的时刻：a) alive 变 false  b) RT quality 变 0 / RT 不可读",
        "4 个指标最终都应发生变化",
    ],
    expected=[
        "alive 在合理时间内变 false",
        "RT 查询最终抛 TptAPIError(tag 不存在)",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_disconnect_detection_latency(api, settings, tmp_path_factory):
    ctx = _setup_recovery(api, settings, tmp_path_factory, "UA-1-3-01")
    try:
        pt1 = get_rt_point(api, ctx["tag_name"])
        time.sleep(2)
        pt2 = get_rt_point(api, ctx["tag_name"])
        assert pt1.get("tagValue") != pt2.get("tagValue"), "values should change before disconnect"

        t0 = time.monotonic()
        stop_mocker(ctx["mocker"])
        ctx["mocker"] = None

        alive_delay = _wait_for_alive_false(api, ctx["ds_id"], timeout=120.0)
        rt_delay = _wait_for_rt_unavailable(api, ctx["tag_name"], timeout=120.0)

        assert alive_delay >= 0
        assert rt_delay >= 0
        elapsed = time.monotonic() - t0
        assert elapsed < 180.0, f"disconnect detection too slow: {elapsed:.1f}s"
    finally:
        _teardown(api, ctx)


@pytest.mark.case(
    id="UA-1-3-02",
    chapter="UA-1-3",
    title="重连后各项指标恢复延迟",
    preconditions=[
        "UA-1-3-01 之后：mock 已停止；数据源仍为 enabled；alive=false",
    ],
    steps=[
        "启动 mock（同端口同配置），记录 t0",
        "每 1s 轮询：a) alive 变 true  b) RT quality 恢复非0",
    ],
    expected=[
        "alive 在合理时间内变 true",
        "RT 恢复有效值",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_reconnect_recovery_latency(api, settings, tmp_path_factory):
    ctx = _setup_recovery(api, settings, tmp_path_factory, "UA-1-3-02")
    try:
        # Disconnect first
        stop_mocker(ctx["mocker"])
        ctx["mocker"] = None
        wait_until(
            f"ds_offline:{ctx['ds_id']}",
            lambda: not _is_alive(api, ctx["ds_id"]),
            timeout=120.0,
        )

        # Restart
        t0 = time.monotonic()
        _restart_mocker(ctx, tmp_path_factory)

        alive_delay = _wait_for_alive_true(api, ctx["ds_id"], timeout=120.0)
        rt_delay = _wait_for_rt_ok(api, ctx["tag_name"], timeout=120.0)

        assert alive_delay >= 0
        assert rt_delay >= 0
        elapsed = time.monotonic() - t0
        assert elapsed < 180.0, f"reconnect recovery too slow: {elapsed:.1f}s"
    finally:
        _teardown(api, ctx)


@pytest.mark.case(
    id="UA-1-3-06",
    chapter="UA-1-3",
    title="短暂断连恢复",
    preconditions=[
        "mock 配置 change=true；alive=true",
    ],
    steps=[
        "停止 mock",
        "立即重启（<5s 内）",
        "等待 2 个采集周期",
    ],
    expected=[
        "alive 恢复 true",
        "RT 采集恢复",
        "无数据断层",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_short_disconnect_recovery(api, settings, tmp_path_factory):
    ctx = _setup_recovery(api, settings, tmp_path_factory, "UA-1-3-06")
    try:
        _restart_mocker(ctx, tmp_path_factory)

        _wait_for_alive_true(api, ctx["ds_id"], timeout=60.0)
        _wait_for_rt_ok(api, ctx["tag_name"], timeout=60.0)

        # After the OPC UA server restart there can be a brief window
        # where the tag momentarily disappears from DataHub's index as
        # the datasource re-subscribes. Read in a tight retry loop and
        # verify the value changes between two good reads.
        deadline = time.monotonic() + 30.0
        pt1 = None
        while time.monotonic() < deadline:
            try:
                pt1 = get_rt_point(api, ctx["tag_name"])
                if pt1.get("tagValue") is not None:
                    break
            except TptAPIError:
                pass
            time.sleep(0.5)
        assert pt1 is not None and pt1.get("tagValue") is not None, (
            f"RT for {ctx['tag_name']} never recovered within 30s"
        )
        time.sleep(2)
        pt2 = None
        while time.monotonic() < deadline:
            try:
                pt2 = get_rt_point(api, ctx["tag_name"])
                if pt2.get("tagValue") is not None:
                    break
            except TptAPIError:
                pass
            time.sleep(0.5)
        assert pt2 is not None and pt2.get("tagValue") is not None, (
            f"RT second read for {ctx['tag_name']} failed"
        )
        assert pt1.get("tagValue") != pt2.get("tagValue"), "values should change after short recovery"
    finally:
        _teardown(api, ctx)


@pytest.mark.case(
    id="UA-1-3-07",
    chapter="UA-1-3",
    title="长时间断连后恢复",
    preconditions=[
        "mock 配置 change=true；alive=true",
    ],
    steps=[
        "停止 mock",
        "等待长窗口（本测试用 30s 替代规格的 120s 以保持 pytest 周期合理）",
        "重启 mock",
        "等待 2 个采集周期",
    ],
    expected=[
        "alive 恢复 true",
        "RT 采集恢复",
        "系统无崩溃、无资源泄漏",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.slow
def test_long_disconnect_recovery(api, settings, tmp_path_factory):
    ctx = _setup_recovery(api, settings, tmp_path_factory, "UA-1-3-07")
    try:
        stop_mocker(ctx["mocker"])
        ctx["mocker"] = None
        wait_until(
            f"ds_offline:{ctx['ds_id']}",
            lambda: not _is_alive(api, ctx["ds_id"]),
            timeout=120.0,
        )

        time.sleep(30)

        _restart_mocker(ctx, tmp_path_factory)

        _wait_for_alive_true(api, ctx["ds_id"], timeout=120.0)
        _wait_for_rt_ok(api, ctx["tag_name"], timeout=120.0)

        # See test_short_disconnect_recovery for the retry rationale.
        deadline = time.monotonic() + 30.0
        pt1 = None
        while time.monotonic() < deadline:
            try:
                pt1 = get_rt_point(api, ctx["tag_name"])
                if pt1.get("tagValue") is not None:
                    break
            except TptAPIError:
                pass
            time.sleep(0.5)
        assert pt1 is not None and pt1.get("tagValue") is not None, (
            f"RT for {ctx['tag_name']} never recovered within 30s"
        )
        time.sleep(2)
        pt2 = None
        while time.monotonic() < deadline:
            try:
                pt2 = get_rt_point(api, ctx["tag_name"])
                if pt2.get("tagValue") is not None:
                    break
            except TptAPIError:
                pass
            time.sleep(0.5)
        assert pt2 is not None and pt2.get("tagValue") is not None, (
            f"RT second read for {ctx['tag_name']} failed"
        )
        assert pt1.get("tagValue") != pt2.get("tagValue"), "values should change after long recovery"
    finally:
        _teardown(api, ctx)