# 测试用例规格目录

本目录是测试用例规格的**唯一事实源**。

## 说明

- 本目录下的 `UA-*.md` 文件是测试规格文档，不是可执行测试代码。
- Case ID（如 `UA-1-1-01`）是规格与实现之间的映射主键。
- 修改标题、步骤、预期结果**不会**自动修改 runtime 实现。
- 修改 Case ID 时**必须**同步检查对应的 runtime handler。
- GUI（`ua_test_gui`）只消费 catalog 或规格数据，不拥有测试规格。
- 不允许在其他目录维护第二份测试用例。

## 目录结构

```text
ua_test_harness/test_cases/
├── UA-1-1.md ~ UA-1-6.md   # UA-1 数据源连接/启停/恢复
├── UA-2-1.md ~ UA-2-5.md   # UA-2 位号管理
└── UA-3-1.md ~ UA-3-6.md   # UA-3 历史数据/采集
```

## 使用方式

- Harness 通过 `ua_test_harness.case_inventory.default_test_cases_dir()` 定位本目录。
- catalog 导出：`python -m ua_test_harness.cli catalog --output <path>`
- inventory 检查：`python -m ua_test_harness.case_inventory --repo-root . --expected-total 419 --output <path>`
