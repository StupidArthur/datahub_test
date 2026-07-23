# supcon_tools 项目 Summary

供用例评审人快速了解项目背景。详细测试用例见 `tpt_data-hub_test_cases.md`。

---

## 1. 项目定位

**supcon_tools** 是 **TPT OPC UA 接入测试工具集**。

**被测系统 (TPT)** = UA 客户端 + 实时数据管理 + 历史数据管理。
**目标**：在普通 Windows 机器上，双击 exe 一键完成 OPC UA 接入测试全流程，无需 Python、无需写代码、无需真实设备。

---

## 2. 工具链

| 组件 | 路径 | 技术栈 | 角色 |
|------|------|--------|------|
| **ua_test_gui** | `ua_test_gui/` | Wails v2.12 + Go 1.25 + React TS + Tailwind | 主桌面应用，UI + 业务调度 |
| **ua_mocker** | `ua_mocker/` | Python 3.11 + asyncua + PyInstaller | OPC UA Mock Server，模拟被采设备 |
| **tpt_api** | `tpt_api/` | Python + Go | TPT 后台 HTTP API 封装库 |
| **qt5-version** | `qt5-version/` | Qt5 | 兼容 Server 2016 1607 的旧版 |

**验证环境**：`http://10.10.58.153:31501`（admin / 123456），本机 IP `10.30.70.77`。

---

## 3. 核心数据流

```
ua_test_gui (Wails/Go/React)
    ↓
启动 ua_mocker.exe → OPC UA Server (如 opc.tcp://10.30.70.77:18950/ua_mocker/)
    ↓
调用 TPT REST API（/ibd-data-hub-web-v2.2/api/...）
    ↓
TPT 连接 mock server，完成数据源/位号组态、采集、写入、历史存储
    ↓
通过 query_history_value 等 API 验证结果
```

**关键事实**：TPT 既是 UA 客户端（连 mock），又是 RT/历史数据管理者（连写+查）。测试时既要测 UA 客户端的"能不能连/能不能采"，也要测 RT/历史的"准不准/快不快"。

---

## 4. TPT 系统（被测对象）

TPT 是一套工业数据采集与管理系统，核心能力：

### 4.1 UA 客户端
- 通过 OPC UA 协议连接下游数据源（OPC-UA-Server）
- 支持浏览节点、读写值、订阅（实际用轮询，5s 网格）
- 支持数据回写（writeTagValues → 写回 UA 源端）
- 维护节点名 → 系统位号名的映射

### 4.2 实时数据管理
- 维护位号当前值缓存（RT cache）
- 采集频率可配（默认 10s/位号）
- 提供 `getRTValue` 和 `queryWithQuality` 两个查询入口
- writeTagValues 写入后：~1s 更新 RT 缓存，~5s 落历史

### 4.3 历史数据管理
- 存储位号时间序列数据
- 支持采样/偏移/填充规则（`queryHistoryValue` 高级接口）
- 分页查询（IPage 结构）
- 起始结束时间间隔不能超过一个月

### 4.4 数据源管理
- 平台叫"数据源"(dsInfo)，每条配一个 OPC UA endpoint
- 支持启用/禁用、断线自动重连、多源并存
- 提供 `ds-info/test` 端点，不注册位号直接测数据源连通性

### 4.5 位号分组
- 树形结构（tag-group），有特殊节点：
  - `0` = Root
  - `1` = Recycle Bin（软删回收站）
  - `2` = Favorites（收藏夹）
- 支持收藏/取消收藏位号

---

## 5. 关键 API 速览

完整封装在 `tpt_api/python/tpt_api/datahub.py` 和 `ua_test_gui/internal/subject/`。

### 5.1 数据源 (ds-info)

| 端点 | 方法 | 用途 |
|------|------|------|
| `/ds-info/add` | POST | 创建数据源（指定 endpoint + 类型） |
| `/ds-info/page` | POST | 分页列数据源 |
| `/ds-info/changeState` | POST | 启用/禁用 |
| `/ds-info/batchDelete` | DELETE | 批量删除 |
| `/ds-info/test` | POST | **测数据源连通性**（5 种 testType：枚举/读RT/读RT库/历史/写） |

### 5.2 位号 (tag-info)

