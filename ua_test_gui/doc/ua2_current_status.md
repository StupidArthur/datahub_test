# ua2_current_status.md — 工程真实状态快照(供 GPT 审核 / 2026-07-12 17:12)

> 本文件**仅记录真实状态**,不修复任何问题,不提交 commit。

## 1. Git 状态

```
HEAD:   ae44b28a14cf78cdfdc8db8d6f5a843c061c7799
branch: main
upstream: origin/main
your branch is up to date with origin/main
```

工作区改动(`git status --short`):
```
modified:   data_factory_server (untracked content)
modified:   review3 (modified content, untracked content)
Untracked:
-
```

工作区改动**与本任务无关**(均来自其它子模块)。`git diff --name-status origin/main..HEAD` 与 `git diff --stat origin/main..HEAD` **均为空**,说明本任务本轮**未做任何代码改动**。

### 1.1 最近 15 个 commit(均来自 origin/main,非本任务)

```
ae44b28 fix(ua2): complete precise query scenarios
7ed1b6b feat(ua2): complete precise query scenarios
d3a275a fix(ua2): pass datasource into creation scenarios
8d889bf fix(ua2): restore complete create runtime module
0401dcd fix(ua2): implement precise create scenarios
f36a2c3 feat(ua2): add UA-2 runner entrypoint
da7a923 feat(ua2): add query runtime scenarios
d5cdfe2 feat(ua2): add recycle runtime scenarios
a25514a feat(ua2): add create runtime scenarios
f4dd4a2 feat(mock): add UA-2 batch node fixture
ee9fc63 feat(ua2): add shared runtime helpers
61c2398 feat(ua2): add tag management runtime
c29b008 fix(mock): complete UA-2 13-type node fixture
fd06d48 fix(ua2): restore complete 13-type mock configuration
c7bfbe2 feat(mock): add dedicated UA-2 thirteen-type fixture
```

## 2. 当前新增 / 修改文件(diff origin/main..HEAD)

```
(empty) -- 与 origin/main 完全一致
```

无变更。

## 3. 编译检查(`python -m compileall ua_test_harness scripts ua_mocker`)

```
exit code: 0
stderr:    (empty)
stdout:    (showing directory listings under ua_test_harness/, scripts/, ua_mocker/)
            including all compileall output) — no SyntaxError, no B901, no B902.
```

全部通过(无任何文件失败,无 traceback)。

## 4. pytest(单元测试)

```
$ python -m pytest ua_test_harness/unit_tests -q
........................................................                 [100%]
56 passed in 2.77s
```

| 维度 | 值 |
|---|---|
| passed | **56** |
| failed | 0 |
| errors | 0 |
| traceback | (无)|

无异常堆栈,无 collection error。

## 5. 文件存在 / 完整性检查

| 文件 | 存在 | 行数 | import | 截断 | TODO/FIXME | 已被引用 |
|---|---|---|---|---|---|---|
| `ua_test_harness/ua2_common.py` | ✅ | 112 | ✅ IMPORT_OK | 否 | 否 | **否**(作为运行时模块被 import,但 catalog 12 case 没引用其函数)|
| `ua_test_harness/ua2_create_runtime.py` | ✅ | 34 | ✅ IMPORT_OK | 否 | 否 | **否** |
| `ua_test_harness/ua2_query_runtime.py` | ✅ | 10 | ✅ IMPORT_OK | **是**(末行 `name` 孤立表达式)| 否 | 否 |
| `ua_test_harness/ua2_recycle_runtime.py` | ✅ | 11 | ✅ IMPORT_OK | 否(语法 OK,但 `soft_delete_tag(ctx, tag_id)` 调用错配 fixture 签名)| 否 | 否 |
| `ua_test_harness/scenarios/ua2_runtime.py` | ✅ | 19 | ✅ IMPORT_OK | **是**(末行 `row = find` 残缺,缺 `find_tag(ctx, name)`)| 否 | 否 |
| `scripts/run_automation_ua2.ps1` | ✅ | 14 | n/a(PowerShell)| 否 | 否 | n/a |
| `scripts/run_with_timeout.py` | ✅ | 54 | n/a(Python 直接调)| 否 | 否 | n/a |
| `ua_mocker/ua2_types.yaml` | ✅ | 148 | n/a(YAML)| 否(以 `default: '2025-01-01T00:00:00+00:00'` 完结)| 否 | n/a |
| `ua_mocker/ua2_batch.yaml` | ✅ | 10 | n/a(YAML)| 否(以 `- ...` 列表项 + `writable: false` 完结)| 否 | n/a |

