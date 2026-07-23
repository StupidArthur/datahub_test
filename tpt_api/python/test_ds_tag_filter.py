"""实测 tag-info/page 按 dsId 过滤是否有效。"""
from tpt_api import AlgAPI, datahub

BASE_URL = "http://10.10.58.153:31501"
USERNAME = "admin"
PASSWORD = "123456"

api = AlgAPI(BASE_URL)
api.login(USERNAME, PASSWORD)

# 1. 拉取数据源列表，找一个有 dsId 的
ds_list = datahub.get_all_ds_info(api)
print(f"数据源总数: {len(ds_list)}")
if not ds_list:
    print("没有数据源")
    exit()

for ds in ds_list[:5]:
    print(f"  dsId={ds.get('id')} dsName={ds.get('dsName')} dsTarUrl={ds.get('dsTarUrl')} alive={ds.get('alive')}")

test_ds = ds_list[0]
ds_id = test_ds.get("id")
print(f"\n测试数据源: dsId={ds_id}, dsName={test_ds.get('dsName')}")

# 2. 不传 dsId，查全平台位号（只取第一页）
all_tags_page = datahub.list_tags(api, page=1, page_size=10, data={})
all_total = all_tags_page.get("total", 0)
all_records = all_tags_page.get("records", [])
print(f"\n不传 dsId: total={all_total}, 本页 {len(all_records)} 条")
for t in all_records[:3]:
    print(f"  tagName={t.get('tagName')} dsId={t.get('dsId')} dsName={t.get('dsName')}")

# 3. 传 dsId，查该数据源下位号
ds_tags_page = datahub.list_tags(api, page=1, page_size=10, data={"dsId": ds_id})
ds_total = ds_tags_page.get("total", 0)
ds_records = ds_tags_page.get("records", [])
print(f"\n传 dsId={ds_id}: total={ds_total}, 本页 {len(ds_records)} 条")
for t in ds_records[:3]:
    print(f"  tagName={t.get('tagName')} dsId={t.get('dsId')} dsName={t.get('dsName')}")

# 4. 校验：传 dsId 后返回的位号是否都属于该数据源
if ds_records:
    mismatched = [t for t in ds_records if t.get("dsId") != ds_id]
    if mismatched:
        print(f"\n[WARNING] 发现 {len(mismatched)} 条 dsId 不匹配，说明 dsId 过滤不严格")
    else:
        print(f"\n[OK] 传 dsId 后返回的位号都属于 dsId={ds_id}，过滤有效")

# 5. 额外：翻页拉该数据源全部位号，看总数是否稳定
ds_all = datahub.get_all_tags(api, page_size=200, data={"dsId": ds_id})
print(f"\n翻页拉取 dsId={ds_id} 全部位号: {len(ds_all)} 条")
