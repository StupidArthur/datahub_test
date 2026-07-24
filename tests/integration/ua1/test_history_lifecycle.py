"""UA-1-2-03 / UA-1-2-05 history lifecycle cases.

History assertions follow the principle from the third-phase task plan:
use explicit UTC time windows, account for async persistence grace
periods, and verify that new data points appear / stop appearing around
the disable / enable moments.

Each test sets up its own datasource, tag, and mocker to avoid ordering
dependencies between tests.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from tpt_api.datahub import (
    add_ds_info,
    add_tag,
    change_ds_state,
    get_history_value,
    list_ds_info,
)
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
from tests.support.rt_helpers import get_rt_point


def _is_alive(api, ds_id: int) -> bool:
    page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", -1)) == ds_id:
            return bool(row.get("alive"))
    return False


def _setup_history_fixture(api, settings, tmp_path_factory, case_id: str) -> dict:
    """Create a connected changing-tag datasource for history tests.

    Returns a dict with ds_id, ds_name, tag_id, tag_name, mocker handle.
    """
    from tests.support.mocker_process import find_free_port as _ffp
    from tests.support.mocker_process import start_mocker as _sm
    from tests.support.mocker_process import stop_mocker as _stpm
    from tests.support.mocker_process import write_mocker_config as _wmcfg

    local_ip = (
        settings.mocker_endpoint.split("//")[1].split(":")[0]
        if settings.mocker_endpoint
        else "127.0.0.1"
    )
    port = _ffp()
    endpoint = f"opc.tcp://{local_ip}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, f"{case_id}-ds")
    tag_name = unique_name(settings.test_prefix, f"{case_id}-tag")

    tmp_dir = tmp_path_factory.mktemp(f"mocker_{case_id.lower()}")
    cfg_path = _wmcfg(tmp_dir, port)
    mocker = _sm(cfg_path, port, host=local_ip)

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
        "mocker": mocker,
    }


def _teardown_history_fixture(api, ctx: dict) -> None:
    if ctx.get("tag_id"):
        delete_tag_if_exists(api, ctx["tag_id"], ctx["tag_name"])
    if ctx.get("ds_id"):
        change_ds_state(api, ctx["ds_id"], False)
        delete_datasource_if_exists(api, ctx["ds_id"], ctx["ds_name"])
    if ctx.get("mocker"):
        stop_mocker(ctx["mocker"])


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _history_count(api, tag_name: str, beg: str, end: str, page_size: int = 50) -> int:
    res = get_history_value(
        api, [tag_name], beg, end,
        is_source=False, page=1, page_size=page_size,
    )
    info = res.get(tag_name, {}) if isinstance(res, dict) else {}
    return int(info.get("total", 0))


def _wait_for_history_count(
    api, tag_name: str, beg: str, end: str, predicate, timeout: float, interval: float = 2.0
) -> int:
    """Poll until history count predicate is satisfied or timeout."""
    deadline = time.monotonic() + timeout
    last = -1
    while time.monotonic() < deadline:
        last = _history_count(api, tag_name, beg, end)
        if predicate(last):
            return last
        time.sleep(interval)
    raise AssertionError(
        f"history count predicate not met within {timeout:.0f}s: last={last}"
    )


@pytest.mark.case(
    id="UA-1-2-03",
    chapter="UA-1-2",
    title="禁用后历史不再增长",
    preconditions=[
        "mock 配置 change=true；数据源 alive=true；采集稳定一段时间",
    ],
    steps=[
        "等待若干采集周期，确认历史基线 > 0",
        "记录禁用动作时间 t_disable",
        "change_ds_state(enabled=false)",
        "等待 alive=false + DataHub 异步落库宽限期",
        "记录稳定时间点 t_stable",
        "在 [t_stable, t_stable + N] 窗口反复查询历史",
        "期望：窗口内历史条数为 0 或不增长",
    ],
    expected=[
        "禁用之后历史窗口内不再有新采集点",
        "已有历史保留",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_history_stops_after_disable(api, settings, tmp_path_factory):
    ctx = _setup_history_fixture(api, settings, tmp_path_factory, "UA-1-2-03")
    try:
        # Establish a baseline: query history from a minute ago.
        # The datasource was just enabled, so the window should pick up
        # the first few collection cycles.
        beg = (datetime.now(timezone.utc) - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        # Let history accumulate a bit
        baseline = _wait_for_history_count(
            api, ctx["tag_name"], beg, _utc_now_str(),
            predicate=lambda n: n > 0, timeout=20.0, interval=2.0,
        )
        assert baseline > 0, f"baseline history should be > 0, got {baseline}"

        change_ds_state(api, ctx["ds_id"], False)
        wait_until(
            f"ds_offline:{ctx['ds_id']}",
            lambda: not _is_alive(api, ctx["ds_id"]),
            timeout=30.0,
        )
        # Async persistence grace: DataHub may flush trailing points for
        # a few seconds after disable. Record the stable boundary AFTER
        # the grace window.
        time.sleep(5)
        t_stable = _utc_now_str()

        # During the next ~15 seconds the platform must not produce any
        # new collection points for this tag.
        deadline = time.monotonic() + 15.0
        last_count = _history_count(api, ctx["tag_name"], t_stable, _utc_now_str())
        while time.monotonic() < deadline:
            time.sleep(3)
            now_count = _history_count(api, ctx["tag_name"], t_stable, _utc_now_str())
            assert now_count == last_count, (
                f"history grew during disable window: stable={t_stable} "
                f"first={last_count} latest={now_count}"
            )
            last_count = now_count
    finally:
        _teardown_history_fixture(api, ctx)


@pytest.mark.case(
    id="UA-1-2-05",
    chapter="UA-1-2",
    title="启用后历史恢复增长",
    preconditions=[
        "mock 配置 change=true；数据源已禁用；mock 仍在运行",
    ],
    steps=[
        "禁用数据源，等待离线稳定",
        "记录重新启用动作时间 t_re_enable",
        "change_ds_state(enabled=true)",
        "等待 alive=true + RT quality 恢复",
        "在 [t_re_enable, now] 窗口轮询历史",
        "期望：新点开始出现",
    ],
    expected=[
        "启用之后历史窗口起点之后有新采集点",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
@pytest.mark.history
@pytest.mark.slow
def test_history_resumes_after_enable(api, settings, tmp_path_factory):
    ctx = _setup_history_fixture(api, settings, tmp_path_factory, "UA-1-2-05")
    try:
        # First, disable and wait for offline stable.
        change_ds_state(api, ctx["ds_id"], False)
        wait_until(
            f"ds_offline:{ctx['ds_id']}",
            lambda: not _is_alive(api, ctx["ds_id"]),
            timeout=30.0,
        )
        time.sleep(5)

        t_re_enable = _utc_now_str()
        change_ds_state(api, ctx["ds_id"], True)
        wait_until(
            f"ds_alive:{ctx['ds_id']}",
            lambda: _is_alive(api, ctx["ds_id"]),
            timeout=60.0,
        )

        def _quality_ok():
            return get_rt_point(api, ctx["tag_name"]).get("quality", 0) != 0

        wait_until(f"rt_q:{ctx['tag_name']}", _quality_ok, timeout=30.0)

        new_count = _wait_for_history_count(
            api, ctx["tag_name"], t_re_enable, _utc_now_str(),
            predicate=lambda n: n > 0, timeout=30.0, interval=2.0,
        )
        assert new_count > 0, (
            f"expected new history points after re-enable in "
            f"window=[{t_re_enable}, now], got {new_count}"
        )
    finally:
        _teardown_history_fixture(api, ctx)