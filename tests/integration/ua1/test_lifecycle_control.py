from __future__ import annotations

import time
from dataclasses import dataclass

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
from tests.support.endpoints import parse_mocker_endpoint
from tests.support.naming import unique_name
from tests.support.polling import wait_until
from tests.support.rt_helpers import assert_rt_unavailable, get_rt_point


def _is_alive(api, ds_id: int) -> bool:
    page = list_ds_info(api, page=1, page_size=50, data={"id": ds_id})
    for row in page.get("records") or []:
        if int(row.get("id", -1)) == ds_id:
            return bool(row.get("alive"))
    return False


@dataclass
class ConnectedChangingTag:
    ds_id: int
    ds_name: str
    tag_id: int
    tag_name: str


@pytest.fixture(scope="module")
def connected_changing_tag(api, mocker_endpoint, settings, tmp_path_factory):
    from tests.support.mocker_process import (
        find_free_port, write_mocker_config, start_mocker, stop_mocker,
    )

    parsed = parse_mocker_endpoint(mocker_endpoint)
    port = find_free_port()
    endpoint = f"opc.tcp://{parsed.host}:{port}/ua_mocker/"
    ds_name = unique_name(settings.test_prefix, "UA-1-2")
    tag_name = unique_name(settings.test_prefix, "UA-1-2-tag")

    tmp_dir = tmp_path_factory.mktemp("mocker_ua12")
    cfg_path = write_mocker_config(tmp_dir, port)
    mocker = start_mocker(cfg_path, port, host=parsed.host)

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

    yield ConnectedChangingTag(ds_id=ds_id, ds_name=ds_name, tag_id=tag_id, tag_name=tag_name)

    delete_tag_if_exists(api, tag_id, tag_name)
    change_ds_state(api, ds_id, False)
    delete_datasource_if_exists(api, ds_id, ds_name)
    stop_mocker(mocker)


def _ensure_alive(api, ctx: ConnectedChangingTag) -> None:
    if not _is_alive(api, ctx.ds_id):
        change_ds_state(api, ctx.ds_id, True)
        wait_until(f"ds_alive:{ctx.ds_id}", lambda: _is_alive(api, ctx.ds_id), timeout=60.0)
        def _q():
            return get_rt_point(api, ctx.tag_name).get("quality", 0) != 0
        wait_until(f"rt_q:{ctx.tag_name}", _q, timeout=240.0)


