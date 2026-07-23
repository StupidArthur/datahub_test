# UA 自动化测试与工具页面实施计划

> 面向执行 Agent。本文是实现指令，不是方向性建议。请按阶段执行、逐步提交、逐步自测，不要跳过基础设施直接批量填测试函数。

## 0. 目标与约束

### 0.1 最终目标

在现有仓库中落地一套可实际运行的 UA 自动化测试系统：

1. Python 自动化执行器可在命令行独立运行；
2. Wails/Go 后端可创建、启动、停止、恢复和查询测试任务；
3. React 工具增加两个核心页面：
   - **测试任务**：选择用例、启动任务、查看实时进度和日志；
   - **测试用例**：查看用例树、用例详情和实现状态；
4. 现有“运行历史”页面升级为通用测试历史结果查看页；
5. `ua_mocker` 和 Go 侧 Mock 规格适配最新 UA-1～UA-3 用例；
6. 结果增量落盘，程序崩溃或关闭后可查看已完成部分；
7. 当晚至少打通最小端到端链路，并执行一轮可产生完整日志的冒烟任务。

### 0.2 本轮明确不做

- 不做 GUI 本身的自动化测试；
- 不实现 `collectTagValue` 手动采集任务接口；
- 不为探索用例强行设定未知业务断言；
- 不为响应时间和性能测试预设 SLA；先记录实测值；
- 不要求一夜内完成所有 115 个测试函数，但必须完成可扩展框架、两个页面、Mock 基础改造和首批端到端用例。

### 0.3 数据和凭据

用户明确要求不强制脱敏。允许在本机任务目录、SQLite、日志和 evidence 中保存完整请求、响应、账号、Token、Cookie 等信息。

仍需遵守：

- 不主动上传到外部平台；
- 不在代码常量中硬编码真实账号密码；
- 凭据来自当前登录态、运行配置文件或环境变量；
- 测试目录默认位于用户本机 `~/.ua_test_gui/`；
- Git 提交中不得包含实际运行生成的凭据、Token、SQLite 数据库和报告目录。

---

# 1. 当前代码基线与迁移原则

## 1.1 当前已有能力

现有代码已经具备：

- Wails + React 主壳；
- 被测对象登录和 Go 内存登录态；
- 四套固定 Mock 的启动、停止和状态事件；
- 简单 Provision；
- 旧 Verify：11 类型单次读写验证；
- SQLite：`runs` 和 `tag_results`；
- 旧 HistoryPage：查看旧 Verify 运行历史；
- Go 侧 TPT API 客户端；
- Python `tpt_api`；
- Python `ua_test_harness`；
- asyncua Mock Server。

## 1.2 迁移原则

1. **不要直接删除旧 Verify 功能**。新系统跑通前保留旧接口和页面能力，最终再决定是否移除。
2. 新自动化系统使用独立业务域名称 `testrun` 或 `automation`，不要继续把所有新逻辑塞进 `verify`。
3. SQLite 采用新表，不复用旧 `tag_results` 表结构承载通用用例结果。
4. Python runner 是唯一用例执行核心；Go 不重写 115 个用例逻辑。
5. Go 负责：任务生命周期、进程、事件、持久化、文件访问、前端 binding。
6. React 只展示状态和发命令，不解析自由文本日志推断任务状态。
7. Python stdout 只输出 NDJSON 结构化事件；普通日志写 stderr 和文件。

---

# 2. 目标架构

```text
React/Wails UI
  ├─ 测试用例页面
  ├─ 测试任务页面
  └─ 历史结果页面
          │ Wails bindings
          ▼
Go automation.Service / RunnerManager
  ├─ 用例目录加载
  ├─ 创建运行配置
  ├─ 启停 Python runner
  ├─ 读取 NDJSON 事件
  ├─ Wails EventsEmit
  ├─ SQLite 增量持久化
  └─ 报告/evidence 文件访问
          │ subprocess
          ▼
Python ua_test_harness.runner
  ├─ pytest/自定义 runner
  ├─ tpt_api client
  ├─ asyncua client
  ├─ Mock 控制适配器
  ├─ fixtures/resource registry
  ├─ history fixture factory
  ├─ polling/assertions
  ├─ metrics
  └─ report/evidence
          │
          ├─ TPT REST API
          └─ OPC UA Mock
```

---

# 3. 目录与文件级改动

## 3.1 Python 自动化目录

优先复用 `ua_test_harness`，不要再创建重复的顶层项目。建议调整为：

