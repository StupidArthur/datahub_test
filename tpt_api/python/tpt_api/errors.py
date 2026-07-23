"""tpt_api 错误类型 + 鉴权错误判定。

与 Go 版 tptapi/errors.go 一一对应。
"""

from __future__ import annotations

# 业务成功 code（与 common/api.py:21 / common_api.py 一致）。
SuccessCode: str = "00000"

# 登录端点（与 common/api.py:52 / alg_update/alg_toolbox/algapi.go:157 一致）。
LoginPath: str = "/tpt-admin/system-manager/umsAdmin/login"

# accountType 写死 "0"。
LoginAccountType: str = "0"

# 鉴权码集合（与 common/api.py:30 / common_api.py:58 / algapi.go:119 对齐）。
auth_codes: set[str] = {"A0230", "A0201", "A0202", "A0203"}

# 鉴权关键词（与 common/api.py:34 / common_api.py:62 / algapi.go:124 对齐）。
auth_keywords: tuple[str, ...] = (
    "未登录",
    "登录已超时",
    "登录过期",
    "token过期",
    "无访问权限",
    "Unauthorized",
)


class TptAuthError(Exception):
    """鉴权失败（登录态过期、token 无效等）。"""

    def __init__(self, code: str, msg: str):
        self.code = code
        self.msg = msg
        super().__init__(f"[{code}] {msg}")


class TptAPIError(Exception):
    """平台返回的业务错误（非鉴权类）。"""

    def __init__(self, code: str, msg: str):
        self.code = code
        self.msg = msg
        # 与父级 common/api.py / common_api.py 兼容：异常上挂 is_auth_error 标记
        self.is_auth_error: bool = False
        super().__init__(f"[{code}] {msg}")


class TptHTTPError(Exception):
    """HTTP 层错误（4xx/5xx 非业务响应）。"""

    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"http {status_code}: {body[:200]}")


def is_auth_response_code(code: str, msg: str) -> bool:
    """判断平台响应 code/msg 是否为鉴权错误。"""
    if code in auth_codes:
        return True
    return any(k in (msg or "") for k in auth_keywords)


def is_auth_error(err: BaseException | None) -> bool:
    """判断 err 是否为鉴权错误。"""
    if err is None:
        return False
    if isinstance(err, TptAuthError):
        return True
    if isinstance(err, TptAPIError) and getattr(err, "is_auth_error", False):
        return True
    return False
