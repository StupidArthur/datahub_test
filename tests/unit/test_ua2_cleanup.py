"""Unit tests for strict_cleanup_ua2_context.

All tests are offline (no real DataHub / mocker).
"""
from __future__ import annotations

import pytest

from tpt_api.errors import TptAPIError

from tests.support.ua2_cleanup import strict_cleanup_ua2_context, _check_port_closed


class _OkAPI:
    """A fake api object that doesn't crash on basic attribute access."""
    pass


def _make_tpt_error(msg: str) -> TptAPIError:
    return TptAPIError(code="A0001", msg=msg)


@pytest.fixture
def patch_datahub(monkeypatch):
    """Patch all datahub functions to avoid real network calls."""
    import tests.support.ua2_cleanup as mod

    calls = {}

    def make_fake(return_value=None, fail_once=None):
        def fake(api, *args, **kwargs):
            calls.setdefault("count", 0)
            calls["count"] += 1
            if fail_once and calls["count"] == 1:
                raise fail_once
            if callable(return_value):
                return return_value(api, *args, **kwargs)
            return return_value
        return fake

    monkeypatch.setattr(mod, "delete_tags_physical", make_fake({}))
    monkeypatch.setattr(mod, "list_recycle_tags", make_fake({"tagInfoList": {"records": []}}))
    monkeypatch.setattr(mod, "list_tags", make_fake({"records": []}))
    monkeypatch.setattr(mod, "change_ds_state", make_fake(None))
    monkeypatch.setattr(mod, "delete_ds_info", make_fake(None))
    monkeypatch.setattr(mod, "list_ds_info", make_fake({"records": []}))
    monkeypatch.setattr(mod, "stop_mocker", make_fake(None))

    return mod, calls


class TestCheckPortClosed:
    def test_invalid_port_unreachable(self):
        assert _check_port_closed("127.0.0.1", 0, timeout=0.1) is True

    def test_known_closed_port(self):
        result = _check_port_closed("127.0.0.1", 65535, timeout=0.5)
        assert result is True