```text
ua_test_harness/
├── pyproject.toml
├── pytest.ini
├── README.md
├── runner.py
├── cli.py
├── catalog.py
├── config.py
├── events.py
├── models.py
├── context.py
├── polling.py
├── assertions.py
├── evidence.py
├── resources.py
├── metrics.py
├── report.py
├── clients/
│   ├── tpt_client.py
│   ├── opcua_client.py
│   └── mock_control.py
├── fixtures/
│   ├── datasource.py
│   ├── tag.py
│   ├── group.py
│   ├── history.py
│   └── environment.py
├── tests/
│   ├── ua_1/
│   ├── ua_2/
│   └── ua_3/
└── unit_tests/
```

若现有目录已有同名能力，优先重构并复用，不要复制。

## 3.2 Go 后端新增目录

```text
ua_test_gui/internal/automation/
├── model.go
├── service.go
├── catalog.go
├── runner.go
├── event.go
├── paths.go
├── ports.go
└── service_test.go

ua_test_gui/internal/adapters/pytestrunner/
├── manager.go
├── process_windows.go
├── process_other.go
├── ndjson.go
└── manager_test.go

ua_test_gui/internal/bindings/automation.go
```

SQLite 修改：

```text
ua_test_gui/internal/adapters/sqlite/store.go
```

推荐将自动化相关 SQL 拆到：

```text
ua_test_gui/internal/adapters/sqlite/automation_store.go
```

## 3.3 React 新增或替换

```text
ua_test_gui/frontend/src/pages/TestCasesPage.tsx
ua_test_gui/frontend/src/pages/TestRunsPage.tsx
ua_test_gui/frontend/src/pages/HistoryPage.tsx
ua_test_gui/frontend/src/components/test/CaseTree.tsx
ua_test_gui/frontend/src/components/test/RunProgress.tsx
ua_test_gui/frontend/src/components/test/StatusBadge.tsx
ua_test_gui/frontend/src/components/test/LogViewer.tsx
ua_test_gui/frontend/src/components/test/CaseResultDetail.tsx
ua_test_gui/frontend/src/components/test/MetricTable.tsx
```

修改：

```text
ua_test_gui/frontend/src/App.tsx
ua_test_gui/frontend/src/lib/api.ts
ua_test_gui/main.go
ua_test_gui/internal/app/container.go
ua_test_gui/internal/app/lifecycle.go
ua_test_gui/internal/app/config.go
```

---

# 4. 用例目录设计

## 4.1 单一事实源

用例文档在 `ua_test_harness/test_cases/*.md`，但运行器不能每次解析 Markdown 表格作为执行目录。请建立机器可读目录：

```text
ua_test_harness/cases/catalog.json
```

或由 Python 代码装饰器生成：

```python
@case(
    id="UA-3-4-010",
    title="分页_首页尾页元数据",
    chapter="UA-3-4",
    kind="regression",
    tags=["history", "fixture-B"],
    timeout_sec=120,
    exclusive_resources=["history-store"],
)
```

推荐方式：测试函数装饰器 + `python -m ua_test_harness.catalog export` 生成 JSON。这样代码元数据是执行事实源，导出的 catalog 给 Go/UI 使用。

## 4.2 Catalog JSON 结构

```json
{
  "version": 1,
  "generatedAt": "2026-07-12T10:00:00Z",
  "chapters": [
    {
      "id": "UA-3-4",
      "title": "历史查询",
      "cases": [
        {
          "id": "UA-3-4-010",
          "title": "分页_首页尾页元数据",
          "kind": "regression",
          "implemented": true,
          "tags": ["history", "fixture-B"],
          "timeoutSec": 120,
          "destructive": false,
          "exclusiveResources": ["history-store"],
          "docPath": "ua_test_harness/test_cases/UA-3-4.md",
          "description": "...",
          "steps": ["..."],
          "assertions": ["..."]
        }
      ]
    }
  ]
}
```

## 4.3 实现状态

用例页面必须显示：

- 已设计；
- 已实现；
- 未实现；
- BLOCKED；
- 探索；
- 性能；
- 响应时间。

`implemented` 必须由代码扫描/装饰器导出，不能在前端硬编码。

---

# 5. Python Runner 设计

## 5.1 CLI

必须支持：

```bash
python -m ua_test_harness.cli catalog --output catalog.json
python -m ua_test_harness.cli run --config run-config.json
python -m ua_test_harness.cli run --config run-config.json --cases UA-3-1-001,UA-3-2-001
python -m ua_test_harness.cli run --config run-config.json --chapters UA-1-1,UA-3-4
```

返回码：

- 0：任务正常完成，允许存在 OBSERVED/MEASURED；
- 1：存在 FAIL/ERROR/CLEANUP_FAILED；
- 2：配置错误或无法启动；
- 130：收到停止信号。

