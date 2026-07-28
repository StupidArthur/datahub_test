# AGENTS.md — DataHub OPC UA 测试仓库的 Agent 上下文

本文件是后续 Agent 进入此仓库的稳定入口。它不是任务清单，也不复制 todo1.md。它描述**架构、约束、约定**，让 Agent 在不阅读大量历史材料的情况下能立刻开始正确的工作。

## 仓库目标

`datahub_test` 是 DataHub 平台 + OPC UA 协议栈的自动化测试仓库。当前阶段是从旧自定义 Harness（`ua_test_harness`）迁移到原生 pytest。新 Case 必须用 pytest 写；旧 Harness 保留用于行为对照与回退，不能删除。

## 五个目录的职责

| 目录 | 职责 | 禁止事项 |
|------|------|----------|
| `tests/` | **唯一**新测试入口：原生 pytest 测试、fixture、helper、文档生成器测试 | 不放 Markdown loader / Catalog / Runner / Case ID 注册表；不放万能 fixture；不在 fixture 里隐藏场景 |
| `tpt_api/` | DataHub HTTP 客户端的唯一边界 | 测试代码不得直接使用 `requests` / `httpx` 调 DataHub；不要在 `tests/support` 写第二套 HTTP 封装 |
| `ua_mocker/` | OPC UA Mock Server：节点、类型、动态值、可选鉴权 | 不放产品业务规则；不放 DataHub 适配 |
| `ua_test_harness/` | 旧自定义测试框架，保留 | 不删、不向其中加新功能；只在迁移期回归比较使用 |
| `ua_test_gui/` | Wails GUI，当前仍走旧 Harness | 切换到 pytest 后端时必须保留旧执行路径；不删除 legacy service；不修改默认执行模式 |

## pytest 是唯一新执行器

禁止新建：

* Catalog、Runner、Case registry
* Markdown loader、动态测试函数生成器
* Case ID → handler 映射
* 自定义 PASS/FAIL 状态机

`@pytest.mark.case(...)` 标记用于**文档生成**与跟踪，不参与执行分发。执行身份是 `tests/.../test_xxx.py::test_xxx` 即 pytest nodeid。

## 测试代码是文档唯一来源

```
pytest 测试代码 → tools.generate_case_docs → docs/test_cases/{UA-1-1.md, UA-1-2.md, ..., case-manifest.json}
```

* `docs/test_cases/*.md` 由 `pytest --collect-only` + `pytest.mark.case` marker 自动生成
* `docs/test_cases/case-manifest.json` 同次 collection 生成，schemaVersion=1
* **禁止手工修改生成 Markdown 或 manifest**——改 marker 后再跑 `python -m tools.generate_case_docs`
* 删除生成 Markdown 不影响 pytest；pytest collection 不读 Markdown
* Case ID 只用于追踪、搜索、文档展示

## `tpt_api` 边界

测试代码唯一允许通过 `tpt_api.datahub` 等高层 API 与 DataHub 通信。原子操作：

* `add_ds_info` / `list_ds_info` / `delete_ds_info` / `change_ds_state`
* `add_tag` / `list_tags` / `delete_tags` / `delete_tags_physical` / `list_recycle_tags`
* `get_rt_value` / `query_history_value` / `get_history_value` / `get_all_history`
* `test_ds_info`

`tpt_api.errors.TptAPIError` 是 DataHub 业务错误唯一异常类型，含 `.code` 与 `.msg` 结构化字段。禁止捕获 `Exception` 后忽略业务错误。

## fixture 约束

根 `tests/conftest.py` 维持最小：

```
settings (session)        # 从环境变量读 DATAHUB_BASE_URL 等
api (session)            # tpt_api.client.AlgAPI；HTTP 客户端在 session 末尾关闭
mocker_endpoint (session) # 从 UA_MOCKER_ENDPOINT 读
```

禁止在根 conftest 新增：