| 端点 | 方法 | 用途 |
|------|------|------|
| `/tag-info/add` | POST | 注册单个位号（13 种数据类型、限值、单位、频率等） |
| `/tag-info/update` | PUT | **全量更新**单个位号（tagName/dataType 必填，未传字段重置默认） |
| `/tag-info/batchUpdate` | POST | 批量改（仅 groupId/unit/frequency） |
| `/tag-info/page` | POST | 分页列位号（无实时值） |
| `/tag-info/batchDeleteLogic` | DELETE | 软删（进回收站 groupId=1） |
| `/tag-info/batchDelete` | DELETE | 物理删 |
| `/tag-info/getNotUsedBaseTagInfoContinue` | POST | 从数据源 browse 未导入位号（**实测未过滤已导入**，API 名易误导） |
| `/tag-info/batchAdd` | POST | 从数据源批量导入（与上一个配套） |
| `/tag-info/export` | POST | 导出 Excel（21 列，含实时值+限值） |
| `/tag-info/importTagInfoStream` | POST | 导入 Excel（conflictStrategy: 0=跳过/1=覆盖，**没有"追加"**） |

### 5.3 位号值 (tag-value)

| 端点 | 方法 | 用途 |
|------|------|------|
| `/tag-value/getRTValue` | POST | 取位号实时值（精确查：`isFromDB=false` 走实时库） |
| `/tag-value/writeTagValues` | POST | 回写位号值（直接落历史+~1s 更新 RT+回写 UA 源端） |
| `/tag-value/getHistoryValue` | POST | 历史值（IPage 分页，支持 interval/offset/option） |
| `/tag-value/getHistoryValueFromDB` | POST | 历史值（旧接口，按 tagName 返 list） |
| `/tag-value/importTagValue` | POST | 同步导入 JSON 历史值 |
| `/tag-value/importTagValueHistory` | POST | 异步导入 Excel/ZIP 历史值 |
| `/tag-value/importCSVTagValueHistory` | POST | CSV 导入（已废弃） |
| `/tag-value/collectTagValue` | POST | 触发采集任务 |

### 5.4 位号分组 (tag-group)

| 端点 | 方法 | 用途 |
|------|------|------|
| `/tag-group/groupTree` | POST | 获取分组树 |
| `/tag-group/add` | POST | 创建分组 |
| `/tag-group/update` | PUT | 编辑（改名/移动） |
| `/tag-group/batchDelete` | DELETE | 删除（isForce=true 连带删位号） |
| `/tag-group/batchAddRelation` | POST | 收藏位号 |
| `/tag-group/batchDelRelation` | DELETE | **双用途**：groupId="1"+回收站位号ID=恢复位号；groupId="2"+收藏位号ID=取消收藏（**返回 false 但操作实际生效**） |
| `/tag-group/get` | POST | 按 groupId 查位号（groupId="1"=回收站/"2"=收藏/"0"=Root） |
| `/tag-group/queryWithQuality` | POST | 查位号带实时值+质量码+dsName（**注意：与 list_tags 的区别是有实时值**） |

### 5.5 13 种数据类型

| 码 | 名称 | 码 | 名称 |
|----|------|----|------|
| 1 | BOOLEAN | 8 | LONG (Int64) |
| 2 | S_BYTE (SByte) | 9 | U_LONG (UInt64) |
| 3 | BYTE | 10 | FLOAT |
| 4 | SHORT (Int16) | 11 | DOUBLE |
| 5 | U_SHORT (UInt16) | 12 | STRING |
| 6 | INT (Int32) | 13 | DATE_TIME |
| 7 | U_INT (UInt32) | | |

### 5.6 add_tag 限值参数

| 参数 | 含义 | 参数 | 含义 |
|------|------|------|------|
| `hiEU` | 量程上限 | `loEU` | 量程下限 |
| `limitUp` | 高限 | `limitDown` | 低限 |
| `limitUpUp` | 高高限 | `limitDownDown` | 低低限 |
| `limitUpUpUp` | 高高高限 | `limitDownDownDown` | 低低低限 |

`update_tag` 全量替换（未传字段重置默认），`batch_update_tags` 只能改 groupId/unit/frequency。

---

## 6. ua_mocker（OPC UA Mock Server）

`ua_mocker/` 是 Python asyncua 实现的 OPC UA Server，被 TPT 当成"真实设备"采集。

### 6.1 启动方式

```bash
# 标准方式（用 config_example.yaml，13 种类型各 4 个节点）
python ua_mocker/main.py ua_mocker/config_example.yaml
# 监听 opc.tcp://0.0.0.0:18950/ua_mocker/
```

### 6.2 节点配置（`config_example.yaml`）

```yaml
server: "0.0.0.0"
port: 18950
namespace_index: 1

nodes:
  - name: "double_ch_"    # 节点名前缀
    type: Double          # 数据类型
    count: 1002           # 节点数
    change: true          # 值持续变化（测试采集频率用）
    writable: false
  - name: "double_wr_"
    type: Double
    count: 2
    default: 0.0
    change: false         # 值固定
    writable: true        # 可写
```

**关键字段**：
- `name`：节点名前缀，实际节点是 `name1`~`nameN`
- `type`：13 种 UA 数据类型之一
- `change`：true 则按周期变化，false 固定
- `writable`：对应 TPT 位号 onlyRead
- `default`：change=false 时的固定值