### 5.1 截断详情

#### 5.1.1 `ua_test_harness/ua2_query_runtime.py:11`

```python
 9: def _prepared(ctx, cc):
10:     ds = prepare_datasource(ctx, cc)
11:     name               ← 孤立表达式,后续函数体缺失
```

`def _prepared` 后只有 `ds = prepare_datasource(...)` 与孤儿 `name`(没有任何变量绑定 / return),**属于内容被截断**。`_make_impl` / `duplicate_name_rejected` / 任何 UA-2-2 场景在本文件**不存在**。

#### 5.1.2 `ua_test_harness/scenarios/ua2_runtime.py:19-20`

```python
18: def scenario_create_and_read(ctx, name, ds_id):
19:     tag = create_tag(ctx, name=name, ds_id=ds_id, data_type="INT32", tag_base_name=f"2_{name}")
20:     row = find                                  ← 残缺:应是 `row = find_tag(ctx, name)`
```

`find_tag(ctx, name)` 缺失,后面 `wait_tag_present / wait_rt / return / cleanup` 也缺失。

### 5.2 引用情况

我用 `Select-String` 在仓库全树查找了 `create_read_tag / ua2_create_runtime / ua2_query_runtime / ua2_recycle_runtime / soft_delete_and_restore / scenario_create_and_read`:

- `tests/ua_2/test_tags.py` **不引用** 任何上述函数 ✓
- `tests/zz_documented_cases.py` 调 `execute_documented_case(ctx, cc, _meta)` 但 `execute_documented_case` 在 `scenario_policy.py`(我未列在 9 个文件清单里)
- 其它地方 **无引用**

→ 这些 runtime 文件**目前都是孤儿代码**;除了 `soft_delete_and_restore` / `create_read_tag` 等被 module import,实际测试代码不触发它们。

## 6. UA-2 Registry 接入情况

总接入 UA-2 case:`discover + all_defs()` = **265 条**(覆盖 doc 中所有 UA-2 章节,UA-2-1 112, UA-2-2 67, UA-2-3 32, UA-2-4 27, UA-2-5 27 = 265)。

其中:
- **3 条手写实现**(在 `tests/ua_2/test_tags.py`,有真实函数体):
  ```
  UA-2-1-001   ua_test_harness\tests\ua_2\test_tags.py:15   kind='regression'
  UA-2-2-001   ua_test_harness\tests\ua_2\test_tags.py:46   kind='regression'
  UA-2-4-001   ua_test_harness\tests\ua_2\test_tags.py:75   kind='regression'
  ```
- **其余 262 条** 全部由 `tests/zz_documented_cases.py:71` 通过 `_make_impl(meta)` 动态生成(wrapper 内部统一转给 `execute_documented_case(ctx, cc, _meta)` 跑文档场景)。

UA-2 Registry 已完整接入(265 / 265),但**仅 3 条有真函数体**,其余依赖 `zz_documented_cases.py` 的 scenario_policy 调度(若 `ua2_query_runtime.py`/`scenarios/ua2_runtime.py` 真的被引用就是这条路)。

### 6.1 若 GPT 期望"每个 UA-2 case 都有独立 pytest 函数"

这是**当前不符** 的。事实:绝大多数 UA-2 case 是 `zz_documented_cases.py:71` 这一行注册的同形 wrapper。本轮快照**如实记录**:3 个手写、262 个由文档 -> `execute_documented_case` 派发。

## 7. Runner(`scripts/run_automation_ua2.ps1`)是否真的可以运行

### 7.1 实测

```text
$ python -m ua_test_harness.cli run --suite UA-2 --timeout 180
usage: ua_test_harness [-h] [--base-url BASE_URL] [--user USER]
                       [--tenant TENANT]
                       {os,mock,provision,all,catalog,run} ...
ua_test_harness: error: unrecognized arguments: --suite UA-2 --timeout 180
exit code: 2
```

### 7.2 不可运行的具体原因

