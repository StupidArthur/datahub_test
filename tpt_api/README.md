# tpt_api

Supcon SaaS / TPT 后台域的统一 HTTP 客户端（Go + Python）。**一份代码覆盖三类业务端点**，共享同一套登录 + 鉴权 + 错误码。

> 当前版本：v0.1.0
>
> designed by yzc

---

## 1. 这是什么

`USER_MANAGER`、`alg_update`、`data-hub-tool` 三个工具各自维护一份 TPT 后台域的 HTTP 客户端（Go × 2 + Python × 2），登录端点、鉴权码、错误码完全一致，但代码散落、签名微差、`TptSaasUserTenantryId` 这种拼写错误被复制了 4 份。

`tpt_api` 把这 4 份合并成两个并行包（Go / Python），按子模块拆分：

| 子模块 | 端点前缀 | 业务域 | 源出处 |
|---|---|---|---|
| `users` | `/xpt-system/api/system-manager/umsAdmin/*` | TPT admin 用户管理 | `USER_MANAGER/internal/api/` + `USER_MANAGER/_preserve/api.py` |
| `algorithms` | `/alg-manager-web-v2.2-tpt/api/algorithm/*` | 算法管理 | `alg_update/common/api.py` + `alg_update/alg_toolbox/algapi.go` |
| `datahub` | `/ibd-data-hub-web-v2.2/api/{tag-info,tag-value,ds-info}/*` | tag + 历史值 + 数据源 | `data-hub-tool/common_api.py` |

三家共享登录端点 `POST /tpt-admin/system-manager/umsAdmin/login`、Bearer token、HTTPS 多租户 cookie（`TptSaasUserTenantryId` / `tenant-id`）、鉴权码 `{A0230, A0201, A0202, A0203}` + 关键词表。

---

## 2. 目录结构

```
tpt_api/
├── README.md            ← 本文件
├── go/                  ← Go 包
│   ├── go.mod
│   ├── client.go        ← Client + Login + doRequest 公共层
│   ├── errors.go        ← 错误类型 + 鉴权判定
│   ├── users.go         ← TPT admin 用户管理 4 端点
│   ├── algorithms.go    ← alg-manager 算法管理
│   ├── datahub.go       ← ibd-data-hub tag + 历史值 + 数据源
│   ├── *_test.go        ← 表驱动 + RoundTripper mock
│   ├── iohelpers.go
│   └── examples/        ← 三个 main.go 可直接 go run
└── python/              ← Python 包
    ├── pyproject.toml
    ├── requirements.txt
    ├── tpt_api/         ← 顶层包
    │   ├── __init__.py
    │   ├── client.py    ← AlgAPI + login + _request
    │   ├── errors.py
    │   ├── types.py
    │   ├── users.py
    │   ├── algorithms.py
    │   ├── datahub.py   ← 含 ds-info 段（add/page/get_by_id/...）
    │   └── examples/    ← python -m tpt_api.examples.*
    └── tests/           ← pytest + httpx.MockTransport
```

---

## 3. Go 用法

### 3.1 快速上手

```go
import "github.com/yzc/tpt_api"

c := tptapi.NewClient("https://supcontpt.supcon.com")
ctx := context.Background()
if err := c.Login(ctx, "admin", "password", "A54Z32M2"); err != nil {
    log.Fatal(err)
}

// 用户管理
resp, _ := c.ListUsers(ctx, 1, 10, "", "", "-createTime")
for _, u := range resp.Records { ... }

// 算法管理
all, _ := c.GetAllAlgorithms(ctx, 100, "-createTime", "", "")
matched, _ := c.MatchLocalFiles("resource")

// data-hub
tags, _ := c.GetAllTagsAllTypes(ctx, 2000, nil)
c.ImportTagValueHistory(ctx, "demo.xlsx", &dsID, "", "", "", nil)
```

### 3.2 测试

```bash
cd tpt_api/go
go test -count=1 ./...
```

### 3.3 HTTPS 多租户

`tenantID` 非空且 baseURL 以 `https://` 开头时，Client 自动：
- 登录请求 body 加 `tenantId` 字段
- 所有请求带 `Cookie: TptSaasUserTenantryId=...; tenant-id=...`

HTTP 单租户场景（`tenantID=""`）：不写 cookie，不带 body 字段。

### 3.4 错误处理

```go
_, err := c.ListUsers(ctx, 1, 10, "", "", "")
if tptapi.IsAuthError(err) {
    // token 过期，跳转登录
}
if tptapi.IsAPIError(err) {
    var apiErr *tptapi.ErrAPI
    errors.As(err, &apiErr)  // 拿到 Code/Msg
}
```

---

