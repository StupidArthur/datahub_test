# to_gpt.md — UA 自动化测试实施进度 + 用例设计 / 自动化编写规范

## 1. 当前进度(2026-07-12 凌晨)

### 1.1 已交付

**Python runner 骨架**(Phase 2):
- `ua_test_harness/{models,events,catalog,config,context,resources,polling,assertions,evidence,metrics,report,runner,cli}.py`
- NDJSON 事件协议(每行合法 JSON,带 ts)
- `@case` 装饰器 + `python -m ua_test_harness.cli catalog export`
- `ResourceRegistry` LIFO 清理
- 32 个单测全过(`pytest ua_test_harness/unit_tests -q`)

**Go automation + SQLite**(Phase 3):
- `internal/automation/{model,catalog,event,paths,ports,runner,service}.go`
- `internal/adapters/pytestrunner/{manager,ndjson,process_windows,process_other}.go`
- `internal/adapters/sqlite/automation_store.go`(6 张新表)
- `internal/bindings/automation.go`(Wails binding)
- 启动恢复 `INTERRUPTED`(run 状态机)

**前端页面**(Phase 4):
- `TestCasesPage` / `TestRunsPage` / `HistoryPage`
- 7 个 test 组件 + Progress 组件 + StatusBadge
- `npm run build` 通过