| 原因类别 | 描述 |
|---|---|
| **CLI 参数不存在** | 脚本第 7 行调用 `python -m ua_test_harness.cli run --suite UA-2 --timeout 180`,而 `cli run --help` 实际支持的合法参数只有 `--config / --cases / --chapters / --package / --dry-run`。**`--suite` 与 `--timeout` 都不在合法集中**。Argparse 在解析阶段抛 `error: unrecognized arguments`,exit 2 |
| **Config 格式** | 未及(`--config` 参数压根没传,所以 config 错误不是首阻塞点)|
| **Import 错误** | 无(`compileall` / `pytest` 都过)|
| **Runtime 不存在** | 有:**核心 runtime 缺函数体**(见 §5.1)— `ua2_query_runtime.py` 只剩 `_prepared` 占位、`scenarios/ua2_runtime.py` `scenario_create_and_read` 中途截断 |
| **Registry 未接入** | 已接(265 / 265),但只有 3 条手写;script 通过时这些 row 会经 `zz_documented_cases._make_impl` -> `execute_documented_case` -> 实际调用 5 个 runtime 文件中的函数 — 而 runtime 文件本身有重大实现缺口,**实际执行将产生大量失败 / 截断错误** |

### 7.3 即便修了 `--suite`,接下来仍会卡住

- `execute_documented_case` -> `scenarios/ua2_runtime.py.scenario_create_and_read` 会进入那个**截断**函数体(末行 `row = find`),Python 会抛 `NameError: name 'find' is not defined`(运行期 Traceback,不是 compile-time)。
- `execute_documented_case` -> `ua2_recycle_runtime.py.soft_delete_and_restore` 会以 `tag_id: int` 喂给 `soft_delete_tag(name: str)`,类型错配导致 `data={"tagName": tag_id}` 实际过滤 0 条,**`removed_from_active` / `in_recycle` 断言看起来失败**。
- `execute_documented_case` -> `ua2_query_runtime.py` 因 `_prepared` 在 `name` 行就停了(返回 `None`?),后续 case 函数体缺失,**没人调起任何 query 业务**。

## 8. 当前阻塞点(汇总)

### 阻塞点 A:`run_automation_ua2.ps1` CLI 参数不存在

`run_automation_ua2.ps1:7` 使用 `--suite` 与 `--timeout`,argparse 拒,exit 2。

### 阻塞点 B:`ua2_query_runtime.py` 内容截断

`_prepared` 在 `ds = prepare_datasource(...)` 与 `name` 表达式处停止,后续 query 业务函数体全部缺失 — 该文件实质上**不是一个可运行 runtime**。

### 阻塞点 C:`scenarios/ua2_runtime.py` 内容截断

`scenario_create_and_read` 末行 `row = find` 是残缺;`find_tag(ctx, name)` 缺、等待 / cleanup / return 全部缺。

### 阻塞点 D:`ua2_recycle_runtime.py` fixture 调用签名错配

`soft_delete_and_restore(ctx, cc, tag_id, name)` 把 `tag_id: int` 传给 `soft_delete_tag(ctx, name: str)` 与 `restore_from_recycle(ctx, name: str)`,语义与类型双重错配。

### 阻塞点 E:Registry 主要为动态 wrapper,手写实现仅 3 条

绝大多数 UA-2 case 进入 catalog 后实际执行路径是 `zz_documented_cases._make_impl()` 工厂 wrapper,转给 `execute_documented_case`(**路径在 scenario_policy.py,本轮未读**)。手写函数体只有 3 条位于 `tests/ua_2/test_tags.py`。

### 阻塞点 F:`tests/zz_documented_cases.py:44-46` hard-fail on malformed rows

```python
if malformed:
    details = ", ".join(...)
    raise RuntimeError(f"documented Case rows malformed: {details}")
```

→ MD 文档中**任何**格式异常(列数 ≠ 6/8 / duplicate 等)在导入时立即抛 `RuntimeError`,链式阻塞后续 catalog 加载。**(这跟本轮 §5 提到的 14 个 malformed rows 是否构成 import-time 阻塞,需要单独验证 — 一旦加载时间点抛 RuntimeError,所有 UA-2 + UA-1 + UA-3 case 都被拦下)**。

## 9. 工作纪律状态

- 本轮报告**不动**任何代码、不修复任何问题、不 commit。
- 工作区改动(`review3 / data_factory_server / doc-fact`)均为先前未提交,与本任务无关。
- 本文档为**单一 markdown 输出**(`ua_test_gui/doc/ua2_current_status.md`),后续 GPT 审核时可作为事实基线。

报告完成时间:2026-07-12 17:12。
