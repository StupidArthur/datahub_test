"""Client 公共层 + 错误类型测试。"""

from __future__ import annotations

import pytest

from tpt_api import (
    TptAPIError,
    TptAuthError,
    TptHTTPError,
    auth_codes,
    auth_keywords,
    is_auth_error,
    is_auth_response_code,
)


def test_success_code_constant() -> None:
    from tpt_api import SuccessCode
    assert SuccessCode == "00000"


def test_login_path_constant() -> None:
    from tpt_api import LoginPath
    assert LoginPath == "/tpt-admin/system-manager/umsAdmin/login"


def test_auth_codes_match_python_parent() -> None:
    assert auth_codes == {"A0230", "A0201", "A0202", "A0203"}


def test_auth_keywords_match_python_parent() -> None:
    assert "未登录" in auth_keywords
    assert "登录已超时" in auth_keywords
    assert "token过期" in auth_keywords
    assert "无访问权限" in auth_keywords
    assert "Unauthorized" in auth_keywords


def test_is_auth_response_code() -> None:
    assert is_auth_response_code("00000", "OK") is False
    assert is_auth_response_code("A0230", "登录已超时") is True
    assert is_auth_response_code("A0400", "参数错误") is False
    assert is_auth_response_code("X0001", "token过期") is True
    assert is_auth_response_code("X0002", "Unauthorized") is True


def test_tpt_auth_error_str() -> None:
    e = TptAuthError("A0230", "登录已超时")
    assert "[A0230]" in str(e)
    assert "登录已超时" in str(e)


def test_tpt_api_error_has_is_auth_error_attr() -> None:
    e = TptAPIError("A0400", "参数错误")
    assert hasattr(e, "is_auth_error")
    assert e.is_auth_error is False


def test_is_auth_error_helper() -> None:
    assert is_auth_error(None) is False
    assert is_auth_error(TptAuthError("A0230", "x")) is True
    e = TptAPIError("A0230", "x")
    e.is_auth_error = True
    assert is_auth_error(e) is True
    assert is_auth_error(ValueError("x")) is False


def test_login_success(api, mock_transport) -> None:  # noqa: ARG001
    """完整登录：注入响应、调用、断言 token。"""
    from tpt_api import AlgAPI
    mock_transport.register(
        "/tpt-admin/system-manager/umsAdmin/login",
        {"code": "00000", "content": {"token": "xyz"}},
    )
    a = AlgAPI("http://test")
    import httpx as _httpx
    a.client = _httpx.Client(base_url=a.base_url, transport=mock_transport)
    a.login("u", "p", "")
    assert a.token == "xyz"
    assert a.token is not None


def test_login_auth_error(api, mock_transport) -> None:  # noqa: ARG001
    """登录响应 code=A0230 → TptAPIError 携带 is_auth_error=True。"""
    from tpt_api import AlgAPI
    mock_transport.register(
        "/tpt-admin/system-manager/umsAdmin/login",
        {"code": "A0230", "msg": "登录已超时"},
    )
    import httpx as _httpx
    a = AlgAPI("http://test")
    a.client = _httpx.Client(base_url=a.base_url, transport=mock_transport)
    with pytest.raises(TptAPIError) as exc_info:
        a.login("u", "p", "")
    assert exc_info.value.is_auth_error is True


def test_request_http_error(api, mock_transport) -> None:  # noqa: ARG001
    """HTTP 4xx 抛 httpx.HTTPStatusError（_request 调了 raise_for_status）。"""
    from tpt_api import AlgAPI
    import httpx as _httpx
    a = AlgAPI("http://test")
    a.token = "abc"
    a.client = _httpx.Client(base_url=a.base_url, transport=mock_transport)
    mock_transport.register("/some", {"code": "00000"}, status=500)
    with pytest.raises(_httpx.HTTPStatusError):
        a._request("POST", "/some", body={})
