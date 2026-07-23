# ua_mocker 用户手册

> 把 YAML 组态变成一个 OPC UA Mock Server：按周期自动变化 / 客户端可写，工业客户端（UAExpert / KEPServer / SCADA 等）连上来就能读到值、写入值。
>
> **当前版本**：v1
>
> designed by yzc

---

## 1. 这是什么

ua_mocker 是一款通用的、YAML 配置驱动的 OPC UA Mock Server：根据一份组态文件创建任意数量、任意类型的变量节点，挂在 `Objects/mocker` 容器下，启动即可被客户端连接。节点支持按 `cycle` 周期自动变化（bool 翻转 / 数字 0–99 锯齿波 / 字符串 a–z 循环 / 时间 +1s），也可声明为可写让客户端写入。

适合客户端测试、协议联调、SCADA 集成验证等场景。

---

## 2. 使用入门

ua_mocker 是命令行工具，**只接受唯一一个位置参数**：组态文件路径。

### 2.1 命令格式

```
ua_mocker <config.yaml>
```

源码运行：

```cmd
python main.py config.yaml
```

打包运行（Windows）：

```cmd
ua_mocker.exe config.yaml
```

打包运行（Linux）：

```bash
./ua_mocker config.yaml
```

> 打包版与源码版参数完全一样，下面所有示例都按打包版写。

**一个具体的案例**：用仓库自带的 `config_example.yaml` 启动，监听 18950 端口：

```cmd
ua_mocker.exe config_example.yaml
```

控制台会输出：

```
开始构建节点树
构建完成
服务启动成功 opc.tcp://0.0.0.0:18950/ua_mocker/
节点数量: 1024
designed by yzc
```

### 2.2 停止

按 `Ctrl + C` 中断。

### 2.3 客户端连上去

- **默认端点**：`opc.tcp://127.0.0.1:18950/ua_mocker/`
- **跨机**：把 `127.0.0.1` 换成 ua_mocker 运行机的 IP，端口随 YAML 的 `port` 改变。

UAExpert 输入上述地址即可看到所有节点。

---

## 3. 功能介绍

### 3.1 总述 — 工作流程

1. 启动时加载 YAML 组态，做必填字段校验
2. 在 OPC UA 命名空间 `ns=<namespace_index>` 下创建容器对象 `mocker`
3. 按 `nodes` 列表逐条创建变量节点，每个节点按 `count` 展开为 `name_1` … `name_N`
4. `change: true` 的节点加入周期更新队列，按 `cycle` 毫秒推一个新值
5. `writable: true` 的节点允许客户端写入，asyncua 负责持久化写值
6. 客户端可订阅或读取，OPC UA 通信在 asyncio 事件循环里跑

整个流程在 **asyncio 事件循环**里跑，单进程。

### 3.2 支持的操作系统

- **Windows** 10 / 11（64 位）
- **Linux**：CentOS、Ubuntu

打包产物是单文件，目标机不需要装 Python。

> ua_mocker 默认端口 `18950` 与 ua_player 默认端口冲突，**不能在同机同时启动这两个工具的默认实例**。要同机共存请改其中一份的 `port`。

### 3.3 支持的 OPC UA 类型（type 字段）

`type` 字段接受以下 13 种类型，大小写敏感：


| type 取值  | 说明         | 起始值（change=true）  | default 示例（change=false） |
| -------- | ---------- | ---------------- | --------------------- |
| Boolean  | 布尔         | `false`          | `true` / `false`      |
| SByte    | 有符号 8 位整数  | `0`              | `0`                   |
| Byte     | 无符号 8 位整数  | `0`              | `0`                   |
| Int16    | 有符号 16 位整数 | `0`              | `0`                   |
| UInt16   | 无符号 16 位整数 | `0`              | `0`                   |
| Int32    | 有符号 32 位整数 | `0`              | `0`                   |
| UInt32   | 无符号 32 位整数 | `0`              | `0`                   |
| Int64    | 有符号 64 位整数 | `0`              | `0`                   |
| UInt64   | 无符号 64 位整数 | `0`              | `0`                   |
| Float    | 32 位浮点     | `0.0`            | `0.0`                 |
| Double   | 64 位浮点     | `0.0`            | `0.0`                 |
| String   | 字符串        | `"a"`            | `""` 或任意字符串           |
| DateTime | 日期时间       | `2025-01-01T00:00:00` | `"2025-01-01T00:00:00Z"` |

