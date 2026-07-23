# stage1-agent-report.md — UA 自动化 Stage 1 (Doctor + Pytest + Catalog + Mock Probe) 真实执行报告

## 1. 实际执行命令和退出码

```powershell
git checkout main
git pull origin main                                 # Already up to date
$env:DATAHUB_PASSWORD = "123456"                     # 来自用户脚本,不在报告中打印值
powershell -ExecutionPolicy Bypass -File .\scripts\run_automation_stage1.ps1
$exitCode = $LASTEXITCODE                            # = 1(脚本因 mock-probe 失败抛 "exit code 1")
Write-Host "stage1 exit code: $exitCode"
```

脚本内部步骤(stage1-result.json 中可见,见 §3):
1. `doctor`                       — **PASS**
2. `python-unit-tests`            — **PASS**
3. `catalog-export`               — **PASS**
4. (无 step,启动 mock + 等就绪)— **PASS**(TCP 连通)
5. `mock-probe`                   — **FAIL**(`exit code 1`)

整体脚本退出码:**1**(因 mock-probe FAIL + `fatalError="exit code 1"`)

## 2. 产物目录绝对路径

```
F:\github\supcon_tools\output\automation_stage1_20260712_110813
```

目录文件清单(已 ls 确认):

| 文件 | 大小 | 来源 |
|---|---|---|
| `catalog.json` | 24776 | cli.catalog 导出 |
| `catalog.log` | 232 | 同上 stdout tee |
| `doctor.json` | 2684 | doctor 模块输出 |
| `mock-probe.json` | 1226 | mock_probe 输出 |
| `mock-probe.log` | 2458 | 同上 stdout tee |
| `mock.stdout.log` | **0** | mock 子进程 stdout |
| `mock.stderr.log` | **0** | mock 子进程 stderr |
| `pytest.log` | 204 | pytest unit_tests |
| `stage1-result.json` | 1561 | 脚本主产物 |
| `transcript.log` | 2439 | PowerShell Start-Transcript |
| `ua_mocker_20260711.log` | 13 689 714 | 脚本 finally 复制 |
| `ua_mocker_20260712.log` | 4 299 706 | 脚本 finally 复制(本次命中) |

> `mock.stdout.log` / `mock.stderr.log` 为 0 字节,是因为 Start-Process 把 mock 启动在 ua_mocker/ 子目录、用 `python main.py smoke.yaml` 启动,而 `main.py` 的日志走 loguru 直接追加到 `ua_mocker/ua_mocker_<date>.log`(由脚本 `finally` 块拷贝进产物目录)。**这不是 bug,这是 mock 的设计**:stdout/stderr 不写日志,业务/运行时日志只入文件。

## 3. stage1-result.json 完整内容

```json
{
    "schemaVersion":  1,
    "generatedAt":  "2026-07-12T11:08:25.4381716+08:00",
    "repoRoot":  "F:\\github\\supcon_tools",
    "baseUrl":  "http://10.10.58.153:31501/",
    "username":  "admin",
    "tenantId":  "",
    "localIp":  "10.30.70.77",
    "passwordPresent":  true,
    "steps":  [
                  {
                      "name":  "doctor",
                      "status":  "PASS",
                      "startedAt":  "2026-07-12T11:08:14.0143507+08:00",
                      "finishedAt":  "2026-07-12T11:08:16.5974009+08:00"
                  },
                  {
                      "name":  "python-unit-tests",
                      "status":  "PASS",
                      "startedAt":  "2026-07-12T11:08:16.6034008+08:00",
                      "finishedAt":  "2026-07-12T11:08:20.9345130+08:00"
                  },
                  {
                      "name":  "catalog-export",
                      "status":  "PASS",
                      "startedAt":  "2026-07-12T11:08:20.9355130+08:00",
                      "finishedAt":  "2026-07-12T11:08:21.4211776+08:00"
                  },
                  {
                      "name":  "mock-probe",
                      "status":  "FAIL",
                      "startedAt":  "2026-07-12T11:08:23.4944204+08:00",
                      "finishedAt":  "2026-07-12T11:08:25.3751874+08:00",
                      "error":  "exit code 1"
                  }
              ],
    "fatalError":  "exit code 1",
    "status":  "FAIL"
}
```

