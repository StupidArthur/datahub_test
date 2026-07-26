from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from asyncua import ua
import pytest

from tests.support.ua2_write_assertions import (
    INTEGER_RANGES,
    WRAP_MAP,
    _check_stable,
    classify_outcome_value,
    classify_write_result,
    expected_wrap_value,
    is_wrap_behaviour,
    normalize_integer_decimal,
    observe_integer_decimal_rejection,
    strict_restore_source_and_cleanup,
    wait_accepted_integer_decimal_outcome,
    wait_accepted_integer_outcome,
    wait_three_way_integer_decimal_sync,
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
        assert expected_wrap_value(2, -129) == 127

    def test_sbyte_128_wraps_to_neg128(self):
        assert is_wrap_behaviour(2, 128) is True
        assert expected_wrap_value(2, 128) == -128

    def test_byte_neg1_wraps_to_255(self):
        assert is_wrap_behaviour(3, -1) is True
        assert expected_wrap_value(3, -1) == 255

    def test_byte_256_wraps_to_0(self):
        assert is_wrap_behaviour(3, 256) is True
        assert expected_wrap_value(3, 256) == 0

    def test_int16_neg32769_wraps_to_32767(self):
        assert is_wrap_behaviour(4, -32769) is True
        assert expected_wrap_value(4, -32769) == 32767

    def test_int16_32768_wraps_to_neg32768(self):
        assert is_wrap_behaviour(4, 32768) is True
        assert expected_wrap_value(4, 32768) == -32768

    def test_uint16_neg1_wraps_to_65535(self):
        assert is_wrap_behaviour(5, -1) is True
        assert expected_wrap_value(5, -1) == 65535

    def test_uint16_65536_wraps_to_0(self):
        assert is_wrap_behaviour(5, 65536) is True
        assert expected_wrap_value(5, 65536) == 0

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


class TestClassifyOutcomeValue:
    def test_kept_original(self):
        assert classify_outcome_value(2, 7, 7) == "kept_original"

    def test_clamped_min(self):
        assert classify_outcome_value(3, 0, 7) == "clamped"

    def test_clamped_max(self):
        assert classify_outcome_value(3, 255, 7) == "clamped"

    def test_converted_byte(self):
        assert classify_outcome_value(3, 100, 7) == "converted"

    def test_converted_sbyte(self):
        assert classify_outcome_value(2, 50, 7) == "converted"

    def test_out_of_range(self):
        assert classify_outcome_value(3, 300, 7) == "out_of_range"

    def test_out_of_range_negative(self):
        assert classify_outcome_value(3, -5, 7) == "out_of_range"

    def test_sbyte_clamped_min(self):
        assert classify_outcome_value(2, -128, 7) == "clamped"

    def test_sbyte_clamped_max(self):
        assert classify_outcome_value(2, 127, 7) == "clamped"

    def test_int16_clamped_min(self):
        assert classify_outcome_value(4, -32768, 123) == "clamped"

    def test_int16_clamped_max(self):
        assert classify_outcome_value(4, 32767, 123) == "clamped"

    def test_uint16_kept(self):
        assert classify_outcome_value(5, 123, 123) == "kept_original"

    def test_int32_range(self):
        name, lo, hi = INTEGER_RANGES[6]
        assert name == "Int32"
        assert lo == -2147483648
        assert hi == 2147483647

    def test_uint32_range(self):
        name, lo, hi = INTEGER_RANGES[7]
        assert name == "UInt32"
        assert lo == 0
        assert hi == 4294967295

    def test_int32_neg2147483649_wraps_to_2147483647(self):
        assert is_wrap_behaviour(6, -2147483649) is True
        assert expected_wrap_value(6, -2147483649) == 2147483647

    def test_int32_2147483648_wraps_to_neg2147483648(self):
        assert is_wrap_behaviour(6, 2147483648) is True
        assert expected_wrap_value(6, 2147483648) == -2147483648

    def test_uint32_neg1_wraps_to_4294967295(self):
        assert is_wrap_behaviour(7, -1) is True
        assert expected_wrap_value(7, -1) == 4294967295

    def test_uint32_4294967296_wraps_to_0(self):
        assert is_wrap_behaviour(7, 4294967296) is True
        assert expected_wrap_value(7, 4294967296) == 0

    def test_uint32_max_is_valid_int(self):
        """4294967295 is a valid Python int, not a float or str."""
        val = 4294967295
        assert isinstance(val, int)
        assert not isinstance(val, bool)
        assert val > 0

    def test_uint32_neg1_is_out_of_range(self):
        assert classify_outcome_value(7, -1, 123456) == "out_of_range"

    def test_uint32_4294967296_is_out_of_range(self):
        assert classify_outcome_value(7, 4294967296, 123456) == "out_of_range"

    def test_int32_clamped_min(self):
        assert classify_outcome_value(6, -2147483648, 123456) == "clamped"

    def test_int32_clamped_max(self):
        assert classify_outcome_value(6, 2147483647, 123456) == "clamped"

    def test_uint32_clamped_min(self):
        assert classify_outcome_value(7, 0, 123456) == "clamped"

    def test_uint32_clamped_max(self):
        assert classify_outcome_value(7, 4294967295, 123456) == "clamped"

    def test_int32_kept_original(self):
        assert classify_outcome_value(6, 123456, 123456) == "kept_original"

    def test_uint32_kept_original(self):
        assert classify_outcome_value(7, 123456, 123456) == "kept_original"

    def test_int32_converted(self):
        assert classify_outcome_value(6, 100000, 123456) == "converted"

    def test_uint32_converted(self):
        assert classify_outcome_value(7, 999999, 123456) == "converted"


class TestClassifyOutcomeExtended:
    def test_sbyte_wrap_127_is_clamped(self):
        """SByte -129 wraps to 127, which equals max → clamped, not out_of_range."""
        assert classify_outcome_value(2, 127, 7) == "clamped"

    def test_sbyte_wrap_128_is_clamped(self):
        """SByte 128 wraps to -128, which equals min → clamped."""
        assert classify_outcome_value(2, -128, 7) == "clamped"

    def test_byte_wrap_255_is_clamped(self):
        """Byte -1 wraps to 255, which equals max → clamped."""
        assert classify_outcome_value(3, 255, 7) == "clamped"

    def test_byte_wrap_0_is_clamped(self):
        """Byte 256 wraps to 0, which equals min → clamped."""
        assert classify_outcome_value(3, 0, 7) == "clamped"

    def test_int16_wrap_32767_is_clamped(self):
        assert classify_outcome_value(4, 32767, 123) == "clamped"

    def test_int16_wrap_neg32768_is_clamped(self):
        assert classify_outcome_value(4, -32768, 123) == "clamped"

    def test_uint16_wrap_65535_is_clamped(self):
        assert classify_outcome_value(5, 65535, 123) == "clamped"

    def test_uint16_wrap_0_is_clamped(self):
        assert classify_outcome_value(5, 0, 123) == "clamped"

    def test_int32_wrap_2147483647_is_clamped(self):
        assert classify_outcome_value(6, 2147483647, 123456) == "clamped"

    def test_int32_wrap_neg2147483648_is_clamped(self):
        assert classify_outcome_value(6, -2147483648, 123456) == "clamped"

    def test_uint32_wrap_4294967295_is_clamped(self):
        assert classify_outcome_value(7, 4294967295, 123456) == "clamped"

    def test_uint32_wrap_0_is_clamped(self):
        assert classify_outcome_value(7, 0, 123456) == "clamped"

    def test_out_of_range_above_uint16(self):
        assert classify_outcome_value(5, 70000, 123) == "out_of_range"

    def test_out_of_range_below_sbyte(self):
        assert classify_outcome_value(2, -200, 7) == "out_of_range"


class TestCheckStable:
    def _make_sample(self, source, vt_name, rv, qv, quality=192,
                     tag_time="2025-01-01T00:00:00Z", ds_alive=True, mocker_alive=True):
        return {
            "source": source,
            "variant_type": vt_name,
            "rt": {
                "tagValue": rv,
                "quality": quality,
                "tagTime": tag_time,
            },
            "qwq": {
                "tagValue": qv,
                "quality": quality,
                "tagTime": tag_time,
            },
            "datasource_alive": ds_alive,
            "mocker_alive": mocker_alive,
        }

    def test_all_stable(self):
        samples = [self._make_sample(7, "SByte", 7, 7) for _ in range(3)]
        result = _check_stable(samples, 7, 2, "SByte")
        assert result["stable"] is True
        assert result["issues"] == []

    def test_source_changed(self):
        samples = [self._make_sample(8, "SByte", 7, 7)]
        result = _check_stable(samples, 7, 2, "SByte")
        assert result["stable"] is False
        assert any("source" in i.lower() or "value" in i.lower() for i in result["issues"])

    def test_variant_type_changed(self):
        samples = [self._make_sample(7, "Int16", 7, 7)]
        result = _check_stable(samples, 7, 2, "SByte")
        assert result["stable"] is False
        assert any("variant_type" in i for i in result["issues"])

    def test_datasource_offline(self):
        samples = [self._make_sample(7, "SByte", 7, 7, ds_alive=False)]
        result = _check_stable(samples, 7, 2, "SByte")
        assert result["stable"] is False
        assert any("datasource" in i.lower() for i in result["issues"])

    def test_mocker_exited(self):
        samples = [self._make_sample(7, "SByte", 7, 7, mocker_alive=False)]
        result = _check_stable(samples, 7, 2, "SByte")
        assert result["stable"] is False
        assert any("mocker" in i.lower() for i in result["issues"])

    def test_quality_missing(self):
        samples = [self._make_sample(7, "SByte", 7, 7, quality=0)]
        result = _check_stable(samples, 7, 2, "SByte")
        assert result["stable"] is False
        assert any("quality" in i.lower() for i in result["issues"])

    def test_tagtime_missing(self):
        samples = [self._make_sample(7, "SByte", 7, 7, tag_time="")]
        result = _check_stable(samples, 7, 2, "SByte")
        assert result["stable"] is False
        assert any("tagtime" in i.lower() or "tagTime" in i for i in result["issues"])

    def test_rt_value_missing(self):
        samples = [{
            "source": 7,
            "variant_type": "SByte",
            "rt": {},
            "qwq": {"tagValue": 7, "quality": 192, "tagTime": "2025-01-01T00:00:00Z"},
            "datasource_alive": True,
            "mocker_alive": True,
        }]
        result = _check_stable(samples, 7, 2, "SByte")
        assert result["stable"] is False
        assert any("RT" in i for i in result["issues"])

    def test_qwq_value_missing(self):
        samples = [{
            "source": 7,
            "variant_type": "SByte",
            "rt": {"tagValue": 7, "quality": 192, "tagTime": "2025-01-01T00:00:00Z"},
            "qwq": {},
            "datasource_alive": True,
            "mocker_alive": True,
        }]
        result = _check_stable(samples, 7, 2, "SByte")
        assert result["stable"] is False
        assert any("QwQ" in i for i in result["issues"])


class TestWaitAcceptedIntegerOutcome:
    """Mock-based tests for wait_accepted_integer_outcome."""

    @pytest.fixture
    def mock_mocker(self):
        m = Mock()
        m.process.poll.return_value = None
        return m

    @pytest.fixture
    def mock_api(self):
        return Mock()

    def _make_trio(self, source, vt, rv, qv, quality=192,
                   tag_time="2025-01-01T00:00:00Z", ds_alive=True):
        return {
            "source": source,
            "variant_type": vt,
            "rt": {"tagValue": rv, "quality": quality, "tagTime": tag_time},
            "qwq": {"tagValue": qv, "quality": quality, "tagTime": tag_time},
            "datasource_alive": ds_alive,
        }

    def test_accepted_does_not_require_input_equal(self, mock_api, mock_mocker):
        """accepted 越界输入不要求最终值等于输入."""
        trio_data = self._make_trio(100, ua.VariantType.UInt16, 100, 100)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            result = wait_accepted_integer_outcome(
                mock_api, endpoint="x", node_name="y", namespace_index=1,
                ds_id=1, tag_name="t", data_type=5,
                expected_variant_type=ua.VariantType.UInt16,
                mocker=mock_mocker, timeout=5.0, interval=0.1,
            )
        assert result["source"] == 100
        assert result["datasource_alive"] is True
        assert result["mocker_alive"] is True

    def test_accepted_gets_clamped_min(self, mock_api, mock_mocker):
        """accepted + clamped output stays at min."""
        trio_data = self._make_trio(0, ua.VariantType.Byte, 0, 0)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            result = wait_accepted_integer_outcome(
                mock_api, endpoint="x", node_name="y", namespace_index=1,
                ds_id=1, tag_name="t", data_type=3,
                expected_variant_type=ua.VariantType.Byte,
                mocker=mock_mocker, timeout=5.0, interval=0.1,
            )
        assert result["source"] == 0  # min for Byte

    def test_accepted_gets_clamped_max(self, mock_api, mock_mocker):
        """accepted + clamped output stays at max."""
        trio_data = self._make_trio(255, ua.VariantType.Byte, 255, 255)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            result = wait_accepted_integer_outcome(
                mock_api, endpoint="x", node_name="y", namespace_index=1,
                ds_id=1, tag_name="t", data_type=3,
                expected_variant_type=ua.VariantType.Byte,
                mocker=mock_mocker, timeout=5.0, interval=0.1,
            )
        assert result["source"] == 255  # max for Byte

    def test_accepted_get_converted(self, mock_api, mock_mocker):
        """accepted + in-range output (not min/max/baseline) → converted."""
        trio_data = self._make_trio(100, ua.VariantType.Byte, 100, 100)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            result = wait_accepted_integer_outcome(
                mock_api, endpoint="x", node_name="y", namespace_index=1,
                ds_id=1, tag_name="t", data_type=3,
                expected_variant_type=ua.VariantType.Byte,
                mocker=mock_mocker, timeout=5.0, interval=0.1,
            )
        assert result["source"] == 100

    def test_source_bool_raises_immediately(self, mock_api, mock_mocker):
        """source is bool → immediate failure."""
        trio_data = self._make_trio(True, ua.VariantType.Boolean, 0, 0)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            with pytest.raises(AssertionError, match="bool"):
                wait_accepted_integer_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=2,
                    expected_variant_type=ua.VariantType.SByte,
                    mocker=mock_mocker, timeout=5.0, interval=0.1,
                )

    def test_variant_type_mismatch_raises_immediately(self, mock_api, mock_mocker):
        """VariantType mismatch → immediate failure."""
        trio_data = self._make_trio(7, ua.VariantType.Int16, 7, 7)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            with pytest.raises(AssertionError, match="VariantType mismatch"):
                wait_accepted_integer_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=2,
                    expected_variant_type=ua.VariantType.SByte,
                    mocker=mock_mocker, timeout=5.0, interval=0.1,
                )

    def test_mocker_exited_raises_immediately(self, mock_api):
        """mocker exited → immediate failure."""
        dead_mocker = Mock()
        dead_mocker.process.poll.return_value = 1  # non-None = exited
        with pytest.raises(AssertionError, match="mocker exited"):
            wait_accepted_integer_outcome(
                mock_api, endpoint="x", node_name="y", namespace_index=1,
                ds_id=1, tag_name="t", data_type=2,
                expected_variant_type=ua.VariantType.SByte,
                mocker=dead_mocker, timeout=5.0, interval=0.1,
            )

    def test_datasource_offline_continues_then_timeout(self, mock_api, mock_mocker):
        """datasource offline → samples collected but never stable."""
        trio_data = self._make_trio(7, ua.VariantType.SByte, 7, 7, ds_alive=False)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            with pytest.raises(AssertionError, match="timeout"):
                wait_accepted_integer_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=2,
                    expected_variant_type=ua.VariantType.SByte,
                    mocker=mock_mocker, timeout=1.0, interval=0.1,
                )

    def test_not_enough_stable_samples(self, mock_api, mock_mocker):
        """fluctuating values → never stable."""
        data = [
            self._make_trio(10, ua.VariantType.SByte, 10, 10),
            self._make_trio(20, ua.VariantType.SByte, 20, 20),
        ]
        idx = [0]
        def _alternating(*_a, **_kw):
            result = data[idx[0] % 2]
            idx[0] += 1
            return result

        with patch("tests.support.ua2_write_assertions._sample_trio", side_effect=_alternating):
            with pytest.raises(AssertionError, match="timeout"):
                wait_accepted_integer_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=2,
                    expected_variant_type=ua.VariantType.SByte,
                    mocker=mock_mocker, timeout=1.0, interval=0.1,
                )

    def test_stable_samples_accumulation(self, mock_api, mock_mocker):
        """2 consecutive identical samples → success."""
        trio_data = self._make_trio(100, ua.VariantType.UInt16, 100, 100)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            result = wait_accepted_integer_outcome(
                mock_api, endpoint="x", node_name="y", namespace_index=1,
                ds_id=1, tag_name="t", data_type=5,
                expected_variant_type=ua.VariantType.UInt16,
                mocker=mock_mocker, timeout=5.0, interval=0.1,
                stable_samples=3,
            )
        assert result["source"] == 100
        assert len(result["samples"]) >= 3