**不**支持：数组、结构体、ByteString、LocalizedText、NodeId 等其它 OPC UA 类型。如果填了未列出的类型名，启动时会直接报错并退出。

### 3.4 change 行为

`change: true` 的节点按 `cycle` 毫秒周期自动推一个新值：


| 类型                       | 变化规则                                  |
| ------------------------ | ------------------------------------- |
| Boolean                  | true / false 翻转                        |
| 数值（SByte / Byte / Int* / UInt* / Float / Double） | 0–99 锯齿波，步长 1，到 99 后回到 0；浮点也按整数步进 |
| String                   | 单字符在 a–z 之间循环，每周期切到下一个字母            |
| DateTime                 | 每周期在时间上 +1 秒                          |
| 其它未列出的类型                  | **不参与** change，启动时写日志警告但不会更新值         |

> 只有 Boolean / 数字 / String / DateTime 这 4 类定义了 change 行为，其它类型的 `change: true` 节点会被加入更新队列但实际不会变。如需变化，建议改用上述 4 种之一。

`change: false` 的节点值固定，**不参与**周期更新。`default` 字段在 `change: false` 时必填，指定节点的初始值。

### 3.5 writable 行为


| YAML `writable` | 客户端能读 | 客户端能写    |
| ------------- | ----- | ------- |
| `false`       | ✅     | ❌      |
| `true`        | ✅     | ✅（写后持久化） |

**可写节点的具体行为**：

- **change 行为冲突**：`writable: true` 与 `change: true` **不可同时为 true**，组态校验会直接拒绝（因为客户端写入会立刻被下一个周期的 change 覆盖）。如需可写必须把 `change` 设为 `false`。
- **默认值**：`change: false` 时取 `default` 字段的值；类型不匹配时做强制转换。
- **写后持久化**：asyncua 维护节点值状态，**进程不重启就一直保留**写入值；**重启进程后恢复为 `default`**（asyncua 默认行为，不写磁盘）。
- **写值回调**：客户端写入时控制台会多一行 `写值 NodeId=... Value=...`，并写入日志文件。

### 3.6 OPC UA 地址空间

- **容器对象**：`ns=<namespace_index>;s=mocker`（在 `Objects` 下）
- **变量节点**：`ns=<namespace_index>;s=<name><i>`，其中 `i` 是 1..`count` 的后缀

浏览路径：

```
Objects
  └── mocker
       ├── bool_ch_1
       ├── bool_ch_2
       ├── double_ch_1
       ├── double_ch_2
       └── ...
```

例如 `namespace_index: 1`、`name: "node_float_"`、`count: 3` → 三个节点 `ns=1;s=node_float_1`、`ns=1;s=node_float_2`、`ns=1;s=node_float_3`，挂在 `Objects/mocker` 下。

### 3.7 多实例

可以同时跑多个 ua_mocker，给不同的 `port`：

```cmd
ua_mocker.exe config_a.yaml    :: 使用 config_a 里的 port
ua_mocker.exe config_b.yaml    :: 使用 config_b 里的 port
```

> 同一机器上两个实例的 `port` 必须不同，否则后启动的会因端口占用失败。各实例相互独立、监听不同端口，客户端可分别连。

---

## 4. 准备输入：YAML 组态

### 4.1 顶层字段


| 键名              | 类型  | 必填  | 说明                                       |
| --------------- | --- | --- | ---------------------------------------- |
| server          | 字符串 | 是   | 监听地址，如 `"0.0.0.0"` 表示本机所有网卡              |
| port            | 整数  | 是   | 端口号，如 `18950`；与其它 OPC UA 服务冲突时修改       |
| cycle           | 整数  | 是   | change=true 节点的更新周期（毫秒），如 `1000` 表示 1 秒 |
| namespace_index | 整数  | 是   | OPC UA 命名空间索引，如 `1`；客户端看到的 ns 与此一致    |
| nodes           | 列表  | 是   | 节点定义列表，见 4.2 节                           |

> `namespace_index` 由组态指定，**不会自动分配**。如果同一客户端连多台 OPC UA Server，需要保证各自的 `namespace_index` 不冲突（或在客户端侧区分）。

### 4.2 节点字段（nodes 中每一项）