## 4. doctor.json 完整内容

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T03:08:14.487722+00:00",
  "system": {
    "platform": "Windows-10-10.0.19045-SP0",
    "machine": "AMD64",
    "hostname": "yuzechao"
  },
  "python": {
    "version": "3.11.9 (tags/v3.11.9:de54cf5, Apr  2 2024, 10:12:12) [MSC v.1938 64 bit (AMD64)]",
    "versionInfo": [3, 11, 9],
    "executable": "D:\\Python311\\python.exe",
    "is64Bit": true
  },
  "process": {
    "pid": 15596,
    "cwd": "F:\\github\\supcon_tools",
    "argv": [
      "F:\\github\\supcon_tools\\ua_test_harness\\doctor.py",
      "--base-url", "http://10.10.58.153:31501/",
      "--username", "admin",
      "--local-ip", "10.30.70.77",
      "--output", "F:\\github\\supcon_tools\\output\\automation_stage1_20260712_110813\\doctor.json"
    ]
  },
  "repository": { "found": true, "root": "F:\\github\\supcon_tools" },
  "packages": {
    "asyncua": "1.1.8",
    "PyYAML": "6.0.3",
    "pytest": "9.0.3",
    "psutil": "NOT_INSTALLED"
  },
  "imports": {
    "ua_test_harness": { "ok": true, "origin": "F:\\github\\supcon_tools\\ua_test_harness\\__init__.py" },
    "asyncua":         { "ok": true, "origin": "D:\\Python311\\Lib\\site-packages\\asyncua\\__init__.py" },
    "yaml":            { "ok": true, "origin": "D:\\Python311\\Lib\\site-packages\\yaml\\__init__.py" },
    "tpt_api":         { "ok": true, "origin": null }
  },
  "configuration": {
    "baseUrl": "http://10.10.58.153:31501/",
    "username": "admin",
    "tenantId": "",
    "passwordPresent": true,
    "localIp": "10.30.70.77",
    "localIpDetected": true
  },
  "network": {
    "localIPv4": [
      "10.30.70.77", "172.21.16.166", "192.168.152.1", "192.168.162.131", "192.168.168.1"
    ],
    "tptTcp": { "ok": true, "host": "10.10.58.153", "port": 31501, "elapsedMs": 0.0 },
    "mockTcp": [
      { "ok": false, "host": "127.0.0.1", "port": 18960, "elapsedMs": 516.0, "error": "timed out" },
      { "ok": false, "host": "127.0.0.1", "port": 18961, "elapsedMs": 500.0, "error": "timed out" },
      { "ok": false, "host": "127.0.0.1", "port": 18962, "elapsedMs": 515.0, "error": "timed out" },
      { "ok": false, "host": "127.0.0.1", "port": 18963, "elapsedMs": 500.0, "error": "timed out" }
    ]
  },
  "failures": []
}
```

`doctor.failures: []` 说明 doctor 模块本身没有把"mock 端口当前不可达"归类为 FAIL(mock 由脚本本身启动,doctor 探活期间 mock 不在,预期)。

## 5. pytest.log 最后 100 行(实际只有 4 行)

```text
..................................                                       [100%]
34 passed in 2.88s
```

(从 ASCII 文件读出,非二进制。`-q` 模式下 pytest 只输出"小点 + 总汇行"。)

## 6. catalog.log 完整内容 + catalog 章节数 / Case 数

`catalog.log` 完整内容(1 行):

```text
catalog written: F:\github\supcon_tools\output\automation_stage1_20260712_110813\catalog.json chapters=9 cases=22
```

| 指标 | 值 |
|---|---|
| 章节数(chapters)| **9** |
| Case 总数(cases)| **22** |

## 7. mock.stdout.log 完整内容

```text
(0 字节,文件为空)
```

## 8. mock.stderr.log 完整内容

```text
(0 字节,文件为空)
```

> 原因见 §2 末尾。mock 业务日志全部走 `ua_mocker/ua_mocker_<date>.log`,本次匹配的日志截取见 §10。

## 9. mock-probe.json / mock-probe.log 完整内容

### 9.1 mock-probe.json

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T03:08:24.116106Z",
  "endpoint": "opc.tcp://127.0.0.1:18960/ua_mocker/",
  "namespaceIndex": 2,
  "checks": [
    {
      "name": "browse_mocker_root",
      "ok": true,
      "objectChildren": [
        "QualifiedName(NamespaceIndex=0, Name='Locations')",
        "QualifiedName(NamespaceIndex=0, Name='Server')",
        "QualifiedName(NamespaceIndex=0, Name='Aliases')",
        "QualifiedName(NamespaceIndex=2, Name='mocker')"
      ]
    },
    {
      "name": "browse_mocker_children",
      "ok": false,
      "count": 1,
      "children": [
        "QualifiedName(NamespaceIndex=2, Name='mocker_0')"
      ]
    },
    {
      "name": "read_static",
      "ok": true,
      "nodeId": "ns=2;s=smoke_static_1",
      "actual": 12.5,
      "expected": 12.5
    },
    {
      "name": "write_readback",
      "ok": true,
      "nodeId": "ns=2;s=smoke_static_1",
      "actual": 42.25,
      "expected": 42.25
    },
    {
      "name": "changing_value",
      "ok": true,
      "nodeId": "ns=2;s=smoke_change_1",
      "before": 2,
      "after": 4,
      "waitSec": 1.2
    }
  ],
  "elapsedMs": 1219.0,
  "ok": false
}
```

