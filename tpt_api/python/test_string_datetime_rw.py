"""实测 String/DateTime 位号的读值和写值。"""
import time
from tpt_api import AlgAPI, datahub

BASE_URL = "http://10.10.58.153:31501"
USERNAME = "admin"
PASSWORD = "123456"

api = AlgAPI(BASE_URL, timeout=60.0)
api.login(USERNAME, PASSWORD)

string_tag = "1_mock_String_wr_1"
datetime_tag = "1_mock_DateTime_wr_1"

print("=== String 位号 ===")
# 写
print(f"写 {string_tag} = 'test_value_{int(time.time())}'")
try:
    datahub.write_tag_values(api, {string_tag: f"test_value_{int(time.time())}"})
    print("  写成功")
except Exception as e:
    print(f"  写失败: {e}")

# 读
print(f"读 {string_tag}...")
try:
    vals = datahub.get_rt_value(api, [string_tag])
    for v in vals:
        print(f"  {v.get('tagName')} = {v.get('tagValue')} (quality={v.get('quality')})")
except Exception as e:
    print(f"  读失败: {e}")

print("\n=== DateTime 位号 ===")
# 写
ts = "2025-06-01T12:00:00Z"
print(f"写 {datetime_tag} = {ts}")
try:
    datahub.write_tag_values(api, {datetime_tag: ts})
    print("  写成功")
except Exception as e:
    print(f"  写失败: {e}")

# 读
print(f"读 {datetime_tag}...")
try:
    vals = datahub.get_rt_value(api, [datetime_tag])
    for v in vals:
        print(f"  {v.get('tagName')} = {v.get('tagValue')} (quality={v.get('quality')})")
except Exception as e:
    print(f"  读失败: {e}")
