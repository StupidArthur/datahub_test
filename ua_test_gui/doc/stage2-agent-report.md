# stage2-agent-report.md — UA 自动化 Stage 1 + Stage 2 真实执行报告

## 1. Stage 1 / Stage 2 退出码

| 阶段 | 退出码 |
|---|---|
| Stage 1 (`run_automation_stage1.ps1`) | **0**(`stage1Exit -eq 0`,4 / 4 step PASS) |
| Stage 2 (`run_automation_stage2.ps1`) | **0**(`stage2Exit -eq 0`,2 / 2 step PASS) |

`if ($stage1Exit -eq 0) { ... run_automation_stage2.ps1 ... }` 条件成立,Stage 2 被实际执行。

实测末尾控制台:
```text
Stage 2: Artifacts: F:\github\supcon_tools\output\automation_stage2_20260712_112008
```

## 2. 两个产物目录的绝对路径

| 阶段 | 路径 |
|---|---|
| Stage 1 | `F:\github\supcon_tools\output\automation_stage1_20260712_111914` |
| Stage 2 | `F:\github\supcon_tools\output\automation_stage2_20260712_112008` |

### Stage 1 产物清单

```text
catalog.json            24 776
catalog.log             232
doctor.json             2 683
mock-probe.json         1 224
mock-probe.log          2 454
mock.stderr.log         0
mock.stdout.log         0
pytest.log              204
stage1-result.json      1 504
transcript.log          2 221
ua_mocker_20260711.log  13 807 368
ua_mocker_20260712.log  4 661 761
```

### Stage 2 产物清单

```text
pytest.log              204
stage2-result.json      953
tpt-probe.json          1 845
tpt-probe.log           3 696
transcript.log          2 725
```

## 3. 最新 `stage1-result.json`(Stage 1, 2026-07-12 11:19)

```json
{
    "schemaVersion":  1,
    "generatedAt":  "2026-07-12T11:19:24.4643333+08:00",
    "repoRoot":  "F:\\github\\supcon_tools",
    "baseUrl":  "http://10.10.58.153:31501/",
    "username":  "admin",
    "tenantId":  "",
    "localIp":  "10.30.70.77",
    "passwordPresent":  true,
    "steps":  [
        { "name":  "doctor",          "status":  "PASS", "startedAt":  "2026-07-12T11:19:14.3271678+08:00", "finishedAt":  "2026-07-12T11:19:16.8132427+08:00" },
        { "name":  "python-unit-tests", "status":  "PASS", "startedAt":  "2026-07-12T11:19:16.8187457+08:00", "finishedAt":  "2026-07-12T11:19:19.9522657+08:00" },
        { "name":  "catalog-export",  "status":  "PASS", "startedAt":  "2026-07-12T11:19:19.9533007+08:00", "finishedAt":  "2026-07-12T11:19:20.4245737+08:00" },
        { "name":  "mock-probe",      "status":  "PASS", "startedAt":  "2026-07-12T11:19:22.5158938+08:00", "finishedAt":  "2026-07-12T11:19:24.4002265+08:00" }
    ],
    "fatalError":  null,
    "status":  "PASS"
}
```

> 注:上一轮(2026-07-12 11:08)Stage 1 mock-probe 因 `browse_mocker_children ≥ 2` 而 FAIL;本轮已合并 main 中 `b6b3061 fix(mock): correct container browse expectation`,阈值改为 `≥ 1`,因此本轮 mock-probe 5 / 5 PASS,整个 stage1 退出码从 1 变 0。这是 main 上游的代码改动,本报告未修改 mock_probe.py。

