"""tpt_api 的 ibd-data-hub tag + 历史值用法示例。

运行：
    DATAHUB_BASE_URL=http://... DATAHUB_USER=... DATAHUB_PASSWORD=... python -m tpt_api.examples.datahub
"""

from __future__ import annotations

import logging
import os
import sys

from tpt_api import AlgAPI, DataTypes, TagTypes
from tpt_api import datahub as dh_mod

logging.basicConfig(level=logging.INFO)


def main() -> int:
    base_url = os.environ.get("DATAHUB_BASE_URL", "http://10.10.58.179:31501")
    api = AlgAPI(base_url, timeout=60.0)  # 60s 与父级 common_api.py 默认一致
    api.login(
        os.environ.get("DATAHUB_USER", ""),
        os.environ.get("DATAHUB_PASSWORD", ""),
        "",
    )
    print("登录成功")

    # 1) 注册位号
    try:
        dh_mod.add_tag(api, "demo.t_double", data_type=DataTypes["DOUBLE"],
                       tag_type=TagTypes["一次位号"], ds_id=2, frequency=10)
        print("位号注册成功")
    except Exception as e:
        print(f"[跳过] AddTag: {e}（可能位号已存在）")

    # 2) 全量拉取（含所有 tagType，避免漏掉）
    all_tags = dh_mod.get_all_tags_all_types(api)
    print(f"全量位号 {len(all_tags)} 个")

    # 3) 按名查
    t = dh_mod.get_tag_by_name(api, "demo.t_double")
    if t:
        print(f"缓存命中: {t.get('tagName')}")

    # 4) 历史值导入（异步）—— 准备一个示例 xlsx
    xlsx_path = os.environ.get("SAMPLE_XLSX", "")
    if xlsx_path and os.path.exists(xlsx_path):
        resp = dh_mod.import_tag_value_history(
            api, xlsx_path, ds_id=2,
            start_time="2025-01-01 00:00:00",
            end_time="2025-01-02 00:00:00",
        )
        print(f"导入响应: status={resp['status_code']} code={resp['code']} is_success={resp['is_success']}")
    else:
        print(f"[跳过] SAMPLE_XLSX={xlsx_path!r} 不存在")

    # 5) 历史值查询（验证）
    hist = dh_mod.get_all_history(api, ["demo.t_double"],
                                  "2025-01-01 00:00:00", "2099-12-31 23:59:59")
    print(f"demo.t_double 共 {len(hist['demo.t_double'])} 个数据点")

    # 6) 位号值 4 接口（采集/实时/历史IPage/回写）
    #    采集(collect)与回写(write)的完整可运行示例见 examples/verify_tag_value.py
    t0 = all_tags[0].get("tagName", "") if all_tags else "demo.t_double"
    rt = dh_mod.get_rt_value(api, tag_names=[t0])
    print(f"{t0} 实时值: {rt[0] if rt else None}")
    hp = dh_mod.query_history_value(api, [t0],
                                    "2025-01-01 00:00:00", "2099-12-31 23:59:59",
                                    page=1, page_size=5)
    print(f"{t0} 历史 IPage total={hp.get('total')} size={hp.get('size')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