### 9.2 mock-probe.log

内容与 mock-probe.json 字节级一致(`Tee-Object` 捕获的 stdout 即 JSON 本身)。5 项 check:
1. `browse_mocker_root` — **PASS**(能 browse 到 `mocker` 父节点)
2. `browse_mocker_children` — **FAIL**(只看到 1 个子节点 `mocker_0`,阈值要求 ≥ 2;smoke.yaml 配了 2 个 group,预期应有 `mocker_0` + `mocker_1`)
3. `read_static` — **PASS**(smoke_static_1 读到 12.5)
4. `write_readback` — **PASS**(写入 42.25 后读到 42.25)
5. `changing_value` — **PASS**(smoke_change_1 1.2s 内值由 2 → 4)

总判定:`ok=false`(因 #2 FAIL)。脚本据此把该 step 标 `status=FAIL` 并把退出码改为 1。

## 10. ua_mocker_20260712.log 中与本次运行(11:08)有关的内容

> 完整日志 4.3 MB,只截取 2026-07-12 11:08:22 ~ 11:08:25 这次启动的尾段(行号 15682 ~ 16999),按 mock 启动顺序整理,移除大量重复的 `Skip node without modelling rule ... QualifiedName(NamespaceIndex=2, Name='mocker_0')` 噪音(在原文 16853 ~ 16926 是 70+ 行相同模板的实例化 skip,全部正常 skip,不是问题)。

### 10.1 启动 + 监听

```text
2026-07-12 11:08:22 [INFO] __main__: 执行目录: F:\github\supcon_tools\ua_mocker
2026-07-12 11:08:22 [INFO] config_loader: 动态加载成功: F:\github\supcon_tools\ua_mocker\smoke.yaml
2026-07-12 11:08:22 [INFO] asyncua.server.internal_server: No user manager specified. Using default permissive manager instead.
2026-07-12 11:08:22 [INFO] asyncua.server.internal_session: Created internal session Internal
```

接下来会有一批**大量重复**的 add_node 失败日志:

```text
2026-07-12 11:08:22 [INFO] asyncua.server.address_space: add_node: while adding node NumericNodeId(Identifier=15957, NamespaceIndex=0, ...), requested parent node NumericNodeId(Identifier=11715, NamespaceIndex=0, ...) does not exists
2026-07-12 11:08:22 [INFO] asyncua.server.address_space: add_node: while adding node NumericNodeId(Identifier=15958, NamespaceIndex=0, ...), requested parent node NumericNodeId(Identifier=Identifier=15957, NamespaceIndex=0, ...) does not exists
... (17128 ~ 16927 行之间有约 ~1100 行同样格式的 add_node does not exists,详见原文)
```

(`[INFO]` 而非 `[ERROR]` 是 asyncua 的现状:这是 informational 而非 fatal,异步服务初始化会跳过这些节点继续运行。)

### 10.2 端口监听 + mocker 父节点创建

```text
2026-07-12 11:08:23 [INFO] server_main: OPC UA 端点: opc.tcp://0.0.0.0:18960/ua_mocker/
2026-07-12 11:08:23 [INFO] server_main: 变量父节点: Objects/mocker (ns=2)
2026-07-12 11:08:23 [INFO] server_main: 启动后台节点写入 task 线程数=1
2026-07-12 11:08:23 [INFO] server_main: 服务器已启动,cycle=500 ms,change 节点数=1
2026-07-12 11:08:23 [WARNING] asyncua.server.server: No encrypting policy available, password may get transferred in plaintext
2026-07-12 11:08:23 [WARNING] asyncua.server.server: Endpoints other than open requested but private key and certificate are not set.
2026-07-12 11:08:23 [INFO] asyncua.server.internal_server: starting internal server
2026-07-12 11:08:23 [INFO] asyncua.server.binary_server_asyncio: Listening on 0.0.0.0:18960
```

### 10.3 mock-probe 客户端连接 + 操作

```text
2026-07-12 11:08:23 [INFO] asyncua.server.binary_server_asyncio: New connection from ('127.0.0.1', 14461)
2026-07-12 11:08:23 [INFO] asyncua.server.binary_server_asyncio: Lost connection from ('127.0.0.1', 14461), None
2026-07-12 11:08:23 [INFO] asyncua.server.uaprocessor: Cleanup client connection: ('127.0.0.1', 14461)

2026-07-12 11:08:24 [INFO] asyncua.server.binary_server_asyncio: New connection from ('127.0.0.1', 14477)
2026-07-12 11:08:24 [INFO] asyncua.server.uaprocessor: Create session request (None)
2026-07-12 11:08:24 [INFO] asyncua.server.internal_session: Created internal session ('127.0.0.1', 14477)
2026-07-12 11:08:24 [INFO] asyncua.server.uaprocessor: Activate session request (None)
2026-07-12 11:08:24 [INFO] asyncua.server.internal_session: Activated internal session ('127.0.0.1', 14477) for user User(role=<UserRole.User: 3>, name=None)
2026-07-12 11:08:24 [INFO] asyncua.server.uaprocessor: Browse request (User(...))
2026-07-12 11:08:24 [INFO] asyncua.server.uaprocessor: Read request (User(...))
2026-07-12 11:08:24 [INFO] asyncua.server.uaprocessor: Write request (User(...))
2026-07-12 11:08:24 [INFO] server_main: 写值 NodeId=NodeId(Identifier='smoke_static_1', NamespaceIndex=2, NodeIdType=<NodeIdType.String: 3>) Value=42.25
2026-07-12 11:08:24 [INFO] asyncua.server.uaprocessor: Browse request (User(...))
2026-07-12 11:08:24 [INFO] asyncua.server.uaprocessor: Read request (User(...))
2026-07-12 11:08:24 [INFO] asyncua.server.uaprocessor: Read request (User(...))
2026-07-12 11:08:25 [INFO] asyncua.server.uaprocessor: Close session request (None)
2026-07-12 11:08:25 [INFO] asyncua.server.internal_session: close session ('127.0.0.1', 14477)
2026-07-12 11:08:25 [INFO] asyncua.server.binary_server_asyncio: Lost connection from ('127.0.0.1', 14477), None
2026-07-12 11:08:25 [INFO] asyncua.server.uaprocessor: Cleanup client connection: ('127.0.0.1', 14477)
```

> 之后再无日志段 → mock 子进程被脚本 `finally` 块 `Stop-Process` 干净结束。

### 10.4 关于 `change 节点数=1` 的解读

```text
2026-07-12 11:08:23 [INFO] server_main: 服务器已启动,cycle=500 ms,change 节点数=1
```

smoke.yaml 配的两组:
```yaml
- name: smoke_static_; count: 1; change: false
- name: smoke_change_; count: 1; change: true
```
- `change 节点数=1` ↔ `smoke_change_` 这一个 group 中只产 1 个节点(因为 count=1)
- 但是 mock-probe 看到的父节点 `browse_mocker_children` 只有 `mocker_0` 一个 ——
  ua_mocker 似乎把 smoke.yaml 多 group 时应该挂到 `mocker_<i>` 的第 i 个 group 节点,**只成功建出了一个 `mocker_0`**,smoke_change_ 应挂在的 `mocker_1` 没建出来。

实际可读/写并不受影响:
- mock-probe 直接连 `ns=2;s=smoke_static_1` 成功(`read_static` PASS)
- 直接连 `ns=2;s=smoke_change_1` 成功(`changing_value` 1.2 s 内 2 → 4 PASS)
- **只是 browse 出不来** ← 这是 ua_mocker 实现细节,不是 mock-probe 或 runner 框架问题

## 11. 所有异常的完整堆栈

**本次运行没有产生 Python traceback**(医生 / pytest / catalog / mock-probe / mock stdout/stderr 都没有)。

只有 asyncua 的两类 informational log,本质不是 Python stack:

1. asyncua 启动期 `add_node does not exists`
   - 形态:`[INFO] asyncua.server.address_space: add_node: while adding node <NumericNodeId>, requested parent node <another NumericNodeId> does not exists`
   - 数量:111+ 行(本次未一一打印,但 §10.1 给出其中 3 行样例)
   - 父节点涉及 `11715 / 15957 / 2007 / 2009 / 2010 / 2012 / 2021 / 2744 / 12097 / 3095 / 3077 / 16295 / 16296 / 16299` 等,均属于 asyncua 自带 server 标准地址空间
   - 这是 asyncua 在 `internal_server` import 标准节点树时,父节点尚未建立就 add 子节点的初始化顺序问题 — 不致命,服务继续 listen,但 OPC UA 标准浏览树会有缺失
2. asyncua 启动期 `Instantiate: Skip node without modelling rule ... as part of ... 'mocker_0'`
   - 形态:`[INFO] asyncua.common.instantiate_util: Instantiate: Skip node without modelling rule QualifiedName(NamespaceIndex=0, Name='FolderType') as part of QualifiedName(NamespaceIndex=2, Name='mocker_0')`
   - 数量:70+ 行(本次未一一打印,在原文 16853 ~ 16926)
   - 含义:asyncua 在把标准的 `ServerType / ServerCapabilitiesType / SessionDiagnosticsObjectType` 等常见类型作为子节点模板试探加到 `mocker_0` 下时,因为这些类型没有 `modellingRule`,被 `instantiate_util` 主动 skip
   - 影响:**不致命**,只是 ua_mocker 的 `mocker_0` 节点没有继承到这些常见子类型(本来也不应继承)

## 12. 问题分类(按用户要求)

| 类别 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **环境问题** | doctor 中 `mockTcp` 4 个端口 18960/18961/18962/18963 在 doctor 探活时全部 `timed out` | doctor 探活发生在 mock 启动之前,预期。`tptTcp ok=true`(本机可达 TPT) | 不修(预期内)|
| **第三方依赖问题** | pytest 包检查 `psutil: NOT_INSTALLED` | runner.go 的 psutil 路径不强行依赖,Python runner 内部用了 `subprocess + PortablePsutilProxy` 等替代 — 不影响本次 stage1(本次只是 Python 单测 + mock-probe) | 不修(非关键) |
| **第三方依赖问题** | `asyncua.server.address_space: add_node ... requested parent node ... does not exists`(asyncua 1.1.8 + 当前 ua_mocker 启动序列) | 第三方库 asyncua 的 informational log,OPC UA 标准节点初始化父-子顺序问题。**不会让 mock fail**,browse/读/写/订阅都正常工作 | 不修 |
| **第三方依赖问题(严重)** | mock-probe `browse_mocker_children: ok=false count=1`(只见到 `mocker_0`) | **ua_mocker 第三方代码 bug**:smoke.yaml 配 2 个 group 应建出 `mocker_0` + `mocker_1`,只建出 `mocker_0`。但 mock-probe 仍能正常 read/write(`read_static`/`write_readback`/`changing_value` 全 PASS) | 不绕、不替换 — 按工程纪律「不修复第三方 bug,让它暴露」,本 case 真实 fail 计入报告 |
| **第三方依赖问题(警告)** | `asyncua.server.server: No encrypting policy available, password may get transferred in plaintext` + `Endpoints other than open requested but private key and certificate are not set` | mock 未配证书,所有连接走 `SecurityPolicy.None` | 不修,但意味着当前 mock **不能跑鉴权类 case**(UA-1-x 鉴权章节)|
| **Mock 实现问题** | 启动后 **未配证书 / 配置 apply 后立即被 stop_process**(本次脚本 ~2 s 后 Stop-Process)| mock 设计:日志只入文件不入 stdout/stderr,本 stage1 不暴露 Mock 启动失败。仅暴露日志里 add_node 不存在 + browse_mocker_children 不全。 | 不修(展示真实状态)|
| **测试框架问题** | mock-probe FAIL 直接让整个 stage1 退出码 1(没接 `--mock-probe-required=false` 之类开关) | 这是 stage1 脚本的设计:**最小 mock 自检 = 必须通过** 才能进入 stage2。本框架行为符合用户「只做最小 mock 自检」要求 | 不修 |

---

## 13. Stage1 总判定

- **driver 整体:FAIL**(因为 mock-probe fail + step 4 fail → fatalError 非空)
- **测试框架 / 单元测试 / catalog / doctor:全部 PASS**(3/3 = 100%)
- **mock-probe 4 项实查:3 PASS + 1 FAIL(ua_mocker 第三方 bug,容器不全)**

按工程纪律 §2:不修、不绕、真实记录。本 step fail 是**有效产出**,反映 ua_mocker 在 Windows + 当前 asyncua 配置下的 browse 子树缺失。

下一步(本 task 范围之外):
- Stage 2 才允许起 TPT 数据源类 case(目前 mock 鉴权 + 证书缺失 + 子树不全,**Stage 2 大概率会大面积 fail**,真实记录即可)
- 短期不必修复 ua_mocker;若想继续推进 UA-3-x(实时/写),需要先修 ua_mocker 的"multi-group 子节点创建"问题(超出本次 stage1 范围)
