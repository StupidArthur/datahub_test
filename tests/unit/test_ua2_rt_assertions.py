from __future__ import annotations

from tests.support.ua2_rt_assertions import has_valid_tag_value, parse_required_timestamp


class TestHasValidTagValue:
    def test_boolean_true_is_valid(self):
        assert has_valid_tag_value({"tagValue": True})

    def test_boolean_false_is_valid(self):
        assert has_valid_tag_value({"tagValue": False})

    def test_integer_zero_is_valid(self):
        assert has_valid_tag_value({"tagValue": 0})

    def test_float_zero_is_valid(self):
        assert has_valid_tag_value({"tagValue": 0.0})

    def test_empty_string_is_valid(self):
        assert has_valid_tag_value({"tagValue": ""})

    def test_none_is_invalid(self):
        assert not has_valid_tag_value({"tagValue": None})

    def test_missing_key_is_invalid(self):
        assert not has_valid_tag_value({})

    def test_other_values_are_valid(self):
        assert has_valid_tag_value({"tagValue": 42})
        assert has_valid_tag_value({"tagValue": "hello"})
        assert has_valid_tag_value({"tagValue": 3.14})


class TestParseRequiredTimestamp:
    def test_valid_iso(self):
        dt = parse_required_timestamp("2025-06-01T12:00:00Z")
        assert dt.year == 2025
        assert dt.month == 6

    def test_missing_raises(self):
        import pytest
        with pytest.raises(AssertionError, match="timestamp missing"):
            parse_required_timestamp("")

    def test_none_raises(self):
        import pytest
        with pytest.raises(AssertionError, match="timestamp missing"):
            parse_required_timestamp(None)

    def test_invalid_string_raises(self):
        import pytest
        with pytest.raises(AssertionError, match="invalid timestamp"):
            parse_required_timestamp("not-a-timestamp")
