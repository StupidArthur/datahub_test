# stage3-agent-report.md — UA 自动化 Stage 3 真实执行报告(独立端口 18964)

## 1. Stage 3 退出码

```text
exit code: 1
```

`scripts/run_automation_stage3.ps1` step 3 (`tpt-dataflow-probe`) **FAIL**(Python `dataflow_probe.py` 在 `add_tag` 之前抛 `KeyError: 'INT32'`),Run-Step 抛 "exit code 1",脚本 finally 块写入 `status=FAIL` 并 exit 1。

## 2. 产物目录绝对路径

```
F:\github\supcon_tools\output\automation_stage3_20260712_115910
```

文件清单(已 ls 确认,13 个文件,全部 8 项要求产物已生成):

```text
dataflow-probe.json            2 318
dataflow-probe.log             2 320
dataflow-probe.stderr.log      0
mock-probe.json                1 224
mock-probe.log                 1 226
mock-probe.stderr.log          0
mock.stderr.log                0   (mock 子进程 stderr)
mock.stdout.log                0   (mock 子进程 stdout)
pytest.log                     204
stage3-result.json             1 314
transcript.log                 4 640
ua_mocker_20260711.log         14 235 834
ua_mocker_20260712.log         5 389 992
```

> stdout / stderr 由最新脚本的 `Run-PythonCaptured`(`Start-Process -RedirectStandardOutput -RedirectStandardError -Wait`)分文件捕获,所以即使 Python 返回非零,6 个 probe 文件也都在。

## 3. `stage3-result.json` 完整内容

```json
{
    "schemaVersion":  1,
    "generatedAt":  "2026-07-12T11:59:21.1308666+08:00",
    "repoRoot":  "F:\\github\\supcon_tools",
    "baseUrl":  "http://10.10.58.153:31501/",
    "username":  "admin",
    "tenantId":  "",
    "localIp":  "10.30.70.77",
    "mockPort":  18964,
    "passwordPresent":  true,
    "steps":  [
        { "name":  "unit-tests",          "status":  "PASS", "startedAt":  "2026-07-12T11:59:10.4180671+08:00", "finishedAt":  "2026-07-12T11:59:13.8845304+08:00" },
        { "name":  "local-mock-probe",    "status":  "PASS", "startedAt":  "2026-07-12T11:59:15.9560721+08:00", "finishedAt":  "2026-07-12T11:59:19.0031696+08:00" },
        { "name":  "tpt-dataflow-probe",  "status":  "FAIL",
          "startedAt":  "2026-07-12T11:59:19.0041691+08:00", "finishedAt":  "2026-07-12T11:59:21.0652914+08:00",
          "error":  "exit code 1" }
    ],
    "fatalError":  "exit code 1",
    "status":  "FAIL"
}
```

