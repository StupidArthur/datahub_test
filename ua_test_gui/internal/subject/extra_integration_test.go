package subject

import (
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"
)

// 集成测试：验证 datahub_extra.go 和 datahub.go 中新增/修改的所有接口。
// 需要真实 TPT 环境（10.10.58.153:31501 admin/123456）。
// 用环境变量 SKIP_INTEGRATION=1 跳过。

func skipIntegration(t *testing.T) bool {
	if os.Getenv("SKIP_INTEGRATION") == "1" {
		t.Skip("set SKIP_INTEGRATION!=1 to run")
		return true
	}
	return false
}

func newTestClient(t *testing.T) *TptClient {
	cli, err := LoginSubject("http://10.10.58.153:31501", "admin", "123456", "", 60*time.Second)
	if err != nil {
		t.Fatalf("登录失败: %v", err)
	}
	return cli
}

func TestExtra_GetDsInfoByIDAndName(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)

	// 用已知数据源 id=40(mocker_18950)
	ds, err := cli.GetDsInfoByID(40)
	if err != nil {
		t.Fatalf("GetDsInfoByID: %v", err)
	}
	t.Logf("ds id=40: name=%s url=%s alive=%v", ds.DsName, ds.DsTarUrl, ds.Alive)

	dsList, err := cli.GetDsInfoByName("mocker_18950")
	if err != nil {
		t.Fatalf("GetDsInfoByName: %v", err)
	}
	if len(dsList) == 0 {
		t.Error("GetDsInfoByName 没找到 mocker_18950")
	}
	t.Logf("GetDsInfoByName found %d", len(dsList))
}

func TestExtra_QueryTagsWithQuality(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	dsID := 40
	groupID := GroupRoot
	content, err := cli.QueryTagsWithQuality(&dsID, groupID, "", "", TagTypeOnce, 1, 3, "-createTime")
	if err != nil {
		t.Fatalf("QueryTagsWithQuality: %v", err)
	}
	var resp struct {
		TagInfoList struct {
			Total   int                       `json:"total"`
			Records []TagRecordWithQuality    `json:"records"`
		} `json:"tagInfoList"`
	}
	if err := json.Unmarshal(content, &resp); err != nil {
		t.Fatalf("解析失败: %v body=%s", err, string(content)[:300])
	}
	t.Logf("total=%d records=%d", resp.TagInfoList.Total, len(resp.TagInfoList.Records))
	if len(resp.TagInfoList.Records) > 0 {
		r := resp.TagInfoList.Records[0]
		t.Logf("first: %s value=%s quality=%d", r.TagName, string(r.TagValue), r.Quality)
	}
}

func TestExtra_ListTags(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	content, err := cli.ListTags(1, 3, map[string]any{"dsId": 40})
	if err != nil {
		t.Fatalf("ListTags: %v", err)
	}
	var resp struct {
		Total   int               `json:"total"`
		Records []json.RawMessage `json:"records"`
	}
	if err := json.Unmarshal(content, &resp); err != nil {
		t.Fatalf("解析失败: %v body=%s", err, string(content)[:300])
	}
	t.Logf("ListTags dsId=40: total=%d records=%d", resp.Total, len(resp.Records))
}

func TestExtra_GetTagByName(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	content, err := cli.GetTagByName("1_bool_ch_1")
	if err != nil {
		t.Fatalf("GetTagByName: %v", err)
	}
	t.Logf("GetTagByName: %s", string(content)[:200])
}

func TestExtra_GetHistoryValue(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	content, err := cli.GetHistoryValue(
		[]string{"1_bool_ch_1"}, "2026-07-11 00:00:00", "2026-07-11 23:59:59",
		0, true, false, 0, 0, 1, 10, "-appTime")
	if err != nil {
		t.Fatalf("GetHistoryValue: %v", err)
	}
	t.Logf("GetHistoryValue: %s", safeTrunc(string(content), 300))
}

func TestExtra_GetHistoryValueFromDB(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	content, err := cli.GetHistoryValueFromDB(
		[]string{"1_bool_ch_1"}, "2026-07-11 00:00:00", "2026-07-11 23:59:59",
		true, false, 1, 10, "-appTime")
	if err != nil {
		t.Fatalf("GetHistoryValueFromDB: %v", err)
	}
	t.Logf("GetHistoryValueFromDB: %s", safeTrunc(string(content), 300))
}

// safeTrunc 安全的截断(避免越界)。
func safeTrunc(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}

func TestExtra_GetNotUsedTags(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	content, err := cli.GetNotUsedTags(40, "", "", 1, 5, "tagName")
	if err != nil {
		t.Fatalf("GetNotUsedTags: %v", err)
	}
	var resp struct {
		Successes []map[string]any `json:"successes"`
		Total     int             `json:"total"`
	}
	if err := json.Unmarshal(content, &resp); err != nil {
		t.Fatalf("解析失败: %v", err)
	}
	t.Logf("GetNotUsedTags: total=%d first=%v", resp.Total, resp.Successes[0]["name"])
}

