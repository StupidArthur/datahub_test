"""tpt_api 公共 Client。

AlgAPI 类与父级 common/api.py / common_api.py 行为兼容：
- 同名类、同名方法
- 异常上挂 is_auth_error 属性
- algorithms / source_map / tags / name_map 缓存属性
- 内部 _request 私有方法、_is_auth_error 私有方法
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .errors import (
    LoginPath,
    LoginAccountType,
    SuccessCode,
    TptAPIError,
    TptAuthError,
    TptHTTPError,
    is_auth_response_code,
)

log = logging.getLogger(__name__)


class AlgAPI:
    """统一封装 TPT 后台域 HTTP 客户端。

    同一实例同时承载：
    - TPT admin 用户管理（client.users 命名空间）
    - alg-manager 算法管理（client.algorithms 命名空间）
    - ibd-data-hub tag + 历史值（client.datahub 命名空间）

    但为了与父级 common/api.py / common_api.py 兼容，所有方法都直接挂在本类上：
    - login / list_algorithms / upload_file / edit_algorithm / ...（alg-manager）
    - list_tags / add_tag / delete_tags / import_tag_value / ...（ibd-data-hub）
    - list_users / create_user / reset_password（user 域，新加）

    复用同一份 token / cookies，所有方法共享鉴权态。
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        # alg_manager.py 默认 60s 是 data-hub 场景；这里默认 30s 兼容算法场景。
        # 继承方可以显式传 timeout=60.0 覆盖。
        self.base_url: str = base_url.rstrip("/")
        self.token: str | None = None
        self._https_mode: bool = self.base_url.startswith("https://")
        self.client: httpx.Client = httpx.Client(base_url=self.base_url, timeout=timeout)

        # 业务缓存（保留父级命名：algorithms / source_map；tag 域用 tags / name_map）
        self.algorithms: list[dict[str, Any]] = []
        self.source_map: dict[str, dict[str, Any]] = {}
        self.tags: list[dict[str, Any]] = []
        self.name_map: dict[str, dict[str, Any]] = {}

    # === 内部辅助 ===

    def _request(
        self,
        method: str,
        path: str,
        body: Any = None,
        params: dict[str, Any] | None = None,
        wrap: bool = True,
    ) -> Any:
        """统一请求方法。"""
        url = f"{self.base_url}/{path.lstrip('/')}"
        json_body = {"data": body} if wrap and body is not None else body
        log.debug("%s %s", method, url)
        r = self.client.request(method, url, json=json_body, params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != SuccessCode and not (self._https_mode and not data.get("isSuccess")):
            exc = TptAPIError(data.get("code", ""), data.get("msg", ""))
            exc.is_auth_error = is_auth_response_code(data.get("code", ""), data.get("msg", ""))
            log.error("业务 code 非 %s: %s %s -> code=%s msg=%s", SuccessCode, method, url,
                      exc.code, exc.msg)
            raise exc
        log.debug("%s %s -> OK", method, url)
        return data.get("content", data)

    def _is_auth_error(self, data: dict[str, Any]) -> bool:
        """判断响应是否为鉴权错误。"""
        return is_auth_response_code(str(data.get("code", "")), data.get("msg", ""))

    def _download(
        self,
        method: str,
        path: str,
        body: Any = None,
        wrap: bool = True,
    ) -> bytes:
        """下载二进制内容（导出文件等），返回 raw bytes。"""
        url = f"{self.base_url}/{path.lstrip('/')}"
        json_body = {"data": body} if wrap and body is not None else body
        log.debug("DOWNLOAD %s %s", method, url)
        r = self.client.request(method, url, json=json_body)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")
        if "json" in content_type:
            # 服务端返回了 JSON 错误而非文件
            data = r.json()
            raise TptAPIError(data.get("code", ""), data.get("msg", ""))
        return r.content

    # === 登录 ===

    def login(self, username: str, password: str, tenant_id: str = "") -> Any:
        """登录 TPT 后台获取 Bearer token。

        - tenant_id 为空时不发 tenantId body 字段也不设 cookie（HTTP 单租户场景）
        - tenant_id 非空时（HTTPS 多租户）会发 tenantId body 字段，并设 TptSaasUserTenantryId /
          tenant-id cookie

        重要：login body 必须包 data 顶层键，否则平台报 A0400「用户请求参数错误」。
        """
        log.info("登录开始: user=%s, https=%s", username, self._https_mode)
        body: dict[str, Any] = {
            "username": username,
            "password": password,
            "remember": False,
            "accountType": LoginAccountType,
            "generateCode": False,
        }
        if self._https_mode and tenant_id:
            body["tenantId"] = tenant_id
            self.client.cookies.set("TptSaasUserTenantryId", tenant_id)
            self.client.cookies.set("tenant-id", tenant_id)

        result = self._request("POST", LoginPath, body=body)

        if self._https_mode:
            # HTTPS 模式：从 body 取 token，同时设 cookie 和 Bearer header
            if isinstance(result, dict) and result.get("token"):
                self.token = result["token"]
                self.client.cookies.set("tpt-token", self.token)
                self.client.headers["Authorization"] = f"Bearer {self.token}"
        else:
            # HTTP 模式：从响应 body 取 Bearer token
            self.token = result["token"]
            self.client.headers["Authorization"] = f"Bearer {self.token}"

        log.info("登录成功: token 长度=%d", len(self.token or ""))
        return result

    # === 内部：DELETE 写操作 + 文件上传（被 datahub 复用） ===

    def _parse_resp(self, r: httpx.Response) -> dict[str, Any]:
        """统一解析导入端点响应。

        返回: {
            "status_code": int,
            "code": str | None,        # 业务 code
            "msg": str,                # 业务 msg
            "is_success": bool,        # HTTP 200 且 (isSuccess/success=true) 且 code="00000"
            "data": any,               # 响应 data 字段 (importTagValue 这里是失败位号 dict)
            "raw": dict | None,        # 完整响应 dict
        }
        """
        try:
            body = r.json()
        except Exception:
            return {
                "status_code": r.status_code,
                "code": None,
                "msg": r.text[:500],
                "is_success": r.status_code == 200,
                "data": None,
                "raw": None,
            }
        is_ok = (
            r.status_code == 200
            and (body.get("isSuccess") or body.get("success"))
            and body.get("code") == SuccessCode
        )
        return {
            "status_code": r.status_code,
            "code": body.get("code"),
            "msg": body.get("msg"),
            "is_success": is_ok,
            "data": body.get("data"),
            "raw": body,
        }