class TestNormalizeInt:
    def test_zero_is_valid_value(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(0) == 0

    def test_negative_int_is_valid_value(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(-128) == -128

    def test_bool_not_accepted_as_int(self):
        from tests.support.ua2_value_normalization import normalize_int
        import pytest
        with pytest.raises(TypeError, match="boolean"):
            normalize_int(True)

    def test_large_positive_int(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(65535) == 65535

    def test_large_negative_int(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(-32768) == -32768

    def test_int32_min(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(-2147483648) == -2147483648

    def test_int32_max(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(2147483647) == 2147483647

    def test_uint32_max(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(4294967295) == 4294967295

    def test_bool_rejected_as_int32(self):
        from tests.support.ua2_value_normalization import normalize_int
        with pytest.raises(TypeError, match="boolean"):
            normalize_int(True)


class TestInt64Ranges:
    def test_int64_range_exists(self):
        name, lo, hi = INTEGER_RANGES[8]
        assert name == "Int64"
        assert lo == -9223372036854775808
        assert hi == 9223372036854775807

    def test_int64_range_type(self):
        name, lo, hi = INTEGER_RANGES[8]
        assert isinstance(lo, int)
        assert isinstance(hi, int)
        assert not isinstance(lo, bool)
        assert not isinstance(hi, bool)

    def test_int64_wrap_neg_boundary(self):
        assert is_wrap_behaviour(8, -9223372036854775809) is True
        assert expected_wrap_value(8, -9223372036854775809) == 9223372036854775807

    def test_int64_wrap_pos_boundary(self):
        assert is_wrap_behaviour(8, 9223372036854775808) is True
        assert expected_wrap_value(8, 9223372036854775808) == -9223372036854775808

    def test_int64_in_range_not_wrap(self):
        assert is_wrap_behaviour(8, 0) is False
        assert is_wrap_behaviour(8, -9223372036854775808) is False
        assert is_wrap_behaviour(8, 9223372036854775807) is False
        assert is_wrap_behaviour(8, 123456) is False

    def test_int64_min_classified_as_clamped(self):
        assert classify_outcome_value(8, -9223372036854775808, 123456) == "clamped"

    def test_int64_max_classified_as_clamped(self):
        assert classify_outcome_value(8, 9223372036854775807, 123456) == "clamped"

    def test_int64_kept_original(self):
        assert classify_outcome_value(8, 123456, 123456) == "kept_original"

    def test_int64_converted(self):
        assert classify_outcome_value(8, 9999999999, 123456) == "converted"

    def test_int64_oor_neg(self):
        assert classify_outcome_value(8, -9223372036854775809, 123456) == "out_of_range"

    def test_int64_oor_pos(self):
        assert classify_outcome_value(8, 9223372036854775808, 123456) == "out_of_range"

    def test_int64_wrap_neg_is_clamped(self):
        assert classify_outcome_value(8, 9223372036854775807, 123456) == "clamped"

    def test_int64_wrap_pos_is_clamped(self):
        assert classify_outcome_value(8, -9223372036854775808, 123456) == "clamped"


class TestNormalizeIntegerDecimal:
    def test_int_from_int(self):
        assert normalize_integer_decimal(0, 8) == "0"
        assert normalize_integer_decimal(123, 8) == "123"
        assert normalize_integer_decimal(-123, 8) == "-123"

    def test_int64_min_max_int(self):
        assert normalize_integer_decimal(-9223372036854775808, 8) == "-9223372036854775808"
        assert normalize_integer_decimal(9223372036854775807, 8) == "9223372036854775807"

    def test_string_with_leading_zeros(self):
        assert normalize_integer_decimal("000123", 8) == "123"
        assert normalize_integer_decimal("-000123", 8) == "-123"

    def test_string_with_plus_sign(self):
        assert normalize_integer_decimal("+123", 8) == "123"

    def test_zero_and_neg_zero(self):
        assert normalize_integer_decimal(0, 8) == "0"
        assert normalize_integer_decimal(-0, 8) == "0"

    def test_large_decimal_string(self):
        assert normalize_integer_decimal("9223372036854775807", 8) == "9223372036854775807"
        assert normalize_integer_decimal("-9223372036854775808", 8) == "-9223372036854775808"

    def test_oor_string(self):
        assert normalize_integer_decimal("9223372036854775808", 8) == "9223372036854775808"
        assert normalize_integer_decimal("-9223372036854775809", 8) == "-9223372036854775809"

    def test_bool_rejected(self):
        with pytest.raises(TypeError, match="boolean"):
            normalize_integer_decimal(True, 8)

    def test_float_rejected(self):
        with pytest.raises(TypeError, match="float"):
            normalize_integer_decimal(1.5, 8)
        with pytest.raises(TypeError, match="float"):
            normalize_integer_decimal(9223372036854775808.0, 8)

    def test_data_type_2_uses_normalize_int(self):
        assert normalize_integer_decimal(127, 2) == "127"
        assert normalize_integer_decimal(-128, 2) == "-128"

    def test_data_type_7_passthrough(self):
        assert normalize_integer_decimal(4294967295, 7) == "4294967295"

    def test_unsupported_data_type(self):
        with pytest.raises(ValueError, match="unsupported"):
            normalize_integer_decimal(0, 99)

    def test_js_safe_value_from_int(self):
        assert normalize_integer_decimal(9999999999, 8) == "9999999999"

    def test_js_safe_value_from_string(self):
        assert normalize_integer_decimal("9999999999", 8) == "9999999999"

    def test_oor_oob_strings(self):
        s = "9223372036854775808"
        assert normalize_integer_decimal(s, 8) == s
        s = "-9223372036854775809"
        assert normalize_integer_decimal(s, 8) == s


class TestNormalizeIntegerDecimalVariantTypes:
    def test_sbyte_via_normalize_int(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(-128) == -128
        assert normalize_int(127) == 127

    def test_byte_via_normalize_int(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(0) == 0
        assert normalize_int(255) == 255

    def test_int16_via_normalize_int(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(-32768) == -32768
        assert normalize_int(32767) == 32767

    def test_uint16_via_normalize_int(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(0) == 0
        assert normalize_int(65535) == 65535

    def test_normalize_int_preserves_large_python_int(self):
        from tests.support.ua2_value_normalization import normalize_int
        assert normalize_int(9999999999) == 9999999999
        assert normalize_int(-9999999999) == -9999999999


class TestNoFloatPaths:
    def test_int64_minus_1_no_float(self):
        s = "-9223372036854775809"
        v = int(s)
        assert isinstance(v, int)
        assert not isinstance(v, float)
        assert v == -9223372036854775809

    def test_int64_plus_1_no_float(self):
        s = "9223372036854775808"
        v = int(s)
        assert isinstance(v, int)
        assert not isinstance(v, float)
        assert v == 9223372036854775808

    def test_wrap_map_hit_no_float(self):
        assert is_wrap_behaviour(8, -9223372036854775809) is True
        assert is_wrap_behaviour(8, 9223372036854775808) is True

    def test_wrap_map_no_int_overflow(self):
        v = -9223372036854775809
        assert isinstance(v, int) and not isinstance(v, float)
        assert expected_wrap_value(8, v) == 9223372036854775807
        v2 = 9223372036854775808
        assert isinstance(v2, int) and not isinstance(v2, float)
        assert expected_wrap_value(8, v2) == -9223372036854775808

    def test_input_python_type_is_str(self):
        s = "-9223372036854775809"
        assert type(s).__name__ == "str"


class TestWaitAcceptedIntegerDecimalOutcome:
    @pytest.fixture
    def mock_mocker(self):
        m = Mock()
        m.process.poll.return_value = None
        return m

    @pytest.fixture
    def mock_api(self):
        return Mock()

    def _make_trio_no_float(self, source, vt, rv, qv, quality=192,
                            tag_time="2025-01-01T00:00:00Z", ds_alive=True):
        return {
            "source": source,
            "variant_type": vt,
            "rt": {"tagValue": rv, "quality": quality, "tagTime": tag_time},
            "qwq": {"tagValue": qv, "quality": quality, "tagTime": tag_time},
            "datasource_alive": ds_alive,
        }

    def test_source_float_raises_immediately(self, mock_api, mock_mocker):
        trio_data = self._make_trio_no_float(1.5, ua.VariantType.Int64, 1, 1)
        from tests.support.ua2_write_assertions import _sample_trio
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            with pytest.raises(AssertionError, match="float"):
                wait_accepted_integer_decimal_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=8,
                    expected_variant_type=ua.VariantType.Int64,
                    mocker=mock_mocker, timeout=1.0, interval=0.1,
                )

    def test_rt_float_raises_immediately(self, mock_api, mock_mocker):
        trio_data = self._make_trio_no_float(100, ua.VariantType.Int64, 1.5, 100)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            with pytest.raises(AssertionError, match="float"):
                wait_accepted_integer_decimal_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=8,
                    expected_variant_type=ua.VariantType.Int64,
                    mocker=mock_mocker, timeout=1.0, interval=0.1,
                )

    def test_qwq_float_raises_immediately(self, mock_api, mock_mocker):
        trio_data = self._make_trio_no_float(100, ua.VariantType.Int64, 100, 1.5)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            with pytest.raises(AssertionError, match="float"):
                wait_accepted_integer_decimal_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=8,
                    expected_variant_type=ua.VariantType.Int64,
                    mocker=mock_mocker, timeout=1.0, interval=0.1,
                )

    def test_source_bool_raises_immediately(self, mock_api, mock_mocker):
        trio_data = self._make_trio_no_float(True, ua.VariantType.Boolean, 0, 0)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            with pytest.raises(AssertionError, match="bool"):
                wait_accepted_integer_decimal_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=8,
                    expected_variant_type=ua.VariantType.Int64,
                    mocker=mock_mocker, timeout=1.0, interval=0.1,
                )

    def test_vt_mismatch_raises_immediately(self, mock_api, mock_mocker):
        trio_data = self._make_trio_no_float(100, ua.VariantType.Int32, 100, 100)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            with pytest.raises(AssertionError, match="VariantType mismatch"):
                wait_accepted_integer_decimal_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=8,
                    expected_variant_type=ua.VariantType.Int64,
                    mocker=mock_mocker, timeout=1.0, interval=0.1,
                )

    def test_stable_two_samples_success(self, mock_api, mock_mocker):
        trio_data = self._make_trio_no_float(100, ua.VariantType.Int64, 100, 100)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            result = wait_accepted_integer_decimal_outcome(
                mock_api, endpoint="x", node_name="y", namespace_index=1,
                ds_id=1, tag_name="t", data_type=8,
                expected_variant_type=ua.VariantType.Int64,
                mocker=mock_mocker, timeout=5.0, interval=0.1,
            )
        assert result["source_decimal"] == "100"
        assert result["rt_decimal"] == "100"
        assert result["qwq_decimal"] == "100"

    def test_mocker_exit_raises(self, mock_api):
        dead = Mock()
        dead.process.poll.return_value = 1
        with pytest.raises(AssertionError, match="mocker exited"):
            wait_accepted_integer_decimal_outcome(
                mock_api, endpoint="x", node_name="y", namespace_index=1,
                ds_id=1, tag_name="t", data_type=8,
                expected_variant_type=ua.VariantType.Int64,
                mocker=dead, timeout=1.0, interval=0.1,
            )

    def test_datasource_offline_then_timeout(self, mock_api, mock_mocker):
        trio_data = self._make_trio_no_float(100, ua.VariantType.Int64, 100, 100, ds_alive=False)
        with patch("tests.support.ua2_write_assertions._sample_trio", return_value=trio_data):
            with pytest.raises(AssertionError, match="timeout"):
                wait_accepted_integer_decimal_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=8,
                    expected_variant_type=ua.VariantType.Int64,
                    mocker=mock_mocker, timeout=1.0, interval=0.1,
                )

    def test_not_enough_stable_samples(self, mock_api, mock_mocker):
        data = [
            self._make_trio_no_float(10, ua.VariantType.Int64, 10, 10),
            self._make_trio_no_float(20, ua.VariantType.Int64, 20, 20),
        ]
        idx = [0]
        def _alt(*_a, **_kw):
            r = data[idx[0] % 2]
            idx[0] += 1
            return r
        with patch("tests.support.ua2_write_assertions._sample_trio", side_effect=_alt):
            with pytest.raises(AssertionError, match="timeout"):
                wait_accepted_integer_decimal_outcome(
                    mock_api, endpoint="x", node_name="y", namespace_index=1,
                    ds_id=1, tag_name="t", data_type=8,
                    expected_variant_type=ua.VariantType.Int64,
                    mocker=mock_mocker, timeout=1.0, interval=0.1,
                )


class TestObserveIntegerDecimalRejection:
    @pytest.fixture
    def mock_mocker(self):
        m = Mock()
        m.process.poll.return_value = None
        return m

    @pytest.fixture
    def mock_api(self):
        api = Mock()
        api.get_rt_value = Mock(return_value=[])
        return api

    def test_float_in_source_raises(self, mock_api, mock_mocker):
        from tests.support.ua2_write_assertions import (
            opcua_read_sync, opcua_read_variant_type_sync,
        )
        with patch("tests.support.ua2_write_assertions.opcua_read_sync", return_value=1.5):
            with patch("tests.support.ua2_write_assertions.opcua_read_variant_type_sync",
                       return_value=(1.5, ua.VariantType.Int64)):
                with pytest.raises(AssertionError, match="float"):
                    observe_integer_decimal_rejection(
                        mock_api, endpoint="x", node_name="y", namespace_index=1,
                        ds_id=1, tag_name="t", data_type=8,
                        baseline_decimal="123456",
                        expected_variant_type=ua.VariantType.Int64,
                        mocker=mock_mocker, timeout=1.0, interval=0.1,
                    )

    def test_source_changed_raises(self, mock_api, mock_mocker):
        with patch("tests.support.ua2_write_assertions.opcua_read_sync", return_value=999):
            with patch("tests.support.ua2_write_assertions.opcua_read_variant_type_sync",
                       return_value=(999, ua.VariantType.Int64)):
                with pytest.raises(AssertionError, match="source changed"):
                    observe_integer_decimal_rejection(
                        mock_api, endpoint="x", node_name="y", namespace_index=1,
                        ds_id=1, tag_name="t", data_type=8,
                        baseline_decimal="123456",
                        expected_variant_type=ua.VariantType.Int64,
                        mocker=mock_mocker, timeout=1.0, interval=0.1,
                    )

    def test_vt_changed_raises(self, mock_api, mock_mocker):
        with patch("tests.support.ua2_write_assertions.opcua_read_sync", return_value=123456):
            with patch("tests.support.ua2_write_assertions.opcua_read_variant_type_sync",
                       return_value=(123456, ua.VariantType.Int32)):
                with pytest.raises(AssertionError, match="VariantType"):
                    observe_integer_decimal_rejection(
                        mock_api, endpoint="x", node_name="y", namespace_index=1,
                        ds_id=1, tag_name="t", data_type=8,
                        baseline_decimal="123456",
                        expected_variant_type=ua.VariantType.Int64,
                        mocker=mock_mocker, timeout=1.0, interval=0.1,
                    )

    def test_bool_source_raises(self, mock_api, mock_mocker):
        with patch("tests.support.ua2_write_assertions.opcua_read_sync", return_value=True):
            with patch("tests.support.ua2_write_assertions.opcua_read_variant_type_sync",
                       return_value=(True, ua.VariantType.Boolean)):
                with pytest.raises(AssertionError, match="bool"):
                    observe_integer_decimal_rejection(
                        mock_api, endpoint="x", node_name="y", namespace_index=1,
                        ds_id=1, tag_name="t", data_type=8,
                        baseline_decimal="123456",
                        expected_variant_type=ua.VariantType.Int64,
                        mocker=mock_mocker, timeout=1.0, interval=0.1,
                    )


class TestStrictRestoreSourceAndCleanup:
    def test_restore_failure_still_cleans_up(self):
        """恢复失败后仍执行资源清理，聚合两个错误。"""
        from tests.support.ua2_write_assertions import strict_restore_source_and_cleanup
        api = Mock()
        m = Mock()
        m.process.poll.return_value = None
        with patch("asyncua.Client", side_effect=RuntimeError("mock server down")):
            with patch("tests.support.ua2_cleanup.strict_cleanup_ua2_context",
                       side_effect=AssertionError("cleanup error")):
                with pytest.raises(AssertionError) as excinfo:
                    strict_restore_source_and_cleanup(
                        api, endpoint="x", node_name="y", namespace_index=1,
                        original_value=123456, original_variant_type=ua.VariantType.Int64,
                        tag_id=1, tag_name="t", ds_id=1, ds_name="d",
                        mocker=m, host="127.0.0.1", port=9999,
                    )
                msg = str(excinfo.value)
                assert "restore" in msg
                assert "cleanup" in msg

    def test_cleanup_only_failure(self):
        """恢复成功，仅清理失败。"""
        from tests.support.ua2_write_assertions import strict_restore_source_and_cleanup
        api = Mock()
        m = Mock()
        m.process.poll.return_value = None
        client_instance = AsyncMock()
        client_instance.__aenter__.return_value = client_instance
        client_instance.get_node.return_value = AsyncMock()
        with patch("asyncua.Client", return_value=client_instance):
            with patch("tests.support.ua2_write_assertions.opcua_read_variant_type_sync",
                       return_value=(123456, ua.VariantType.Int64)):
                with patch("tests.support.ua2_cleanup.strict_cleanup_ua2_context",
                           side_effect=AssertionError("cleanup error")):
                    with pytest.raises(AssertionError) as excinfo:
                        strict_restore_source_and_cleanup(
                            api, endpoint="x", node_name="y", namespace_index=1,
                            original_value=123456, original_variant_type=ua.VariantType.Int64,
                            tag_id=1, tag_name="t", ds_id=1, ds_name="d",
                            mocker=m, host="127.0.0.1", port=9999,
                        )
                    assert "cleanup" in str(excinfo.value)
