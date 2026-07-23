"""验证 4 个新位号值接口（真实环境，手动跑）。

只读验证默认开启（get_rt_value / query_history_value）；
写/触发接口默认跳过，用环境变量显式启用，避免误写。

用法（Git Bash）:
  DATAHUB_USER=xxx DATAHUB_PASSWORD=xxx \\
      python -m tpt_api.examples.verify_tag_value [tagName]

环境变量:
  DATAHUB_BASE_URL    默认 http://10.10.58.153:31556
  DATAHUB_USER        账号（必填）
  DATAHUB_PASSWORD    密码
  WRITE=1             启用 write_tag_values 回写验证
  COLLECT=1           启用 collect_tag_value 采集验证（需 GROUP_ID/TENANT_ID）
  GROUP_ID / TENANT_ID  collect_tag_value 的参数
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta

from tpt_api import AlgAPI
from tpt_api import datahub as dh

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    base_url = os.environ.get("DATAHUB_BASE_URL", "http://10.10.58.153:31556")
    user = os.environ.get("DATAHUB_USER", "")
    pwd = os.environ.get("DATAHUB_PASSWORD", "")
    if not user:
        print("DATAHUB_USER 未设置")
        return 2

    api = AlgAPI(base_url, timeout=60.0)
    api.login(user, pwd, "")
    print("登录成功")

    # 取一个 tagName（命令行参数 > 自动取第一个）
    tag = sys.argv[1] if len(sys.argv) > 1 else None
    if not tag:
        tags = dh.get_all_tags_all_types(api)
        if not tags:
            print("平台无位号，无法验证 get_rt_value / query_history_value")
            return 1
        tag = tags[0].get("tagName", "")
        print(f"未传 tagName，自动选用: {tag}")

    # 1) get_rt_value（只读）
    print("\n[1] get_rt_value")
    try:
        rt = dh.get_rt_value(api, tag_names=[tag])
        print(f"  返回 {len(rt)} 条; 首条: {rt[0] if rt else None}")
    except Exception as e:
        print(f"  失败: {e!r}")

    # 2) query_history_value（只读，最近 1 小时）
    print("\n[2] query_history_value（最近 1 小时）")
    try:
        end = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        beg = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        hist = dh.query_history_value(api, [tag], beg, end, page=1, page_size=5)
        print(f"  total={hist.get('total')} size={hist.get('size')} "
              f"pages={hist.get('pages')}")
        print(f"  records[:2]: {hist.get('records', [])[:2]}")
    except Exception as e:
        print(f"  失败: {e!r}")

    # 3) write_tag_values（写）— 默认跳过
    if os.environ.get("WRITE") == "1":
        print("\n[3] write_tag_values")
        try:
            val = 123.45
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            resp = dh.write_tag_values(api, {tag: val}, tag_time=now, quality_code=192)
            print(f"  resp: {resp}")
            # 读回验证：写入记录直接进历史，用 query_history_value(is_source=True) 立即可查
            # （writeTagValues 直接写历史，不受 UA 5s 采集周期限制；getRTValue 写后 ~1s 才反映）
            beg = (datetime.now() - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
            end = (datetime.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
            hit = None
            for i in range(4):  # 立即 + 重试，最多 ~6s
                if i:
                    time.sleep(2)
                h = dh.query_history_value(api, [tag], beg, end, is_source=True,
                                           page=1, page_size=50, sort="-tagTime")
                hit = next((x for x in (h.get("records") or [])
                            if str(x.get("tagValue")) == str(val)), None)
                if hit:
                    break
            if hit:
                print(f"  ✅ 读回命中: tagValue={hit.get('tagValue')!r} "
                      f"tagTime={hit.get('tagTime')}")
            else:
                print(f"  ⚠️ history 未命中 {val}（位号可能不可写）")
        except Exception as e:
            print(f"  失败: {e!r}")
    else:
        print("\n[3] write_tag_values 跳过（设 WRITE=1 启用）")

    # 4) collect_tag_value（触发采集任务）— 默认跳过，参数复杂
    if os.environ.get("COLLECT") == "1":
        print("\n[4] collect_tag_value")
        try:
            group_id = int(os.environ.get("GROUP_ID", "0"))
            tenant_id = os.environ.get("TENANT_ID", "")
            es_dto = {"jobType": 1, "jobName": "verify_collect",
                      "executeWay": "MANUAL", "scheduleType": "MANUAL"}
            ok = dh.collect_tag_value(api, es_dto, group_id, tenant_id)
            print(f"  content={ok}")
        except Exception as e:
            print(f"  失败: {e!r}")
    else:
        print("\n[4] collect_tag_value 跳过（设 COLLECT=1 + GROUP_ID + TENANT_ID 启用）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
