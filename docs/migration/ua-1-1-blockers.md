# UA-1-1 Migration Blockers

## UA-1-1-07 数据源有鉴权，配正确凭据

- **Case ID**: UA-1-1-07
- **原始预期**: DataHub 使用 dsExtInfo 中的 username/password 连接带认证的 OPC UA server，alive=true
- **已有代码行为**: 旧 Harness handler 未实现真实认证测试（mock 无鉴权）
- **真实环境观察**: DataHub 接受 dsExtInfo={username, password} 并存储，但启用数据源后 60s 内未变 alive。DataHub 可能不使用 dsExtInfo 中的凭据进行 OPC UA 连接认证。
- **缺少的能力**: DataHub 平台侧 OPC UA 认证连接能力（或正确的字段名/格式尚未确认）
- **尝试过的方法**:
  1. 启动带 asyncua UserNameIdentityToken 认证的 mocker（验证匿名拒绝、正确凭据通过、错误凭据拒绝）
  2. 创建 datasource 时传 ds_ext_info={"username":"u1","password":"p1"}
  3. DataHub 成功存储 dsExtInfo 但连接未成功
- **后续建议**: 确认 DataHub 平台是否支持 OPC UA 用户名密码认证；若支持，确认正确的字段名和格式；若不支持，将此 Case 标记为产品能力缺失