## 5.2 Run Config

Go 每次启动任务生成：

```text
~/.ua_test_gui/runs/<run-id>/run-config.json
```

示例：

```json
{
  "runId": "20260712_220000_a81f",
  "selectedCaseIds": ["UA-1-1-001", "UA-3-1-001"],
  "subject": {
    "baseUrl": "http://10.10.58.153:31501",
    "tenantId": "",
    "username": "admin",
    "password": "...",
    "token": "..."
  },
  "localIp": "10.10.58.20",
  "mock": {
    "controlMode": "wails-managed",
    "endpoints": {
      "functional": "opc.tcp://10.10.58.20:18960/ua_mocker/",
      "reconnect": "opc.tcp://10.10.58.20:18961/ua_mocker/",
      "performance": "opc.tcp://10.10.58.20:18962/ua_mocker/",
      "abnormal": "opc.tcp://10.10.58.20:18963/ua_mocker/"
    }
  },
  "timeouts": {
    "pollIntervalMs": 500,
    "rtVisibilitySec": 30,
    "historyVisibilitySec": 120,
    "dsConnectSec": 60
  },
  "paths": {
    "runDir": "...",
    "evidenceDir": "...",
    "reportPath": ".../report.json"
  }
}
```

账号、密码、Token 可完整写入本机配置。任务结束后保留，便于复现；不要提交到 Git。

## 5.3 结构化事件协议

Python stdout 每行必须是一个 JSON 对象，不输出普通文本。

事件最少包含：

```json
{"event":"run_started","runId":"...","total":6,"ts":"..."}
{"event":"case_started","caseId":"UA-3-1-001","index":1,"total":6,"ts":"..."}
{"event":"step_started","caseId":"UA-3-1-001","stepId":"setup-tag","title":"创建位号","ts":"..."}
{"event":"step_finished","caseId":"UA-3-1-001","stepId":"setup-tag","status":"PASS","durationMs":1234,"ts":"..."}
{"event":"log","level":"INFO","caseId":"UA-3-1-001","message":"...","ts":"..."}
{"event":"metric","caseId":"UA-3-5-001","name":"p95_ms","value":83.2,"unit":"ms","ts":"..."}
{"event":"evidence","caseId":"UA-3-1-001","kind":"api_response","path":"evidence/...json","ts":"..."}
{"event":"case_finished","caseId":"UA-3-1-001","status":"PASS","durationMs":3000,"summary":"...","ts":"..."}
{"event":"cleanup_finished","caseId":"UA-3-1-001","status":"PASS","ts":"..."}
{"event":"run_finished","status":"FINISHED","passed":5,"failed":1,"observed":0,"measured":0,"ts":"..."}
```

状态枚举：

- `PENDING`
- `RUNNING`
- `PASS`
- `FAIL`
- `ERROR`
- `SKIP`
- `BLOCKED`
- `OBSERVED`
- `MEASURED`
- `CANCELLED`
- `CLEANUP_FAILED`

事件必须带 `ts`。Go 侧不得通过日志字符串猜状态。

## 5.4 stderr 和文件日志

- stderr 写完整 Python 日志；
- 同时写 `<runDir>/runner.log`；
- Go 捕获 stderr，追加到任务日志并推送 `automation:log`；
- stdout 非法 JSON 时，Go 记录 protocol error，但不要立刻丢弃整次运行；连续协议错误超过阈值再终止。

## 5.5 Context 与资源清理

实现 `RunContext`、`CaseContext`、`ResourceRegistry`。

每创建资源立即登记清理动作。清理按 LIFO 执行。必须支持：

- 数据源；
- 位号；
- 分组；
- 收藏关系；
- 回收站位号；
- Mock 启停状态；
- OPC UA 原值；
- 临时文件；
- 历史造数清单。

无论用例 PASS、FAIL、ERROR 或取消，都必须执行清理。

## 5.6 轮询

禁止在功能测试中使用固定长 `sleep` 替代状态等待。实现：

```python
wait_until(name, condition, timeout, interval, stable_count=1)
wait_ds_alive(...)
wait_ds_offline(...)
wait_tag_visible(...)
wait_tag_absent(...)
wait_rt_value(...)
wait_rt_quality(...)
wait_history_points(...)
wait_recycle_contains(...)
wait_group_tree(...)
```

轮询过程写 evidence 时间线。

## 5.7 历史数据工厂

按 `ua_test_gui/doc/history-data-fixtures.md` 实现：