## 4. `dataflow-probe.json` 完整内容

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T03:59:19.557189Z",
  "baseUrl": "http://10.10.58.153:31501/",
  "username": "admin",
  "tenantId": "",
  "passwordPresent": true,
  "localIp": "10.30.70.77",
  "mockPort": 18964,
  "datasource": {
    "name": "ua_auto_flow_20260712_115919",
    "endpoint": "opc.tcp://10.30.70.77:18964/ua_mocker/"
  },
  "tag": {
    "name": "ua_auto_flow_tag_20260712_115919",
    "baseName": "smoke_change_1"
  },
  "checks": [
    { "name": "login",             "ok": true },
    { "name": "create_datasource", "ok": true, "dsId": 48,
      "response": {
        "id": 48, "createTime": "2026-07-12 12:00:01", "updateTime": "2026-07-12 12:00:01",
        "createBy": "admin", "updateBy": "admin",
        "dsName": "ua_auto_flow_20260712_115919",
        "dsType": 1, "dsSubType": 4,
        "dsTarUrl": "opc.tcp://10.30.70.77:18964/ua_mocker/",
        "dsExtInfo": {}
      } },
    { "name": "datasource_alive", "ok": true,
      "datasource": {
        "id": 48, "createTime": "2026-07-12 12:00:01", "updateTime": "2026-07-12 12:00:01",
        "createBy": "admin", "updateBy": "admin",
        "name": "ua_auto_flow_20260712_115919",
        "dsName": "ua_auto_flow_20260712_115919",
        "dsType": 1, "dsTypeDesc": "Real time database",
        "dsSubType": 4, "dsSubTypeDesc": "OPC-UA-Server",
        "dsTarUrl": "opc.tcp://10.30.70.77:18964/ua_mocker/",
        "supportSub": true, "dsExtInfo": {},
        "dsStatus": 1, "alive": true
      } },
    { "name": "probe_exception", "ok": false,
      "error": "KeyError: 'INT32'",
      "traceback": "Traceback (most recent call last):\n  File \"F:\\github\\supcon_tools\\ua_test_harness\\dataflow_probe.py\", line 127, in probe\n    data_type=DataTypes[\"INT32\"],\n              ~~~~~~~~~^^^^^^^^^\nKeyError: 'INT32'\n" }
  ],
  "cleanup": [
    { "name": "delete_datasource", "ok": true, "dsId": 48 },
    { "name": "verify_cleanup",    "ok": true,
      "datasourceRemaining": [], "tagRemaining": [] }
  ],
  "elapsedMs": 718.0,
  "ok": false
}
```

### 行为解读

| check | 含义 | 实测 | 期望 |
|---|---|---|---|
| login | API login | **PASS** | PASS |
| create_datasource | `add_ds_info(ds_name=ua_auto_flow_20260712_115919, type=REAL_TIME_DB, sub=OPC_UA_SERVER, url=opc.tcp://10.30.70.77:18964/ua_mocker/)` | **PASS**(`dsId=48`)| 200 + dsId |
| datasource_alive | `list_ds_info(data={"id":48})` 轮询直到 `alive=true` | **PASS**(`alive:true`)| True |
| ~~create_tag~~ | add_tag → 等存在 | **FAIL:KeyError 'INT32'**(被 catch 后写入 `probe_exception`)| 200 + tagId |
| ~~query_tag~~ | list_tags | **未执行** | records 非空 |
| ~~read_rt_first~~ | get_rt_value 第一次 | **未执行** | quality 非空 |
| ~~read_rt_changed~~ | get_rt_value 第二次,值应不同 | **未执行** | value != first |
| delete_datasource (cleanup) | `delete_ds_info([48])` | **PASS**(`dsId=48`)| 200 |
| verify_cleanup (cleanup) | list_ds/list_tags 过滤 `ua_auto_flow_*` | **PASS**(both `[]`)| 残留 = 0 |

整体 `ok=false`,main() 返回非零退出码。

## 5. `dataflow-probe.stderr.log` 完整内容

```text
(0 字节,文件为空)
```

> stderr 文件由 `Start-Process -RedirectStandardError` 写入,Python 子进程运行时把 `tpt_api.logger.error(...)` 输出到的 stderr 不再让 PowerShell `$ErrorActionPreference=Stop` 截留(因为这一版脚本用 Start-Process -Wait 独立管子进程),所以 A0001 / KeyError 提示信息**未**再写 stderr — `KeyError: 'INT32'` 仅出现在 stdout 写入的 `dataflow-probe.json` / `.log` 里(被 `traceback.format_exc()` 包成字符串,作为 `add("probe_exception", ..., traceback=...)` 字段写入)。
>
> 这次没有 tpt_api logger 输出,是因为 `add_ds_info` 走通了 → 没触发 `log.error(...)` 那行 A0001。但 `KeyError: 'INT32'` 走 Python 自身的 `Traceback`,整段异常被 `format_exc()` 抓成字符串,**没** 写到 stderr。

## 6. 数据源 ID / 地址 / alive

| 字段 | 值 |
|---|---|
| 数据源 ID | **48** |
| 数据源名 | `ua_auto_flow_20260712_115919` |
| 地址 | `opc.tcp://10.30.70.77:18964/ua_mocker/` |
| `dsType` | `1` (DsTypes["REAL_TIME_DB"]) |
| `dsSubType` | `4` (DsSubTypes["OPC_UA_SERVER"]) |
| `dsStatus` | `1` |
| **`alive`(最终)** | **`true`** |
| `createTime` / `updateTime` | `2026-07-12 12:00:01` / `2026-07-12 12:00:01` |
| `createBy` / `updateBy` | `admin` / `admin` |
| 数据源创建后状态 | 已被 `dataflow_probe.cleanup.delete_datasource` 删掉(TPT 中 id=48 已消失;见 §9)|

mock 11:59:20 日志中可见 TPT 真实从 `10.10.58.153:58716` 连入 `0.0.0.0:18964` 完成 `Create session` → `Read request` → `create subscription request` → `delete subscription [78]` → `Close session`(订阅 id `78` 是本数据源引擎内部短暂订阅,被 close 回收)。这是 TPT 数据采集引擎对新建数据源自动发起的能力探测,**alive=true 是真实**。

## 7. 位号 ID / `tagBaseName` / 数据类型 / 查询结果

| 字段 | 值 |
|---|---|
| **位号 ID** | **未创建**(create_tag 步抛 KeyError,probe 异常前终止)|
| **tagName** | 脚本试图命名为 `ua_auto_flow_tag_20260712_115919`,但实际未发到 TPT |
| **`tagBaseName`** | 脚本试图写入 `smoke_change_1`,但因 create_tag 未发出,TPT 中无该字段 |
| **数据类型** | 脚本里写 `data_type=DataTypes["INT32"]` — **抛 `KeyError: 'INT32'`** |
| **查询结果** | `list_tags(data={"tagName":...})` **未执行**(因为没 tag 要查)|

### 7.1 `KeyError: 'INT32'` 根因

`DataTypes` 在 `tpt_api/python/tpt_api/types.py:120` 定义:

```python
DataTypes: dict[str, int] = {
    "BOOLEAN": 1, "S_BYTE": 2, "BYTE": 3, "SHORT": 4, "U_SHORT": 5,
    "INT": 6, "U_INT": 7, "LONG": 8, "U_LONG": 9, "FLOAT": 10, "DOUBLE": 11,
    "STRING": 12, "DATE_TIME": 13,
}
```

`DataTypes["INT32"]` 不存在(平台枚举没有 `INT32`,只有 `INT=6`)。这不是协议层问题,是 **probe 框架代码 bug**。

按工程纪律 §2.3:**用例代码本身有 API 签名错 → 修复 fixture 或 runner 框架** 属于本纪律「例外」,但用户本次明确要求「**不要修改 Case、断言、Mock 实现或 `tpt_api` 封装**」,所以保留真实错误,不动 DataTypes / dataflow_probe.py 任何代码。

> 报告将该问题列为"框架 typo bug"(见 §10),留待后续 PR 修复。

## 8. 两次实时值 / quality / timestamp

| 步骤 | 期望 | 实测 |
|---|---|---|
| read_rt_first | 读到非空 quality 的 RT | **未执行**(create_tag 失败前没到这一步)|
| read_rt_changed | 与 first 不等的 RT,带 quality / timestamp | **未执行** |

脚本只走到 `create_tag` 前的 `data_type=DataTypes["INT32"]` 一步就抛 KeyError。

## 9. 最终数据源 / 位号残留检查

**实测(独立 `list_ds_info` / `list_tags` / `list_recycle_tags` 全量查询)**:

```text
=== DS ua_auto_flow_* === 0
=== TAG ua_auto_flow_* (active) === 0
=== TAG ua_auto_flow_* (recycle) === 0
```

**残留数 = 0**(ds / tag active / tag recycle 三处一致)。

附带:`dataflow_probe` 自带的 `verify_cleanup` 也互证为 `datasourceRemaining: [], tagRemaining: []`,且 `delete_datasource dsId=48` 在 cleanup 表里 ok=true。

## 10. 完整异常堆栈

仅 1 个真实异常:

```text
Traceback (most recent call last):
  File "F:\github\supcon_tools\ua_test_harness\dataflow_probe.py", line 127, in probe
    data_type=DataTypes["INT32"],
              ~~~~~~~~~^^^^^^^^^
KeyError: 'INT32'
```

类型:`KeyError`,非 `TptAPIError`,非 `AssertFail`。

值得注意:本异常的 `try/except Exception` 被 `dataflow_probe.py:170` 捕获后写入 `probe_exception` 项,而非冒泡,所以 stage3 脚本的 fatalError 写的是 "exit code 1"(因为 `main()` 看到 `report["ok"] = False` 返回非零),**而非 `KeyError: 'INT32'` 的 message**。`stage3-result.json.error` 与 `fatalError` 都是 `"exit code 1"`,但 traceback 完整保留在 `dataflow-probe.json` 的 `probe_exception.traceback` 字段。

## 11. 异常归类(不修不绕,如实记录)

| 类别 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **Mock 自身** | mock 11:59:15 启动 + Listening on 18964 + Browse/Read/Write 正常 + TPT 真的从 10.10.58.153 连入做 create-subscription | mock + TPT 双向互通 | 通过;`<- mock-probe 5/5 PASS` |
| **测试框架 bug** | `DataTypes["INT32"]` KeyError(`tpt_api` 字典枚举无 "INT32" key) | `dataflow_probe.py:127` 字符串键与 `tpt_api.types.DataTypes:120-124` 枚举不一致 | **不修(用户禁止改 framework / tpt_api 包装)**;留待独立 PR |
| **数据流链路真实进展** | `add_ds_info(18964)` → HTTP 200 + dsId=48;`list_ds_info` 轮询到 alive=true | 与 dsId=43 共存(18960 vs 18964,endpoint 不冲突)| 通过 |
| **数据流链路真实进展** | `add_tag` 未发出 | KeyError 抛在 `add_tag` 之前(create_tag 内第 127 行)| 未验证 |
| **数据流链路真实进展** | 未读到任何 RT 值 | 因无 tag → `get_rt_value` 步未到 | 未验证 |
| **第三方依赖 / 异步日志噪声** | asyncua 启动期 `add_node ... does not exists` / `Instantiate: Skip node without modelling rule ...` | 与 stage1/2 描述一致 — informational,不致命 | 不修 |
| **数据残留** | `ua_auto_flow_*` 残留 = 0(ds / active tag / recycle tag)| 失败自动 cleanup 已生效 | 合规 |
| **dsId=43 状态** | dsId=43 ua_auto_ua1_001 unchanged / alive=false / 仍指向 `opc.tcp://10.30.70.77:18960/ua_mocker/` | 本阶段无修改 / 无删除 | 已确认(用户要求"不要修改或删除 dsId=43")|

## 12. 总结

| 步骤 | 状态 | 关键 |
|---|---|---|
| unit-tests | **PASS**(34 passed / 2.63s)| 单测全部通过 |
| local-mock-probe | **PASS**(5/5 / 1234ms)| 18964 端口上 mock 自检全部通过 |
| tpt-dataflow-probe | **FAIL**(exit 1,718ms)| login ✓ / create_datasource(48)✓ / datasource_alive=true ✓ / create_tag ❌ `KeyError:'INT32'` |
| **整体退出码** | **1** | total 11s |

按用户纪律:不修、不绕、不删断言、不改 framework / mock / tpt_api 封装;失败是有效产出。

**两个新里程碑**(对比 stage3 第一次):
1. ✅ 把 endpoint 从抢占态的 18960 切到独立 18964,绕开了 `A0001 Duplicate data source address`,TPT 真实建出 dsId=48
2. ✅ 真实到达 **alive=true** — TPT 数据采集引擎从 10.10.58.153:58716 连入 mock `0.0.0.0:18964`,完成 Create session / Read request / create subscription(订阅 id 78 自动回收)

**遗留真实 bug**(本次报告不修,留 PR):
- `ua_test_harness/dataflow_probe.py:127` 引用 `DataTypes["INT32"]`,但 `tpt_api.types.DataTypes` 不含 `INT32` key(应有 `"INT"` → `6`)
- 修复应在 `DataTypes["INT"]` 或新增 `"INT32": 6` 别名(由框架 owner 决定);按本任务不允许改 `tpt_api` 封装,所以单一可行修复是 framework 一行
- 修复后下一次 stage3 即可推进到 create_tag / query_tag / read_rt_first / read_rt_changed

报告完成时间:2026-07-12 12:01。