| 字段       | 类型    | 必填   | 说明                                                  |
| -------- | ----- | ---- | --------------------------------------------------- |
| name     | 字符串   | 是    | 名称前缀，与下标拼接得到节点名，如 `"node_float_"` + 1 → `node_float_1` |
| type     | 字符串   | 是    | OPC UA 数据类型，见 3.3 节                                 |
| count    | 整数    | 是    | 该 name 下生成的节点个数，节点名为 name_1 … name_count          |
| default  | 视类型而定 | 条件必填 | 初始值。**仅当 change=false 时必填**；change=true 时不要写        |
| change   | 布尔    | 是    | 是否按 cycle 周期自动变化                                    |
| writable | 布尔    | 是    | 是否允许客户端写                                            |

### 4.3 校验

启动时会对组态做基本校验，**以下情况会直接报错并退出**（不打印文件级 stacktrace）：

- YAML 文件不存在 → `FileNotFoundError`
- YAML 解析失败 → `ValueError: YAML 解析失败: ...`
- 顶层缺少 `server` / `port` / `cycle` / `namespace_index` / `nodes` → `组态缺少必填项: <key>`
- `nodes` 不是列表 → `组态中 nodes 必须为列表`
- 节点项不是字典 → `nodes[<i>] 必须为键值对`
- 节点项缺少 `name` / `type` / `count` / `change` / `writable` → `nodes[<i>] 缺少必填项: <k>`
- `change=false` 但缺 `default` → `nodes[<i>] change=false 时必须提供 default`
- `type` 不在 13 种支持列表里 → `不支持的类型: <name>，支持: [...]`
- 端口被占用 → 启动失败（asyncua 抛异常，日志记录）

### 4.4 一个最小可用的 YAML

3 个不变化、可写的 Float 节点：

```yaml
server: "0.0.0.0"
port: 18950
cycle: 1000
namespace_index: 1

nodes:
  - name: "node_float_"
    type: Float
    count: 3
    default: 0.0
    change: false
    writable: true
```

得到节点：`ns=1;s=node_float_1`、`ns=1;s=node_float_2`、`ns=1;s=node_float_3`，初始值 0.0，客户端可写。

### 4.5 一个完整可用的 YAML（覆盖全部 13 种类型）

```yaml
server: "0.0.0.0"
port: 18950
cycle: 1000
namespace_index: 1

nodes:
  # Boolean：2 个自变化只读 + 2 个固定可写
  - name: "bool_ch_"
    type: Boolean
    count: 2
    change: true
    writable: false
  - name: "bool_wr_"
    type: Boolean
    count: 2
    default: false
    change: false
    writable: true

  # SByte
  - name: "sbyte_ch_"
    type: SByte
    count: 2
    change: true
    writable: false
  - name: "sbyte_wr_"
    type: SByte
    count: 2
    default: 0
    change: false
    writable: true

  # Byte
  - name: "byte_ch_"
    type: Byte
    count: 2
    change: true
    writable: false
  - name: "byte_wr_"
    type: Byte
    count: 2
    default: 0
    change: false
    writable: true

  # Int16
  - name: "int16_ch_"
    type: Int16
    count: 2
    change: true
    writable: false
  - name: "int16_wr_"
    type: Int16
    count: 2
    default: 0
    change: false
    writable: true

  # UInt16
  - name: "uint16_ch_"
    type: UInt16
    count: 2
    change: true
    writable: false
  - name: "uint16_wr_"
    type: UInt16
    count: 2
    default: 0
    change: false
    writable: true

  # Int32
  - name: "int32_ch_"
    type: Int32
    count: 2
    change: true
    writable: false
  - name: "int32_wr_"
    type: Int32
    count: 2
    default: 0
    change: false
    writable: true

  # UInt32
  - name: "uint32_ch_"
    type: UInt32
    count: 2
    change: true
    writable: false
  - name: "uint32_wr_"
    type: UInt32
    count: 2
    default: 0
    change: false
    writable: true

  # Int64
  - name: "int64_ch_"
    type: Int64
    count: 2
    change: true
    writable: false
  - name: "int64_wr_"
    type: Int64
    count: 2
    default: 0
    change: false
    writable: true

  # UInt64
  - name: "uint64_ch_"
    type: UInt64
    count: 2
    change: true
    writable: false
  - name: "uint64_wr_"
    type: UInt64
    count: 2
    default: 0
    change: false
    writable: true

  # Float
  - name: "float_ch_"
    type: Float
    count: 2
    change: true
    writable: false
  - name: "float_wr_"
    type: Float
    count: 2
    default: 0.0
    change: false
    writable: true

  # Double（按需放大 count 模拟高密度标签）
  - name: "double_ch_"
    type: Double
    count: 100
    change: true
    writable: false
  - name: "double_wr_"
    type: Double
    count: 2
    default: 0.0
    change: false
    writable: true

  # String
  - name: "string_ch_"
    type: String
    count: 2
    change: true
    writable: false
  - name: "string_wr_"
    type: String
    count: 2
    default: ""
    change: false
    writable: true

  # DateTime
  - name: "datetime_ch_"
    type: DateTime
    count: 2
    change: true
    writable: false
  - name: "datetime_wr_"
    type: DateTime
    count: 2
    default: "2025-01-01T00:00:00Z"
    change: false
    writable: true
```