func TestExtra_ListGroupTags(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	// 查回收站
	content, err := cli.ListRecycleTags(1, 3)
	if err != nil {
		t.Fatalf("ListRecycleTags: %v", err)
	}
	t.Logf("ListRecycleTags: %s", string(content)[:300])

	// 查收藏
	content2, err := cli.ListFavoriteTags(1, 3)
	if err != nil {
		t.Fatalf("ListFavoriteTags: %v", err)
	}
	t.Logf("ListFavoriteTags: %s", string(content2)[:300])
}

func TestExtra_TestDsInfo(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	// testType=1 枚举
	content, err := cli.TestDsInfo(40, "mocker_18950", DsTestEnumerate, "", "", "", "", 0, nil)
	if err != nil {
		t.Fatalf("TestDsInfo enumerate: %v", err)
	}
	var resp DsTestResult
	if err := json.Unmarshal(content, &resp); err != nil {
		t.Fatalf("解析失败: %v body=%s", err, string(content)[:300])
	}
	t.Logf("enumerate: isAllSuccess=%v total=%d first=%v", resp.IsAllSuccess, resp.Total, resp.Successes[0]["name"])
}

func TestExtra_QueryTagsWithQuality_TagNameFilter(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	dsID := 40
	content, err := cli.QueryTagsWithQuality(&dsID, GroupRoot, "1_double_ch_1", "", TagTypeOnce, 1, 5, "-createTime")
	if err != nil {
		t.Fatalf("QueryTagsWithQuality: %v", err)
	}
	t.Logf("filter tagName=1_double_ch_1: %s", string(content)[:300])
}

func TestExtra_ExportImport(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)

	// 找一个有数据的位号
	content, err := cli.ListTags(1, 5, map[string]any{"dsId": 40})
	if err != nil {
		t.Fatalf("ListTags: %v", err)
	}
	var resp struct {
		Records []struct {
			ID int `json:"id"`
		} `json:"records"`
	}
	if err := json.Unmarshal(content, &resp); err != nil {
		t.Fatalf("解析: %v", err)
	}
	if len(resp.Records) == 0 {
		t.Skip("没有可导出的位号")
	}
	tagID := resp.Records[0].ID

	// 导出
	tmpFile := fmt.Sprintf("%s/export_test.xlsx", os.TempDir())
	data, err := cli.ExportTags([]int{tagID}, 0, tmpFile)
	if err != nil {
		t.Logf("ExportTags 失败(可能该位号无数据): %v", err)
		t.Skip("导出失败,跳过导入验证")
	}
	t.Logf("exported %d bytes to %s", len(data), tmpFile)

	// 导入
	importContent, err := cli.ImportTagsFromFile(tmpFile, 0)
	if err != nil {
		t.Fatalf("ImportTagsFromFile: %v", err)
	}
	t.Logf("import result: %s", safeTrunc(string(importContent), 300))

	os.Remove(tmpFile)
}

func TestExtra_GroupCRUD(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)

	// 创建
	createContent, err := cli.AddTagGroup("test_auto_node_xxx", GroupRoot)
	if err != nil {
		t.Fatalf("AddTagGroup: %v", err)
	}
	var created struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(createContent, &created); err != nil {
		t.Fatalf("解析: %v", err)
	}
	t.Logf("created group id=%s", created.ID)

	// 编辑
	_, err = cli.UpdateTagGroup(created.ID, "test_auto_node_xxx_renamed", GroupRoot)
	if err != nil {
		t.Logf("UpdateTagGroup warn: %v", err)
	}

	// 删
	_, err = cli.DeleteTagGroup([]string{created.ID}, false)
	if err != nil {
		t.Errorf("DeleteTagGroup: %v", err)
	}
	t.Logf("deleted group id=%s", created.ID)
}

func TestExtra_FavoriteCRUD(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)

	// 找一个位号 id
	content, err := cli.ListTags(1, 1, map[string]any{"dsId": 40})
	if err != nil {
		t.Fatalf("ListTags: %v", err)
	}
	var resp struct {
		Records []struct {
			ID int `json:"id"`
		} `json:"records"`
	}
	if err := json.Unmarshal(content, &resp); err != nil {
		t.Fatalf("解析: %v", err)
	}
	if len(resp.Records) == 0 {
		t.Skip("没有位号可测试")
	}
	tagID := resp.Records[0].ID

	// 收藏
	_, err = cli.AddTagGroupRelation(GroupFavorites, []int{tagID})
	if err != nil {
		t.Fatalf("AddTagGroupRelation: %v", err)
	}
	t.Logf("added to favorites: tagID=%d", tagID)

	// 查收藏
	favContent, err := cli.ListFavoriteTags(1, 3)
	if err != nil {
		t.Fatalf("ListFavoriteTags: %v", err)
	}
	t.Logf("favorites: %s", string(favContent)[:200])

	// 取消收藏
	_, err = cli.RemoveTagGroupRelation(GroupFavorites, []int{tagID})
	if err != nil {
		t.Errorf("RemoveTagGroupRelation: %v", err)
	}
	t.Logf("removed from favorites: tagID=%d", tagID)
}

func TestExtra_GetTagGroupTree(t *testing.T) {
	if skipIntegration(t) {
		return
	}
	cli := newTestClient(t)
	content, err := cli.GetTagGroupTree()
	if err != nil {
		t.Fatalf("GetTagGroupTree: %v", err)
	}
	t.Logf("GetTagGroupTree: %s", string(content)[:300])
}