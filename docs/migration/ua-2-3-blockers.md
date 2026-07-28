# UA-2-3 Blocker 记录

## UA-2-3-006 导出表头规格偏移

| 字段 | 值 |
|------|-----|
| Case ID | UA-2-3-006 |
| 规格要求 | 21 列（Tag Name ~ Hi EU） |
| 实际结果 | 24 列 |
| 是否稳定复现 | 是（每次导出均 24 列） |
| 影响导入模板兼容性 | 否（导入按语义匹配非按列位置） |

### 实际完整表头

| # | 名称 |
|---|------|
| 0 | Tag Name |
| 1 | Base Tag Name |
| 2 | Tag Type |
| 3 | Datasource Name |
| 4 | Unit |
| 5 | Data Type |
| 6 | Expression |
| 7 | Tag Value |
| 8 | Frequency |
| 9 | High Limit |
| 10 | HH Limit |
| 11 | HHH Limit |
| 12 | Low Limit |
| 13 | LL Limit |
| 14 | LLL Limit |
| 15 | Description |
| 16 | Group Name |
| 17 | Real-time Push |
| 18 | Readonly |
| 19 | Lo EU |
| 20 | Hi EU |
| 21 | None（空表头列，可能是列分隔符） |
| 22 | 当前值 |
| 23 | 质量码 |

### 分析

前 21 列为 canonical 配置字段，与规格完全一致。额外 3 列（空表头、当前值、质量码）是产品追加的运行时信息，不影响导入模板兼容性，因为导入 API 按字段语义而非列位置解析。
