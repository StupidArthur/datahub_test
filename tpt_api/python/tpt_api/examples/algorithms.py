"""tpt_api 的 alg-manager 算法管理用法示例。

运行：
    ALG_BASE_URL=http://... ALG_USER=... ALG_PASSWORD=... python -m tpt_api.examples.algorithms
"""

from __future__ import annotations

import logging
import os
import sys

from tpt_api import AlgAPI
from tpt_api import algorithms as alg_mod

logging.basicConfig(level=logging.INFO)


def main() -> int:
    base_url = os.environ.get("ALG_BASE_URL", "http://10.16.11.1:31501")
    api = AlgAPI(base_url)
    api.login(os.environ.get("ALG_USER", ""), os.environ.get("ALG_PASSWORD", ""), "")
    print("登录成功")

    # 1) 拉全量算法
    all_algos = alg_mod.get_all_algorithms(api)
    print(f"共 {len(all_algos)} 个算法")
    for a in all_algos[:5]:
        print(f"  id={a.get('id')} sourcePath={a.get('sourcePath')}")

    # 2) 按 sourcePath 查
    info = alg_mod.get_by_source_path(api, "spc_pid_identification_analysis.py")
    if info:
        print(f"缓存命中: {info.get('sourcePath')} (id={info.get('id')})")

    # 3) 上传 + 编辑（如果本地有 zip）
    zip_path = "resource/spc_pid_identification_analysis.zip"
    if os.path.exists(zip_path):
        result = alg_mod.upload_file(api, zip_path)
        print(f"上传响应: {result}")
        alg_mod.edit_algorithm(api, source_path="spc_pid_identification_analysis.py")
        print("EditAlgorithm 成功")
    else:
        print(f"[跳过] {zip_path} 不存在")

    # 4) 匹配本地 resource/
    matched = alg_mod.match_local_files(api, "resource")
    exist = sum(1 for m in matched if m["isExist"])
    miss = sum(1 for m in matched if not m["isExist"])
    print(f"本地资源匹配: {exist} 个已存在，{miss} 个未在平台")

    return 0


if __name__ == "__main__":
    sys.exit(main())
