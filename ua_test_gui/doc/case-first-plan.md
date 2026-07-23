# Case-first 开发顺序

## 当前优先级

在 419 条文档 Case 全部完成可执行实现之前，冻结新的 GUI 功能开发和 GUI 联调。

冻结不代表删除现有 GUI、Go 编排或 SQLite 代码；这些代码保留，只停止扩展。仅允许修复会阻断命令行 Case 执行、结果落盘或清理的底层缺陷。

## 总量与分组

| 领域 | Case 数 |
|---|---:|
| UA-1 数据源 | 56 |
| UA-2 位号 | 265 |
| UA-3 采集、实时、写、历史、性能 | 98 |
| **总计** | **419** |

机器可读进度以 `python -m ua_test_harness.case_inventory` 生成的覆盖矩阵为准，不再使用手工估算。

## 实现顺序

1. 先让 Stage 3 最小真实数据流通过。
2. 生成并校验 419 条 Case 清单，修复文档 ID 与代码 ID 不一致。
3. 完成 UA-1 的 56 条。
4. 完成 UA-2 的 265 条。
5. 完成 UA-3 的 98 条。
6. catalog 中 419 条全部为 `IMPLEMENTED` 后，再恢复 GUI 联调。

每批建议 10～25 条，按同一 fixture、同一 Mock 能力或同一 API 分组。每批必须同时提交实现、单测、CLI 运行配置和真实执行报告。

## “已实现”的判定

一条 Case 只有同时满足以下条件，才能标记为 `IMPLEMENTED`：

- ID 与 `ua_test_harness/test_cases/*.md` 完全一致；
- `@case` 元数据包含章节、标题、类型、超时、文档路径和资源约束；
- 函数体包含前置条件、动作和文档要求的断言；
- 不使用空函数、固定 PASS、吞异常或降低阈值；
- 创建的 TPT 数据源、位号、分组和 Mock 状态均登记 LIFO 清理；
- 失败能明确分类为 FAIL、ERROR、BLOCKED、OBSERVED、MEASURED 或 CLEANUP_FAILED；
- CLI 可以按 Case ID 单独运行；
- 对复用 fixture 和映射逻辑有单元测试。

真实环境尚未运行或因环境阻塞的 Case 可以是 `IMPLEMENTED`，但不能标记为 `VERIFIED`。

## GUI 恢复条件

同时满足以下条件后恢复 GUI 工作：

- 覆盖矩阵 `documented=419`；
- 覆盖矩阵 `implemented=419`；
- 无重复文档 ID、无格式错误、无代码孤儿 ID；
- Python 单元测试通过；
- 全量 catalog 可导出；
- 各章节至少完成一轮 CLI 真实执行并保留报告；
- 所有运行产生的资源均有残留检查。