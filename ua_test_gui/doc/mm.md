# 项目记忆与进度

## 项目概述

**supcon_tools** 是 TPT OPC UA 接入测试工具集。被测系统 TPT = UA 客户端 + 实时数据管理 + 历史数据管理。
工具链：ua_test_gui（Wails 桌面应用）+ ua_mocker（Python Mock Server）+ tpt_api（Python 接口封装库）。
验证环境：`http://10.10.58.153:31501`（admin/123456），本机 IP `10.30.70.77`。

---

## 当前工作：设计 UA 客户端测试用例

### 文件位置
- 测试用例文档：`ua_test_gui/doc/tpt_data-hub_test_cases.md`
- 测试设计方法论：`ua_test_gui/doc/how-to-design-test-case.md`

### 一级结构（已定稿）

**功能测试：**
| 编号 | 一级点 | 状态 |
|------|--------|------|
| UA-1 | 数据源管理 | ✅ 二级+三级全部评审落盘 |
| UA-2 | 位号管理 | ⏳ 二级已提案，待评审三级（接口补充中） |
| UA-3 | 数据采集 | 待评审二级 |
| UA-4 | 数据回写 | 待评审二级 |

**非功能测试：**
| 编号 | 一级点 | 状态 |
|------|--------|------|
| UA-5 | 系统响应性 | 待评审二级 |
| UA-6 | 读写吞吐与容量 | 待评审二级 |

### UA-1 数据源管理（已完成，45 条三级点）

| 二级点 | 三级点数 | 内容 |
|--------|---------|------|
| UA-1-1 连接建立 | 12 | 可达(3) + 不可达(2) + 鉴权(3) + 质量码(3) + 重复地址(1) |
| UA-1-2 启停控制 | 8 | 禁用(3) + 启用(2) + 幂等循环(3) |
| UA-1-3 断线与自动重连 | 8 | 断开延迟(1) + 重连延迟(1) + 5次统计(1) + 特殊场景(5) |
| UA-1-4 多数据源并存 | 6 | 并存(1) + 隔离(3) + 同底层位号(1) + 重名拒绝(1) |
| UA-1-5 数据源删除 | 9 | 2×2矩阵(4) + 回收站(2) + 其他(3) |
| UA-1-6 数据源测试功能 | 13 | ds-info/test 5种testType的枚举/读/写/历史 |

### UA-2 位号管理（待评审，二级提案）

| 编号 | 二级点 | 理由 |
|------|--------|------|
| UA-2-1 | 位号注册 | tagName/tagBaseName/dataType/dsId/onlyRead/frequency/限值 各参数 + 边界 |
| UA-2-2 | 位号枚举与查询 | tag-info/page + queryWithQuality + getNotUsedBaseTagInfoContinue |
| UA-2-3 | 位号删除 | 软删（回收站）、物理删、删后重建 |
| UA-2-4 | 位号采集配置 | frequency 对采集间隔的影响、onlyRead 对写值的限制 |

注意：UA-2-2 的"未注册位号发现"已归到 UA-1-6（ds-info/test testType=1）。

---

## 测试设计方法论要点（how-to-design-test-case.md）

1. **层次划分**：同级不混维度，功能/非功能分开，一条用例可含多断言
2. **测"停"先证"动"**：验证数据停止变化前，同条用例先证明数据在变化
3. **多因素矩阵覆盖**：如删除 = 禁用/启用 × 有位号/无位号 = 4 条
4. **时延重复统计**：重复 N 轮，输出 avg/max/min
5. **被测功能 vs 验证工具**：API 自身也可能是被测功能，不能自己验自己
6. **前置条件可能无法满足**：保留用例，标记 NA
7. **预期结果要可判定**：不写"值正确"，写"RT 值 = mock 节点当前值"

---

## tpt_api 接口模块（已封装并验证）

位置：`tpt_api/python/tpt_api/datahub.py`

