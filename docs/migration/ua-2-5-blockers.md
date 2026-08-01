# UA-2-5 Blocker 记录

## B1 收藏操作解除普通分组归属（023/026/027）

| 字段 | 值 |
|------|-----|
| 影响 Case | UA-2-5-023, UA-2-5-026, UA-2-5-027 |
| 规格要求 | 收藏（addRelation groupId='2'）后，位号同时保留原普通分组关系与收藏关系；取消收藏（removeRelation）后原分组关系仍在 |
| 实际结果 | 收藏后位号从原普通分组移除，落入 Root + 收藏夹；取消收藏后原分组关系不恢复（Root 归属也消失，位号进入无分组状态） |
| 是否稳定复现 | 是（canonical 27 道重跑 023/026/027 均 FAIL） |

### 分析

产品 `addTagGroupRelation` 会把位号从原普通分组整体迁出，只保留收藏分组（groupId='2'）与 Root（groupId='0'）。`removeTagGroupRelation` 只删除收藏关系，不会把位号放回原来的普通分组。因此：

- UA-2-5-023 收藏单个位号 → 原分组 `_check_tag_in_group` 为 False
- UA-2-5-026 取消收藏 → 位号未回到原分组，仍不在任何普通分组
- UA-2-5-027 取消收藏返回 false（实际上已生效）→ 位号同样离开原分组

### 测试证据（record_property）

- 023: `in_g1_after_fav=false`、`in_root_after_fav=true`、`product_limitation=favoriting_removes_group_assignment`
- 026: 收藏后 `_check_tag_in_group(原分组)=false`；取消收藏后 `unfavorite_fallback_root=false`、`product_limitation=favoriting_removes_group_assignment`
- 027: `after_still_in_g1=false`、`after_in_root=false`、`product_limitation=favoriting_removes_group_assignment`

### 分组归属验证约束（架构规则）

- 禁止用 `list_tags` 断言 groupId（`list_tags` 不返回 groupId 字段，恒为 None）
- 分组归属只能通过 `query_tags_with_quality(group_id=..., tag_name=...)` 精确 `tagName` 匹配确认（helper `_check_tag_in_group`）

## 影响总览

| 维度 | 值 |
|------|-----|
| 阻塞迁移 | UA-2-5-023/026/027 共 3 道 |
| blocker 引起 FAIL | 3 |
| 不受影响 | UA-2-5-001~022, 024~025（通过）；006/007/008/012/013/017/019/020/021/025（spec_pending XFAIL） |
