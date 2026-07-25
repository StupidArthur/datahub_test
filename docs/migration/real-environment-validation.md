# 真实环境验证记录

## 环境摘要

- 真实 DataHub 环境
- Windows 开发机
- 远程可达 OPC UA endpoint

本阶段使用与生产对齐的 DataHub + OPC UA 集成环境，串行执行 24 条
原生 pytest Case。结果用于验证迁移代码在真实产品行为下的语义正确性、
cleanup 安全性和恢复路径。

具体地址与凭据**未写入**本仓库（凭据安全规则：禁止将密码、token、
Authorization header 写入仓库任何文件）。本阶段在当前 PowerShell 进程
环境变量中临时设置 `DATAHUB_*` 与 `UA_MOCKER_ENDPOINT`，并通过唯一前缀
`DATAHUB_TEST_PREFIX=pytest_native_<runId>_` 隔离本轮资源。

## 执行摘要

| 维度 | 数量 |
|------|------|
| 总 Case 数 | 24 |
| PASS | 23 |
| FAIL | 0 |
| XFAIL | 1 (UA-1-1-07) |
| XPASS | 0 |
| SKIP | 0 |
| ERROR | 0 |

UA-1-1-07 标记为 `pytest.mark.xfail(strict=True, ...)`，原因详见
`docs/migration/ua-1-1-blockers.md`：DataHub 平台不消费 `dsExtInfo`
中的 OPC UA username/password。

## 每条 Case

| Case ID | nodeid | 结果 | 耗时 | 主要观察 | cleanup |
|---------|--------|------|------|----------|---------|
| UA-1-1-01 | tests/integration/ua1/test_connection_establishment.py::test_normal_connection_no_path | PASS | ~2s | url 无 path 时正常；RT 192 | ok |
| UA-1-1-02 | tests/integration/ua1/test_connection_establishment.py::test_normal_connection_with_path | PASS | ~2s | url 带 path 时正常 | ok |
| UA-1-1-03 | tests/integration/ua1/test_connection_establishment.py::test_two_url_formats | PASS | ~5s | 两条 ds 都 alive，tag 独立采集 | ok |
| UA-1-1-04 | tests/integration/ua1/test_connection_establishment.py::test_unreachable_address | PASS | ~30s | 不可达地址 30s 内持续 false（已修正 host 改为 10.30.70.77） | ok |
| UA-1-1-05 | tests/integration/ua1/test_connection_establishment.py::test_offline_to_online | PASS | ~95s | 动态端口停→起后 ds 恢复 alive、RT 出现 | ok |
| UA-1-1-06 | tests/integration/ua1/test_connection_establishment.py::test_auth_required_no_creds | PASS | ~10s | 真实 UserNameIdentityToken 拒绝匿名 | ok |
| UA-1-1-07 | tests/integration/ua1/test_connection_establishment.py::test_auth_correct_creds | XFAIL | 60s | DataHub 平台能力缺失 | finally 已执行；datasource、tag 和动态 mocker 无残留 |
| UA-1-1-08 | tests/integration/ua1/test_connection_establishment.py::test_no_auth_extra_creds | PASS | ~3s | 多余凭据不影响匿名连接 | ok |
| UA-1-1-09 | tests/integration/ua1/test_connection_establishment.py::test_quality_default | PASS | ~3s | RT quality=192 默认 | ok |
| UA-1-1-10 | tests/integration/ua1/test_connection_establishment.py::test_quality_192 | PASS | ~3s | 配置 goodQuality=192 后 RT quality=192 | ok |
| UA-1-1-11 | tests/integration/ua1/test_connection_establishment.py::test_quality_zero | PASS | ~3s | 配置 goodQuality=0 后 RT 正常 | ok |
| UA-1-1-12 | tests/integration/ua1/test_connection_establishment.py::test_duplicate_url_rejected | PASS | <1s | 重复地址抛 TptAPIError code=A0001 | ok |
| UA-1-2-01 | tests/integration/ua1/test_lifecycle_control.py::test_disable_running_datasource | PASS | ~3s | disable 后 RT 抛 TptAPIError | ok |
| UA-1-2-02 | tests/integration/ua1/test_lifecycle_control.py::test_rt_state_after_disable | PASS | ~3s | disable 后 RT 抛 TptAPIError（修正前是 fake-data）| ok |
| UA-1-2-03 | tests/integration/ua1/test_history_lifecycle.py::test_history_stops_after_disable | PASS | ~180s | disable 后 90s 宽限期内历史条数稳定（增加 grace 到 90s）| ok |
| UA-1-2-04 | tests/integration/ua1/test_lifecycle_control.py::test_reenable_disabled_datasource | PASS | ~2s | enable 后 RT quality 恢复 | ok |
| UA-1-2-05 | tests/integration/ua1/test_history_lifecycle.py::test_history_resumes_after_enable | PASS | ~180s | enable 后 ~90s 出现新历史点 | ok |
| UA-1-2-06 | tests/integration/ua1/test_lifecycle_control.py::test_repeat_enable | PASS | <1s | 重复 enable 不抛错 | ok |
| UA-1-2-07 | tests/integration/ua1/test_lifecycle_control.py::test_repeat_disable | PASS | <1s | 重复 disable 不抛错 | ok |
| UA-1-2-08 | tests/integration/ua1/test_lifecycle_control.py::test_multiple_start_stop_cycles | PASS | ~3s | 2 轮 disable→enable 循环 | ok |
| UA-1-3-01 | tests/integration/ua1/test_recovery_and_reconnect.py::test_disconnect_detection_latency | PASS | ~50s | 停 mocker 后 alive→false 延迟，RT 抛 TptAPIError | ok |
| UA-1-3-02 | tests/integration/ua1/test_recovery_and_reconnect.py::test_reconnect_recovery_latency | PASS | ~60s | 重启 mocker 后 alive→true，RT 恢复 | ok |
| UA-1-3-06 | tests/integration/ua1/test_recovery_and_reconnect.py::test_short_disconnect_recovery | PASS | ~30s | 短断连后立即恢复；RT 重连后短暂消失需 retry | ok |
| UA-1-3-07 | tests/integration/ua1/test_recovery_and_reconnect.py::test_long_disconnect_recovery | PASS | ~150s | 30s 长断连后仍能恢复 | ok |

