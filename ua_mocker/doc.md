# OPC UA Server & Data Mock Server

- Python 3.13，PyInstaller 打包
- 支持 Windows / CentOS / Ubuntu
- 无界面，命令行启动，**唯一一个命令行参数**：组态文件路径

---

## 组态文件

- **格式**：YAML
- **内容要点**：
  - `server`：监听地址，如 `"0.0.0.0"`
  - `port`：端口，如 `18950`
  - `cycle`：数据变化周期（ms），如 `1000`
  - `namespace_index`：OPC UA 命名空间索引，如 `1`
  - `nodes`：节点列表

### 节点项

| 字段 | 说明 |
|------|------|
| name | 名称前缀，与 count 拼接得到 BrowseName/DisplayName/NodeId 中的字符串部分 |
| type | OPC UA 数据类型：Boolean, SByte, Byte, Int16, UInt16, Int32, UInt32, Int64, UInt64, Float, Double, String, DateTime |
| count | 该 name 下节点个数，生成 name_1 … name_count |
| default | 初始值，**仅当 change 为 false 时有效**；change 为 true 时不需要 |
| change | 是否按周期自动变化 |
| writable | 是否允许客户端写；写成功后持久化，下次读返回写入值 |

### NodeId / BrowseName / DisplayName

- 统一使用「配置中 name + 下标」的字符串，例如 `node_float_1`。
- NodeId 形式：`ns=<namespace_index>;s=<name><i>`，命名空间索引与组态中的 `namespace_index` 一致（如配置 1 则客户端看到 ns=1）。

---

## change == true 时的规则

- **周期**：统一使用组态中的 `cycle`（毫秒）。
- **Boolean**：每个周期在 true / false 之间翻转，与 cycle 对齐。
- **数值类型**：0~99 锯齿波，步长 1，周期为 cycle。
- **String**：单字符 a~z 循环，周期为 cycle。

---

## 安全与日志

- **用户权限**：暂不实现（匿名访问）。
- **日志**：输出到**执行程序所在目录**下的日志文件。