```python
class HistoryFixtureFactory:
    def create_acquisition_dataset(...):  # A
    def create_import_dataset(...):       # B
    def create_write_dataset(...):        # C
    def create_regular_dataset(...)
    def create_boundary_dataset(...)
    def create_sparse_dataset(...)
    def create_multi_tag_dataset(...)
    def create_performance_dataset(...)
```

造数完成后必须查询核验；不满足预期时返回 setup failure，而不是把历史查询判失败。

---

# 6. Go 任务编排设计

## 6.1 核心模型

`internal/automation/model.go` 至少定义：

```go
type RunStatus string

type TestRun struct {
    ID             int64
    RunKey         string
    Status         RunStatus
    CreatedAt      string
    StartedAt      string
    FinishedAt     string
    SelectedCases  []string
    Total          int
    Progress       int
    Passed         int
    Failed         int
    Errors         int
    Skipped        int
    Blocked        int
    Observed       int
    Measured       int
    CleanupFailed  int
    CurrentCaseID  string
    CurrentStep    string
    PID            int
    ExitCode       *int
    RunDir         string
    ReportPath     string
    LogPath        string
    ErrorMessage   string
}

type CaseResult struct {
    RunID          int64
    CaseID         string
    Title          string
    Status         string
    StartedAt      string
    FinishedAt     string
    DurationMs     int64
    Summary        string
    CleanupStatus  string
}

type StepResult struct {...}
type TestEvent struct {...}
type Metric struct {...}
type Evidence struct {...}
```

## 6.2 Store 接口

定义独立接口：

```go
type Store interface {
    CreateAutomationRun(...)
    UpdateAutomationRun(...)
    AddAutomationEvent(...)
    UpsertCaseResult(...)
    AddStepResult(...)
    AddMetric(...)
    AddEvidence(...)
    ListAutomationRuns(...)
    GetAutomationRun(...)
    ListCaseResults(...)
    ListRunEvents(...)
    MarkInterruptedRuns(...)
}
```

不要继续扩展旧 `verify.ResultStore`。

## 6.3 RunnerManager

`pytestrunner.Manager` 负责：

- 一次只允许一个 active run；
- 创建 `exec.Cmd`；
- 设置工作目录；
- 传入 config 路径；
- 捕获 stdout/stderr；
- 解析 NDJSON；
- 保存 PID；
- 支持取消；
- 监听退出；
- Windows 使用 Job Object 或进程树终止策略，避免 Python 子进程残留；
- Wails 退出时主动停止任务并等待清理。

接口建议：

```go
type Runner interface {
    Start(ctx context.Context, spec RunSpec, onEvent func(Event), onLog func(string)) (*ProcessInfo, error)
    Stop(runKey string) error
    Active() *ProcessInfo
}
```

## 6.4 Service 行为

实现：

```go
ListTestCases()
StartTestRun(req StartRunRequest)
StopTestRun(runID int64)
GetActiveRun()
ListTestRuns(filter RunFilter)
GetTestRunDetail(runID int64)
GetRunEvents(runID int64, afterID int64)
ReadRunLog(runID int64, offset int64, limit int)
OpenRunDirectory(runID int64)
```

`StartTestRun` 前置检查：

1. 已登录；
2. 没有 active run；
3. selectedCaseIds 非空；
4. 所有 ID 在 catalog 中；
5. Python 路径可用；
6. runner module 可 import；
7. 本机目录可写；
8. 需要的 Mock 规格存在；
9. 性能用例必须显式确认独占环境（请求字段 `allowPerformance=true`）。

## 6.5 登录信息传递

`subject.Service` 当前保存 baseURL、user、password、tenantID。新增只供自动化内部使用的快照方法：

```go
type CredentialsSnapshot struct {
    BaseURL string
    Username string
    Password string
    TenantID string
    Token string
}
```

不要将此方法暴露给前端普通页面。`automation.Service` 通过依赖调用并写入 run-config。

若 TptClient token 字段不可访问，可：

- 直接传用户名密码，让 Python 自己登录；
- token 可选。

第一版优先传用户名密码，降低 Go 私有字段改造量。

## 6.6 Wails 事件

统一事件名：

- `automation:run`
- `automation:case`
- `automation:step`
- `automation:log`
- `automation:metric`
- `automation:evidence`

事件 payload 使用稳定 DTO。前端收到事件后更新 active run；页面重新打开时仍要通过 API 拉取数据库状态，不能只依赖内存事件。

---

# 7. SQLite 新表

新增迁移，保留旧表。

