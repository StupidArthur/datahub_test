"""实测删除数据源的前置条件：直接删 / 先禁用再删 / 先删位号再删。"""
import sys
import time
from tpt_api import AlgAPI, datahub

BASE_URL = "http://10.10.58.153:31501"
USERNAME = "admin"
PASSWORD = "123456"

api = AlgAPI(BASE_URL)
api.login(USERNAME, PASSWORD)

# 1. 创建一个新的测试数据源
ts = int(time.time())
ds_name = f"test_delete_{ts}"
endpoint = f"opc.tcp://10.99.99.99:{40000 + (ts % 10000)}/ua_mocker/"
print(f"创建测试数据源: {ds_name} -> {endpoint}")
try:
    new_ds = datahub.add_ds_info(api, ds_name=ds_name, ds_tar_url=endpoint)
    ds_id = new_ds.get("id")
    print(f"创建成功: dsId={ds_id}")
except Exception as e:
    print(f"创建失败: {e}")
    sys.exit(1)

# 2. 尝试直接删除
print("\n[1] 直接删除数据源...")
try:
    datahub.delete_ds_info(api, [ds_id])
    print("  直接删除成功")
    sys.exit(0)
except Exception as e:
    print(f"  直接删除失败: {e}")

# 3. 先禁用再删除
print("\n[2] 先禁用再删除...")
try:
    datahub.change_ds_state(api, ds_id, enabled=False)
    print("  禁用成功")
except Exception as e:
    print(f"  禁用失败: {e}")

try:
    datahub.delete_ds_info(api, [ds_id])
    print("  禁用后删除成功")
    sys.exit(0)
except Exception as e:
    print(f"  禁用后删除仍失败: {e}")

print("\n结论：删除数据源需要先清空位号或满足其它前置条件")
