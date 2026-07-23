# case-inventory-agent-report.md — Stage 3 + Case inventory 重跑(2026-07-12 12:22)

## 1. Stage 3 退出码与步骤

| step | 状态 | 关键 |
|---|---|---|
| `unit-tests` | **FAIL** exit 2 | pytest collection error:`type_mapping.py:16 SyntaxError: unterminated string literal(检测到 line 16 起的 `"UINT`)`,test_type_mapping.py 一开始 import 就崩 |
| `local-mock-probe` | **未执行** | step 1 fail 抛 "exit code 2",Run-Step 接住 throw,后续 step 跳过 |
| `tpt-dataflow-probe` | **未执行** | 同上 |
| **整体 script exit** | **1** | `stage3-result.json.status = FAIL` / `fatalError = "exit code 2"` |

伪代码级结论:本轮 stage3 未启动 mock、未发任何 TPT HTTP 请求、无数据源 / 位号 / RT 值 / 残留变化。

### Stage 3 产物目录

```
F:\github\supcon_tools\output\automation_stage3_20260712_122156
```

```text
pytest.log                     2 922    (含完整 traceback)
stage3-result.json               742
transcript.log                 2 453
ua_mocker_20260711.log     14 477 970
ua_mocker_20260712.log      5 389 992
```

> step 1 失败后未生成 `mock-probe.*` / `dataflow-probe.*`,因为根本没启动 mock。

### Stage 3 完整异常堆栈

```text
==================================== ERRORS ====================================
______ ERROR collecting ua_test_harness/unit_tests/test_type_mapping.py _______
D:\Python311\Lib\site-packages\_pytest\python.py:507: in importtestmodule
    mod = import_path(
D:\Python311\Lib\site-packages\_pytest\pathlib.py:587: in import_path
    importlib.import_module(module_name)
D:\Python311\Lib\importlib\__init__.py:126: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
<frozen importlib._bootstrap>:1204: in _gcd_import
    ???
<frozen importlib._bootstrap>:1176: in _find_and_load
    ???
<frozen importlib._bootstrap>:1147: in _find_and_load_unlocked
    ???
<frozen importlib._bootstrap>:690: in _load_unlocked
    ???
D:\Python311\Lib\site-packages\_pytest\assertion\rewrite.py:197: in exec_module
    exec(co, module.__dict__)
ua_test_harness\unit_tests\test_type_mapping.py:5: in <module>
    from ua_test_harness.type_mapping import (
E     File "F:\github\supcon_tools\ua_test_harness\type_mapping.py", line 16
E       "UINT
E       ^
E   SyntaxError: unterminated string literal (detected at line 16)
=========================== short test summary info ============================
ERROR ua_test_harness/unit_tests/test_type_mapping.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!
1 error in 0.37s
```

类型:`SyntaxError`(framework 自身 typo bug — `ua_test_harness/type_mapping.py:16` 的字符串字面量被截断:`"UINT` 没有闭合)。

按用户纪律「不修 framework / tpt_api 封装」+「失败保留」→ 保留真实错误,未改 `type_mapping.py`。

### 2. 位号创建 / 两次实时值 / 质量码 / 清理结果

| 步骤 | 状态 |
|---|---|
| 创建数据源(datasource) | **未执行**(stage3 的 step 1 即终止)|
| 等待 `alive=true` | **未执行** |
| 创建位号(tag) | **未执行** |
| 查询位号 | **未执行** |
| 第一次实时值 / quality / timestamp | **未执行** |
| 第二次实时值(应与 first 不等) | **未执行** |
| delete_tags_physical | **未执行** |
| delete_ds_info | **未执行** |
| `verify_cleanup`(`ua_auto_flow_*` 残留 = 0)| **未执行**(但与上一次 stage3 跑成功的 `verify_cleanup` 同样结论 — 因为本次没有创建任何 ua_auto_flow_* 流量,显然残留 = 0)|

## 3. Case inventory 退出码与步骤

| step | 状态 | 关键 |
|---|---|---|
| `python-unit-tests` | **FAIL** exit 2 | 同个 `type_mapping.py:16` SyntaxError 让 pytest collection error 阻塞 |
| `case-inventory` | **未执行** | step 1 throw 后即跳过 |
| **整体 script exit** | **1** | `case-inventory-result.json.status = FAIL` |

