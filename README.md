# datahub_test

DataHub + OPC UA 自动化测试仓库。

## 目录结构

| 目录 | 职责 |
|------|------|
| `tests/` | 原生 pytest 测试（目标架构） |
| `tools/` | 文档生成器、环境诊断等开发工具 |
| `tpt_api/` | DataHub HTTP 客户端库（Python） |
| `ua_mocker/` | OPC UA Mock Server（asyncua） |
| `ua_test_harness/` | 旧测试框架（保留，迁移期并存） |
| `ua_test_gui/` | Wails GUI（尚未切换到 pytest） |
| `ua_tpt_manager/` | TPT 管理工具 |

## 原生 pytest 目标架构

```text
pytest test
  → 少量 fixture (settings / api / mocker_endpoint)
  → tpt_api
  → DataHub

pytest test
  → 显式 mocker 场景 (tests/support/mocker_process.py)
  → ua_mocker
```

## Python 环境

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ./tpt_api/python
pip install pytest pyyaml httpx asyncua
```

## 环境变量

复制 `.env.example` 为 `.env` 并填入真实值：

```text
DATAHUB_BASE_URL=http://<host>:<port>
DATAHUB_TENANT_ID=
DATAHUB_USER=admin
DATAHUB_PASSWORD=<password>
DATAHUB_TOKEN=
UA_MOCKER_ENDPOINT=opc.tcp://<local_ip>:18960/ua_mocker/
DATAHUB_TEST_PREFIX=pytest_native_
```

## 环境诊断

```bash
python -m tools.check_test_environment
```

## 单元测试

```bash
pytest tests/unit -q
```

## Collection

```bash
pytest --collect-only -q tests
```

## 文档生成

```bash
python -m tools.generate_case_docs
python -m tools.generate_case_docs --check
```

## 真实 integration 测试

```bash
pytest tests/integration -v
```

## 旧 Harness 对照

旧 Harness 保留在 `ua_test_harness/`，用于行为对照：

```bash
python -m ua_test_harness.cli run --config <run-config.json> --cases UA-1-1-01
```

## GUI

`ua_test_gui/` 尚未切换到 pytest 执行器。未来通过 `case-manifest.json` 获取 Case 列表，用 pytest nodeid 执行。

## 资源清理安全规则

- 测试资源名称：`DATAHUB_TEST_PREFIX + Case ID + 随机后缀`
- 只清理当前测试明确创建的资源（按 ID）
- 禁止批量清理非本测试资源
- cleanup 失败必须暴露，不允许静默忽略