**Mock 适配**(Phase 5):
- 启动失败保留 entry(plan 10.5 #1)
- `StartAllMocks` 错误不再吞(plan 10.5 #2)
- 性能参数持久化(plan 10.5 #5)
- `UaNodeSpec` 扩展字段(Mode / SequenceStart / FailRead / StatusCode / TimestampOffsetMs)

**首批真实用例**(Phase 6):
- 13 个用例 catalog 已注册(原 plan 11 标的)
- 与 `tpt_api` 真实签名对齐后,UA-1-1-01(基础数据源连接)在真环境 PASS

**端到端冒烟**(Phase 7):
- 框架自测通过(NDJSON / report / cleanup / exit code 全部正确)

**commit 历史**(分支 `feat/ua-automation-nightly`):
```
d94f7a6 feat: deliver UA automation system end-to-end (Phase 1-7)
b41490f fix: align fixtures with tpt_api signatures and real TPT environment
```

### 1.2 已实现 / 文档差距

| 章节 | doc 中 case 数 | 已实现 | 缺口 |
|---|---|---|---|
| UA-1-1 连接建立 | 12 | 12 | 0 |
| UA-1-2 启停控制 | 8 | 0 | 8 |
| UA-1-3 断线恢复 | 8 | 0 | 8 |
| UA-1-4 ~ UA-1-6 | 6+9+13 | 0 | 28 |
| UA-2-1 位号管理 | 112 | 0 | 112 |
| UA-2-2 ~ UA-2-5 | 67+32+27+27 | 0 | 153 |
| UA-3-1 采集 | 20 | 0 | 20 |
| UA-3-2 实时 | 21 | 0 | 21 |
| UA-3-3 写 | 22 | 0 | 22 |
| UA-3-4 历史 | 8 | 0 | 8 |
| UA-3-5 响应时间 | 12 | 0 | 12 |
| UA-3-6 性能 | 15 | 0 | 15 |
| **总计** | **419** | **12** | **407** |

注:plan.md 0.2 写"115 个测试函数",文档实际 419 个(plan 数字漏算 UA-3-6 性能 + 探索 + 部分变体)。

### 1.3 真环境冒烟真实结果(已跑)

| case | 真实结果 | 原因 |
|---|---|---|
| UA-1-1-01 | **PASS** | ds 创建 → 启用 → 轮询 alive=true 全链路通 |
| UA-1-1-02 | 未跑 | case 已实现,还没跑真环境 |
| UA-1-1-03 ~ UA-1-1-12 | 未跑 | case 已实现,还没跑真环境 |
| UA-3-1-001 ~ UA-3-5-001 | ERROR / 超时 | ua_mocker 在 Windows + 当前 asyncua 下无法创建子节点(容器是空的),RT quality=0 |

### 1.4 阻碍 / 环境 / 第三方工具问题(不绕路,如实记录)

1. **ua_mocker `add_node` 失败**(第三方 bug,本任务不修):
   - log: `requested parent node NumericNodeId(Identifier=15957, NamespaceIndex=0) does not exists`
   - 表现:mock 进程 listen 成功,但 `mocker.<type>_r_<n>` 等子节点一个都没建出来
   - 影响:UA-3-x(依赖 RT 读取)全部 quality=0 / 超时
   - 当前做法:跑真环境,让 case 真实 fail/timeout,记入报告

2. **`mock_manager.start` 子进程 cwd 错**(已修):
   - 原代码把 cwd 设到 mock_work/functional,Python `import log_util` 找不到同级模块
   - 改为 cwd = `ua_mocker/`(main.py 所在目录)

3. **tpt_api 签名差异**(已修):
   - `AlgAPI.login` 是方法,不是 `from tpt_api.users import login`
   - `DsTypes["REAL_TIME_DB"]`、`DsSubTypes["OPC_UA_SERVER"]`、`TagTypes["一次位号"]`
   - `add_ds_info(ds_name=..., ds_tar_url=..., ds_type=..., ds_sub_type=...)` — 没有 `ds_status` 参数
   - `write_tag_values({tagName: value})` — 传 dict 不是 list
   - `get_history_value(beg_time=..., end_time=...)` — `beg_time` 不是 `begin_time`,时间是字符串
   - `get_tag_by_name` 是内存缓存 `api.name_map`,改用 `list_tags(data={"tagName":...})` 实时查

4. **重名 tag 残留**(已修):
   - `delete_tags` 是逻辑删除(进回收站),TPT 拒绝重名 add
   - 解决:`delete_tags_physical` 物理删 active + recycle 两边

5. **DS alive 依赖 endpoint 路由可达**:
   - TPT 在 `10.10.58.153` 上,要它能连 mock,endpoint 必须指向 TPT 视角可达的 IP
   - 本机 `172.21.16.166` / `10.30.70.77` 中只有 `10.30.70.77` 与 TPT 同网段
   - rc.json `localIp` 固定为 `10.30.70.77`

6. **DS "Duplicate name" / "in use"**:
   - 上轮 case ERROR 时未清理的 ds 仍在占用,需手工逐个 delete_ds_info
   - 没有自动批量清残留的运维工具

### 1.5 待办

1. 补齐 UA-1-2 / UA-1-3 全部 16 个 case
2. 补齐 UA-1-4 / UA-1-5 / UA-1-6 全部 28 个 case
3. 补齐 UA-2-1 ~ UA-2-5 全部 153 个 case(模板:增/查/改/删/分组/批量/回收站)
4. 补齐 UA-3-1 ~ UA-3-6 全部 98 个 case(模板:RT/写/历史/响应时间/性能)
5. 真实环境跑完整 419 个 case,把结果写到 nightly-report.md 第二轮

---

## 2. 工程纪律(AGENTS.md)

### 2.1 环境/工具问题不绕路

发现环境问题或第三方工具(如 ua_mocker)bug:
- **说出来**,在 commit message 或报告里如实记录
- 不要绕其他路径强行修复(换底层、改协议、装新依赖等)
- 不要替换掉有问题的组件;让它暴露

### 2.2 Case 跑不过不改 Case

实现并运行 `plan.md` / `ua_test_harness/test_cases/*.md` 中定义的 case 时:
- **Case 怎么写就怎么实现**,不删断言、不放宽阈值、不改步骤
- 不要为"跑通过"加 `try/except` 把错误吞掉
- 不要为"跑通过"修改用例的步骤顺序或断言条件
- 如果 case 跑不过 → 让它 fail,在 report.json / NDJSON 事件 / nightly-report.md 里如实记录真实结果

### 2.3 唯一的例外:自己代码的实现 bug

- 用例代码本身有 typo / API 签名错 / 参数名错 → 修复 fixture 或 runner 框架
- 修复后必须保证 case 的步骤、断言、阈值不变
- 不许改 case 内容来"配合"框架 bug

### 2.4 跑通不是目标,实现 + 真实记录才是

- 当前任务目标:把 case 需求实现一遍,产生**一轮时机测试的真实结果**
- 失败的 case 是有效产出(说明实现 + 环境的真实状态)
- 报告里要区分:
  - "代码 bug 导致 fail"
  - "环境/工具限制导致 fail"
  - "case 自身断言失败"(按 §2.2,这种最优先;若非断言失败就改 case,先确认是不是自己代码 bug)

---

## 3. 用例设计规范(从 ua_test_harness/test_cases/*.md 抽取出的共性)

### 3.1 命名

- ID 格式:`UA-<chapter>-<sub>-<NN>`,NN 是两位数,严格与 `ua_test_harness/test_cases/<chapter>.md` 一致
  - 正例:`UA-1-1-01`、`UA-3-4-008`
  - 反例:`UA-1-1-001`(三位数)、`UA-1-1-1`(位数不对)
- 章节 prefix:
  - `UA-1-x`:数据源(连接 / 启停 / 断线 / 鉴权 / 质量码 / 其他)
  - `UA-2-x`:位号管理(增 / 查 / 改 / 删 / 分组 / 收藏 / 回收站)
  - `UA-3-x`:运行时(采集 / 实时 / 写 / 历史 / 响应时间 / 性能)

### 3.2 表结构

每个 case 一行,固定 6 列:

```
| 编号 | 三级点 | 前置条件 | 测试步骤 | 预期结果 | 验证手段 |
```

- **编号**:与 doc 文件里表格严格一致
- **三级点**:case 的人类可读标题
- **前置条件**:依赖的环境(mock 启动 / 数据源存在 / 位号存在 / 鉴权配置等)
- **测试步骤**:1. 2. 3. 编号的可执行步骤
- **预期结果**:用断言/观察指标描述(alive、quality、条数、值等)
- **验证手段**:用哪个 API 验证(list_ds_info / getRTValue / query_history 等)

### 3.3 章节分组

每个 MD 文件内部分多个 `## <group>` 小节(## 可达案例 / ## 不可达案例 / ## 鉴权案例 / ...),每节一张表。
一节内的 case 共享前置条件。

### 3.4 文档里常见的断言模板

| 章节 | 断言形态 |
|---|---|
| 连接 | alive=true / alive=false |
| 实时 | RT quality=192 / quality=0 / 值在变化 / 值不变化 |
| 历史 | 禁用期间条数不增加 / 启用后新记录落库 |
| 写 | RT 读到写入值 / write RT 一致性 |
| 响应时间 | p95_ms / p50_ms / 总耗时 |
| 性能 | poll N 个位号 RT 全部 quality=192 |
| 鉴权 | alive=false(鉴权失败)/ alive=true(配正确凭据)/ alive=true(多余凭据不影响) |
| 重复 | 报错 Duplicate data source address / Duplicate name |

### 3.5 文档里常见的前置条件模板

- "mock 已启动,端口可达"
- "数据源已禁用 / 已 alive=true / 已 alive=false"
- "mock 配置 change=true(值持续变化)"
- "mock 配置 username/password 鉴权"
- "已有数据源指向 url-A"
- "case 编号 N 的前置:N 执行后"

---

## 4. 自动化用例编写规则

### 4.1 实现结构

每个 case 一个 Python 函数,用 `@case(...)` 装饰,函数签名固定:

```python
@case(
    id="UA-X-Y-NN",                # 必须与 doc 中一致
    title="<三级点原文>",
    chapter="UA-X-Y",
    kind="regression" | "exploratory" | "performance" | "response_time",
    tags=[...],
    timeout_sec=<根据 case 估的秒数>,
    steps=[StepDef(step_id=..., title=...), ...],
    assertions=["...", ...],
)
def ua_x_y_NN_简短描述(ctx, cc):
    # 1. 前置(mock / login / 注册依赖)
    # 2. 动作(add_ds_info / change_state / add_tag / write / read)
    # 3. 断言(用 fixtures.check_true 等)
    # 4. 不抛 AssertionError 就 PASS
```

### 4.2 命名

- 函数名:`ua_{chapter_no_dash}_{NN}_{title_slug}`,全部小写、下划线分隔
  - 例:`ua_1_1_01_url_no_path`、`ua_3_1_001_collect_starts_automatically`

### 4.3 上下文

- `ctx`:RunContext,含 `emitter`、`config`、`bag`、`registry`、`evidence_root`
- `cc`:CaseContext,含 `case_id`、`title`、`registry`(LIFO)、`evidence_dir`、`bag`
- 不要新建全局状态;所有依赖走 fixture

### 4.4 资源清理

- 每创建一个资源(datasource / tag / 收藏 / 历史造数)就 `ctx.registry.register(name, kind, cleanup_fn)`
- cleanup_fn 在 case 结束时(finally)LIFO 执行;无论 PASS / FAIL / ERROR / 取消 都执行
- 不要在 cleanup_fn 里 catch Exception;让异常往上抛(runner 会把它转 CLEANUP_FAILED)

### 4.5 等待

- **禁止固定长 sleep 替代状态等待**(plan 5.6)
- 用 `wait_until(name, condition, timeout, interval, stable_count)` 或场景封装(`wait_ds_alive` / `wait_tag_present` / `wait_rt_value` / `wait_history_points`)
- 轮询过程写 evidence 时间线(`polling.py` 的 `on_poll` 回调)

### 4.6 失败处理

- 断言失败 → `raise AssertFail("...")` 或用 fixtures.check_*(...)
- 业务异常 → 让异常自然上抛(runner 把它转 ERROR)
- **不要**为了"跑通过"加 try/except 把错误吞掉
- **不要**为了"跑通过"删断言或放宽阈值

### 4.7 凭据

- TPT 账号密码走 `RunConfig.subject`,**不要**写死在代码常量里
- Mock 启停走 `mock_control.start_mock(key)` / `stop_mock(key)`,**不要**直接调 subprocess

### 4.8 报告与 NDJSON

- 每个 case 完成后,runner 自动写 NDJSON 事件 + report.json + runner.log
- 用例函数内可用 `ctx.emitter.log / metric / evidence / step_started / step_finished` 增加细节
- 不要 stdout 普通日志(会破坏 NDJSON 协议)

### 4.9 evidence 落盘

- 调用 `evidence.write_json_evidence(emitter, case_id, evidence_dir, kind=..., title=..., payload=...)` 写 JSON 证据
- 用于复盘失败原因,不用于断言(断言应该用 fixture API)

### 4.10 真实记录分类

case fail 时在 summary / nightly-report.md 里分类:
1. **FAIL**:断言失败(可能是 mock 问题,也可能是真实环境不满足)
2. **ERROR**:代码 bug(typo / API 错 / fixture 异常)
3. **OBSERVED**:探索类输出,信息性
4. **MEASURED**:响应时间类输出,信息性
5. **BLOCKED**:前置不满足,跳过
6. **CLEANUP_FAILED**:清理失败(通常 cleanup_fn 抛异常)

---

## 5. 一次性提交 / 合并纪律

- Phase 内可以多次小 commit(修复 fixture / 适配 tpt_api),但**不要**为了"跑通"在一次 commit 里改 case + 改 fixture + 删断言
- 合并到 main 前必须:
  - `pytest ua_test_harness/unit_tests -q` 全过
  - 真环境至少跑过一轮,失败原因全部归类后写进 `nightly-report.md`
  - 工程纪律全部遵守(不绕路、不吞错、不删断言)

---

## 6. 待写章节(下一步)

### 6.1 UA-1-2 启停控制(8 个 case)
- 模板:change_state(enabled=True/False) → 轮询 alive → 验证 RT quality 与值的变化
- 复用:UA-1-1-01 fixture + tag fixture + polling

### 6.2 UA-1-3 断线恢复(8 个 case)
- 模板:stop mock → 轮询 alive=false → start mock → 轮询 alive=true + RT 恢复
- 注意:当前 ua_mocker 容器是空的(§1.4 #1),RT 验证部分会真实失败

### 6.3 UA-1-4 ~ UA-1-6 (28 个)
- 模板待 §6.7 整体讨论

### 6.4 UA-2-x 位号管理(153 个)
- 模板:add_tag / list_tags / get_tag_by_name / write_tag_values / get_rt_value / batch_delete_tags / recycle / restore / 收藏 / 分组关联
- 大部分可在 list_tag / add_tag 已验证基础上铺

### 6.5 UA-3-1 ~ UA-3-6 (98 个)
- 模板:create_ds → add_tag → wait_rt → read_rt / write → wait_rt_match / history_import → verify_history
- 阻塞:ua_mocker 子节点缺失(§1.4 #1),RT 验证全部 fail,如实记录

### 6.6 codegen 工具(可选)
- 写 `ua_test_harness/codegen/md2cases.py`:解析 ua_test_harness/test_cases/*.md → 自动生成 @case 函数骨架(无函数体或最简函数体)
- 用法:先 codegen 出 419 个骨架,再人工填函数体(对 419 个 case 来说 codegen 仍省一半时间)
- 不强求:骨架可执行只是为了让 catalog 能导出 + dry-run 能列出全部 case

### 6.7 fixture 模板库规划
按章节批量复用:
- `_ensure_mock_and_login(ctx, key="functional")`:5 行
- `_make_ds(ctx, name, endpoint)`:3 行
- `_make_tag(ctx, name, ds_id, **kwargs)`:5 行
- `_wait_rt_quality_ok(ctx, name, timeout)`:3 行
- `_write_and_wait_rt(ctx, name, value, timeout)`:5 行
- `_cleanup_one_tag(api, name)` / `_cleanup_all_ua_tags(api)` / `_cleanup_all_ua_ds(api)`

放在 `ua_test_harness/tests/_helpers.py`,所有 chapter 子包共用