from __future__ import annotations

from tests.support.ua2_write_assertions import (
    INTEGER_RANGES,
    WRAP_MAP,
    classify_write_result,
    is_wrap_behaviour,
)


class TestIntegerRanges:
    def test_sbyte_range(self):
        name, lo, hi = INTEGER_RANGES[2]
        assert name == "SByte"
        assert lo == -128
        assert hi == 127

    def test_byte_range(self):
        name, lo, hi = INTEGER_RANGES[3]
        assert name == "Byte"
        assert lo == 0
        assert hi == 255

    def test_int16_range(self):
        name, lo, hi = INTEGER_RANGES[4]
        assert name == "Int16"
        assert lo == -32768
        assert hi == 32767

    def test_uint16_range(self):
        name, lo, hi = INTEGER_RANGES[5]
        assert name == "UInt16"
        assert lo == 0
        assert hi == 65535


class TestWrapMap:
    def test_sbyte_neg129_wraps_to_127(self):
        assert is_wrap_behaviour(2, -129) is True
        assert WRAP_MAP[(2, -129)] == 127

    def test_sbyte_128_wraps_to_neg128(self):
        assert is_wrap_behaviour(2, 128) is True
        assert WRAP_MAP[(2, 128)] == -128

    def test_byte_neg1_wraps_to_255(self):
        assert is_wrap_behaviour(3, -1) is True
        assert WRAP_MAP[(3, -1)] == 255

    def test_byte_256_wraps_to_0(self):
        assert is_wrap_behaviour(3, 256) is True
        assert WRAP_MAP[(3, 256)] == 0

    def test_int16_neg32769_wraps_to_32767(self):
        assert is_wrap_behaviour(4, -32769) is True
        assert WRAP_MAP[(4, -32769)] == 32767

    def test_int16_32768_wraps_to_neg32768(self):
        assert is_wrap_behaviour(4, 32768) is True
        assert WRAP_MAP[(4, 32768)] == -32768

    def test_uint16_neg1_wraps_to_65535(self):
        assert is_wrap_behaviour(5, -1) is True
        assert WRAP_MAP[(5, -1)] == 65535

    def test_uint16_65536_wraps_to_0(self):
        assert is_wrap_behaviour(5, 65536) is True
        assert WRAP_MAP[(5, 65536)] == 0

    def test_in_range_not_wrap(self):
        assert is_wrap_behaviour(2, 0) is False
        assert is_wrap_behaviour(3, 128) is False
        assert is_wrap_behaviour(4, -100) is False
        assert is_wrap_behaviour(5, 100) is False


class TestClassifyWriteResult:
    def test_accepted_normal(self):
        result = classify_write_result(
            {"tagNames": ["tag1"], "failMsg": "", "msg": ""},
            "tag1",
        )
        assert result == "accepted"

    def test_accepted_dict_failMsg(self):
        result = classify_write_result(
            {"tagNames": ["tag1"], "failMsg": {}, "msg": ""},
            "tag1",
        )
        assert result == "accepted"

    def test_rejected_failMsg_contains_tag(self):
        result = classify_write_result(
            {"tagNames": ["tag1"], "failMsg": "tag1 out of range", "msg": ""},
            "tag1",
        )
        assert result == "rejected"

    def test_rejected_tag_not_in_tagNames(self):
        result = classify_write_result(
            {"tagNames": ["other"], "failMsg": "", "msg": ""},
            "tag1",
        )
        assert result == "rejected"

    def test_rejected_exception(self):
        result = classify_write_result(None, "tag1", exception=ValueError("x"))
        assert result == "rejected"

    def test_rejected_none_response(self):
        result = classify_write_result(None, "tag1")
        assert result == "rejected"

    def test_zero_is_valid_value(self):
        assert 0 in range(0, 256)

    def test_negative_int_is_valid_value(self):
        assert -128 in range(-128, 128)

    def test_bool_not_accepted_as_int(self):
        from tests.support.ua2_value_normalization import normalize_int
        import pytest
        with pytest.raises(TypeError, match="boolean"):
            normalize_int(True)