```
universal_resource_manager / scenario_fixture / mocker_scenario_fixture /
case_runtime / cleanup_registry / 任何 autouse 环境清理
```

需要稳定前置的，按模块局部 fixture 定义在 `tests/integration/ua1/<test_xxx>.py` 内，且 fixture 只创建资源不编排场景。具体场景（启停、重连、错误注入、endpoint 变化）必须出现在测试函数体中。

## mocker 原则

`tests/support/mocker_process.py` 是唯一允许显式启动/停止 mocker 的入口：

* `find_free_port` / `write_mocker_config` / `start_mocker` / `wait_port_ready` / `stop_mocker`
* 测试函数必须用 `mocker = start_mocker(...); try: ... finally: stop_mocker(mocker)` 显式控制
* 不通过端口号杀进程，不允许 kill 非本测试启动的进程
* 临时 YAML 写到 pytest `tmp_path_factory` 目录，**不提交**
* 默认节点：`2_smoke_static_1`（Double, default=12.5, writable）和 `2_smoke_change_1`（Int32, change=true）
* `write_mocker_config(..., auth={enabled,username,password})` 启用 OPC UA 用户名密码认证

## cleanup 安全规则

* cleanup helper 只能清理当前测试记录的资源 ID（datasource id、tag id）
* 只忽略明确的"资源不存在"错误（msg 含 `not exist` / `不存在`）；网络、鉴权、服务端异常必须传播
* cleanup 失败必须使测试失败（`AssertionError` 或 `TptAPIError`）
* 不允许批量清理带前缀的所有资源；不允许清空整个回收站；不允许 kill 非本测试进程
* 名称约定：`{DATAHUB_TEST_PREFIX}{Case ID}_{8 hex}`，例如 `pytest_native_UA-1-1-01_a1b2c3d4`

## `get_rt_value` 不允许 fake 数据

历史教训：`tests/integration/ua1/test_lifecycle_control.py` 中曾把 `TptAPIError("Tag Dose Not Exist")` 转换为 `{"tagName": ..., "tagValue": None, "quality": 0}` 的虚假返回，掩盖了真实产品行为。

当前 helper 拆分约定（`tests/support/rt_helpers.py`）：

* `get_rt_point(api, tag_name)` — 正常读取，传播 `TptAPIError`
* `try_get_rt_point(api, tag_name)` — 返回 `{}` 表示 tag 不存在；用于"轮询等待"的探针
* `assert_rt_unavailable(api, tag_name)` — 断言抛 `TptAPIError`，用于 UA-1-2-02 类用例

测试代码**不得**在 `_get_rt_point` 风格 helper 中把异常转换为假对象。

## 生成文档与离线检查

```bash
python -m compileall -q tests tools ua_test_harness tpt_api/python/tpt_api ua_mocker
pytest tests/unit -q
pytest --collect-only -q tests
python -m tools.generate_case_docs --check
pytest tpt_api/python/tests -q
python -m tools.check_test_environment
```

CI（`.github/workflows/offline-checks.yml`）会跑以上命令 + `cd ua_test_gui && go test ./...`。CI **不能**访问真实 DataHub / 真实 mocker 长进程 / 旧 Harness integration。

## integration 测试要求

* `pytest tests/integration/ua1 -v` 串行执行（不使用 pytest-xdist）
* 资源命名严格遵守 `DATAHUB_TEST_PREFIX + Case ID + 8 hex`
* 执行前后审计当前 prefix 残留资源；只清理本测试创建的 ID
* `pytest.mark.integration` 与 `pytest.mark.destructive` 已注册；额外 marker 在 `pyproject.toml` 同步注册
* 真实环境跑前先 `python -m tools.check_test_environment` 验证连通性

## 双轨 GUI

GUI (`ua_test_gui/`) 当前仍通过 `pytestrunner` 启动旧 Harness（`python -m ua_test_harness.cli run --config ...`）。

新增 native pytest 路径必须：

