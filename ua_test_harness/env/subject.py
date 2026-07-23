"""被测对象(datahub/TPT 实例):URL 截断解析 + 登录。

URL 截断规则(填到哪一级都有可能,自己截出有效的 base_url):
- 协议:http / https(看前缀,不带租户默认 http 也合法)
- base_url = 协议://host:port,丢弃其后所有 path / query
  (无论填到 /tpt-admin/、完整登录路径、还是 /doc.html,都截到 host:port,
   规避 tpt-admin/tpt-admin 这类 405)
- 租户 ID:query 的 tenantId/tenant_id/tenant 优先;其次 path /tenant/{id};都没有=空(单租户)

解析时机:算法简单,前端可实时解析(后端这里同步提供,登录前复用同一份)。
密码默认落盘保存(测试工具,怎么方便怎么来)——但落盘逻辑不在此处,这里只管解析+登录。
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs

from tpt_api import AlgAPI


@dataclass
class SubjectUrl:
    raw: str
    protocol: str       # "http" / "https"
    base_url: str       # "协议://host:port"
    tenant_id: str      # 可能为空(单租户)


def parse_subject_url(raw: str) -> SubjectUrl:
    """截断 URL -> 协议 + base_url + 租户。"""
    s = (raw or "").strip()
    if "://" not in s:
        raise ValueError(f"URL 缺协议(http/https): {raw!r}")
    u = urlparse(s)
    if u.scheme.lower() not in ("http", "https"):
        raise ValueError(f"仅支持 http/https,得到 {u.scheme!r}")
    if not u.hostname:
        raise ValueError(f"URL 解析不出 host: {raw!r}")
    protocol = u.scheme.lower()
    netloc = u.hostname + (f":{u.port}" if u.port else "")
    base_url = f"{protocol}://{netloc}"

    # 租户:query 优先
    tenant_id = ""
    if u.query:
        qs = parse_qs(u.query)
        for key in ("tenantId", "tenant_id", "tenant"):
            if qs.get(key):
                tenant_id = qs[key][0]
                break
    # 再看 path /tenant/{id}
    if not tenant_id and u.path:
        parts = [p for p in u.path.split("/") if p]
        for i, p in enumerate(parts):
            if p == "tenant" and i + 1 < len(parts):
                tenant_id = parts[i + 1]
                break
    return SubjectUrl(raw=s, protocol=protocol, base_url=base_url, tenant_id=tenant_id)


def login_subject(base_url: str, user: str, password: str,
                  tenant_id: str = "", timeout: float = 60.0) -> AlgAPI:
    """用截断后的 base_url + 账密 + 租户登录,返回已登录的 AlgAPI。"""
    api = AlgAPI(base_url, timeout=timeout)
    api.login(user, password, tenant_id)
    return api
