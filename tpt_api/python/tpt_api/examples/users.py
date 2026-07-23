"""tpt_api 的 TPT admin 用户管理用法示例。

运行：
    TPT_BASE_URL=https://... TPT_USER=admin TPT_PASSWORD=xxx python -m tpt_api.examples.users
"""

from __future__ import annotations

import logging
import os
import sys

from tpt_api import AlgAPI, UserDraft
from tpt_api import users as users_mod

logging.basicConfig(level=logging.INFO)


def main() -> int:
    base_url = os.environ.get("TPT_BASE_URL", "https://supcontpt.supcon.com")
    username = os.environ.get("TPT_USER", "admin")
    password = os.environ.get("TPT_PASSWORD", "")
    tenant_id = os.environ.get("TPT_TENANT_ID", "")

    if not password:
        print("错误: TPT_PASSWORD 未设置", file=sys.stderr)
        return 1

    api = AlgAPI(base_url)
    api.login(username, password, tenant_id)
    print(f"登录成功, token 前 8 位: {api.token[:8]}")

    # 1) 分页列用户
    page = users_mod.list_users(api, page=1, page_size=10)
    print(f"共 {page.total} 条，本页 {len(page.records)} 条：")
    for u in page.records:
        print(f"  id={u.id} username={u.username} nickName={u.nickName} email={u.email}")

    # 2) 关键词搜索
    keyword = os.environ.get("KEYWORD", "test")
    page = users_mod.list_users(api, page=1, page_size=10, keyword=keyword)
    print(f"含 {keyword!r} 的用户共 {page.total} 条")

    # 3) 创建 + 重置密码
    target_username = os.environ.get("TARGET_USERNAME", "test_demo")
    new_password = "Init@2026"
    users_mod.create_user(api, UserDraft(
        username=target_username, password=new_password, nickName="测试用户",
        email=f"{target_username}@example.com",
    ))
    print(f"用户 {target_username} 创建成功")

    all_users = users_mod.get_all_users(api)
    for u in all_users:
        if u.username == target_username:
            users_mod.reset_password(api, u.id, "NewPwd@2026")
            print(f"用户 {u.username} (id={u.id}) 密码已重置")

    return 0


if __name__ == "__main__":
    sys.exit(main())