```sql
CREATE TABLE IF NOT EXISTS automation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    selected_cases_json TEXT NOT NULL,
    total INTEGER DEFAULT 0,
    progress INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    blocked INTEGER DEFAULT 0,
    observed INTEGER DEFAULT 0,
    measured INTEGER DEFAULT 0,
    cleanup_failed INTEGER DEFAULT 0,
    current_case_id TEXT,
    current_step TEXT,
    pid INTEGER DEFAULT 0,
    exit_code INTEGER,
    run_dir TEXT,
    report_path TEXT,
    log_path TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS automation_case_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER DEFAULT 0,
    summary TEXT,
    cleanup_status TEXT,
    UNIQUE(run_id, case_id)
);

CREATE TABLE IF NOT EXISTS automation_step_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_id TEXT NOT NULL,
    step_id TEXT,
    title TEXT,
    status TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_ms INTEGER DEFAULT 0,
    message TEXT
);

CREATE TABLE IF NOT EXISTS automation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    case_id TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automation_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_id TEXT,
    name TEXT NOT NULL,
    value REAL,
    text_value TEXT,
    unit TEXT,
    labels_json TEXT
);

CREATE TABLE IF NOT EXISTS automation_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    case_id TEXT,
    kind TEXT,
    path TEXT NOT NULL,
    title TEXT,
    metadata_json TEXT
);
```

索引：

- runs status/created_at；
- case_results run_id/status；
- events run_id/id；
- metrics run_id/case_id；
- evidence run_id/case_id。

应用启动时将数据库里遗留的 `RUNNING` 标记为 `INTERRUPTED`，除非检测到 PID 仍属于当前管理器。

---

# 8. Wails Binding

新增 `AutomationBinding`，绑定到 `main.go`。

方法：

```go
ListTestCases() (automation.Catalog, error)
StartTestRun(req automation.StartRunRequest) (automation.TestRun, error)
StopTestRun(runID int64) (automation.TestRun, error)
GetActiveTestRun() (*automation.TestRun, error)
ListTestRuns(req automation.ListRunsRequest) ([]automation.TestRun, error)
GetTestRunDetail(runID int64) (automation.RunDetail, error)
GetRunEvents(req automation.GetEventsRequest) ([]automation.TestEvent, error)
ReadRunLog(req automation.ReadLogRequest) (automation.LogChunk, error)
OpenRunDirectory(runID int64) error
RefreshTestCatalog() (automation.Catalog, error)
```

Wails 生成模型后，前端 `lib/api.ts` 增加封装。

---

# 9. 前端页面设计

## 9.1 导航调整

`App.tsx` 建议：

```text
环境管理
- 被测对象
- 操作系统环境检测
- ua-server-mock 管理

自动化测试
- 测试用例
- 测试任务
- 运行历史

辅助工具
- 数据源组态
- 旧验证（迁移期保留，可标“旧版”）
```

页面 key：

- `cases`
- `runs`
- `history`

## 9.2 测试用例页面

布局：左侧章节树，右侧用例列表/详情。

功能：

- 搜索 case ID、标题、标签；
- 按 UA-1/UA-2/UA-3 展开；
- 按 implemented、kind、status 筛选；
- 复选多个用例；
- “选择本章节”“选择全部已实现回归用例”；
- 显示用例：ID、标题、类型、实现状态、超时、资源锁、文档链接；
- 点击显示详情：描述、前置、步骤、断言、造数方式、清理；
- “使用所选用例创建任务”按钮，跳转测试任务页并带 selection。

不要在前端读取 Markdown。只使用 catalog API。

## 9.3 测试任务页面

分三块。

### A. 任务配置

- 当前被测对象；
- 当前 local IP；
- 已选择用例数量；
- 按章节汇总；
- 是否包含探索/性能；
- 性能测试确认开关；
- 运行名称/备注；
- 启动按钮；
- 清空选择；
- 快捷方案：冒烟、全功能回归、UA-1、UA-2、UA-3、仅探索、仅响应时间、仅性能。

### B. Active Run

- Run ID；
- 状态；
- 总进度条；
- 当前用例；
- 当前步骤；
- 各状态计数；
- 开始时间和已运行时长；
- 停止按钮；
- 打开运行目录；
- 最近 200 条结构化日志；
- 自动滚动开关；
- 过滤 INFO/WARN/ERROR。

### C. 用例执行列表

每行：

- case ID；
- 标题；
- 状态；
- 耗时；
- 清理状态；
- 摘要；
- 点击查看步骤/evidence。

页面刷新或重新进入时调用 `GetActiveTestRun` 和 detail API 恢复显示。

## 9.4 历史结果页面

替换旧 HistoryPage 为通用任务历史，旧 Verify 历史可暂时另放一个 tab。

