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

* 单一分支：`refactor/native-pytest-slice`
* 不 rebase 已推送提交，不 force push，不合并 main
* 每完成一项独立修改 commit + push
* 禁止 `git add .`；逐文件检查后 `git add <file>`
* commit message 形如 `feat(area): <description>` / `fix(area): <description>` / `test(area): <description>` / `docs(area): <description>` / `ci(area): <description>`

## 当前状态参考

* 已迁移 18 条 Case（UA-1-1-01 ~ 12，UA-1-2-01/02/04/06/07/08）
* 阻塞：UA-1-1-07 鉴权（产品能力待确认）、UA-1-2-03/05 历史（迁移中）、UA-1-3 整组（未迁移）
* GUI：仍 default legacy；native pytest 后端作为增量能力
* 详细迁移历史：见 `docs/migration/` 下各 blocker 文件