## 4. Python 用法

### 4.1 快速上手

```python
from tpt_api import AlgAPI, UserDraft
from tpt_api import users as users_mod

api = AlgAPI("https://supcontpt.supcon.com")
api.login("admin", "password", "A54Z32M2")

# 用户管理
page = users_mod.list_users(api, page=1, page_size=10)
for u in page.records:
    print(u.username, u.email)

# 算法管理
from tpt_api import algorithms as alg_mod
all_algos = alg_mod.get_all_algorithms(api)
matched = alg_mod.match_local_files(api, "resource")

# data-hub
from tpt_api import datahub as dh_mod
tags = dh_mod.get_all_tags_all_types(api)
resp = dh_mod.import_tag_value_history(api, "demo.xlsx", ds_id=2)
```

### 4.2 安装与测试

```bash
cd tpt_api/python
pip install -e ".[test]"
pytest tests/ -q
```

### 4.3 与父级代码的兼容性

- 类名 `AlgAPI` 不变（保持 `api = AlgAPI(url); api.login(...)` 风格）
- 异常上挂 `is_auth_error` 属性（与父级 `common/api.py` / `common_api.py` 一致）
- 业务缓存属性名 `algorithms` / `source_map` / `tags` / `name_map` 不变
- 方法名（用户管理）`list_users` / `get_all_users` / `create_user` / `reset_password`
- 方法名（算法管理）`list_algorithms` / `get_all_algorithms` / `upload_file` / `edit_algorithm` / `match_local_files` / `release_algorithm` / `get_by_id` / `get_by_source_path` / `list_local_resources`
- 方法名（数据源）`list_ds_info` / `get_all_ds_info` / `get_ds_info_by_id` / `get_ds_info_by_name` / `ds_info_to_model` / `add_ds_info`
- 方法名（tag）`add_tag` / `list_tags` / `get_all_tags` / `get_all_tags_all_types` / `delete_tags` / `delete_tags_by_name` / `delete_tags_physical` / `get_tag_by_name`
- 方法名（历史值）`import_tag_value` / `import_tag_value_history` / `import_csv_tag_value_history` / `get_history_value` / `get_all_history`
- 方法名（位号值）`collect_tag_value` / `get_rt_value` / `query_history_value` / `write_tag_values`

**迁移路径**：把 `from common.api import AlgAPI` 改为 `from tpt_api import AlgAPI` 即可，业务代码不需要改。

---

## 5. 命名约定（必读）

**`add_tag` 的 `tagName` 和 `tagBaseName` 约定**：

- 绑定到 OPC UA 数据源时，**`tagBaseName`（底层位号名）= `"{namespace_index}_{node_name}"`**
  - 例：OPC UA 节点 `ns=1;s=loop_demo_1` → `tagBaseName = "1_loop_demo_1"`
- `tagName`（系统位号名）通常与 `tagBaseName` 一致，但可以取用户友好的别名
- 现有平台数据遵循此约定（如 `1_FIC202_RATE.VALUE`、`1_FIC202_CON.VALUE`）

**`add_tag` 用法**：

```python
from tpt_api import AlgAPI
from tpt_api import datahub as dh_mod

api = AlgAPI("http://...")
api.login("u", "p")

# 绑定到 OPC UA 节点 ns=1;s=loop_demo_1
dh_mod.add_tag(
    api,
    tag_name="1_loop_demo_1",          # 系统位号名（可见）
    tag_base_name="1_loop_demo_1",     # 底层位号名（指向 OPC UA 节点）
    data_type=11,                       # DOUBLE
    ds_id=9,                            # ds-info id
)
```

> **坑警告**：
> - 如果不传 `tag_base_name`，默认 = `tag_name`（与旧父级代码兼容）
> - 但绑定 OPC UA 数据源时**必须**传 namespaced 形式，否则 tpt 找不到对应节点
> - `tagName` 全局唯一；同名的 tag 跨 ds 不能共存（A0001 错误）

---

## 6. data-hub 端点全集

### 6.1 数据源（ds-info）

| 方法 | HTTP | 端点 | 说明 |
|---|---|---|---|
| `list_ds_info` | POST | `/ds-info/page` | 分页列（MyBatis Page） |
| `get_all_ds_info` | POST | `/ds-info/page` | 自动翻页拉全量 |
| `get_ds_info_by_id` | — | — | 从 `get_all_ds_info` 缓存里按 id 查 |
| `get_ds_info_by_name` | — | — | 从缓存里按 `dsName` 或 `name` 查 |
| `ds_info_to_model` | — | — | dict → `DsInfo` dataclass |
| `add_ds_info` | POST | `/ds-info/add` | 新增接入数据源 |