列表字段：

- Run ID；
- 创建/开始/结束时间；
- 状态；
- 用例数；
- PASS/FAIL/ERROR/OBSERVED/MEASURED；
- 耗时；
- 操作。

筛选：

- 日期；
- 状态；
- 章节；
- 是否包含性能；
- 关键字。

详情：

- 汇总卡；
- 用例结果表；
- 单用例步骤；
- 指标表；
- evidence 文件；
- 原始事件；
- 完整 runner.log；
- report.json；
- 打开目录。

日志采用分页/增量读取，不一次性加载大文件。

---

# 10. Mock 改造

## 10.1 当前不足

现有四套 Mock 仅有：

- 13 类型变化/可写节点；
- reconnect；
- performance；
- 名称长度和可写异常节点。

最新用例还需要：

- 多种采集频率对照；
- 明确静态只读节点；
- 同 NodeId 跨数据源隔离；
- 可控唯一值序列；
- 单节点异常；
- 质量码/时间行为（若 asyncua 支持）；
- 大整数边界；
- DateTime；
- 只读和可写的完整矩阵；
- 稀疏历史由导入完成，不要求 Mock 直接制造；
- 性能节点参数化；
- 测试过程中动态改值能力。

## 10.2 YAML Schema 扩展

在兼容旧字段的前提下增加可选字段：

```yaml
nodes:
  - name: mock_Double_static_ro_
    type: Double
    count: 10
    change: false
    writable: false
    default: 12.5
    mode: static
    sequence_start: 0
    sequence_step: 1
    fail_read: false
    timestamp_mode: server
```

建议支持：

- `mode`: `static | increment | toggle | sequence`；
- `sequence_start`；
- `sequence_step`；
- `fail_read`（若服务端实现难度过高，可先通过删除/禁用单节点模拟并标注限制）；
- `status_code`（可选，若 asyncua 写 DataValue 可实现）；
- `source_timestamp_offset_ms`（可选探索）；
- `writable`；
- `default`。

不要破坏旧 YAML。

## 10.3 Mock 规格重组

保留端口，更新内容：

### functional

- 13 类型 × 变化只读；
- 13 类型 × 静态可写；
- 13 类型 × 静态只读；
- Int64/UInt64 边界节点；
- DateTime 固定节点和变化节点；
- Unicode String；
- 相同 NodeId 模板供另一个 Mock 使用；
- frequency 对照节点（1s/5s/10s 的 DataHub frequency 是位号配置，但源端节点需稳定可控）。

### reconnect

- 与 functional 至少有一组相同 NodeId、不同默认值；
- 独立 heartbeat；
- 变化节点和可写节点；
- 用于停止/恢复，不承载性能大数据。

### abnormal

- 长名称；
- 只读写入；
- 类型错配目标；
- 不存在节点由测试直接构造；
- 可选单节点异常；
- 字符串极长值；
- 数值边界。

### performance

- pollN 变化 Double；
- writeN 可写 Double/Boolean；
- 可配置 batch/container；
- 启动日志输出节点构建阶段和耗时；
- 不默认 10000/1000 固死，使用 GUI 参数。

## 10.4 动态控制

测试 runner 需要控制源端值。第一版直接使用 asyncua 写可写静态节点，不必新增 Mock HTTP 控制面。

对于不可写变化节点，只读取。

若后续需要单节点异常和质量码动态切换，再增加本机控制接口。不要在第一晚阻塞主链路。

## 10.5 Go Mock 管理修复

必须修复：

1. 启动失败后不要立即从 `run` map 删除，保留 failed runtime 和 reason；
2. `StartAllMocks` 不得吞掉同步启动错误；
3. list summary 返回 reason/logPath/configPath；
4. 增加 `ReadMockLogTail` binding；
5. 性能参数应持久化到本机配置，而不是仅内存；
6. Automation 可查询 Mock endpoint/status；
7. 停止测试任务不默认停止所有 Mock，除非本次任务启动了它且登记为临时资源。

---

# 11. 第一批必须实现的测试用例

一夜目标不是 115 个全部实现，而是框架端到端加代表性覆盖。至少实现：

1. `UA-1-1-001`：基础数据源连接建立；
2. `UA-1-2` 中一个启停用例；
3. `UA-1-3` 中一个断线恢复用例；
4. `UA-2-1` 中一个位号新增闭环；
5. `UA-2-2` 中一个位号查询；
6. `UA-2-4` 中一个软删除+恢复；
7. `UA-3-1-001`：自动开始采集；
8. `UA-3-2-001`：实时库按名称读取；
9. `UA-3-2-012`：数据库模式读取；
10. `UA-3-3-001`：单个位号写入；
11. `UA-3-4-001`：方式 B 造数并基础历史查询；
12. `UA-3-5-001`：单个位号实时读响应时间，状态为 MEASURED。

