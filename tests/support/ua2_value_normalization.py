"""Type-specific value normalization for OPC UA default-read cases.

All normalizers accept raw values from DataHub (getRTValue, queryWithQuality)
and from asyncua direct OPC UA reads, and return a Python object suitable
for exact or approx comparison.

Normalization functions raise ``TypeError`` / ``ValueError`` on inputs that
do not match the target type's canonical form.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest


def normalize_boolean(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        if raw == 1:
            return True
        if raw == 0:
            return False
        raise ValueError(f"integer {raw} is not a valid boolean (only 0/1)")
    if isinstance(raw, str):
        lower = raw.strip().lower()
        if lower in ("true", "1"):
            return True
        if lower in ("false", "0"):
            return False
        raise ValueError(f"cannot parse boolean from {raw!r}")
    raise TypeError(f"unexpected boolean type: {type(raw).__name__} {raw!r}")


def normalize_int(raw: object) -> int:
    if isinstance(raw, bool):
        raise TypeError(f"boolean {raw!r} must not be accepted as integer")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        if raw != int(raw):
            raise ValueError(f"float with fractional part cannot be int: {raw}")
        return int(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw.lstrip("-").isdigit():
            raise ValueError(f"string is not a valid integer: {raw!r}")
        return int(raw)
    raise TypeError(f"unexpected int type: {type(raw).__name__} {raw!r}")


def normalize_int64_as_str(raw: object, *, unsigned: bool = False) -> str:
    """Normalize Int64/UInt64 values to decimal string for lossless comparison.

    When ``unsigned=True`` (UInt64), negative values are rejected.
    Leading zeros are stripped. Leading ``+`` is stripped.
    """
    if isinstance(raw, bool):
        raise TypeError(f"boolean {raw!r} must not be accepted as Int64")
    if isinstance(raw, int):
        if unsigned and raw < 0:
            raise ValueError(f"negative value {raw} not allowed for UInt64")
        return str(raw)
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            raise ValueError(f"not a valid integer string: {raw!r}")
        negative = raw[0] == "-"
        if raw[0] in "+-":
            raw = raw[1:]
        if negative and unsigned:
            raise ValueError(f"negative value {raw!r} not allowed for UInt64")
        if not raw.isdigit():
            raise ValueError(f"not a valid integer string: {raw!r}")
        digits = raw.lstrip("0") or "0"
        if negative:
            return "-" + digits
        return digits
    if isinstance(raw, float):
        raise TypeError("float must not be used for Int64/UInt64 normalization")
    raise TypeError(f"unexpected type for Int64/UInt64: {type(raw).__name__} {raw!r}")


def normalize_float(raw: object, abs_tol: float = 1e-6) -> float:
    """Normalize to float and return approx wrapper."""
    if isinstance(raw, bool):
        raise TypeError("boolean must not be accepted as float")
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        return float(raw.strip())
    raise TypeError(f"unexpected float type: {type(raw).__name__} {raw!r}")


def normalize_double(raw: object, abs_tol: float = 1e-12) -> float:
    return normalize_float(raw, abs_tol)


def normalize_string(raw: object) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="strict")
    raise TypeError(f"unexpected string type: {type(raw).__name__} {raw!r}")


def normalize_datetime(raw: object) -> datetime:
    """Normalize a DataHub RT value or asyncua value to a UTC datetime.

    Accepted input forms:
    - **int**: OPC UA FILETIME (100-ns intervals since 1601-01-01 UTC)
    - **str**: ISO-format datetime string or ``DateTime{utcTime=...}``
    - **datetime**: naive → assume UTC; aware → convert to UTC
    """
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    if isinstance(raw, float):
        raise TypeError(f"float {raw} must not be used for datetime normalization")
    if isinstance(raw, int):
        utc_ticks = raw
        seconds, remainder = divmod(utc_ticks, 10_000_000)
        return epoch + timedelta(seconds=seconds, microseconds=remainder // 10)
    if isinstance(raw, str):
        import re as _re
        m = _re.match(r"DateTime\{utcTime=(\d+)", raw)
        if m:
            utc_ticks = int(m.group(1))
            seconds, remainder = divmod(utc_ticks, 10_000_000)
            return epoch + timedelta(seconds=seconds, microseconds=remainder // 10)
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            raw = raw.replace(tzinfo=timezone.utc)
        return raw.astimezone(timezone.utc)
    raise TypeError(f"unexpected datetime type: {type(raw).__name__} {raw!r}")


def assert_value_equal(expected: object, actual: object, data_type: int, *, abs_tol_float: float = 1e-6, abs_tol_double: float = 1e-12) -> None:
    """Compare two values according to ``data_type`` after normalization."""
    _BOOL_TYPES = {1}
    _INT_TYPES = {2, 3, 4, 5, 6, 7}
    _INT64_TYPE = 8
    _UINT64_TYPE = 9
    _FLOAT_TYPES = {10}
    _DOUBLE_TYPES = {11}
    _STRING_TYPES = {12}
    _DATETIME_TYPES = {13}

    if data_type in _BOOL_TYPES:
        a = normalize_boolean(expected)
        b = normalize_boolean(actual)
        assert a == b, f"bool mismatch: {a} != {b}"
    elif data_type in _INT_TYPES:
        a = normalize_int(expected)
        b = normalize_int(actual)
        assert a == b, f"int mismatch: {a} != {b}"
    elif data_type == _INT64_TYPE:
        a = normalize_int64_as_str(expected)
        b = normalize_int64_as_str(actual)
        assert a == b, f"Int64 mismatch: {a} != {b}"
    elif data_type == _UINT64_TYPE:
        a = normalize_int64_as_str(expected, unsigned=True)
        b = normalize_int64_as_str(actual, unsigned=True)
        assert a == b, f"UInt64 mismatch: {a} != {b}"
    elif data_type in _FLOAT_TYPES:
        a = normalize_float(expected, abs_tol_float)
        b = normalize_float(actual, abs_tol_float)
        assert a == pytest.approx(b, abs=abs_tol_float), f"float mismatch: {a} != {b}"
    elif data_type in _DOUBLE_TYPES:
        a = normalize_double(expected, abs_tol_double)
        b = normalize_double(actual, abs_tol_double)
        assert a == pytest.approx(b, abs=abs_tol_double), f"double mismatch: {a} != {b}"
    elif data_type in _STRING_TYPES:
        a = normalize_string(expected)
        b = normalize_string(actual)
        assert a == b, f"string mismatch: {a!r} != {b!r}"
    elif data_type in _DATETIME_TYPES:
        a = normalize_datetime(expected)
        b = normalize_datetime(actual)
        assert a == b, f"datetime mismatch: {a} != {b}"
    else:
        raise ValueError(f"unknown data_type {data_type}")
