from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.integration.ua2.test_tag_group_operations import _check_tag_in_group

MOD = "tests.integration.ua2.test_tag_group_operations"


def _qwq(records):
    return {"tagInfoList": {"records": records, "total": len(records)}}


def _rec(tag_name):
    return {"id": 1, "tagName": tag_name, "tagBaseName": tag_name, "dsId": 1}


def test_in_group_returns_true():
    api = object()
    with patch(f"{MOD}.query_tags_with_quality", return_value=_qwq([_rec("t1")])) as m:
        assert _check_tag_in_group(api, "t1", "g2") is True
    m.assert_called_once_with(api, group_id="g2", tag_name="t1", page_size=10)


def test_not_in_group_returns_false():
    api = object()
    with patch(f"{MOD}.query_tags_with_quality", return_value=_qwq([_rec("t1")])):
        assert _check_tag_in_group(api, "t2", "g2") is False


def test_other_group_empty_returns_false():
    api = object()
    with patch(f"{MOD}.query_tags_with_quality", return_value=_qwq([])):
        assert _check_tag_in_group(api, "t1", "g1") is False


def test_prefix_name_no_false_match():
    api = object()
    with patch(f"{MOD}.query_tags_with_quality", return_value=_qwq([_rec("tagA_1")])):
        assert _check_tag_in_group(api, "tagA", "g2") is False


def test_multiple_records_finds_exact():
    api = object()
    with patch(
        f"{MOD}.query_tags_with_quality",
        return_value=_qwq([_rec("a"), _rec("b"), _rec("c")]),
    ):
        assert _check_tag_in_group(api, "b", "g2") is True


def test_empty_tag_info_list_returns_false():
    api = object()
    with patch(f"{MOD}.query_tags_with_quality", return_value={"tagInfoList": None}):
        assert _check_tag_in_group(api, "t1", "g2") is False


def test_missing_records_key_returns_false():
    api = object()
    with patch(f"{MOD}.query_tags_with_quality", return_value={}):
        assert _check_tag_in_group(api, "t1", "g2") is False


def test_malformed_return_never_false_positive():
    api = object()
    malformed = [
        {"tagInfoList": {"records": None}},
        {"tagInfoList": {"records": [{"no_tag_name": "t1"}]}},
        {"tagInfoList": {"records": [{"tagName": None}]}},
    ]
    for bad in malformed:
        with patch(f"{MOD}.query_tags_with_quality", return_value=bad):
            assert _check_tag_in_group(api, "t1", "g2") is False

    with patch(f"{MOD}.query_tags_with_quality", return_value={"tagInfoList": "string"}):
        with pytest.raises((AttributeError, TypeError)):
            _check_tag_in_group(api, "t1", "g2")