**`add_ds_info` 重要细节**：
- 必填：`dsName` / `dsType` / `dsSubType` / `dsTarUrl`
- `dsType` / `dsSubType` 传 int，函数内部自动转字符串（平台约定）
- `dsTarUrl` 全局唯一；重复 → `A0001: Duplicate data source address`

### 6.2 位号（tag-info）

| 方法 | HTTP | 端点 | 说明 |
|---|---|---|---|
| `add_tag` | POST | `/tag-info/add` | 新增位号（命名约定见 §5） |
| `list_tags` | POST | `/tag-info/page` | 分页列 |
| `get_all_tags` | POST | `/tag-info/page` | 自动翻页 |
| `get_all_tags_all_types` | POST | `/tag-info/page` | 跨所有 `tagType` 拉取（避免漏数据） |
| `get_tag_by_name` | — | — | 从 `get_all_tags` 缓存查 |
| `delete_tags` | DELETE | `/tag-info/batchDeleteLogic` | **逻辑删除**（进回收站，**name 仍被占用**） |
| `delete_tags_by_name` | DELETE | `/tag-info/batchDeleteLogic` | 按名查 id 后调 `delete_tags` |
| `delete_tags_physical` | DELETE | `/tag-info/batchDelete` | **物理删除**（清回收站，**name 释放**） |

> **删除的坑**：
> - `delete_tags` 软删后 name 仍被占用，add 报 `A0001: duplicated`
> - 真删必须用 `delete_tags_physical`（慎用，不可恢复）

### 6.3 位号值（tag-value）

| 方法 | HTTP | 端点 | 说明 |
|---|---|---|---|
| `import_tag_value` | POST | `/tag-value/importTagValue` | JSON 同步导入（≤10000 条） |
| `import_tag_value_history` | POST | `/tag-value/importTagValueHistory` | Excel/ZIP 异步导入（注意 API 拼写是 `corn` 不是 `cron`） |
| `import_csv_tag_value_history` | POST | `/tag-value/importCSVTagValueHistory` | CSV 导入（已废弃） |
| `collect_tag_value` | POST | `/tag-value/collectTagValue` | 触发/配置一次位号值采集任务（esDTO 透传） |
| `get_rt_value` | POST | `/tag-value/getRTValue` | 取位号实时值（`list[dict]`，按名/id/组查） |
| `get_history_value` | POST | `/tag-value/getHistoryValueFromDB` | 查历史值（单页，`{tagName:{list,total}}`） |
| `get_all_history` | POST | `/tag-value/getHistoryValueFromDB` | 自动翻页，按 tag 聚合 |
| `query_history_value` | POST | `/tag-value/getHistoryValue` | 取历史值（IPage 分页，支持 interval 采样/offset/option） |
| `write_tag_values` | POST | `/tag-value/writeTagValues` | 实时库回写（`{tagName:value}`，共用 tagTime/qualityCode） |

> **`query_history_value` ≠ `get_history_value`**：
> - `get_history_value`（getHistoryValueFromDB）：响应 `{tagName: {list, total}}`，按 tag 聚合
> - `query_history_value`（getHistoryValue）：MyBatis IPage 分页（records/total/size/pages），支持 `interval` 采样、`offset` 偏移、`option` 填充规则；起止间隔不超过一个月
>
> **`write_tag_values` 返回**：`{tagNames:[成功位号], failMsg:{tagName: 原因}, msg}`，`failMsg` 空=全部成功。
>
> **写后读回验证**：`query_history_value(is_source=True)` **立即可查到**写入记录（writeTagValues 直接写历史，不受 UA 5s 采集周期限制；实测 +0s 命中，appTime=写入时刻）。`get_rt_value` 写后约 **1 秒**才反映（+0s 仍旧值、+1s 已新值，`is_from_db` True/False 都一样）——写完立刻读会拿到旧值，等 ~1s。
>
> **双向数据流**（asyncua 直连源端实测，UA 源端 `opc.tcp://host:18950/` `ns=1;s=test_write` ↔ datahub `1_test_write`）：
> - ① `write_tag_values` 会**回写 UA 源端**——写前源端节点=123.45、写 999.99 后源端节点=999.99（不止写 datahub 历史+当前值）。
> - ② 源端值变动 → `get_rt_value` **~1s** 反映（datahub 当前值快照更新快于轮询，推测订阅/快速刷新）；`query_history_value` **~4s** 出现（落在 ~5s 轮询网格，poller 采样落库）。

### 6.4 回收站

