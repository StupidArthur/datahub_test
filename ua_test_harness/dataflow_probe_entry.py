"""Stage 3 探针入口：安装 OPC UA 类型兼容别名后调用真实探针。"""
from __future__ import annotations

from tpt_api.types import DataTypes

from ua_test_harness.type_mapping import OPCUA_TO_TPT_DATA_TYPE


def install_type_aliases() -> None:
    """把 OPC UA 类型名作为兼容别名挂到平台 DataTypes 映射。"""
    for opcua_name, platform_key in OPCUA_TO_TPT_DATA_TYPE.items():
        DataTypes.setdefault(opcua_name, DataTypes[platform_key])


def main() -> int:
    install_type_aliases()
    from ua_test_harness.dataflow_probe import main as probe_main

    return probe_main()


if __name__ == "__main__":
    raise SystemExit(main())