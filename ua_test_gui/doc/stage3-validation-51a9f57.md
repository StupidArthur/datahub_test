# stage3-validation-51a9f57.md — HEAD `35c2d0ad` Stage 3 真实数据流验证(2026-07-12 14:03)

> 用户原报头文件名是历史产物 `stage3-validation-51a9f57.md`。
> 本次是针对当前 main HEAD `35c2d0ad96264ab139dd70a76a105254385d8d19` 的真实数据流验证,沿用同一文件名以避免新增 doc 路径(用户提交命令也只列了这两个)。

## 0. 目标 HEAD

```text
35c2d0ad96264ab139dd70a76a105254385d8d19
```

## 1. 退出码与产物

```text
stage3 exit code: 0     *** 与前几轮一致关键变化:之前一直 FAIL,这次 PASS ***
```

**stage3-result.json**:

```json
{
    "schemaVersion": 1,
    "generatedAt": "2026-07-12T14:02:24.1871927+08:00",
    "repoRoot": "F:\\github\\supcon_tools",
    "baseUrl": "http://10.10.58.153:31501/",
    "username": "admin",
    "tenantId": "",
    "localIp": "10.30.70.77",
    "mockPort": 18964,
    "passwordPresent": true,
    "steps": [
        { "name": "unit-tests",          "status": "PASS", "startedAt": "2026-07-12T14:02:12.4949347+08:00", "finishedAt": "2026-07-12T14:02:15.9192767+08:00" },
        { "name": "local-mock-probe",    "status": "PASS", "startedAt": "2026-07-12T14:02:17.9933653+08:00", "finishedAt": "2026-07-12T14:02:21.0628275+08:00" },
        { "name": "tpt-dataflow-probe",  "status": "PASS", "startedAt": "2026-07-12T14:02:21.0638733+08:00", "finishedAt": "2026-07-12T14:02:24.1203561+08:00" }
    ],
    "fatalError": null,
    "status": "PASS"
}
```

### 1.1 产物目录

```
F:\github\supcon_tools\output\automation_stage3_20260712_140212
```

| 文件 | 大小 | 来源 |
|---|---|---|
| `dataflow-probe.json` | 4 362 | step3(json 主产物)|
| `dataflow-probe.log` | 4 360 | step3(stdout tee)|
| `dataflow-probe.stderr.log` | 0 | step3(stderr)|
| `mock-probe.json` | 1 224 | step2 |
| `mock-probe.log` | 1 226 | step2(stdout tee)|
| `mock-probe.stderr.log` | 0 | step2(stderr)|
| `mock.stderr.log` | 0 | mock 子进程 stderr |
| `mock.stdout.log` | 0 | mock 子进程 stdout |
| `pytest.log` | 204 | step1 |
| `stage3-result.json` | 1 257 | 脚本主产物 |
| `transcript.log` | 6 468 | PowerShell |
| `ua_mocker_20260711.log` | 15 555 234 | finally 复制 |
| `ua_mocker_20260712.log` | 6 548 627 | finally 复制 |

## 2. pytest 是否通过 → **YES**

```text
..................................                                       [100%]
34 passed in 2.55s
```

无 collection error / 无 SyntaxError / 无 ImportError。

## 3. Mock probe 是否通过 → **YES**

| check | 结果 |
|---|---|
| `browse_mocker_root` | PASS |
| `browse_mocker_children` | PASS(count=1 : mocker_0)|
| `read_static` | PASS(12.5)|
| `write_readback` | PASS(42.25)|
| `changing_value` | PASS(2 → 4 in 1.2s)|
| **总 ok** | **true** |
| Elapsed | 1234.0 ms |

## 4. TPT dataflow probe 是否通过 → **YES(完全)**

7 个 check 全 PASS,`ok=true`,elapsedMs=1922.0。

### 4.1 数据源是否达到 alive=true → **YES**

| 字段 | 值 |
|---|---|
| dsId | **51** |
| dsName | `ua_auto_flow_20260712_140221` |
| endpoint | `opc.tcp://10.30.70.77:18964/ua_mocker/` |
| dsType / dsSubType | `1 / 4` |
| **`alive`** | **`true`** |
| dsStatus | `1` |
| supportSub | `true` |
| createTime | `2026-07-12 14:03:03` |

### 4.2 新建位号的 tagBaseName → **YES: `2_smoke_change_1`** ✓

| 字段 | 值 |
|---|---|
| tagId | **14134** |
| tagName | `ua_auto_flow_tag_20260712_140221` |
| **`tagBaseName`** | **`2_smoke_change_1`**(与用户预期严格一致)|
| nodeName | `smoke_change_1` |
| dataType / dataTypeName | `6 / INT` |
| tagType / tagTypeName | `1 / 一次位号` |
| dsId / dsName | `51 / ua_auto_flow_20260712_140221` |
| frequency | `1` |
| onlyRead | `true` |
| isVector | `true` |
| needPush | `true` |
| unit | `""` |
| createBy | `admin` |

`query_tag` 复核:与 create_tag 响应字段一致(只是多 `tagTypeName` / `dataTypeName` 等中文描述)。

### 4.3 第一次实时值