行为摘要：

- `xxx_ch_*`：每 1 秒按各自规则自变化（bool 翻转 / 数字 0–99 锯齿 / 字符串 a–z / 时间 +1s），只读。
- `xxx_wr_*`：固定为 `default`，客户端可写，写后保持直到下次写入或重启。

> 仓库根目录的 `config_example.yaml` 是这份模板的变体（Double 的 `count` 放大到 1002 模拟高密度标签场景），可以直接用作模板或拷走即用。

### 4.6 DateTime 的 default 格式

`default` 字段支持以下写法（ISO 8601）：

- `"2025-01-01T00:00:00Z"`（UTC）
- `"2025-01-01T00:00:00+08:00"`（带时区）
- `"2025-01-01T00:00:00"`（naive，视为本地时间）

---

## 5. 控制台与日志

### 5.1 控制台输出

控制台**仅**会输出以下信息（无其他日志）：

- `开始构建节点树`
- `构建完成`
- `服务启动成功 opc.tcp://<地址>:<端口>/ua_mocker/`
- `节点数量: <数量>`
- `designed by yzc`
- 客户端对可写节点写值时：`写值 NodeId=... Value=...`

其余日志（组态加载、错误、asyncua 异常）只写入日志文件，不输出到控制台。

### 5.2 日志文件

- **位置**：执行程序所在目录（脚本方式为 `ua_mocker/` 目录，打包后为 exe 所在目录）
- **文件名**：`ua_mocker_YYYYMMDD.log`（按天）
- **内容**：组态加载、端点、命名空间、服务器启动、客户端写值等完整日志

> 当天多次启动会持续往同一个日志文件追加；按天切换文件便于按日期归档。

---

## 6. 已知限制

- **change 类型有限**：只有 Boolean / 数值 / String / DateTime 4 类定义了 change 行为，其它类型即使配了 `change: true` 也不会变化
- **writable 与 change 互斥**：`writable: true` 的节点必须把 `change` 设为 `false`，否则客户端写入会被下一个周期覆盖
- **端口冲突**：默认 `18950` 与 ua_player 默认端口冲突，**同机不能同时跑两份默认实例**，要共存请改 `port`
- **namespace_index 不自动分配**：需要组态指定，与其它 OPC UA Server 共存时要在客户端侧区分 ns
- **写值不持久化到磁盘**：进程重启后所有可写节点恢复为 `default`（asyncua 默认内存行为）
- **仅支持匿名访问**：未实现用户权限与安全策略
- **不支持的 OPC UA 类型**：数组、结构体、ByteString、LocalizedText、NodeId 等，配了会启动报错

---

## 7. 常见问题

- **启动报「组态缺少必填项」**：检查 `server` / `port` / `cycle` / `namespace_index` / `nodes` 是否齐全
- **启动报「缺少 default」**：该节点 `change: false` 但没填 `default`，补上即可
- **启动报「不支持的类型」**：`type` 拼写错了或用了不支持的类型，参考 3.3 节
- **客户端连不上**：检查防火墙、组态的 `server`/`port`、本机测试用 `127.0.0.1`
- **看不到节点**：浏览器展开 `Objects → mocker`，节点都在 `mocker` 下
- **不知道 NodeId**：按 `ns=<namespace_index>;s=<name><下标>` 拼接，例如 `ns=1;s=double_ch_42`

---

designed by yzc