### 6.3 TPT 与 mock 之间的位号映射

TPT 通过 `tagBaseName` 关联 UA 节点，约定格式 `"<namespace>_<nodeName>"`，例 ns=1 节点 `double_ch_1` → tagBaseName `"1_double_ch_1"`。

---

## 7. 已知问题与陷阱

1. **DateTime 读回格式**：TPT 返回 `DateTime{utcTime=133801632000000000, javaDate=Wed Jan 01 08:00:00 CST 2025}`（Java toString），不是 ISO 字符串。需要解析 `utcTime` 字段（OPC UA 时间戳，1601 起 100ns 单位）转 UTC。
2. **getNotUsedBaseTagInfoContinue 不过滤已导入**：API 名暗示只查未导入的位号，实测导入后立即查询仍会出现（可能有缓存延迟）。导出的"未导入"判断在前端做。
3. **update_tag 全量替换**：未传字段会被重置为默认值（如 tag_base_name 不传则变回 = tag_name）。编辑时需传入所有需要保留的字段。
4. **remove_tag_group_relation 返回 false**：但操作实际生效，需要 list_favorite_tags 二次确认。
5. **export_tags 需有采集数据**：无数据的位号导出时服务端返回 500。
6. **add_tag 缺少 type=1（一次位号）以外的 tagType 支持**：二次位号、虚位号接口暂未支持。
7. **writeTagValues 方向**：直接落历史（+0s） + ~1s 更新 RT 缓存 + 回写 UA 源端。源端变动方向：~1s 更新 RT 缓存（订阅/快速刷新）+ ~5s 落历史（轮询网格）。
8. **import_tags_from_file conflictStrategy**：0=跳过、1=覆盖。**前端没有"追加"**。
9. **当前被测接口与底层 mock server 实际不在同一台机器**：TPT 在 10.10.58.153，mock server 在本机 10.30.70.77。TPT 必须能访问到 mock server 的 IP:port。
10. **mock server 端口可能被占用**：用 18950 端口时如果 DataFactory (review3/) 在跑，会冲突；备用 18952 等。

---

## 8. 验证环境状态

- mock server 在 10.30.70.77:18950 运行中（config_example.yaml，1052 节点）
- TPT 数据源 id=40（mocker_18950）alive=true
- 已导入约 100 个位号到 ds_id=40
- 10.30.70.77 和 10.99.99.99 相关的旧数据源已全部清理

---

## 9. 测试用例评审要点

用例文件 `tpt_data-hub_test_cases.md` 拆成：
- 总表：一级 + 二级（含描述）
- 子文件 `test_cases/UA-*-*.md`：每个二级点的三级详情

**评审关注**：
- 测试步骤是否可执行（前置条件、具体操作）
- 预期结果是否可判定（具体值、字段）
- 验证手段是否准确（用对了 API 吗）
- 边界值覆盖是否完整
- 同一行为多入口（getRTValue vs queryWithQuality）需双验证
- 关注"读"用例的"取两个不同值"——不能只验证 quality，要确认值本身在变
- 关注"写"用例的"写下去再读回来"闭环

---

## 10. 文件索引

| 路径 | 用途 |
|------|------|
| `tpt_api/python/tpt_api/datahub.py` | Python 接口封装（已含所有 30+ 函数，含限值参数、Excel 解析、queryWithQuality 等） |
| `tpt_api/python/tpt_api/client.py` | HTTP 客户端基类 |
| `ua_test_gui/internal/subject/` | Go 端最新接口封装（4 文件 + helpers） |
| `tpt_api/go/*_full.go` | 从 ua_test_gui 同步过来的最新 Go 代码 |
| `ua_mocker/server_main.py` | mock server 主逻辑（已优化批量节点创建） |
| `ua_mocker/config_example.yaml` | 13 种类型节点配置 |
| `ua_test_gui/frontend/src/pages/SubjectPage.tsx` | 登录页（自动登录已实现） |
| `ua_test_gui/frontend/src/pages/MockPage.tsx` | mock 管理页（性能参数等） |
| `ua_test_gui/frontend/src/pages/VerifyPage.tsx` | 验证页（11 类型读写回写遍历） |
| `ua_test_gui/frontend/src/pages/ProvisionPage.tsx` | 数据源/位号组态页 |
| `ua_test_gui/doc/tpt_data-hub_test_cases.md` | 测试用例总表 |
| `ua_test_harness/test_cases/*.md` | 各二级点详情 |
| `ua_test_gui/doc/how-to-design-test-case.md` | 测试设计方法论 |
| `ua_test_gui/doc/mm.md` | 项目记忆与进度 |