| 方法 | HTTP | 端点 | 说明 |
|---|---|---|---|
| `list_recycle_tags` | POST | `/tag-group/get` | 单页（`groupId="1"` 是回收站） |
| `get_all_recycle_tags` | POST | `/tag-group/get` | 翻页（注意响应在 `content.tagInfoList.records`） |

---

## 7. 与现有客户端的关系

| 现有位置 | 状态 | 迁移目标 |
|---|---|---|
| `USER_MANAGER/internal/api/{client,users,types,errors}.go` | 在用 | `tpt_api/go/{client,users,errors}.go` + `types` 字段 |
| `alg_update/alg_toolbox/algapi.go` | 工具未发布（v0.x） | `tpt_api/go/algorithms.go` |
| `alg_update/common/api.py` | 在用 | `tpt_api/python/tpt_api/algorithms.py`（AlgAPI 算法部分） |
| `alg_update/api.py`（顶层 copy） | 在用 | 同上 |
| `alg_update/alg_republish/api.py` | 在用 | 同上 |
| `data-hub-tool/common_api.py` | 在用 | `tpt_api/python/tpt_api/datahub.py`（AlgAPI tag 部分） |
| `alg_update/data-hub-tool/common_api.py` | 过时快照 | 删 |

> 详见：USER_MANAGER/app.go + alg_update/alg_publish/alg_publish.py + data-hub-tool/migrate.py 等业务调用方，在切到 tpt_api 后 import 路径换掉即可。

---

## 8. 已知限制

- **HTTP 超时**：Go 默认 30s，Python 默认 30s（data-hub 场景建议显式 `AlgAPI(url, timeout=60.0)`，与父级 `common_api.py:25` 一致）。
- **`doRequest` 不直接支持 query params**：Go 版 `ListAlgorithms` 把 `extend` 拼到 URL 上；Python 版用 `params=` 参数。
- **平台分叉的细节**：`data-hub-tool/common_api.py` 和 `alg_update/common/api.py` 都从 `common/api.py` 分叉已久，本包在 `algorithms.py` 和 `datahub.py` 各自完整保留这些分叉，但**登录代码、错误码判定统一到一份**（`tpt_api/{go,python}/client.*` 的 `_request`/`doRequest`）。
- **`TptSaasUserTenantryId` 拼写错误**（多一个 `r`）是平台侧实际行为，本包沿用未修正。
- **`delete_tags` 软删 / `delete_tags_physical` 硬删**：见 §6.2 的"删除的坑"。
- **同名 tag 跨 ds 不能共存**：`add_tag` 的 `tagName` 全局唯一（见 §5）。

---

## 9. 验证状态

| 语言 | 单元测试 | examples |
|---|---|---|
| Go | `cd tpt_api/go && go test -count=1 ./...` 全部通过 | `go run ./examples/{users,algorithms,datahub}/main.go` |
| Python | `cd tpt_api/python && pytest tests/ -q` → **43 passed**（含 ds-info 5 + 算法 9 + tag/history 13 + 位号值 4 新增） | `python -m tpt_api.examples.{users,algorithms,datahub,verify_tag_value}` |

> 位号值 4 接口（collect/getRT/query_history/write）已真实环境验证：get_rt_value 取真实值（写后 ~1s 反映）、query_history_value 7 天 4718 条、write_tag_values 回写经读回确认（`examples/verify_tag_value.py` `WRITE=1` 启用回写+读回）。

---

## 10. 迁移示例

### Go: USER_MANAGER 的 client 调用

```go
// 旧
import "USER_MANAGER/internal/api"
c := api.NewClient("https://...")
c.Login(ctx, "u", "p", "t")
c.ListUsers(ctx, 1, 10, "", "", "-createTime")

// 新
import "github.com/yzc/tpt_api"
c := tptapi.NewClient("https://...")
c.Login(ctx, "u", "p", "t")
c.ListUsers(ctx, 1, 10, "", "", "-createTime")
```

### Python: alg_update 的 AlgAPI 调用

```python
# 旧
import sys; sys.path.insert(0, "..")
from common.api import AlgAPI
api = AlgAPI("http://...")
api.login("u", "p")
api.get_all_algorithms()
api.upload_file("pkg.zip")

# 新
from tpt_api import AlgAPI
api = AlgAPI("http://...")
api.login("u", "p")
api.get_all_algorithms()  # 通过 algorithms.py 暴露
api.upload_file("pkg.zip")
```

> 注：Python `from tpt_api import AlgAPI` 后，方法调用与父级一致；`algorithms.py` / `datahub.py` / `users.py` 把方法按子模块拆分到独立函数 / 命名空间，但**所有方法都通过 `AlgAPI` 实例调用**（如 `api.list_tags(...)` / `api.get_all_algorithms()`），方便从父级代码直接切换。
