# UA-2-1 Migration Blockers

## UA-2-1-044 Byte 最大值 255 被拒绝

- **Case ID**: UA-2-1-044
- **原始预期**: Byte 节点可写入 0~255，三端一致
- **真实环境行为**:
  - 写入 0 → 成功
  - 写入 255 → DataHub 返回 `[A0400]Write tag value type convert failed, target type: BYTE`
  - `tagNames` 为空，`failMsg` 含转换错误
- **可能原因**: DataHub 将 OPC UA Byte (0–255) 映射为 Java 有符号 `byte` (–128 to 127)，255 超出范围
- **缺少的能力**: DataHub 平台侧 OPC UA 无符号类型（Byte/UInt16）的正确范围转换
- **代码状态**: `test_byte_min_max` 保持真实 FAIL，用于持续暴露产品限制

## UA-2-1-048 UInt16 最大值 65535 被拒绝

- **Case ID**: UA-2-1-048
- **原始预期**: UInt16 节点可写入 0~65535，三端一致
- **真实环境行为**:
  - 写入 0 → 成功
  - 写入 65535 → DataHub 返回 `[A0400]Write tag value type convert failed, target type: U_SHORT`
  - `tagNames` 为空，`failMsg` 含转换错误
- **可能原因**: DataHub 内部映射 U_SHORT 时无法处理最大值 65535（可能为有符号类型或边界检查问题）
- **缺少的能力**: DataHub 平台侧无符号类型 U_SHORT 的正确最大值处理
- **代码状态**: `test_uint16_min_max` 保持真实 FAIL，用于持续暴露产品限制

## UA-2-1-052 UInt32 最大值 4294967295 被拒绝

- **Case ID**: UA-2-1-052
- **原始预期**: UInt32 节点可写入 0~4294967295，三端一致
- **真实环境行为**:
  - 写入 0 → 成功
  - 写入 4294967295 → DataHub 返回 `[A0400]Write tag value type convert failed, target type: U_INT`
  - `tagNames` 为空，`failMsg` 含转换错误
  - 写入 0 时三端一致验证通过
- **可能原因**: DataHub 内部映射 U_INT 时无法处理无符号整型最大值 4294967295（可能通过 JSON 传输时被截断或有符号化）
- **缺少的能力**: DataHub 平台侧无符号类型 U_INT 的正确最大值处理（参见 UA-2-1-044/048 同类问题）
- **代码状态**: `test_uint32_min_max` 保持真实 FAIL，用于持续暴露产品限制
