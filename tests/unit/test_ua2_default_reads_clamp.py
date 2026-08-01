from __future__ import annotations

import time

import pytest

from tests.integration.ua2 import test_tag_creation_default_reads as mod


class _FakeRT:
    def __init__(self, tagValue):
        self.tagValue = tagValue

    def get(self, key, default=None):
        if key == "tagValue":
            return self.tagValue
        if key == "quality":
            return 192
        if key == "tagTime":
            return "2026-08-01T00:00:00Z"
        return default


def _snap_of(rt_val, source_val):
    return {
        "rt": _FakeRT(rt_val),
        "source_before": source_val,
        "source_after": source_val,
        "rt_ts": time.monotonic(),
    }


class TestSnapshotMatchesRt:
    def test_accepts_match_in_window(self):
        assert mod._snapshot_matches_rt(_snap_of(3, 3), 4, "t", [3, 5])

    def test_rejects_no_match(self):
        assert not mod._snapshot_matches_rt(_snap_of(7, 3), 4, "t", [3, 5])

    def test_none_rt_rejected(self):
        assert not mod._snapshot_matches_rt(_snap_of(None, 3), 4, "t", [3, 5])

    def test_zero_quality_rejected(self):
        snap = _snap_of(3, 3)
        snap["rt"] = {"tagValue": 3, "quality": 0, "tagTime": "t"}
        assert not mod._snapshot_matches_rt(snap, 4, "t", [3, 5])

    def test_differ_from_rejects_equal(self):
        assert not mod._snapshot_matches_rt(_snap_of(3, 3), 4, "t", [3, 5], differ_from=3)

    def test_differ_from_accepts_different_match(self):
        assert mod._snapshot_matches_rt(_snap_of(5, 5), 4, "t", [3, 5], differ_from=3)


class TestWaitClampedMatch:
    def test_static_single_shot(self, monkeypatch):
        monkeypatch.setattr(mod, "get_rt_point", lambda api, tag_name: _FakeRT(3))
        source_fn = lambda: 3
        snap = mod._wait_clamped_match(
            "api", "t", source_fn, 4,
            node_name="n", node_type="Int16",
            endpoint="opc.tcp://h:p/", namespace_index=1,
            is_change=False,
        )
        assert snap["rt"].get("tagValue") == 3

    def test_change_accepts_lagged_rt_in_window(self, monkeypatch):
        source_values = iter([0, 1, 2, 3, 4, 5])
        monkeypatch.setattr(mod, "get_rt_point", lambda api, tag_name: _FakeRT(3))
        monkeypatch.setattr(mod, "_assert_source_variant_type", lambda *a, **k: None)
        source_fn = lambda: next(source_values)
        snap = mod._wait_clamped_match(
            "api", "t", source_fn, 4,
            node_name="n", node_type="Int16",
            endpoint="opc.tcp://h:p/", namespace_index=1,
            is_change=True,
            timeout=5.0, interval=0.0,
        )
        assert snap["rt"].get("tagValue") == 3

    def test_change_differ_from_waits_for_new_value(self, monkeypatch):
        rt_values = iter([3, 3, 5])
        source_values = iter([0, 1, 2, 3, 4, 5])
        monkeypatch.setattr(mod, "get_rt_point", lambda api, tag_name: _FakeRT(next(rt_values)))
        monkeypatch.setattr(mod, "_assert_source_variant_type", lambda *a, **k: None)
        source_fn = lambda: next(source_values)
        snap = mod._wait_clamped_match(
            "api", "t", source_fn, 4,
            node_name="n", node_type="Int16",
            endpoint="opc.tcp://h:p/", namespace_index=1,
            is_change=True,
            differ_from=3,
            timeout=5.0, interval=0.0,
        )
        assert snap["rt"].get("tagValue") == 5

    def test_change_timeout_reports_sequences(self, monkeypatch):
        monkeypatch.setattr(mod, "get_rt_point", lambda api, tag_name: _FakeRT(99))
        source_fn = lambda: 3
        with pytest.raises(AssertionError, match="RT never matched any observed source value"):
            mod._wait_clamped_match(
                "api", "t", source_fn, 4,
                node_name="n", node_type="Int16",
                endpoint="opc.tcp://h:p/", namespace_index=1,
                is_change=True,
                timeout=0.3, interval=0.01,
            )

    def test_change_timeout_message_has_source_and_rt(self, monkeypatch):
        monkeypatch.setattr(mod, "get_rt_point", lambda api, tag_name: _FakeRT(99))
        source_fn = lambda: 3
        try:
            mod._wait_clamped_match(
                "api", "t", source_fn, 4,
                node_name="n", node_type="Int16",
                endpoint="opc.tcp://h:p/", namespace_index=1,
                is_change=True,
                timeout=0.2, interval=0.01,
            )
            raise AssertionError("expected timeout")
        except AssertionError as exc:
            msg = str(exc)
            assert "source samples observed" in msg
            assert "RT samples" in msg
