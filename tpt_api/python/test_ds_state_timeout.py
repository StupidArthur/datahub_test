"""实测数据源有位号时 changeState 是否真的禁用成功。"""
import sys
import time
from tpt_api import AlgAPI, datahub
from tpt_api.types import DataTypes

BASE_URL = "http://10.10.58.153:31501"
USERNAME = "admin"
PASSWORD = "123456"

api = AlgAPI(BASE_URL, timeout=60.0)
api.login(USERNAME, PASSWORD)

# 1. 创建测试数据源
ts = int(time.time())
ds_name = f"test_state_to_{ts}"
endpoint = f"opc.tcp://10.99.99.99:{40000 + (ts % 10000)}/ua_mocker/"
print(f"创建: {ds_name}")
new_ds = datahub.add_ds_info(api, ds_name=ds_name, ds_tar_url=endpoint)
ds_id = new_ds.get("id")
print(f"dsId={ds_id}, 初始状态 dsStatus={new_ds.get('dsStatus')}")

# 2. 加 3 个位号
tag_names = [f"test_state_to_tag_{ts}_{i}" for i in range(3)]
for tag in tag_names:
    datahub.add_tag(
        api,
        tag_name=tag,
        ds_id=ds_id,
        data_type=DataTypes["DOUBLE"],
        tag_base_name=f"1_{tag}",
        frequency=10,
    )
print(f"加了 {len(tag_names)} 个位号")

# 3. 调用 changeState 禁用，捕获超时
print("\n调用 changeState 禁用...")
try:
    r = datahub.change_ds_state(api, ds_id, enabled=False)
    print(f"  changeState 返回: {r}")
except Exception as e:
    print(f"  changeState 异常: {type(e).__name__}: {e}")

# 4. 查询数据源当前状态
print("\n查询数据源状态...")
all_ds = datahub.get_all_ds_info(api)
matched = [d for d in all_ds if d.get("id") == ds_id]
if matched:
    print(f"  dsStatus={matched[0].get('dsStatus')}")
else:
    print("  数据源不存在")

# 5. 尝试删除数据源
print("\n尝试删除数据源...")
try:
    datahub.delete_ds_info(api, [ds_id])
    print("  删除成功")
except Exception as e:
    print(f"  删除失败: {type(e).__name__}: {e}")

# 6. 查询位号状态
print("\n按 tagName 查询位号:")
for tag in tag_names:
    found = datahub.get_all_tags(api, data={"tagName": tag})
    print(f"  {tag}: {len(found)} 条")

print("\n按 dsId 查询位号:")
found_by_ds = datahub.get_all_tags(api, data={"dsId": ds_id})
print(f"  dsId={ds_id}: {len(found_by_ds)} 条")
