# all-case-static-validation.md — 419 Case 静态注册 + inventory 验证(2026-07-12 14:03)

## 1. 用户期望 HEAD 与实测

```text
expected HEAD: 35c2d0ad96264ab139dd70a76a105254385d8d19
actual HEAD:   35c2d0ad96264ab139dd70a76a105254385d8d19
```

✓ 完全匹配。

## 2. 脚本退出码与四步是否全部执行

```text
static exit code: 0
```

`scripts/run_all_case_static.ps1` **完整执行四步**(全部 PASS),把退出码写为 0,产物目录包含全部 9+ 个文件:

```
F:\github\supcon_tools\output\all_case_static_20260712_140154
```

```text
all-case-static-result.json  1 541
case-inventory.json       399 644
case-inventory.log            170
case-inventory.stderr.log       0
catalog.json              373 802
catalog.log                    115
catalog.stderr.log               0
compile.log                      0
compile.stderr.log               0
pytest.log                     101
pytest.stderr.log                0
transcript.log                 775
```

### 2.1 四步全部 PASS(`all-case-static-result.json`)

| step | status | exitCode |
|---|---|---|
| `python-compile` | **PASS** | 0 |
| `python-unit-tests` | **PASS** | 0 |
| `catalog-export` | **PASS** | 0 |
| `case-inventory` | **PASS** | 0 |

整体 `fatalError=null`、`status=PASS`、exit 0。

## 3. catalog 与 inventory 419 / 419

### 3.1 catalog

```text
catalog written: ... chapters=17 cases=419
```

按章节分组(总和 419):

| chapter | cases | chapter | cases |
|---|---|---|---|
| UA-1-1 | 12 | UA-2-4 | 27 |
| UA-1-2 | 8 | UA-2-5 | 27 |
| UA-1-3 | 8 | UA-3-1 | 20 |
| UA-1-4 | 6 | UA-3-2 | 21 |
| UA-1-5 | 9 | UA-3-3 | 22 |
| UA-1-6 | 13 | UA-3-4 | 8 |
| UA-2-1 | 112 | UA-3-5 | 12 |
| UA-2-2 | 67 | UA-3-6 | 15 |
| UA-2-3 | 32 | | |
| | | **合计** | **419** |

`Case ID` 唯一性:419 / 419 unique(无重复)。

### 3.2 case-inventory strict-structure

```text
case inventory written: ... documented=419 implemented=419 unimplemented=0 coverage=100.0%
```

| 指标 | 期望 | 实测 |
|---|---|---|
| documented | 419 | **419** ✓ |
| implemented | 419 | **419** ✓ |
| unimplemented | 0 | **0** ✓ |
| malformedRows | 0 | **0** ✓ |
| duplicateDocumentIds | 0 | **0** ✓ |
| orphanImplementations | 0 | **0** ✓ |
| coveragePercent | 100.0 | **100.0** ✓ |
| structureOk | true | **true** ✓ |

strict-structure 通过 → 没有输出 `STRUCTURE_ERROR:` 行。

## 4. 单元测试与异常堆栈

| 维度 | 实测 |
|---|---|
| 单元测试 | 46 passed(`pytest -q ua_test_harness/unit_tests` 输出)|
| `pytest.log` 完整内容 | `..............................................                           [100%]` / `46 passed in 4.24s` |
| 4 步异常堆栈 | **0**(全部 PASS)|

> 本轮静态无任何异常堆栈,无 import / collection / SyntaxError。

## 5. 总结

| 用户要求 | 实测 | 评 |
|---|---|---|
| 单元测试和 419 Case 静态验证是否继续通过 | **YES** | 4 步全 PASS / inventory 419:419 / structureOk=true |
| 整体退出码 | **0** | PASS |

报告完成时间:2026-07-12 14:03。