### Case inventory 产物目录

```
F:\github\supcon_tools\output\case_inventory_20260712_122214
```

```text
pytest.log                     1 460
pytest.stderr.log                 0
case-inventory-result.json       602
transcript.log                   887
```

> `case-inventory.json` / `case-inventory.log` / `case-inventory.stderr.log` **未生成**,因为 step 1 pytest 失败触发 `Run-Captured` 抛错,后续 `case-inventory` 步未跑。

### 独立调用的 inventory 数据

为拿到真实 summary,我用同一份已发布的 `ua_test_harness.case_inventory` 模块,在临时目录独立跑了一次(`PYTHONPATH=F:\github\supcon_tools`),输出写到 `C:\Users\yuzechao\AppData\Local\Temp\opencode\case-inventory2.json`,**未改动 / 不创建任何 case / 不动 framework / 不动文档**。

---

## 4. inventory summary 完整内容(独立调用结果)

```json
{
  "schemaVersion": 1,
  "generatedAt": "<UTC ISO>",
  "repoRoot": "F:\\github\\supcon_tools",
  "summary": {
    "expectedTotal": 419,
    "documented": 405,
    "implemented": 22,
    "unimplemented": 383,
    "coveragePercent": 5.43,
    "duplicateDocumentIds": 0,
    "malformedRows": 14,
    "orphanImplementations": 0,
    "structureOk": false
  },
  "duplicates": [],
  "malformed": [/* 14 条,见 §6 */],
  "orphanImplementations": [],
  "cases": [/* 405 条,见 §5 */]
}
```

`case inventory written: ... documented=405 implemented=22 unimplemented=383 coverage=5.43%`

| 指标 | 期望(用户给定)| 实测 | 评 |
|---|---|---|---|
| `documented` | 419 | **405** | 差 14 |
| `malformedRows` | 0 | **14** | 13 条 7 列 + 1 条 5 列 |
| `duplicateDocumentIds` | 0 | **0** | ✓ |
| `orphanImplementations` | 0 | **0** | ✓ |
| `implemented` | ~22 | **22** | ✓ |
| `unimplemented` | 419 - 22 = 397 | **383** | 因为 documented 实际只 405,差 14 反映在 unimplemented 上 |
| `structureOk` | true | **false** | documented != expectedTotal |

## 5. 419 条按章节统计

`cases` 列表共 405 条(全部由 case_inventory 解析文档所得),按 chapter 分组:

| chapter | documented | unimplemented | implemented |
|---|---|---|---|
| UA-1-1 | 12 | 0 | **12** |
| UA-1-2 | 8 | 8 | 0 |
| UA-1-3 | 8 | 8 | 0 |
| UA-1-4 | 6 | 6 | 0 |
| UA-1-5 | 9 | 9 | 0 |
| UA-1-6 | 13 | 13 | 0 |
| UA-2-1 | 99 | 99 | **1**(`UA-2-1-001`)|
| UA-2-2 | 67 | 67 | **1**(`UA-2-2-001`)|
| UA-2-3 | 32 | 32 | 0 |
| UA-2-4 | 27 | 26 | **1**(`UA-2-4-001`)|
| UA-2-5 | 27 | 27 | 0 |
| UA-3-1 | 20 | 18 | **2**(`UA-3-1-001`,`UA-3-1-004`)|
| UA-3-2 | 21 | 19 | **2**(`UA-3-2-001`,`UA-3-2-012`)|
| UA-3-3 | 22 | 21 | **1**(`UA-3-3-001`)|
| UA-3-4 | 7 | 6 | **1**(`UA-3-4-001`)|
| UA-3-5 | 12 | 11 | **1**(`UA-3-5-001`)|
| UA-3-6 | 15 | 15 | 0 |
| **小计(<= 419 例)** | **405** | **383** | **22** |
| 缺口(expectedTotal 419 - documented 405) | **14** | | |

> **关于 14 缺口 + 14 malformed 的一一对应**:见 §6 列数异常详情。

## 6. duplicate / malformed / orphan 完整列表

### 6.1 duplicateDocumentIds

```text
(empty) -> duplicateDocumentIds = 0
```

无重复 ID。

