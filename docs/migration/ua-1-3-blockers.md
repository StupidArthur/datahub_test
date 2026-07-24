# UA-1-3 Migration Blockers

## Migrated cases (4/8) — all PASS in real-environment validation (4th phase)

The following cases have a working pytest implementation in
`tests/integration/ua1/test_recovery_and_reconnect.py`:

- UA-1-3-01 disconnect detection latency
- UA-1-3-02 reconnect recovery latency
- UA-1-3-06 short disconnect recovery
- UA-1-3-07 long disconnect recovery (window shortened to 30s from the
  spec's 120s to keep pytest cycle time manageable; the spec value is
  recorded in the test docstring)

Each migrated case allocates a free port, creates its own datasource +
tag + mocker, and reuses the port across restart cycles. Stop / restart
of the mocker is explicit at the test function level — no fixture hides
the scenario.

## Deferred cases (4/8)

The following cases are not migrated in this phase. Each entry lists
the original expectation, the legacy handler behaviour, the observed
real-environment behaviour, the missing capability, and follow-up
suggestions.

### UA-1-3-03 反复断开-重连 5 次时延统计

- **原始预期**: 5 轮"断开->重连"，每轮记录 4 个断开延迟 + 4 个重连延迟，输出 min/max/avg，验证一致性
- **真实环境观察**: 单次断开+重连在真实环境 30~90s 之间；5 轮顺序执行将让单测试占据 5~10 分钟，远超常规 integration 测试预算
- **缺少的能力**: 稳定的、可重现的延迟基线；当前每次运行延迟受 DataHub 后台调度影响，差异较大
- **后续建议**: 当 DataHub 性能稳定后再迁移；可拆为单独的性能子套件，独立超时，独立 CI 调度

### UA-1-3-04 断连期间 writeTagValues

- **原始预期**: datasource alive=false 期间 writeTagValues 写入是否落历史库
- **真实环境观察**: DataHub 在 datasource offline 时的写入行为尚未确认；旧 Harness 同样未覆盖此路径
- **缺少的能力**: DataHub 离线期间的写语义文档
- **后续建议**: 单独探测用例；首轮仅观察 response，记录 observed 结果，不立即固化为断言

### UA-1-3-05 断连期间写入值重连后同步源端

- **原始预期**: 断连期间写入的值是否同步到 UA server 源端
- **真实环境观察**: DataHub 一般不向 OPC UA server 回写（UA server 是采集源），此 Case 可能是规格错误
- **后续建议**: 平台侧确认 OPC UA server 是否支持 write；如不支持，本 Case 应作为规格错误归档

### UA-1-3-08 断连期间增删位号重连后生效

- **原始预期**: datasource alive=false 期间 add_tag / delete_tags，重连后新位号正常采集
- **真实环境观察**: DataHub 允许 datasource 离线时增删位号（API 不依赖 alive），但重连后是否立即生效取决于平台调度
- **缺少的能力**: 离线增删位号在重连后的激活时机
- **后续建议**: 单条探测用例 + observed；后续如稳定则可断言

## 通用备注

* UA-1-3 系列普遍依赖 DataHub 真实环境；CI 不运行
* 旧的 `ua_test_harness/tests/ua_1/test_datasource.py` 没有真实 UA-1-3 handler，仅有 ua1_precise.py 实现了部分逻辑
* 当前 pytest 测试以时间轮询 + 显式上限取代固定 sleep，避免无限等待