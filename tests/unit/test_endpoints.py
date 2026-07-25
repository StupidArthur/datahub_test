"""Unit tests for tests/support/endpoints.py parser.

Uses example / documentation IPs (192.0.2.10, mocker.example.test) so
the test never depends on the real development machine address.
"""
from __future__ import annotations

import pytest

from tests.support.endpoints import parse_mocker_endpoint


def test_parse_endpoint_with_path_ip():
    p = parse_mocker_endpoint("opc.tcp://192.0.2.10:18960/ua_mocker/")
    assert p.host == "192.0.2.10"
    assert p.port == 18960
    assert p.path == "/ua_mocker/"
    assert p.url_no_path == "opc.tcp://192.0.2.10:18960"
    assert p.url_with_path == "opc.tcp://192.0.2.10:18960/ua_mocker/"


def test_parse_endpoint_with_path_hostname():
    p = parse_mocker_endpoint("opc.tcp://mocker.example.test:18960/ua_mocker/")
    assert p.host == "mocker.example.test"
    assert p.port == 18960
    assert p.path == "/ua_mocker/"
    assert p.url_with_path == "opc.tcp://mocker.example.test:18960/ua_mocker/"


def test_parse_endpoint_without_path():
    p = parse_mocker_endpoint("opc.tcp://192.0.2.10:18960")
    assert p.host == "192.0.2.10"
    assert p.port == 18960
    assert p.path == ""
    assert p.url_no_path == "opc.tcp://192.0.2.10:18960"
    # url_with_path defaults to appending /ua_mocker/ when no path
    assert p.url_with_path == "opc.tcp://192.0.2.10:18960/ua_mocker/"


def test_parse_endpoint_with_custom_path():
    p = parse_mocker_endpoint("opc.tcp://192.0.2.10:18960/custom/path")
    assert p.path == "/custom/path"
    assert p.url_with_path == "opc.tcp://192.0.2.10:18960/custom/path"


def test_parse_endpoint_empty_string():
    with pytest.raises(ValueError, match="cannot parse endpoint"):
        parse_mocker_endpoint("")


def test_parse_endpoint_missing_port():
    with pytest.raises(ValueError, match="cannot parse endpoint"):
        parse_mocker_endpoint("opc.tcp://192.0.2.10/ua_mocker/")


def test_parse_endpoint_wrong_scheme():
    with pytest.raises(ValueError, match="cannot parse endpoint"):
        parse_mocker_endpoint("http://192.0.2.10:18960/ua_mocker/")


def test_parse_endpoint_no_scheme():
    with pytest.raises(ValueError, match="cannot parse endpoint"):
        parse_mocker_endpoint("192.0.2.10:18960/ua_mocker/")