* 读取 `docs/test_cases/case-manifest.json`
* 用 pytest nodeid（不是 Case ID）启动 `python -m pytest <nodeid> --junitxml=...`
* 解析 JUnit XML → passed / failed / error / skipped / xfail / xpass
* 解析结果回写：nodeid 或 classname+name 组合 → manifest Case
* **保留** legacy service 默认不动；新增 mode 选项至少实现 Go 后端 + 单元测试

## 禁止事项（架构级）

* 不删除旧 Harness
* 不让 Markdown 参与 pytest collection / 执行 / 状态判定
* 不动态生成 pytest 测试函数
* 不创建新 Catalog / Runner / Case ID handler map
* 不在 fixture 中隐藏 mocker 重启 / 鉴权 / 断连行为
* 不允许 `pytest.raises(Exception)`；必须断言 `TptAPIError` 或更具体类型
* 不允许 `try: ... except Exception: pass` 静默吞掉 cleanup 错误
* 不允许 `time.sleep()` 后不验证状态——必须用 `wait_until(name, condition, timeout)` 轮询
* 不允许把异常转换为虚假正常返回
* 不允许用 `pytest.skip` 掩盖未实现功能（用 `pytest.mark.xfail(strict=True)` + 完整可执行测试 + blocker 文档）
* 不修改生成 Markdown / manifest
* 不批量 kill Python / mocker 进程
* 不在命令行参数中传密码
* 不提交 `.env` / 运行日志 / JUnit 结果 / 真实环境配置

## 提交与推送

* 直接在 main 上工作
* 每次开始执行 `git switch main` 和 `git pull --ff-only`
* 小批次独立 commit 并 push origin main
* 不创建长期分支或 PR
* 不 rebase 已推送提交，不 force push
* 禁止 `git add .`；只暂存明确文件
* commit message 形如 `feat(area): <description>` / `fix(area): <description>` / `test(area): <description>` / `docs(area): <description>` / `ci(area): <description>`

## 真实集成测试环境

* Agent 所在主机始终是能够访问真实 DataHub 和 OPC UA mocker 的集成测试主机。
* 不得默认声称"没有真实环境""无法访问真实环境"，也不得只执行离线检查后结束任务。
* 每个迁移批次完成离线验证后，必须主动询问用户：

  * 是否立即执行真实环境测试；
  * 当前 shell 是否已经加载或需要重新设置测试环境配置。
* 用户确认执行后，必须运行真实集成测试和完整回归。
* 环境变量暂未加载时，不得将集成 Case 记为 SKIP 后结束；应先设置下列固定测试配置。

固定 DataHub 配置：

```text
DATAHUB_BASE_URL=http://10.10.58.153:31501
DATAHUB_USER=admin
DATAHUB_PASSWORD=123456
```

固定 OPC UA mocker 主机：

```text
10.30.70.77
```

OPC UA 规则：

* mocker 使用 `10.30.70.77` 上的动态端口。
* 不得固定复用某个测试端口。
* 实际 endpoint、host 和 port 必须从测试 context 获取。
* canonical endpoint 参考：

```text
opc.tcp://10.30.70.77:18960/ua_mocker/
```

真实环境运行前，在 PowerShell 中设置：

```powershell
$env:DATAHUB_BASE_URL = "http://10.10.58.153:31501"
$env:DATAHUB_USER = "admin"
$env:DATAHUB_PASSWORD = "123456"
$env:UA_MOCKER_ENDPOINT = "opc.tcp://10.30.70.77:18960/ua_mocker/"
```

然后执行：

```powershell
python -m tools.check_test_environment
```

环境检查成功后，运行当前批次测试和完整回归。不得使用：

```text
-x
--maxfail
pytest.skip 掩盖环境未设置
```

不得把"环境变量未配置"作为 Agent 所在主机无法运行真实测试的结论。

## 当前状态参考

