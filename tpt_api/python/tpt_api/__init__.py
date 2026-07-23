"""tpt_api —— Supcon SaaS / TPT 后台域的 Python HTTP 客户端。

一份代码覆盖三类业务端点（共享同一套登录 + 鉴权 + 错误码）：

- TPT admin 用户管理  (pkg/USER_MANAGER Go 端  +  Python common/api.py 的 tpt-admin 部分)
- alg-manager 算法管理 (alg_update/common/api.py  +  alg_update/alg_toolbox/algapi.go)
- ibd-data-hub 位号 + 历史值 (data-hub-tool/common_api.py)

鉴权机制三家完全一致：POST /tpt-admin/system-manager/umsAdmin/login 拿 Bearer token，
HTTPS 多租户场景额外带 TptSaasUserTenantryId / tenant-id cookie。

设计原则：
- 端点 URL / 请求/响应字段 / 错误码语义与父级代码 1:1 对齐
- 行为兼容：AlgAPI 类名、is_auth_error 属性、get_all_xxx / match_local_files 等方法签名
  全部沿用现有调用方期望
- 单一 Client 承载三类业务，按子模块拆分文件
"""

from .client import AlgAPI, LoginPath, LoginAccountType, SuccessCode
from .errors import (
    TptAuthError,
    TptAPIError,
    TptHTTPError,
    is_auth_error,
    auth_codes,
    auth_keywords,
    is_auth_response_code,
)
from .types import (
    # TPT admin
    User,
    UserDraft,
    PageResponse,
    LoginResponse,
    OperationStatus,
    # alg-manager
    Algorithm,
    # ibd-data-hub
    ImportResponse,
    DataTypes,
    TagTypes,
    DefaultTagTypesAll,
    DsInfo,
    DsTypes,
    DsSubTypes,
)

__version__ = "0.1.0"
__all__ = [
    "AlgAPI",
    "LoginPath",
    "LoginAccountType",
    "SuccessCode",
    "TptAuthError",
    "TptAPIError",
    "TptHTTPError",
    "is_auth_error",
    "auth_codes",
    "auth_keywords",
    "is_auth_response_code",
    "User",
    "UserDraft",
    "PageResponse",
    "LoginResponse",
    "OperationStatus",
    "Algorithm",
    "ImportResponse",
    "DataTypes",
    "TagTypes",
    "DefaultTagTypesAll",
    "DsInfo",
    "DsTypes",
    "DsSubTypes",
]
