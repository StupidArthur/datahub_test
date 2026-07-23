"""删除所有 ua_test 开头的数据源下的位号。"""
import sys
import time
from tpt_api import AlgAPI, datahub

BASE_URL = "http://10.10.58.153:31501"
USERNAME = "admin"
PASSWORD = "123456"

api = AlgAPI(BASE_URL, timeout=60.0)
api.login(USERNAME, PASSWORD)

# 1. 列出所有 ua_test 开头的数据源
all_ds = datahub.get_all_ds_info(api)
ua_test_ds = [d for d in all_ds if d.get("dsName", "").lower().startswith("ua_test")]
print(f"找到 {len(ua_test_ds)} 个 ua_test 开头的数据源:")
for d in ua_test_ds:
    print(f"  dsId={d.get('id')} name={d.get('dsName')} url={d.get('dsTarUrl')} status={d.get('dsStatus')}")

if not ua_test_ds:
    print("没有需要清理的数据源")
    sys.exit(0)

# 2. 逐个数据源清理位号
total_deleted = 0
for d in ua_test_ds:
    ds_id = d.get("id")
    ds_name = d.get("dsName")
    print(f"\n处理数据源: {ds_name} (dsId={ds_id})")

    tags = datahub.get_all_tags(api, data={"dsId": ds_id})
    print(f"  找到 {len(tags)} 个位号")
    if not tags:
        continue

    tag_ids = [t.get("id") for t in tags if t.get("id")]
    print(f"  准备删除 {len(tag_ids)} 个位号...")

    try:
        datahub.delete_tags(api, tag_ids)
        print("    软删成功")
    except Exception as e:
        print(f"    软删失败: {e}")
        continue

    try:
        datahub.delete_tags_physical(api, tag_ids)
        print("    物理删成功")
    except Exception as e:
        print(f"    物理删失败: {e}")
        continue

    total_deleted += len(tag_ids)

print(f"\n总共删除 {total_deleted} 个位号")
