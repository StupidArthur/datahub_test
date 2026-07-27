from __future__ import annotations

import pytest
from tests.support.ua2_helpers import tag_base_name, parse_tag_base_name


class TestTagBaseName:
    def test_basic(self):
        assert tag_base_name("static_1", 1) == "1_static_1"

    def test_default_namespace(self):
        assert tag_base_name("foo") == "1_foo"

    def test_large_namespace(self):
        assert tag_base_name("bar", 999) == "999_bar"

    def test_zero_namespace(self):
        assert tag_base_name("x", 0) == "0_x"

    def test_empty_node_name_raises(self):
        with pytest.raises(ValueError, match="empty"):
            tag_base_name("")

    def test_negative_namespace_raises(self):
        with pytest.raises(ValueError, match="non-negative"):
            tag_base_name("x", -1)


class TestParseTagBaseName:
    def test_basic(self):
        assert parse_tag_base_name("1_static_1") == (1, "static_1")

    def test_large_namespace(self):
        assert parse_tag_base_name("999_bar") == (999, "bar")

    def test_zero_namespace(self):
        assert parse_tag_base_name("0_x") == (0, "x")

    def test_node_with_underscore(self):
        assert parse_tag_base_name("2_a_b_c") == (2, "a_b_c")

    def test_no_underscore_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            parse_tag_base_name("abc")

    def test_non_digit_namespace_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            parse_tag_base_name("abc_def")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="invalid"):
            parse_tag_base_name("")

    def test_roundtrip(self):
        raw = "my_node"
        ns = 3
        encoded = tag_base_name(raw, ns)
        decoded_ns, decoded_raw = parse_tag_base_name(encoded)
        assert decoded_ns == ns
        assert decoded_raw == raw
