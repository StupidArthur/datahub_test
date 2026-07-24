# UA-1-1 Migration Blockers

## UA-1-1-07 数据源有鉴权，配正确凭据

- **Case ID**: UA-1-1-07
- **原始预期**: DataHub 使用 dsExtInfo 中的 username/password 连接带认证的 OPC UA server，alive=true
- **已有代码行为**:
  - 旧 Harness handler（`ua_test_harness/tests/ua_1/test_datasource.py:247 ua_1_1_07_auth_ok`）：未实现真实认证测试（mock functional 无鉴权），仅在普通 endpoint 上断言 alive=true
  - 旧 Harness precise 实现（`ua_test_harness/ua1_precise.py:555 ext_auth`）：传 `{"username":"uauser","password":"uapass"}`，但仍挂在 functional endpoint（无鉴权），并未真正验证鉴权连接成功
  - 旧 Harness unit 测试同样依赖 functional endpoint 上的 alive=true；只在 abnormal endpoint 存在时尝试断言 alive=false（cases 6/7）
- **tpt_api / Go 现状**:
  - `tpt_api/datahub.py:add_ds_info(..., ds_ext_info={"username": ..., "password": ...})` 已支持，请求体序列化为 `{"data": {"dsName":..., "dsExtInfo":{"username":...,"password":...}}}`
  - `tpt_api/go/datahub_extra_full.go` 同样支持
  - `ua_test_gui/frontend` 仅有 Subject（DataHub 登录）凭据 UI，没有任何 datasource 凭据 UI 入口
  - `ua_test_gui/internal/subject/datahub_extra.go` 与 tpt_api 同形，确认字段名 `dsExtInfo` 一致
- **ua_mocker 现状**:
  - `ua_mocker/server_main.py:_setup_auth` 已实现 `UserNameIdentityToken` 认证；可拒绝匿名、接受正确凭据、拒绝错误凭据
  - `tests/support/mocker_process.py:write_mocker_config(..., auth={enabled,username,password})` 提供测试入口
  - 在没有 `auth` 段时行为与匿名 mocker 完全一致
- **真实环境观察**: DataHub 接受 dsExtInfo={username, password} 并存储，但启用数据源后 60s 内未变 alive
- **可能原因**:
  1. DataHub 平台端 OPC UA 客户端不消费 dsExtInfo 中的凭据（最可能）
  2. 凭据字段名错误：尝试过 `username/password`，尚未尝试 `userName/credential/auth` 等变体
  3. DataHub 期望凭据放在请求体的其他位置（如 HTTP header、单独的 query 字段）
- **缺少的能力**: DataHub 平台侧 OPC UA 认证连接能力（或正确的字段名/格式尚未确认）
- **尝试过的方法**:
  1. 启动带 asyncua UserNameIdentityToken 认证的 mocker（验证匿名拒绝、正确凭据通过、错误凭据拒绝）
  2. 创建 datasource 时传 `ds_ext_info={"username":"u1","password":"p1"}`
  3. DataHub 成功存储 dsExtInfo 但连接未成功
- **代码状态**: 测试以 `pytest.mark.xfail(strict=True, ...)` 标记；strict 确保 DataHub 一旦支持就立即转为失败以便审查
  - xfail **不会** 跳过 Python 的 `finally` 块；当 `wait_until` 在 `try` 中抛 `WaitTimeout` 触发 XFAIL 后，测试仍会进入 `finally` 路径（disable datasource、delete datasource、delete tag、stop mocker）。定向回归（5th phase）已确认 0 残留
- **4th phase 真实环境验证 (2026-07-24)**: 在真实 DataHub 上运行确认 XFAIL 状态；DataHub 接受 `ds_ext_info` 但 60s 内未变 alive；标记与观察一致
- **后续建议**:
  - 等待 DataHub 平台支持 OPC UA datasource 认证
  - 一旦支持，按真实字段名调整 `tpt_api.add_ds_info` 的 `ds_ext_info` schema，并增加 MockTransport 单元测试覆盖凭据 payload
  - GUI 端需要新增 datasource 凭据编辑 UI（当前 SubjectPage 仅承载 DataHub 登录凭据）

## UA-1-1-10 / UA-1-1-11 好值质量码字段名

- **观察**: 旧 Harness `ua_test_harness/ua1_precise.py:556-557` 同时使用 `goodQualityCode`（int）与 `goodQuality` 两个字段名：
  ```python
  ext_quality_192 = {"goodQualityCode": 192, "goodQuality": 192}
  ext_quality_0 = {"goodQualityCode": 0, "goodQuality": 0}
  ```
- **当前测试**: `tests/integration/ua1/test_connection_establishment.py` UA-1-1-10/11 仅传 `goodQuality: "192"` / `goodQuality: "0"`（字符串）
- **风险**: 若 DataHub 实际只识别 `goodQualityCode`（int），当前测试可能误报"配置成功"。建议在真实环境同时验证两个字段名的接受情况
- **代码状态**: 未阻塞，但需在 native-pytest-comparison.md 中记录差异