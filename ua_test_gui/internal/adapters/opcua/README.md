# OPC UA 源端 Client（gopcua 封装）

本目录封装 `github.com/gopcua/opcua`，实现 `verify.SourceClient` 接口，用于：

- 验证 mock 节点存在/可读/可写
- 写源端值后查 TPT 传播
- 就绪探针（Discover）

依赖方向：`opcua -> verify`（仅实现接口），不反向依赖 verify。

---

## 1. 已解决的问题

### 1.1 Write 必须显式调用 `DataValue.UpdateMask()`

**问题现象**：直接构造 `&ua.DataValue{Value: v}` 并写入，服务端返回 `BadTypeMismatch`。

**根因**：gopcua 编码时按 `EncodingMask` 决定是否序列化 `Value` 字段。如果 `UpdateMask()` 没被调用，`mask=0`，`Value` 不会被编码，服务端收到 `VariantType=Null`，与目标节点类型不匹配。

**代码位置**：`client.go:111-114`

```go
v, err := ua.NewVariant(value)
dv := &ua.DataValue{Value: v}
dv.UpdateMask() // 必须显式置位，否则 Value 不被编码
```

**相关 memory**：[[gopcua-datavalue-encodingmask]]

---

### 1.2 端口监听 ≠ UA Server 就绪

**问题现象**：mock 子进程刚启动时端口已经打开，但 UA 协议栈还没初始化完，此时直接 Connect/Read 会失败。

**根因**：asyncua 启动分阶段：先 bind TCP 端口，再构建地址空间、注册 endpoint。只看端口会被假就绪误导。

**解决方案**：`Discover()` 通过 Browse `ObjectsFolder`（NodeID `i=85`）并检查目标 namespace 下是否有节点，确认 UA 服务真正可访问。

**代码位置**：`client.go:166-199`

---

### 1.3 单节点读写的完整错误处理

**问题现象**：早期只检查 `err != nil`，漏掉 `StatusCode` 非 OK、结果为空、`Value` 为 nil 等情况。

**当前处理**：

- `Read`：检查 `resp.Results` 长度、`dv.Status`、`dv.Value` 是否为 nil
- `Write`：检查 `resp.Results` 长度与 `StatusOK`

**代码位置**：`client.go:76-128`

---

## 2. 优化点

### 2.1 批量读 `ReadMany`

将多个节点打包到一个 `ReadRequest` 中，减少网络往返。

**代码位置**：`client.go:130-162`

---

### 2.2 懒连接 + 幂等 Connect

`ensureConnected` 在每次操作前检查连接；`Connect` 在 `c.client != nil` 时直接返回 nil，避免重复建连。

**代码位置**：`client.go:43-73`

---

### 2.3 工厂解耦

`factory.go` 实现 `verify.SourceClientFactory`，让 `verify.Service` 通过接口创建 client，不直接 import gopcua。

**代码位置**：`factory.go`

---

### 2.4 无安全模式默认配置

ua_mocker 不启用加密/签名，client 默认使用 `MessageSecurityModeNone`，避免握手失败。

**代码位置**：`client.go:47`

---

## 3. 使用约定

- `NewUaSourceClient(endpoint, namespaceIndex)` 创建未连接 client；namespaceIndex 默认 1。
- `Connect(ctx)` 显式建立连接；也可以让 `Read`/`Write`/`Discover` 自动连接。
- 使用完毕后调用 `Close(ctx)` 释放连接。
- 所有节点名按 `ns=<namespaceIndex>;s=<name>` 构造字符串 NodeID。

---

## 4. 注意事项

- `UpdateMask()` 是 gopcua 的坑点，后续若新增 Write 相关封装（如批量写）必须同步调用。
- `Discover` 只 Browse 直接挂在 ObjectsFolder 下的节点；分容器后节点挂在子 Object 下，但 Discover 仅用于就绪探针（确认 server 已初始化），不用于枚举全部节点。
- 当前 client 无连接池/重连策略，短时间多次操作建议调用方复用同一 client 实例。
