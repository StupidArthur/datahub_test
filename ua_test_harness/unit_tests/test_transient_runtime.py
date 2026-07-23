from __future__ import annotations

import pytest


def test_read_rt_treats_initial_missing_tag_as_not_ready(monkeypatch) -> None:
    from ua_test_harness.fixtures import tag
    from ua_test_harness.clients import tpt_client

    monkeypatch.setattr(tpt_client, "get_api", lambda _ctx: object())

    def missing(*_args, **_kwargs):
        raise RuntimeError("[500] Tag Dose Not Exist")

    monkeypatch.setattr(tag, "get_rt_value", missing)
    assert tag.read_rt(object(), "ua_auto_tag") == {}


def test_read_rt_reraises_non_transient_errors(monkeypatch) -> None:
    from ua_test_harness.fixtures import tag
    from ua_test_harness.clients import tpt_client

    monkeypatch.setattr(tpt_client, "get_api", lambda _ctx: object())

    def denied(*_args, **_kwargs):
        raise RuntimeError("permission denied")

    monkeypatch.setattr(tag, "get_rt_value", denied)
    with pytest.raises(RuntimeError, match="permission denied"):
        tag.read_rt(object(), "ua_auto_tag")


def test_safe_delete_accepts_timeout_when_resource_is_already_gone(monkeypatch) -> None:
    from ua_test_harness.fixtures import datasource

    rows = iter([
        {"id": 54, "dsName": "ua_auto_ua1_ds_test"},
        None,
    ])
    monkeypatch.setattr(datasource, "find_ds_by_id", lambda _api, _id: next(rows))

    def timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(datasource, "delete_ds_info", timeout)
    datasource._safe_delete(object(), 54)
