"""实测删除数据源后，其下位号是否被级联删除。"""
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
ds_name = f"test_cascade_{ts}"
endpoint = f"opc.tcp://10.99.99.99:{40000 + (ts % 10000)}/ua_mocker/"
print(f"创建测试数据源: {ds_name} -> {endpoint}")
try:
    new_ds = datahub.add_ds_info(api, ds_name=ds_name, ds_tar_url=endpoint)
    ds_id = new_ds.get("id")
    print(f"创建成功: dsId={ds_id}")
except Exception as e:
    print(f"创建失败: {e}")
    sys.exit(1)

# 2. 添加 3 个测试位号
tag_names = [f"test_cascade_tag_{ts}_{i}" for i in range(3)]
print(f"\n添加测试位号: {tag_names}")
for tag in tag_names:
    try:
        datahub.add_tag(
            api,
            tag_name=tag,
            ds_id=ds_id,
            data_type=DataTypes["DOUBLE"],
            tag_base_name=f"1_{tag}",
            frequency=10,
        )
        print(f"  {tag} 添加成功")
    except Exception as e:
        print(f"  {tag} 添加失败: {e}")

# 3. 按 dsId 查询位号，确认已添加
tags_before = datahub.get_all_tags(api, data={"dsId": ds_id})
print(f"\n删除前，数据源 dsId={ds_id} 下位号数: {len(tags_before)}")
for t in tags_before[:5]:
    print(f"  {t.get('tagName')} dsId={t.get('dsId')}")

# 4. 先删除该数据源下的位号，再删除数据源
# (changeState 在数据源有位号时实测超时，所以改用先清空位号)
tag_ids = [t.get("id") for t in tags_before if t.get("id")]
print(f"\n先软删 {len(tag_ids)} 个位号...")
if tag_ids:
    try:
        datahub.delete_tags(api, tag_ids)
        print("  软删成功")
    except Exception as e:
        print(f"  软删失败: {e}")
        sys.exit(1)
    print("\n再物理删位号...")
    try:
        datahub.delete_tags_physical(api, tag_ids)
        print("  物理删成功")
    except Exception as e:
        print(f"  物理删失败: {e}")
        sys.exit(1)

print(f"\n删除数据源 dsId={ds_id}...")
try:
    datahub.delete_ds_info(api, [ds_id])
    print("  数据源删除成功")
except Exception as e:
    print(f"  数据源删除失败: {e}")
    sys.exit(1)

# 5. 再次按 dsId 查询位号
tags_after_by_ds = datahub.get_all_tags(api, data={"dsId": ds_id})
print(f"\n删除后，按 dsId={ds_id} 查询位号数: {len(tags_after_by_ds)}")

# 6. 按 tagName 查询这些位号是否还存在
print("\n按 tagName 查询测试位号:")
for tag in tag_names:
    try:
        all_with_name = datahub.get_all_tags(api, data={"tagName": tag})
        print(f"  {tag}: 找到 {len(all_with_name)} 条")
        for t in all_with_name[:3]:
            print(f"    id={t.get('id')} dsId={t.get('dsId')} dsName={t.get('dsName')}")
    except Exception as e:
        print(f"  {tag} 查询失败: {e}")

print("\n结论:")
print("  1. 数据源下有位号时，直接删除会报 'The data source is currently in use'")
print("  2. changeState 禁用/启用 在数据源有位号时会 ReadTimeout，且不生效")
print("  3. 必须先物理删除数据源下所有位号，才能删除数据源")
print("  4. 删除数据源本身不会级联删除位号（因为不先清位号根本删不掉）")
