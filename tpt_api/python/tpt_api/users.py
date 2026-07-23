"""TPT admin 用户管理 4 端点（与 USER_MANAGER/internal/api/users.go 1:1 对齐）。

端点（POST，统一 base URL）：
- /xpt-system/api/system-manager/umsAdmin/listByOrgId  分页
- /xpt-system/api/system-manager/umsAdmin              单建
- /xpt-system/api/system-manager/umsAdmin/resetPwd     重置密码
"""

from __future__ import annotations

import logging
from typing import Any

from .client import AlgAPI
from .types import (
    OperationStatus,
    PageResponse,
    User,
    UserDraft,
)

log = logging.getLogger(__name__)


# 写操作端点前缀。
UserListByOrgPath = "/xpt-system/api/system-manager/umsAdmin/listByOrgId"
UserCreatePath = "/xpt-system/api/system-manager/umsAdmin"
UserResetPwdPath = "/xpt-system/api/system-manager/umsAdmin/resetPwd"

# 默认模糊搜索字段。
DEFAULT_SEARCH_FIELDS: tuple[str, ...] = ("nickName", "username", "phone", "email")


def list_users(
    api: AlgAPI,
    page: int = 1,
    page_size: int = 10,
    org_id: str = "",
    keyword: str = "",
    sort: str = "",
    search_fields: tuple[str, ...] | list[str] | None = None,
) -> PageResponse:
    """分页拉后台用户列表。

    - page 从 1 开始
    - page_size 默认 10
    - org_id 空串表示全部组织
    - keyword 空串表示不过滤；非空时跨 search_fields 任一字段模糊匹配
    - search_fields 自定义模糊字段，默认 DEFAULT_SEARCH_FIELDS
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10
    if not search_fields:
        search_fields = DEFAULT_SEARCH_FIELDS

    field_keys = "|".join(f"*{f}*" for f in search_fields)
    admin_where: dict[str, str] = {}
    if keyword:
        admin_where[field_keys] = keyword

    body: dict[str, Any] = {
        "data": {
            "adminWhere": admin_where,
            "orgId": org_id,
        },
        "requestBase": {
            "page": f"{page}-{page_size}",
            "sort": sort,
        },
    }
    raw = api._request("POST", UserListByOrgPath, body=body, wrap=False)
    return PageResponse.from_dict(raw if isinstance(raw, dict) else {})


def get_all_users(
    api: AlgAPI,
    keyword: str = "",
    sort: str = "",
    page_size: int = 200,
    search_fields: tuple[str, ...] | list[str] | None = None,
) -> list[User]:
    """自动翻页拉全部后台用户。"""
    if page_size < 1:
        page_size = 200
    all_users: list[User] = []
    page = 1
    while True:
        resp = list_users(api, page=page, page_size=page_size, org_id="",
                          keyword=keyword, sort=sort, search_fields=search_fields)
        all_users.extend(resp.records)
        if len(resp.records) < page_size:
            break
        page += 1
    return all_users


def create_user(api: AlgAPI, draft: UserDraft) -> OperationStatus:
    """创建一个后台用户。

    内部固定参数（v1 不暴露给前端）：
    - status: 0
    - orgIds: [1]
    - orgName: "默认组织"
    - type: "2" (普通用户)
    - roleIds: "5"
    - gender: "1"
    - code: 沿用 username
    - icon: ""

    响应不含 userId，调用方需 get_all_users 反查 username 拿 id。
    """
    body: dict[str, Any] = {
        "data": {
            "status": 0,
            "orgIds": [1],
            "username": draft.username,
            "code": draft.username,
            "nickName": draft.nickName,
            "password": draft.password,
            "gender": "1",
            "email": draft.email,
            "phone": draft.phone,
            "orgName": "默认组织",
            "type": "2",
            "roleIds": "5",
            "icon": "",
        },
    }
    raw = api._request("POST", UserCreatePath, body=body, wrap=False)
    if isinstance(raw, dict):
        return OperationStatus(code=raw.get("code", ""), msg=raw.get("msg", ""))
    return OperationStatus()


def reset_password(api: AlgAPI, user_id: int, new_password: str) -> OperationStatus:
    """重置指定用户的密码。

    user_id 来自 list_users 返回的 id 字段。

    注意：平台行为是 reset 后旧密码仍可登录，重置成功 ≠ 旧密码失效。
    """
    body: dict[str, Any] = {
        "data": {
            "id": user_id,
            "newPwd": new_password,
            "confirmPwd": new_password,
        },
    }
    raw = api._request("POST", UserResetPwdPath, body=body, wrap=False)
    if isinstance(raw, dict):
        return OperationStatus(code=raw.get("code", ""), msg=raw.get("msg", ""))
    return OperationStatus()