### 6.2 orphanImplementations

```text
(empty) -> orphanImplementations = 0
```

无 orphan 实现。

### 6.3 malformedRows(14 条)

> 注：下表中 `ua_test_gui/doc/test_cases/` 路径已迁移至 `ua_test_harness/test_cases/`。

| path | line | caseId | columnCount |
|---|---|---|---|
| ua_test_gui/doc/test_cases/UA-2-1.md | 123 | UA-2-1-026 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 124 | UA-2-1-027 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 125 | UA-2-1-028 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 126 | UA-2-1-029 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 127 | UA-2-1-030 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 128 | UA-2-1-031 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 129 | UA-2-1-032 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 130 | UA-2-1-033 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 131 | UA-2-1-034 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 132 | UA-2-1-035 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 133 | UA-2-1-036 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 134 | UA-2-1-037 | **7** |
| ua_test_gui/doc/test_cases/UA-2-1.md | 135 | UA-2-1-038 | **7** |
| ua_test_gui/doc/test_cases/UA-3-4.md | 20 | UA-3-4-008 | **5** |

模式:
- UA-2-1.md 第 123-135 行 13 条:`UA-2-1-026 ~ UA-2-1-038` 都是 **7 列**(在 8 列主线之间漏掉 1 列,可能是删除了一列时漏改)
- UA-3-4.md 第 20 行 `UA-3-4-008` 只有 **5 列**(只比基线少 1 列)

`documented (405) + malformed (14) = 419 = expectedTotal`。换句话说,**14 个 malformed 行如果按 6 / 8 列格式规范补齐,就能刚好命中 419**。这正是用户期望 baseline 的精确来源。

按用户「不修改 Case / 文档」— 这 14 行**保持原样**,报告不做"补齐"建议。

### 6.4 实现案例 ID 列表(22 条)

| id | 文件 | 行号 | kind |
|---|---|---|---|
| UA-1-1-01 | ua_test_harness\tests\ua_1\test_datasource.py | 66 | (regression) |
| UA-1-1-02 | 同上 | 91 | (regression) |
| UA-1-1-03 | 同上 | 116 | (regression) |
| UA-1-1-04 | 同上 | 145 | (regression) |
| UA-1-1-05 | 同上 | 176 | (regression) |
| UA-1-1-06 | 同上 | 208 | (regression) |
| UA-1-1-07 | 同上 | 233 | (regression) |
| UA-1-1-08 | 同上 | 258 | (regression) |
| UA-1-1-09 | 同上 | 282 | (regression) |
| UA-1-1-10 | 同上 | 308 | (regression) |
| UA-1-1-11 | 同上 | 335 | (regression) |
| UA-1-1-12 | 同上 | 361 | (regression) |
| UA-2-1-001 | ua_test_harness\tests\ua_2\test_tags.py | 15 | regression |
| UA-2-2-001 | 同上 | 46 | regression |
| UA-2-4-001 | 同上 | 75 | (regression) |
| UA-3-1-001 | ua_test_harness\tests\ua_3\test_collection.py | 19 | (regression) |
| UA-3-1-004 | ua_test_harness\tests\ua_3\test_13_types.py | 25 | (exploratory) |
| UA-3-2-001 | ua_test_harness\tests\ua_3\test_collection.py | 54 | (regression) |
| UA-3-2-012 | ua_test_harness\tests\ua_3\test_collection.py | 91 | (regression) |
| UA-3-3-001 | ua_test_harness\tests\ua_3\test_collection.py | 128 | (regression) |
| UA-3-4-001 | ua_test_harness\tests\ua_3\test_collection.py | 169 | (regression) |
| UA-3-5-001 | ua_test_harness\tests\ua_3\test_collection.py | 201 | (regression) |

(`kind` 字段在 inventory JSON 里出现乱码 `kind=ع` 因 kind 字符串是中文 "回归",不是问题。)

> `UA-3-1-013types` 已消失(被 commit `9a17d40 fix(cases): align 13-type collection with documented id` 改成 `UA-3-1-004` 对齐文档)。

## 7. 单元测试结果(独立调用 `pytest`,只跳 type_mapping collection 错误)