class TestStrictCleanup:
    def test_all_none_no_error(self):
        strict_cleanup_ua2_context(
            None,
            tag_id=None, tag_name=None,
            ds_id=None, ds_name=None,
            mocker=None, host=None, port=None,
        )

    def test_tag_cleanup_success(self, patch_datahub):
        mod, _ = patch_datahub
        strict_cleanup_ua2_context(
            _OkAPI(),
            tag_id=42, tag_name="test-tag",
            ds_id=None, ds_name=None,
            mocker=None, host=None, port=None,
        )

    def test_ds_cleanup_success(self, patch_datahub):
        mod, _ = patch_datahub
        mod.list_ds_info = lambda api, page=1, page_size=999: {"records": []}
        strict_cleanup_ua2_context(
            _OkAPI(),
            tag_id=None, tag_name=None,
            ds_id=1, ds_name="test-ds",
            mocker=None, host=None, port=None,
        )

    def test_tag_delete_api_error_reported(self, patch_datahub):
        mod, _ = patch_datahub
        mod.delete_tags_physical = lambda api, ids: (_ for _ in ()).throw(
            TptAPIError(code="A0001", msg="write failed")
        )

        with pytest.raises(AssertionError, match="write failed"):
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=42, tag_name="test-tag",
                ds_id=None, ds_name=None,
                mocker=None, host=None, port=None,
            )

    def test_tag_delete_not_exist_ignored(self, patch_datahub):
        mod, _ = patch_datahub
        mod.delete_tags_physical = lambda api, ids: (_ for _ in ()).throw(
            TptAPIError(code="A0001", msg="not exist")
        )

        strict_cleanup_ua2_context(
            _OkAPI(),
            tag_id=42, tag_name="test-tag",
            ds_id=None, ds_name=None,
            mocker=None, host=None, port=None,
        )

    def test_recycle_residual_reported(self, patch_datahub):
        mod, _ = patch_datahub
        mod.list_recycle_tags = lambda api, page=1, page_size=999: {
            "tagInfoList": {"records": [{"tagName": "test-tag", "id": 99}]}
        }

        with pytest.raises(AssertionError, match="still present"):
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=None, tag_name="test-tag",
                ds_id=None, ds_name=None,
                mocker=None, host=None, port=None,
            )

    def test_recycle_cleanup_after_active_delete(self, patch_datahub):
        """If recycle has tag after active delete, it should be physically deleted too."""
        mod, calls = patch_datahub
        recycle_deleted = []

        original_delete = mod.delete_tags_physical

        def track_delete(api, ids):
            recycle_deleted.extend(ids if isinstance(ids, list) else [ids])
            if len(recycle_deleted) <= 2:
                return {}
            return original_delete(api, ids)

        mod.delete_tags_physical = track_delete
        mod.list_recycle_tags = lambda api, page=1, page_size=999: {
            "tagInfoList": {"records": [{"tagName": "test-tag", "id": 99}]}
        }

        with pytest.raises(AssertionError):
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=42, tag_name="test-tag",
                ds_id=None, ds_name=None,
                mocker=None, host=None, port=None,
            )

        assert 99 in recycle_deleted

    def test_multiple_errors_aggregated(self, patch_datahub):
        mod, _ = patch_datahub
        mod.delete_tags_physical = lambda api, ids: (_ for _ in ()).throw(
            TptAPIError(code="A0001", msg="delete failed")
        )
        mod.list_recycle_tags = lambda api, page=1, page_size=999: {
            "tagInfoList": {"records": [{"tagName": "still-here", "id": 5}]}
        }

        with pytest.raises(AssertionError) as exc:
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=1, tag_name="still-here",
                ds_id=None, ds_name=None,
                mocker=None, host=None, port=None,
            )
        msg = str(exc.value)
        assert "delete failed" in msg

    def test_ds_delete_error_reported(self, patch_datahub):
        mod, _ = patch_datahub
        mod.delete_ds_info = lambda api, ids: (_ for _ in ()).throw(
            TptAPIError(code="A0001", msg="in use")
        )

        with pytest.raises(AssertionError, match="in use"):
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=None, tag_name=None,
                ds_id=5, ds_name="test-ds",
                mocker=None, host=None, port=None,
            )

    def test_ds_still_exists_reported(self, patch_datahub):
        mod, _ = patch_datahub
        mod.delete_ds_info = lambda api, ids: {}
        mod.list_ds_info = lambda api, page=1, page_size=999: {
            "records": [{"id": 5, "name": "test-ds", "dsStatus": 0}]
        }

        with pytest.raises(AssertionError, match="still exists"):
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=None, tag_name=None,
                ds_id=5, ds_name="test-ds",
                mocker=None, host=None, port=None,
            )

    def test_mocker_stop_failure_reported(self, patch_datahub):
        mod, _ = patch_datahub
        mod.stop_mocker = lambda m: (_ for _ in ()).throw(RuntimeError("mocker crash"))

        with pytest.raises(AssertionError, match="mocker crash"):
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=None, tag_name=None,
                ds_id=None, ds_name=None,
                mocker=object(),
                host=None, port=None,
            )

    def test_port_still_listening_reported(self, patch_datahub):
        mod, _ = patch_datahub
        mod._check_port_closed = lambda h, p, timeout=3.0: False

        with pytest.raises(AssertionError, match="still listening"):
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=None, tag_name=None,
                ds_id=None, ds_name=None,
                mocker=object(),
                host="10.0.0.1",
                port=8888,
            )

    def test_cleanup_failure_is_fail_not_xfail(self, patch_datahub):
        mod, _ = patch_datahub
        mod.delete_ds_info = lambda api, ids: (_ for _ in ()).throw(
            TptAPIError(code="A0001", msg="in use")
        )

        cleanup_failed = False
        try:
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=None, tag_name=None,
                ds_id=5, ds_name="test-ds",
                mocker=None, host=None, port=None,
            )
        except AssertionError:
            cleanup_failed = True

        assert cleanup_failed, "cleanup failure must raise AssertionError, never become xfail"

    def test_recycle_query_failure_not_hide_tag_check(self, patch_datahub):
        mod, _ = patch_datahub
        mod.list_recycle_tags = lambda api, page=1, page_size=999: (_ for _ in ()).throw(
            RuntimeError("recycle down")
        )

        with pytest.raises(AssertionError) as exc:
            strict_cleanup_ua2_context(
                _OkAPI(),
                tag_id=None, tag_name="some-tag",
                ds_id=None, ds_name=None,
                mocker=None, host=None, port=None,
            )
        assert "recycle down" in str(exc.value)