推荐额外实现：

- 13 类型参数化采集；
- 13 类型参数化写入；
- 分页 25 点数据集；
- Mock 断线恢复。

## 11.1 冒烟预设

Catalog 中定义 preset：

```json
{
  "id": "smoke",
  "title": "核心冒烟",
  "caseIds": [
    "UA-1-1-001",
    "UA-2-1-001",
    "UA-3-1-001",
    "UA-3-2-001",
    "UA-3-3-001",
    "UA-3-4-001"
  ]
}
```

GUI 默认允许一键运行。

---

# 12. 实施阶段与提交顺序

## Phase 1：盘点和保护基线

1. 新建开发分支；
2. 运行现有 Go test；
3. 运行前端 build；
4. 运行 Python 单测；
5. 记录现有失败，不要把已有失败误判为新改动；
6. 不修改测试用例文档内容。

提交：

```text
chore: establish automation implementation baseline
```

## Phase 2：Python runner 骨架

实现：catalog、config、events、context、resource registry、polling、report、CLI。

测试：

- catalog 可导出；
- 空用例运行；
- 假用例 PASS/FAIL/ERROR；
- stdout 每行合法 JSON；
- SIGINT/SIGTERM 清理；
- report.json 生成。

提交：

```text
feat(ua-test-harness): add structured automation runner core
```

## Phase 3：Go automation 与 SQLite

实现新表、store、manager、service、binding、事件转发。

测试：

- 创建 run；
- 假 Python runner 事件落库；
- 非法 JSON；
- 进程退出；
- 停止；
- 重启后 interrupted；
- 一次只允许一个 active run。

提交：

```text
feat(ua-test-gui): add automation run orchestration and persistence
```

## Phase 4：两个页面和历史升级

实现 TestCasesPage、TestRunsPage、HistoryPage。

测试：

- TypeScript build；
- 空 catalog；
- 未实现用例；
- active run 事件更新；
- 页面切换后恢复；
- 历史详情；
- 大日志增量读取。

提交：

```text
feat(ua-test-gui): add test catalog and run progress pages
```

## Phase 5：Mock 适配

先修状态机，再扩充节点规格。

测试：

- 四套 Mock 可启动；
- ready/failed/stopped 正确；
- 失败原因保留；
- 13 类型读写；
- functional/reconnect 同 NodeId 不同值；
- performance 参数生效；
- 日志可读。

提交：

```text
feat(ua-mocker): align mock scenarios with UA automation cases
```

## Phase 6：首批真实用例

按第 11 节实现。

提交可按章节拆：

```text
feat(ua-tests): implement initial UA-1 automation cases
feat(ua-tests): implement initial UA-2 automation cases
feat(ua-tests): implement initial UA-3 automation cases
```

## Phase 7：端到端运行与修复

运行 smoke，修复框架问题。不要通过放宽断言掩盖真实失败。

提交：

```text
fix(ua-tests): stabilize end-to-end smoke execution
```

---

# 13. 测试要求

## 13.1 Go

```bash
cd ua_test_gui
go test ./...
go vet ./...
```

重点单测：

- NDJSON parser；
- runner lifecycle；
- SQLite migration；
- event -> state projection；
- cancellation；
- interrupted recovery；
- catalog loading。

## 13.2 Frontend

```bash
cd ua_test_gui/frontend
npm install
npm run build
```

至少人工验证：

- 用例树加载；
- 筛选和选择；
- 启动任务；
- 实时进度；
- 实时日志；
- 停止任务；
- 历史列表；
- 历史详情；
- 关闭/重开页面；
- active run 恢复。

## 13.3 Python

```bash
python -m pytest ua_test_harness/unit_tests -q
python -m ua_test_harness.cli catalog --output /tmp/catalog.json
python -m ua_test_harness.cli run --config <fake-config>
```

必须覆盖：

- 事件 schema；
- 资源 LIFO 清理；
- cleanup failure；
- polling timeout；
- history fixture 规则数据集；
- report 统计；
- cancellation。

## 13.4 Mock

```bash
python -m pytest ua_mocker -q
```

没有现成测试目录则新增最小单测：

- YAML 兼容；
- 新字段默认值；
- 节点数量；
- 类型映射；
- sequence engine；
- invalid config。

---

# 14. 今晚实际运行步骤

## 14.1 环境预检

记录到：