### 数据源管理
| 函数 | 端点 | 说明 |
|------|------|------|
| add_ds_info | POST /ds-info/add | 创建数据源 |
| delete_ds_info | DELETE /ds-info/batchDelete | 删除数据源 |
| change_ds_state | POST /ds-info/changeState | 启用/禁用 |
| list_ds_info | POST /ds-info/page | 分页列数据源 |
| get_all_ds_info | - | 翻页拉全部 |
| get_ds_info_by_id | - | 按 ID 查 |
| get_ds_info_by_name | - | 按名查 |
| test_ds_info | POST /ds-info/test | 数据源测试（5种testType） |

### ds-info/test 的 5 种 testType
| testType | 常量 | 功能 | 关键参数 |
|----------|------|------|---------|
| 1 | DsTestEnumerate | 枚举位号 | dsId |
| 2 | DsTestReadRT | 读实时值(源端) | dsId + tagName |
| 3 | DsTestReadRTDB | 读实时值(库) | dsId + tagName |
| 4 | DsTestHistory | 读历史值 | dsId + tagName + beginTime + endTime |
| 5 | DsTestWrite | 写值 | dsId + tagName + tagValue |

### 位号管理
| 函数 | 端点 | 说明 |
|------|------|------|
| add_tag | POST /tag-info/add | 注册位号（仅一次位号，二次/虚位号待补） |
| update_tag | PUT /tag-info/update | 编辑单个位号（全量更新，未传字段重置默认） |
| batch_update_tags | POST /tag-info/batchUpdate | 批量改(仅groupId/unit/frequency) |
| list_tags | POST /tag-info/page | 分页列位号（不带实时值） |
| query_tags_with_quality | POST /tag-group/queryWithQuality | 查位号（带实时值+质量码+dsName） |
| get_not_used_tags | POST /tag-info/getNotUsedBaseTagInfoContinue | 查未导入位号（游标分页，实测未过滤已导入） |
| batch_add_tags | POST /tag-info/batchAdd | 从数据源批量导入 |
| get_tag_by_name | - | 按名查 |
| get_all_tags / get_all_tags_all_types | - | 翻页拉全部 |
| delete_tags | DELETE /tag-info/batchDeleteLogic | 软删（进回收站） |
| delete_tags_physical | DELETE /tag-info/batchDelete | 物理删 |
| delete_tags_by_name | - | 按名删 |
| export_tags | POST /tag-info/export | 导出Excel（parse=True返回List[List]） |
| import_tags_from_file | POST /tag-info/importTagInfoStream | 导入Excel（conflictStrategy: 0=跳过,1=覆盖） |

### 位号分组
| 函数 | 端点 | 说明 |
|------|------|------|
| get_tag_group_tree | POST /tag-group/groupTree | 获取分组树 |
| add_tag_group | POST /tag-group/add | 创建分组节点 |
| update_tag_group | PUT /tag-group/update | 编辑分组（改名/移动） |
| delete_tag_group | DELETE /tag-group/batchDelete | 删除分组（isForce=true连带删位号） |
| add_tag_group_relation | POST /tag-group/batchAddRelation | 收藏位号 |
| remove_tag_group_relation | DELETE /tag-group/batchDelRelation | **双用途**：groupId="1"+回收站位号ID=恢复位号；groupId="2"+收藏位号ID=取消收藏（返回false但实际生效） |
| list_favorite_tags | POST /tag-group/get (groupId="2") | 查收藏列表 |
| list_recycle_tags | POST /tag-group/get (groupId="1") | 查回收站 |

### 位号值
| 函数 | 端点 | 说明 |
|------|------|------|
| get_rt_value | POST /tag-value/getRTValue | 取实时值 |
| write_tag_values | POST /tag-value/writeTagValues | 回写位号值 |
| get_history_value | POST /tag-value/getHistoryValueFromDB | 历史值(旧) |
| query_history_value | POST /tag-value/getHistoryValue | 历史值(IPage分页) |
| collect_tag_value | POST /tag-value/collectTagValue | 触发采集 |
| import_tag_value | POST /tag-value/importTagValue | 同步JSON历史值 |
| import_tag_value_history | POST /tag-value/importTagValueHistory | 异步Excel历史值 |