@pytest.mark.case(
    id="UA-1-2-01",
    chapter="UA-1-2",
    title="禁用运行中数据源",
    preconditions=[
        "mock 配置 change=true；数据源 alive=true，位号正常采集",
    ],
    steps=[
        "连续 getRTValue 2 次，确认值在变化",
        "change_ds_state(enabled=false)",
        "等待",
        "检查 alive 和 RT",
    ],
    expected=[
        "alive=false",
        "RT 查询抛 TptAPIError(tag 不存在)",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_disable_running_datasource(api, connected_changing_tag):
    ctx = connected_changing_tag
    _ensure_alive(api, ctx)

    pt1 = get_rt_point(api, ctx.tag_name)
    time.sleep(2)
    pt2 = get_rt_point(api, ctx.tag_name)
    assert pt1.get("tagValue") != pt2.get("tagValue"), "values should change before disable"

    change_ds_state(api, ctx.ds_id, False)
    wait_until(f"ds_offline:{ctx.ds_id}", lambda: not _is_alive(api, ctx.ds_id), timeout=30.0)

    assert_rt_unavailable(api, ctx.tag_name, timeout=10.0)


@pytest.mark.case(
    id="UA-1-2-02",
    chapter="UA-1-2",
    title="禁用后位号 RT 状态",
    preconditions=[
        "数据源已禁用",
    ],
    steps=[
        "禁用数据源",
        "getRTValue 读原位号",
    ],
    expected=[
        "RT 查询抛 TptAPIError",
        "错误信息指示 tag 不存在",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_rt_state_after_disable(api, connected_changing_tag):
    ctx = connected_changing_tag
    _ensure_alive(api, ctx)
    change_ds_state(api, ctx.ds_id, False)
    wait_until(f"ds_offline:{ctx.ds_id}", lambda: not _is_alive(api, ctx.ds_id), timeout=30.0)

    assert_rt_unavailable(api, ctx.tag_name, timeout=10.0)


@pytest.mark.case(
    id="UA-1-2-04",
    chapter="UA-1-2",
    title="重新启用已禁用数据源",
    preconditions=[
        "mock 仍在运行；数据源已禁用",
    ],
    steps=[
        "禁用数据源",
        "change_ds_state(enabled=true)",
        "等待 alive",
        "连续 getRTValue 确认值变化",
    ],
    expected=[
        "alive=true",
        "RT quality 恢复非0",
        "采集值恢复变化",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_reenable_disabled_datasource(api, connected_changing_tag):
    ctx = connected_changing_tag
    _ensure_alive(api, ctx)
    change_ds_state(api, ctx.ds_id, False)
    wait_until(f"ds_offline:{ctx.ds_id}", lambda: not _is_alive(api, ctx.ds_id), timeout=30.0)

    change_ds_state(api, ctx.ds_id, True)
    wait_until(f"ds_alive:{ctx.ds_id}", lambda: _is_alive(api, ctx.ds_id), timeout=60.0)

    def _quality_ok():
        return get_rt_point(api, ctx.tag_name).get("quality", 0) != 0

    wait_until(f"rt_quality:{ctx.tag_name}", _quality_ok, timeout=240.0)

    pt1 = get_rt_point(api, ctx.tag_name)
    time.sleep(2)
    pt2 = get_rt_point(api, ctx.tag_name)
    assert pt1.get("tagValue") != pt2.get("tagValue"), "values should change after re-enable"


@pytest.mark.case(
    id="UA-1-2-06",
    chapter="UA-1-2",
    title="重复启用",
    preconditions=[
        "已 alive=true",
    ],
    steps=[
        "change_ds_state(enabled=true)",
    ],
    expected=[
        "无异常",
        "状态保持 alive=true",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_repeat_enable(api, connected_changing_tag):
    ctx = connected_changing_tag
    _ensure_alive(api, ctx)
    change_ds_state(api, ctx.ds_id, True)
    time.sleep(1)
    assert _is_alive(api, ctx.ds_id), "should stay alive after repeat enable"


@pytest.mark.case(
    id="UA-1-2-07",
    chapter="UA-1-2",
    title="重复禁用",
    preconditions=[
        "已 alive=false",
    ],
    steps=[
        "禁用数据源",
        "再次 change_ds_state(enabled=false)",
    ],
    expected=[
        "无异常",
        "状态保持 alive=false",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_repeat_disable(api, connected_changing_tag):
    ctx = connected_changing_tag
    _ensure_alive(api, ctx)
    change_ds_state(api, ctx.ds_id, False)
    wait_until(f"ds_offline:{ctx.ds_id}", lambda: not _is_alive(api, ctx.ds_id), timeout=30.0)

    change_ds_state(api, ctx.ds_id, False)
    time.sleep(1)
    assert not _is_alive(api, ctx.ds_id), "should stay offline after repeat disable"


@pytest.mark.case(
    id="UA-1-2-08",
    chapter="UA-1-2",
    title="多次启停循环",
    preconditions=[
        "mock 配置 change=true；数据源正常",
    ],
    steps=[
        "禁用->等->启用->等->禁用->等->启用",
        "每步验证状态和 RT",
    ],
    expected=[
        "每次状态正确切换",
        "禁用时 RT 查询抛 TptAPIError",
        "启用时 quality 恢复非0",
        "最终 alive=true",
    ],
)
@pytest.mark.integration
@pytest.mark.destructive
def test_multiple_start_stop_cycles(api, connected_changing_tag):
    ctx = connected_changing_tag
    _ensure_alive(api, ctx)

    for cycle in range(2):
        change_ds_state(api, ctx.ds_id, False)
        wait_until(f"off_{cycle}", lambda: not _is_alive(api, ctx.ds_id), timeout=30.0)
        assert_rt_unavailable(api, ctx.tag_name, timeout=10.0)

        change_ds_state(api, ctx.ds_id, True)
        wait_until(f"on_{cycle}", lambda: _is_alive(api, ctx.ds_id), timeout=60.0)

        def _q():
            return get_rt_point(api, ctx.tag_name).get("quality", 0) != 0

        wait_until(f"q_{cycle}", _q, timeout=240.0)

    assert _is_alive(api, ctx.ds_id), "final state should be alive"