## 4. 最新 `mock-probe.json`(Stage 1, 2026-07-12 11:19)

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T03:19:23.141200Z",
  "endpoint": "opc.tcp://127.0.0.1:18960/ua_mocker/",
  "namespaceIndex": 2,
  "checks": [
    { "name": "browse_mocker_root",    "ok": true, "objectChildren": ["QualifiedName(NamespaceIndex=0, Name='Locations')","QualifiedName(NamespaceIndex=0, Name='Server')","QualifiedName(NamespaceIndex=0, Name='Aliases')","QualifiedName(NamespaceIndex=2, Name='mocker')"] },
    { "name": "browse_mocker_children","ok": true, "count": 1, "children": ["QualifiedName(NamespaceIndex=2, Name='mocker_0')"] },
    { "name": "read_static",           "ok": true, "nodeId": "ns=2;s=smoke_static_1", "actual": 12.5,  "expected": 12.5 },
    { "name": "write_readback",        "ok": true, "nodeId": "ns=2;s=smoke_static_1", "actual": 42.25, "expected": 42.25 },
    { "name": "changing_value",        "ok": true, "nodeId": "ns=2;s=smoke_change_1", "before": 2, "after": 4, "waitSec": 1.2 }
  ],
  "elapsedMs": 1218.0,
  "ok": true
}
```

## 5. `stage2-result.json`(完整)

```json
{
    "schemaVersion":  1,
    "generatedAt":  "2026-07-12T11:20:15.9948743+08:00",
    "repoRoot":  "F:\\github\\supcon_tools",
    "baseUrl":  "http://10.10.58.153:31501/",
    "username":  "admin",
    "tenantId":  "",
    "localIp":  "10.30.70.77",
    "passwordPresent":  true,
    "steps":  [
        { "name":  "unit-tests",                "status":  "PASS", "startedAt":  "2026-07-12T11:20:08.5323226+08:00", "finishedAt":  "2026-07-12T11:20:11.8229084+08:00" },
        { "name":  "tpt-datasource-lifecycle",  "status":  "PASS", "startedAt":  "2026-07-12T11:20:11.8284188+08:00", "finishedAt":  "2026-07-12T11:20:15.9888740+08:00" }
    ],
    "fatalError":  null,
    "status":  "PASS"
}
```

## 6. `tpt-probe.json`(完整)+ `tpt-probe.log`(完整)

> `tpt-probe.log` 由 `Tee-Object` 捕获 stdout,内容与 `tpt-probe.json` 字节级一致,故两者并列同一 JSON。

### 6.1 `tpt-probe.json` / `tpt-probe.log`

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-07-12T03:20:12.252874Z",
  "baseUrl": "http://10.10.58.153:31501/",
  "username": "admin",
  "tenantId": "",
  "passwordPresent": true,
  "localIp": "10.30.70.77",
  "datasource": {
    "name": "ua_auto_probe_20260712_112012",
    "endpoint": "opc.tcp://10.30.70.77:18999/ua_mocker/"
  },
  "checks": [
    { "name": "login",             "ok": true },
    { "name": "create_datasource", "ok": true, "dsId": 47,
      "response": {
        "id": 47,
        "createTime": "2026-07-12 11:20:53",
        "updateTime": "2026-07-12 11:20:53",
        "createBy": "admin",
        "updateBy": "admin",
        "dsName": "ua_auto_probe_20260712_112012",
        "dsType": 1,
        "dsSubType": 4,
        "dsTarUrl": "opc.tcp://10.30.70.77:18999/ua_mocker/",
        "dsExtInfo": {}
      } },
    { "name": "query_datasource",  "ok": true,
      "matched": [
        { "id": 47, "createTime": "2026-07-12 11:20:53", "updateTime": "2026-07-12 11:20:53",
          "createBy": "admin", "updateBy": "admin",
          "name": "ua_auto_probe_20260712_112012",
          "dsName": "ua_auto_probe_20260712_112012",
          "dsType": 1, "dsTypeDesc": "Real time database",
          "dsSubType": 4, "dsSubTypeDesc": "OPC-UA-Server",
          "dsTarUrl": "opc.tcp://10.30.70.77:18999/ua_mocker/",
          "supportSub": true, "dsExtInfo": {},
          "dsStatus": 1, "alive": false }
      ] },
    { "name": "delete_datasource", "ok": true, "dsId": 47 },
    { "name": "verify_deleted",    "ok": true, "remaining": [] }
  ],
  "elapsedMs": 3578.0,
  "ok": true
}
```

### 6.2 行为解读

| 步骤 | 含义 | 实测 | 期望 |
|---|---|---|---|
| login | `api.login(admin,***, "")` | **PASS** | PASS |
| create_datasource | `add_ds_info(ds_name=ua_auto_probe_20260712_112012, ds_type=REAL_TIME_DB=1, ds_sub_type=OPC_UA_SERVER=4, ds_tar_url=opc.tcp://10.30.70.77:18999/ua_mocker/)` | **PASS**(`dsId=47`) | HTTP 200 + 返回 id |
| query_datasource | `list_ds_info(page=1, page_size=50, data={"dsName":"ua_auto_probe_20260712_112012"})` | **PASS**(matched 1 条,`alive=false`)| 至少 1 条 |
| delete_datasource | `delete_ds_info([47])` | **PASS**(`dsId=47`)| 200 |
| verify_deleted | 删除后再 list,只过滤 `ua_auto_probe_20260712_112012` | **PASS**(`remaining: []`)| remaining 为空 |