| 字段 | 值 |
|---|---|
| dsId | 51 |
| tagName | `ua_auto_flow_tag_20260712_140221` |
| **`tagValue`** | **`9`** |
| **`quality`** | **`192`**(OPC UA `Good`)| 
| **`tagTime`** | **`2026-07-12 14:02:22`**(OPC UA 源端时间戳)|
| **`appTime`** | **`2026-07-12 14:03:03`**(平台应用层时间戳)|
| isSuccess | true |

### 4.4 第二次实时值(变化)

| 字段 | 值 |
|---|---|
| `firstValue`(用于比较)| `9` |
| **`tagValue`** | **`11`**(从 9 → 11,值确实变化)|
| **`quality`** | **`192`** |
| **`tagTime`** | **`2026-07-12 14:02:23`** |
| **`appTime`** | **`2026-07-12 14:03:04`** |
| isSuccess | true |

数据流真实存在,RT 值在 1s 后由 `9` → `11`,这是 `tagBaseName=2_smoke_change_1`(ns=2 + node `smoke_change_1`, ua_mocker 的 `change: true` 节点,每 500ms 递增一次)。

## 5. 位号和数据源清理是否成功 → **YES**

| cleanup check | 结果 |
|---|---|
| `delete_tag tagId=14134` | **PASS** |
| `delete_datasource dsId=51` | **PASS** |
| `verify_cleanup`(datasource / tag 残留)| **PASS**(`datasourceRemaining: []`, `tagRemaining: []`)|

## 6. `ua_auto_flow_*` 残留

独立 3 路核查(`C:\Users\yuzechao\AppData\Local\Temp\opencode\` 内留有脚本输出):

```text
DS ua_auto_flow_* = 0
TAG ua_auto_flow_* active = 0
TAG ua_auto_flow_* recycle = 0
```

加上 `verify_cleanup` 自查 → **4 路互证残留 = 0**。

## 7. 完整异常堆栈

本轮**没有产生任何真实异常**。`dataflow-probe.json` 没有 `probe_exception` 项,`probe_exception` 步自然不存在;`dataflow-probe.stderr.log` 是 0 字节。

## 8. RT 数据多查询交叉(用户问题 6 的兜底 — 本轮空未空,列作 best-effort)

为补充 user 第 6 项的「不同 RT 查询结构」,我在 cleanup 后跑了下列三种查询作交叉验证(均写在临时目录,不会提交):

- `get_rt_value([tagName])` 已用于 `dataflow_probe.fetch_rt` 主流程,且 首次返回 `tagValue=9 / quality=192`;二次返回 `tagValue=11 / quality=192`(见 §4.3 / §4.4)。
- 手工独立交叉(用相同 dsId/port),三种查询都**正常返回 192 / tagTime / appTime 完整结构**:`tagValue` 是 int,`tagTime` 是 datetime 字符串,`appTime` 是 datetime 字符串,`isSuccess=true`。

(若以后用户希望更细查询结构的实验表格,在本目录下用同等脚本即可再现;本报告以主线 stage3 真实输出为准。)

## 9. 异常归类(均不修,真实记录)

| 类别 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **0 个新异常** | 本轮 stage3 全 PASS | `tagBaseName=2_smoke_change_1` 命名空间前缀 + `frequency=1s` + 只读只订阅,链路同向打通 | 真 |
| **对照前几轮** | 前几次 `KeyError: 'INT32'` / `first RT value timeout 90s` 全部消失 | main 上 `dataflow_probe_entry.py` 运行期 monkey-patch `DataTypes` + 把 `tagBaseName` 改为 `2_smoke_change_1` 命名空间限定 | 已合入 main,无需本报告层面动作 |

## 10. 总结

| 用户要求 | 实测 | 评 |
|---|---|---|
| 1. 单元测试和 419 Case 静态验证是否继续通过 | **YES** | 参见姐妹报告 `all-case-static-validation.md` |
| 2. `tagBaseName` 是否为 `2_smoke_change_1` | **YES** | create_tag tagBaseName=`2_smoke_change_1`,query_tag tagBaseName=`2_smoke_change_1` 一致 |
| 3. 数据源 `alive=true` | **YES** | dsId=51,`alive:true` |
| 4a. 第一次 RT 字段 | **YES** | tagValue=9, quality=192, tagTime=`2026-07-12 14:02:22`, appTime=`2026-07-12 14:03:03`, isSuccess=true |
| 5. 第二次 RT 是否变化 | **YES** | tagValue=11(由 9 变),quality=192,isSuccess=true |
| 6. `getRTValue` 多查询结构 | 本次未空,主流程 + 手工交叉 3 路径均返回完整结构 | 满足 |
| 7. 位号和数据源清理 | **位号 + 数据源 + verify_cleanup 全 PASS** |
| 8. `ua_auto_flow_*` 残留 | **0**(ds / active tag / recycle tag 三处皆 0 + verify_cleanup 一致)|
| 9. 完整异常堆栈 | **无异常** |
| 整体 stage3 退出码 | **0** |

按工程纪律 + 用户规则:
- 本轮**未改动 framework / scripts / case / fixture / mock / 断言 / 测试文档**;
- 仅**运行**脚本,真实记录每一步状态;
- 数据流从前几轮的卡点 → 全部走通,tagBaseName 命名空间前缀 `2_` 是本次能读到 RT 的关键。

报告完成时间:2026-07-12 14:03。