```text
~/.ua_test_gui/nightly/<date>/environment.txt
```

内容：

- Git commit；
- Windows 版本；
- Go/Node/npm/Python 版本；
- TPT base URL；
- local IP；
- Python 路径；
- ua_mocker 路径；
- 端口 18960～18963；
- 登录结果；
- 数据库路径。

## 14.2 构建

```bash
cd ua_test_gui/frontend
npm install
npm run build

cd ..
go test ./...
wails build
```

Python：

```bash
python -m pip install -e .
python -m pytest ua_test_harness/unit_tests -q
```

## 14.3 运行顺序

1. 启动 functional Mock；
2. 登录 TPT；
3. 运行最小框架 self-test；
4. 运行 smoke preset；
5. 若 smoke 中途失败，仍保留后续日志和 evidence；
6. 修复基础框架后重新跑 smoke；
7. smoke 稳定后跑首批所有已实现用例；
8. 最后跑响应时间基线；
9. 不在框架未稳定时跑大规模性能用例。

## 14.4 建议命令

CLI：

```bash
python -m ua_test_harness.cli run --config run-config-smoke.json
```

GUI：

- 测试用例 → 选择“核心冒烟”；
- 测试任务 → 启动；
- 保持应用运行；
- 运行结束后打开历史详情；
- 保存/保留运行目录。

---

# 15. 明早必须提供的材料

Agent 完成后，不要只说“完成”。必须留下：

1. 最终 Git commit SHA；
2. 所有提交列表；
3. `git status`；
4. `go test ./...` 输出；
5. `npm run build` 输出；
6. Python unit test 输出；
7. smoke run ID；
8. smoke `report.json`；
9. `runner.log`；
10. Go 应用日志；
11. Mock server.log；
12. SQLite 中 run 汇总；
13. 失败用例 evidence；
14. 页面截图：
    - 测试用例页；
    - 测试任务运行中；
    - 历史结果详情；
15. 未完成项列表；
16. 已知限制；
17. 任何改变用例语义的地方。

建议汇总文件：

```text
nightly-report.md
```

结构：

```markdown
# Nightly implementation report
## Commits
## Build results
## Unit tests
## Smoke run
## Passed cases
## Failed cases
## Framework errors
## Mock issues
## UI issues
## Artifacts
## Next actions
```

---

# 16. 验收标准

## 16.1 最低可接受

- `plan.md` 所述架构骨架存在；
- Python runner 能运行至少 6 个真实用例；
- 测试用例页面可查看 catalog；
- 测试任务页面可启动、显示进度、显示日志、停止；
- 历史页面可查看任务和逐用例结果；
- SQLite 增量保存；
- Mock 至少支持首批用例；
- smoke 产生 report 和日志；
- 构建通过，或明确记录阻塞原因。

## 16.2 不可接受

- 页面用假数据；
- 进度从日志字符串正则猜测；
- Python runner 只打印文本，没有事件协议；
- 任务仅存在内存，应用重启后全丢；
- 使用大量固定 sleep；
- 用例 ID 与文档不一致；
- 为了让测试通过而删除断言；
- 测试失败时没有 evidence；
- 停止任务后遗留 Python/Mock 子进程；
- 将运行生成的账号、Token、数据库或报告提交 Git。

---

# 17. 后续完整实现顺序

首批稳定后按以下顺序补齐：

1. UA-1 全部功能回归；
2. UA-2 全部功能回归；
3. UA-3-1～UA-3-4 回归；
4. 探索用例，输出 OBSERVED；
5. UA-3-5 响应时间，输出 MEASURED；
6. 根据实测确定阈值并固化；
7. UA-3-6 性能测试；
8. 性能基线比较和趋势；
9. 打包 Python runner 和 ua_mocker，确保目标 Windows 机器无需开发环境；
10. 旧 Verify 页面和旧表确认无用后再迁移或删除。

---

# 18. Agent 执行注意事项

- 每完成一个 Phase 立即提交，不要积累巨型未提交修改；
- 每次提交前运行相关最小测试；
- 遇到平台行为不明确，记录 observation，不自行发明产品规则；
- 遇到 API 返回值与最终状态不一致，以用例文档规定的最终状态为准；
- 历史数据造数严格引用 `history-data-fixtures.md`；
- 所有临时名称使用 runId；
- 所有 destructive 用例必须有旁路对象验证隔离；
- 功能用例默认串行；
- 响应时间和性能用例独占环境；
- UI 事件只是实时体验，数据库是最终事实源；
- report.json 是对外分析的主报告；
- 明早保留全部失败现场，不要清空日志后只给总结。