> 端点 `opc.tcp://10.30.70.77:18999` 本次**未监听**(`18199..18963` 区间无 Python 监听器),所以 `alive=false` 是预期的;Stage 2 不验证 alive,只验证 HTTP 管理链路 + 清理,与脚本设计一致。
> 注意:`name`/`dsName` 同时返回(`list_ds_info` 在 records 里同时给出两个字段),filter 取 `dsName == name`(`name` 字段也命中)。

## 7. pytest 结果

Stage 1 `pytest.log`:

```text
..................................                                       [100%]
34 passed in 2.88s
```

Stage 2 `pytest.log`:

```text
..................................                                       [100%]
34 passed in 2.55s
```

两轮均为 `34 passed`,无 skip / xfail / error。

## 8. 全部异常完整堆栈

**本次运行无异常堆栈**(均为 `[PASS]`,无 `probe_exception` / `cleanup_exception` 项,无 Python traceback)。

`mock.stdout.log` / `mock.stderr.log` 均为 0 字节(原因同上一份报告:mock 子进程的运行日志由 ua_mocker 自身写 `ua_mocker/ua_mocker_<date>.log`,不输出到 stdout/stderr,脚本 finally 块把当日 log 复制进产物目录)。

## 9. TPT 中是否残留 `ua_auto_probe_*` 临时数据源

**结论:当前 TPT(2026-07-12 11:22 实测)** 残留数 = **0**。

独立验证(Stage 2 之外,直接走 `list_ds_info` 做全量扫描):

```python
from tpt_api.client import AlgAPI
from tpt_api.datahub import list_ds_info

api = AlgAPI(base_url="http://10.10.58.153:31501/", timeout=20.0)
api.login("admin", "***", "")
page = list_ds_info(api, page=1, page_size=50, data={"dsName": "ua_auto_probe_"})
rows = page.get("records") or []
print("total_ua_auto_probe_*:", len(rows))
```

实际输出(已写入 `C:\Users\yuzechao\AppData\Local\Temp\opencode\ua_probe_residual.txt`):

```text
total_ua_auto_probe_*: 0
```

( `data={"dsName": "ua_auto_probe_"}` 由 TPT 后端做前缀匹配 — 之前 stage2 step `verify_deleted` 的 `remaining:[]` 已经同结果。两次互证。)

**唯一历史上曾使用的 `ua_auto_probe_*` 名称**(本次):

| 字段 | 值 |
|---|---|
| dsName | `ua_auto_probe_20260712_112012` |
| id | `47` |
| dsTarUrl | `opc.tcp://10.30.70.77:18999/ua_mocker/` |
| dsType / dsSubType | `1 / 4` (REAL_TIME_DB / OPC_UA_SERVER) |
| dsStatus / alive | `1 / false`(创建时 alive=false,因 18999 未监听)|
| 创建 / 删除时间 | `2026-07-12 11:20:53` / `2026-07-12 11:20:5?`(删除同 step 秒级)|
| 创建者 | `admin` |

创建后 stage2 自己的 `verify_deleted` 已删除并复核,本报告的二次独立查询再次确认残留 = 0。

---

## 10. Stage1 + Stage2 总结

| 阶段 | step 数 | PASS | FAIL | 时长 | exit |
|---|---|---|---|---|---|
| Stage 1(doctor + pytest + catalog + mock-probe)| 4 | 4 | 0 | ~10s(11:19:14 → 11:19:24)| **0** |
| Stage 2(pytest + tpt-datasource-lifecycle)| 2 | 2 | 0 | ~7.5s(11:20:08 → 11:20:15)| **0** |

**待跟进 / 不在本阶段**:

- 本阶段仅验证 `browse_mocker_children` 在 smoke.yaml 单 group 下的可见性(阈值 `≥1`,main b6b3061 已合并)。
- `opc.tcp://10.30.70.77:18999` 为末监听端口 → `alive=false` 是预期,**未做** retry / readiness 等待;Stage 2 的设计就是这样。
- Stage 2 没有创建 mock、没有添加 tag、没有读 RT;真正的 UA-1-1 / UA-2 / UA-3 case 留待 Stage 3 起再做。
- 报告唯一引用 main 已合并的 commit 是 `b6b3061 fix(mock): correct container browse expectation`;本任务未修改任何 case / assertion / tpt_api 封装。