```text
==================================== ERRORS ====================================
______ ERROR collecting ua_test_harness/unit_tests/test_type_mapping.py _______
ImportError while importing test module ...
ua_test_harness\unit_tests\test_type_mapping.py:5: in <module>
    from ua_test_harness.type_mapping import (
E   File "F:\github\supcon_tools\ua_test_harness\type_mapping.py", line 16
E     "UINT
E     ^
E   SyntaxError: unterminated string literal (detected at line 16)
=========================== short test summary info ============================
ERROR ua_test_harness/unit_tests/test_type_mapping.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!
1 error in 0.37s
```

exit code 2 / collected 0 / 0 passed / 0 skipped / 0 failed。
pytest 1 error during collection(`test_type_mapping.py` collection-only error)。

### 已知存在的 framework bug 列表(任一次 stage3 报告均列,本轮新增 `type_mapping.py` SyntaxError)

| 编号 | 模块 | bug | 状态 |
|---|---|---|---|
| 1 | `ua_test_harness/type_mapping.py:16` | `"UINT` 未闭合字符串字面量,语法错误 → pytest collection 失败,影响 stage3 / inventory 单测 step | **不修** |
| 2 | `ua_test_harness/dataflow_probe.py:127` | `DataTypes["INT32"]` KeyError(`tpt_api.types.DataTypes:120` 只有 `"INT"=6`,无 `"INT32"`)| **不修**(从前次报告延续)|
| 3 | ua_mocker 多 group 子节点创建 | smoke.yaml 中 `mocker_1` 未创建(详情见 stage1-agent-report)| 第三方,不修 |

## 8. 异常归类(均不修,真实记录)

| 类别 | 现象 | 根因 | 处理 |
|---|---|---|---|
| **framework typo bug** | `type_mapping.py:16 SyntaxError` | 文件被截断在第 16 行 `"UINT`(unicode 截断 / 复制粘贴事故);commit 57262a6 留下了 bad state | **不修**(用户禁)|
| **framework typo bug**(连续)| `dataflow_probe.py:127 DataTypes["INT32"]` | 平台枚举无 "INT32" key | **不修** |
| **ua_mocker**(第三方,延续)| browse_mocker_children 只见到 1 个 group | 第三方 bug | 不修 |
| **case_inventory 期望 vs 实际** | 419 期望 baseline 与 actual 405 / 14 malformed 一一对应;structural fail 因 `documented=405 != 419` | 文档 UA-2-1.md 行 123-135(13 条 7 列)+ UA-3-4.md 行 20(1 条 5 列)未补齐成 6/8 列规范 | 保留真实缺口,不动文档 |
| **inventory 脚本未产出** | case-inventory.json / .log / .stderr.log 未生成 | Run-Captured 在 step1(`python-unit-tests`)fail 抛错后未到 step2 | 已确认 |
| **stage3 脚本未跑 mock/dataflow** | mock-probe.json / dataflow-probe.json 未生成 | Run-Step 在 step1 fail 抛错后未到 step2/step3 | 已确认 |
| **数据残留** | `ua_auto_flow_*` / 任何 dataflow 状态变更 | 本轮未发起任何 dataflow 操作 | **真实** 残留 = 0 |

## 9. 总结

| Step | 结果 |
|---|---|
| stage3 `unit-tests` | **FAIL**(SyntaxError in type_mapping.py:16)|
| stage3 `local-mock-probe` | **未执行** |
| stage3 `tpt-dataflow-probe` | **未执行** |
| stage3 整体 | exit **1** |
| inventory `python-unit-tests` | **FAIL**(同上 collection error)|
| inventory `case-inventory` | **未执行** |
| inventory 整体 | exit **1** |
| **独立调 inventory 模块** | documented=405 / implemented=22 / unimplemented=383 / coverage=**5.43%** / malformed=14 / duplicate=0 / orphan=0 / structureOk=**false** |

按工程纪律 + 用户规则:
- 本轮**未触发任何 case / mock / framework / tpt_api / 文档 / fixture 的修改**;
- 仅**读取**了 docs 与现有代码实现,产出 inventory JSON(写到 `C:\Users\yuzechao\AppData\Local\Temp\opencode\`,不会提交);
- 报告真实记录 14 个 malformed 行(用户「不补齐」)。

报告完成时间:2026-07-12 12:25。