### add_tag 完整参数（含限值）
- 必填：tag_name, data_type, ds_id
- 可选：tag_type, group_id, unit, only_read, frequency, need_push, tag_desc, is_vector, tag_base_name
- 限值：hi_eu(量程上限), lo_eu(量程下限), limit_up(高限), limit_up_up(高高限), limit_up_up_up(高高高限), limit_down(低限), limit_down_down(低低限), limit_down_down_down(低低低限)

---

## 已知问题与发现

1. **DateTime 读回格式**：TPT 返回 `DateTime{utcTime=..., javaDate=...}`（Java toString），不是 ISO 字符串。ua_test_gui 的 `compare.go` 已加 `parseJavaDateTime` 解析。
2. **getNotUsedBaseTagInfoContinue 不过滤已导入**：API 名暗示只查未导入的，实测导入后仍出现，可能有缓存延迟。
3. **update_tag 全量替换**：未传字段会被重置为默认值（如 tag_base_name 不传则变回=tag_name）。
4. **remove_tag_group_relation 返回 false**：但操作实际生效，以 list_favorite_tags 确认为准。
5. **export_tags 需有采集数据**：无数据的位号导出时服务端返回 500。

---

## 其他已完成的工作

### ua_test_gui 代码改动（未提交）
- `compare.go`：testValueFor 加 DateTime/String case + tryAsTime 时间归一化（含 Java DateTime 解析）
- `typemap_test.go`：修过时断言（String/DateTime 已支持）
- `compare_test.go`：补 Java DateTime 格式比较用例
- `provision/service.go`：修过时注释
- `SubjectPage.tsx`：自动登录（打开即登录，改信息防抖重试，首次才弹toast）
- `MockPage.tsx`：refresh() 改 Promise.all 并行加载

### Go 端接口模块（已同步到 tpt_api）

`ua_test_gui/internal/subject/` 的最新 Go 代码已同步到 `tpt_api/go/`，加 `_full.go` 后缀以区别于原版：
- `datahub_full.go` / `datahub_extra_full.go`：所有新增 datahub 接口（test_ds_info、query_tags_with_quality、batch_*、export/import、tag-group 全套等）
- `model_full.go`：TptClient + 数据模型
- `helpers_full.go`：multipart + 文件下载辅助
- `service_full.go` / `state_full.go`：LoginSubject + 状态管理
- 冲突点已处理：`truncate`/`writeFile` 在新文件中重命名为 `truncateStr`/`writeFileBytes`
- 原 tptapi 的 `Client` + `NewClient` + `Login(ctx, ...)` API 保持不变
- 验证：`go build ./...` + `go test ./...` + examples 全部通过

### ua_mocker 代码改动（未提交）
- `server_main.py`：批量节点创建优化（分容器+AddNodesItem 批量，万级节点从 O(n²) 降级）
- `main.spec`/`ua_mocker.spec`：console=False

### 当前环境状态
- mock server 在 10.30.70.77:18950 运行中（config_example.yaml，1052 节点）
- TPT 数据源 id=40（mocker_18950）alive=true
- 已导入约 100 个位号到 ds_id=40
- 10.30.70.77 和 10.99.99.99 相关的旧数据源已全部清理

---

## 下一步

1. **继续评审 UA-2 位号管理三级点**（接口已补全，可以展开三级了）
2. 然后依次 UA-3 数据采集 -> UA-4 数据回写 -> UA-5 系统响应性 -> UA-6 读写吞吐
3. 全部评审完后，统一落盘到 `tpt_data-hub_test_cases.md`

---

## 用例评审待补充约定

- **实时值获取要双入口验证**：`getRTValue` 和 `queryWithQuality` 都能拿到实时缓存的 tagValue/quality/tagTime，但用途不同（精确查 vs 浏览式查带实时值）。涉及到"获取实时值"的测试用例，需分别验证两个入口，不只是一个。
- **同一行为多个入口 = 多条用例**：当系统有多个 API 入口实现同一功能（如导出/导入位号用 export_tags + import_tags_from_file，实时值查 getRTValue + queryWithQuality），每条用例要么覆盖全部入口，要么拆成多条按入口分别验证。
