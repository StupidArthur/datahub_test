from __future__ import annotations

from unittest.mock import Mock, patch

from asyncua import ua
import pytest

from tests.support.ua2_write_assertions import (
    INTEGER_RANGES,
    WRAP_MAP,
    classify_outcome_value,
    classify_write_result,
    expected_wrap_value,
    is_wrap_behaviour,
    wait_accepted_integer_outcome,
    _check_stable,
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