### 迁移计数
| 组 | 总量 | PASS | FAIL (产品限) | XFAIL (未约定) | 未迁移 |
|----|------|------|--------------|----------------|--------|
| UA-1-1 | 12 | 12 | 0 | 0 | 0 |
| UA-1-2 | 6 | 4 | 0 | 2 | 0 |
| UA-2-1 | 112 | 62 | 10 | 40 | 0 |
| UA-2-2 | 67 | 56 | 0 | 11 | 0 |
| UA-2-3 | 29 | 23 | 1 | 5 | 0 |
| UA-2-4 | 27 | 5 | 4 | 10 | 8 |

FAIL 十四道确认产品能力限制：
- **UA-2-1-019** 空 tagName → 产品接受空 tagName，回落为节点名
- **UA-2-1-044** Byte 255 → DataHub signed-byte 映射限制（`Write tag value type convert failed`）
- **UA-2-1-048** UInt16 65535 → DataHub U_SHORT 映射限制
- **UA-2-1-052** UInt32 4294967295 → DataHub U_INT 映射限制
- **UA-2-1-058** UInt64 18446744073709551615 → DataHub U_LONG 映射限制
- **UA-2-1-066** 空字符串值被拒绝（`writing tag value can not be null`）
- **UA-2-1-071** DateTime UTC ISO 被拒绝（`tag data type error`）
- **UA-2-1-072** DateTime 带时区被拒绝（`tag data type error`）
- **UA-2-1-074** DateTime epoch 边界被拒绝（`tag data type error`）
- **UA-2-1-027** SByte 默认读取偶发时序竞争（change node 值漂移：期望 3 实际 2）
- **UA-2-4-001/002/003** 软删除后 `list_tags` 仍返回位号（双重可见）
- **UA-2-4-009** 软删除后 `write_tag_values` 成功且传播到 OPC UA 源

XFAIL 50 道为行为未约定（overflow / coercion / whitespace / length 129 / special chars / unicode / Int64 out-of-range / UInt64 negative and overflow / NaN/Inf / length boundaries / frequency effect / alarm limits / history / batchAdd / spec_pending）。

### 清理基础设施
- **`tests/support/ua2_cleanup.py`**: `strict_cleanup_ua2_context()` — 六步严格清理（物理删 tag → 清回收站 → 禁 DS → 删 DS → 停 mocker → 验端口），所有错误聚合不吞
- **残差验证**: 执行前后 COW 审计 DS/active-tag/recycle-tag/mocker/dynamic-port 零残留

### 恢复 API 注意事项
- 恢复位号: `remove_tag_group_relation(api, group_id="1", tag_ids=[...])`
- API 返回 `false` 但操作实际生效，必须以 `list_recycle_tags` 确认为准
- 验证模式: 软删除后 `assert recycle 无此 ID` → 恢复后 `assert recycle 无此 ID` + RT 轮询
- 恢复测试文件: `tests/integration/ua2/test_tag_delete_restore.py`

### 架构约束已确认
- UA-2-1-012/015 使用 `setup_ds_only()` + `try_add_tag()` 分步模式，严格 cleanup 后动态 `pytest.xfail`
- 不动态生成测试函数、不创建 Catalog/Runner、不在 fixture 隐藏场景
- GUI 仍 default legacy；native pytest 后端作为增量能力

### 详细迁移历史
- UA-1-1 阻塞（UA-1-1-07 鉴权）：见 `docs/migration/ua-1-1-07-blocker.md`
- UA-1-2 阻塞（UA-1-2-03/05 历史）：见 `docs/migration/ua-1-2-03-blocker.md`
- UA-2-1 全组已迁移并回归
- UA-2-3 全组已迁移并回归（3 FAIL：006/010 表头偏移，017 DateTime 导入拒绝）
- UA-2-4 已迁移 001~019（5 PASS + 4 FAIL 产品限 + 10 XFAIL spec_pending）；020~027 待迁移