## 性能观察

| 指标 | 观测值 |
|------|--------|
| 连接建立延迟（alive=true）| 首次约 2-5s；动态端口重连约 30-60s |
| 断开检测延迟（alive→false）| 约 2-5s |
| RT 不可用延迟 | 与 alive→false 几乎同步 |
| 重连恢复延迟（alive→true）| 约 5-10s |
| 历史恢复延迟 | enable 后约 60-90s 出现首个历史点 |
| 异步落库宽限期 | disable 后约 60-90s |

## 环境阻塞与已修复问题

### 1. UA-1-1-04 不可达地址使用 `127.0.0.1` 错误

**症状**：`127.0.0.1` 是 DataHub 远端主机自己的 loopback，不是开发机。

**修复**：`tests/integration/ua1/test_connection_establishment.py` 改为
使用 `settings.mocker_endpoint` 解析出的 host（默认 10.30.70.77），与
DataHub 视角一致。

### 2. UA-1-2-03/05 历史查询时间字段为本地时间

**症状**：DataHub 历史 API 期望 `yyyy-MM-dd HH:mm:ss` 格式的本地时间；
UTC 字符串导致窗口下溢、`total=0` 静默返回。

**修复**：`_now_local_str()` 使用 `datetime.now()`（本地时间）；窗口
`beg` 同样使用本地时间；baseline 与 re-enable 等待 240s。

### 3. DataHub 历史异步持久化延迟 60-90 秒

**症状**：新 tag 创建后立即查询历史返回 0；首个 batch 出现在约 60-90s 后。

**修复**：baseline 等待 timeout 调整到 240s，poll interval 10s。30 秒为
batch 间隔。

### 4. DataHub disable 后仍有 ~60-90s 滞后期持续采集

**症状**：disable 后立即查询 disable 窗口内历史条数为 0；60s 后条数增加
（平台 flush 缓冲数据）。

**修复**：grace period 从 5s 增加到 90s；之后断言两次 60s 间隔
count 一致（说明 disable 后真实无新数据）。

### 5. 测试 polling 窗口 bug：`end` 不展开

**症状**：`_wait_for_history_count(api, tag_name, beg, _now_local_str(), ...)`
中 `_now_local_str()` 在测试函数中求值一次，固定为测试开始时的字符串；
240s 轮询期间窗口不展开，初始窗口外的新历史点看不到。

**修复**：`_wait_for_history_count` 接受 `end_or_callable`；
调用方传 `_now_local_str`（函数引用），每次轮询重新求值，实现滑动窗口。

### 6. `_wait_for_rt_ok` 不容忍 TptAPIError

**症状**：mocker 重启后 DataHub 短暂报 `Tag Dose Not Exist`（重订阅窗口）；
原 `_wait_for_rt_ok` 调用 `get_rt_point` 直接抛错，导致测试 fail。

**修复**：`_wait_for_rt_ok` 内部 try/except `TptAPIError`，继续轮询。

### 7. `_restart_mocker` 不处理已 None 的 mocker

**症状**：UA-1-3-02/07 测试中先 `stop_mocker` + `ctx["mocker"]=None`，
再调 `_restart_mocker`，后者又尝试 stop None。

**修复**：`_restart_mocker` 先判断 `ctx["mocker"] is not None` 再 stop。

### 8. 短断连 RT 读仍可能短暂失败

**症状**：`_wait_for_rt_ok` 之后紧跟 `get_rt_point` 仍可能偶发失败。

**修复**：UA-1-3-06/07 改为带 retry 的 read loop（deadline 30s，0.5s 间隔），
分别获得两次有效读后断言值变化。

## cleanup 结果

| 资源类型 | 测试后残留 |
|----------|-----------|
| datasource | 0 |
| active tag | 0 |
| recycle tag | 0 |
| 动态端口监听 | 0（除 18960 默认 smoke.yaml mocker）|
| 动态 mocker 进程 | 0 |

## GUI native backend 真实 smoke

- `TestGUI_NativeSmoke_EndToEnd`：最小 pytest 项目 + manifest，通过
  `automation.NativeService` + `nativepytest.Manager` 完整链路运行，
  验证 pass/fail/xfail/xpass 状态映射正确。
- `TestGUI_NativeSmoke_Cancel`：长测试 + 取消场景，验证 `Stop`
  路径。

两个 smoke 都通过，Go 离线测试在 `SKIP_INTEGRATION=1` 下全绿。

## 关联修复 commit

- `fix(ua1): use correct remote host for unreachable address`
- `fix(ua1): correct history window with local time and sliding end`
- `fix(ua1): tolerate transient tag-missing during OPC UA restart`
- `fix(ua1): make _restart_mocker tolerate None mocker handle`