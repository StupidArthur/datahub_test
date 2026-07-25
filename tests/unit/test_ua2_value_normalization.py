from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.support.ua2_value_normalization import (
    assert_value_equal,
    normalize_boolean,
    normalize_datetime,
    normalize_float,
    normalize_int,
    normalize_int64_as_str,
    normalize_string,
)


class TestNormalizeBoolean:
    def test_true(self):
        assert normalize_boolean(True) is True
        assert normalize_boolean(1) is True
        assert normalize_boolean("true") is True
        assert normalize_boolean("True") is True
        assert normalize_boolean("1") is True

    def test_false(self):
        assert normalize_boolean(False) is False
        assert normalize_boolean(0) is False
        assert normalize_boolean("false") is False
        assert normalize_boolean("False") is False
        assert normalize_boolean("0") is False

    def test_rejects_nonempty_string(self):
        with pytest.raises(ValueError):
            normalize_boolean("false-ish")
        with pytest.raises(ValueError):
            normalize_boolean("yes")

    def test_assert_value_equal_boolean(self):
        assert_value_equal(True, True, 1)
        assert_value_equal("true", True, 1)
        assert_value_equal(False, 0, 1)
        with pytest.raises((ValueError, AssertionError)):
            assert_value_equal("yes", True, 1)


class TestNormalizeInt:
    def test_exact_int(self):
        assert normalize_int(42) == 42
        assert normalize_int(-7) == -7

    def test_int_from_float(self):
        assert normalize_int(3.0) == 3

    def test_rejects_bool(self):
        with pytest.raises(TypeError):
            normalize_int(True)

    def test_rejects_float_with_fraction(self):
        with pytest.raises(ValueError):
            normalize_int(3.14)

    def test_string(self):
        assert normalize_int("42") == 42
        assert normalize_int("-7") == -7

    def test_assert_value_equal(self):
        assert_value_equal(42, 42, 6)
        assert_value_equal("42", 42, 6)
        with pytest.raises((TypeError, AssertionError)):
            assert_value_equal(True, 1, 6)


class TestNormalizeInt64:
    def test_int(self):
        assert normalize_int64_as_str(42) == "42"
        assert normalize_int64_as_str(-7) == "-7"

    def test_large_value(self):
        assert normalize_int64_as_str(2**63 - 1) == str(2**63 - 1)
        assert normalize_int64_as_str(2**64 - 1) == str(2**64 - 1)

    def test_string(self):
        assert normalize_int64_as_str("42") == "42"
        assert normalize_int64_as_str("-7") == "-7"

    def test_rejects_float(self):
        with pytest.raises(TypeError):
            normalize_int64_as_str(42.0)

    def test_rejects_bool(self):
        with pytest.raises(TypeError):
            normalize_int64_as_str(True)

    def test_assert_value_equal_large(self):
        val = str(2**63 - 1)
        assert_value_equal(val, val, 8)
        assert_value_equal(int(val), val, 8)
        with pytest.raises(AssertionError):
            assert_value_equal("42", "43", 8)


class TestNormalizeFloat:
    def test_float(self):
        val = normalize_float(3.14)
        assert isinstance(val, float)

    def test_int(self):
        val = normalize_float(42)
        assert val == 42.0

    def test_rejects_bool(self):
        with pytest.raises(TypeError):
            normalize_float(True)

    def test_approx_float(self):
        assert_value_equal(3.14, 3.1400001, 10, abs_tol_float=1e-3)
        with pytest.raises(AssertionError):
            assert_value_equal(3.14, 3.15, 10, abs_tol_float=1e-3)


class TestNormalizeDouble:
    def test_approx_double(self):
        assert_value_equal(3.14, 3.1400000001, 11, abs_tol_double=1e-9)
        with pytest.raises(AssertionError):
            assert_value_equal(3.14, 3.15, 11, abs_tol_double=1e-9)


class TestNormalizeString:
    def test_string(self):
        assert normalize_string("hello") == "hello"

    def test_bytes(self):
        assert normalize_string(b"hello") == "hello"

    def test_exact(self):
        assert_value_equal("hello", "hello", 12)
        with pytest.raises(AssertionError):
            assert_value_equal("hello", " world ", 12)


class TestNormalizeDateTime:
    def test_utctime_to_datetime(self):
        """FILETIME 0 = 1601-01-01 00:00:00 UTC."""
        dt = normalize_datetime(0)
        assert dt == datetime(1601, 1, 1, tzinfo=timezone.utc)
        assert dt.tzinfo is not None

    def test_utctime_one_second(self):
        dt = normalize_datetime(10_000_000)
        assert dt == datetime(1601, 1, 1, 0, 0, 1, tzinfo=timezone.utc)

    def test_utctime_modern(self):
        """FILETIME 133827840000000000 ticks -> verified via epoch formula."""
        utc_val = 133_827_840_000_000_000
        dt = normalize_datetime(utc_val)
        assert dt.tzinfo == timezone.utc
        assert dt.year >= 2024  # verify it's a modern date

    def test_iso_string(self):
        dt = normalize_datetime("2025-06-15T10:30:00")
        assert dt.year == 2025
        assert dt.month == 6
        assert dt.day == 15
        assert dt.tzinfo == timezone.utc

    def test_naive_datetime(self):
        dt = normalize_datetime(datetime(2025, 6, 15, 10, 30, 0))
        assert dt.tzinfo == timezone.utc

    def test_aware_datetime(self):
        from datetime import timedelta
        dt = normalize_datetime(datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc))
        assert dt.tzinfo == timezone.utc

    def test_asyncua_string_format(self):
        raw = "DateTime{utcTime=133827840000000000, javaDate=Mon Jan 01 08:00:00 CST 2025}"
        dt = normalize_datetime(raw)
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2025

    def test_assert_value_equal_datetime(self):
        utc = 133_827_840_000_000_000
        dt = normalize_datetime(utc)
        assert_value_equal(utc, dt.isoformat(), 13)
        with pytest.raises(AssertionError):
            assert_value_equal(utc, "2024-01-01T00:00:00", 13)
