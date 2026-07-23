package tptapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// ibd-data-hub-web-v2.2 位号 + 历史值管理端点
// （与 data-hub-tool/common_api.py 1:1 对齐，复用同一份 tpt-admin 登录）。

const (
	DataHubBasePath = "/ibd-data-hub-web-v2.2/api"

	// DataHubTagAdd 注册位号
	DataHubTagAdd = DataHubBasePath + "/tag-info/add"
	// DataHubTagPage 分页列位号
	DataHubTagPage = DataHubBasePath + "/tag-info/page"
	// DataHubTagBatchDeleteLogic 批量逻辑删除位号（进回收站）
	DataHubTagBatchDeleteLogic = DataHubBasePath + "/tag-info/batchDeleteLogic"
	// DataHubTagBatchDelete 批量物理删除位号（清回收站）
	DataHubTagBatchDelete = DataHubBasePath + "/tag-info/batchDelete"
	// DataHubTagGroupGet 按 groupId 查位号（回收站在 groupId=1）
	DataHubTagGroupGet = DataHubBasePath + "/tag-group/get"

	// DataHubImportTagValue 同步 JSON 导入历史值（≤10000 条）
	DataHubImportTagValue = DataHubBasePath + "/tag-value/importTagValue"
	// DataHubImportTagValueHistory 异步 Excel/ZIP 导入历史值
	DataHubImportTagValueHistory = DataHubBasePath + "/tag-value/importTagValueHistory"
	// DataHubImportCSVTagValueHistory CSV 导入历史值（已废弃）
	DataHubImportCSVTagValueHistory = DataHubBasePath + "/tag-value/importCSVTagValueHistory"
	// DataHubGetHistoryValueFromDB 查历史值（验证用）
	DataHubGetHistoryValueFromDB = DataHubBasePath + "/tag-value/getHistoryValueFromDB"
)

// 平台 dataType 枚举（实测）。
var DataTypes = map[string]int{
	"BOOLEAN": 1, "S_BYTE": 2, "BYTE": 3, "SHORT": 4, "U_SHORT": 5,
	"INT": 6, "U_INT": 7, "LONG": 8, "U_LONG": 9, "FLOAT": 10, "DOUBLE": 11,
}

// 平台 tagType 枚举。
var TagTypes = map[string]int{
	"一次位号": 1,
	"虚位号":   4,
}

// DefaultTagTypesAll 全量扫描时遍历的 tagType 集合。
// 注：get_all_tags() 默认 data 为空时平台只返回默认类，会漏掉其它 tagType 的位号。
// 共享给 GetAllTagsAllTypes。
var DefaultTagTypesAll = []int{1, 4, 0, 2, 3, 5}

// 导入响应（写操作端点专用，统一解析）。
type ImportResponse struct {
	StatusCode int            `json:"status_code"`
	Code       *string        `json:"code"`
	Msg        string         `json:"msg"`
	IsSuccess  bool           `json:"is_success"`
	Data       any            `json:"data"`
	Raw        map[string]any `json:"raw,omitempty"`
}

// parseImportResp 统一解析导入端点响应（HTTP 200 / code=00000 不等于数据落地）。
func parseImportResp(resp *http.Response, body []byte) ImportResponse {
	out := ImportResponse{StatusCode: resp.StatusCode}
	var raw map[string]any
	if err := json.Unmarshal(body, &raw); err != nil {
		out.Msg = truncate(string(body), 500)
		out.IsSuccess = resp.StatusCode == 200
		return out
	}
	out.Raw = raw
	if code, ok := raw["code"].(string); ok {
		out.Code = &code
	}
	if msg, ok := raw["msg"].(string); ok {
		out.Msg = msg
	}
	isSuccessFlag := false
	if v, ok := raw["isSuccess"].(bool); ok {
		isSuccessFlag = v
	} else if v, ok := raw["success"].(bool); ok {
		isSuccessFlag = v
	}
	codeVal := ""
	if out.Code != nil {
		codeVal = *out.Code
	}
	out.IsSuccess = resp.StatusCode == 200 && isSuccessFlag && codeVal == SuccessCode
	if d, ok := raw["data"]; ok {
		out.Data = d
	}
	return out
}

// === 位号管理 ===

// AddTag 注册一个位号。
//
// 参数：
//   - tagName:    系统位号名（也是底层位号名，默认同名）
//   - dataType:   数据类型代码 (1=BOOLEAN .. 11=DOUBLE)，默认 11=DOUBLE
//   - tagType:    位号类型 (1=一次位号, 4=虚位号)，默认 1
//   - dsID:       数据源 ID（默认 2 = "我的数据源"）
//   - groupID:    位号分组 ID，默认 "0" = Root
//   - unit:       单位
//   - onlyRead:   是否只读
//   - frequency:  采集频率（秒）
//   - needPush:   是否需要推送
//   - tagDesc:    描述，默认 "{tag_name} 描述"
//   - isVector:   是否向量
func (c *Client) AddTag(ctx context.Context, tagName string, dataType, tagType, dsID int,
	groupID, unit string, onlyRead bool, frequency int, needPush bool, tagDesc string, isVector bool) (map[string]any, error) {
	if tagDesc == "" {
		tagDesc = tagName + " 描述"
	}
	body := map[string]any{
		"data": map[string]any{
			"tagType":   tagType,
			"dsId":      dsID,
			"tagBaseName": tagName,
			"tagName":   tagName,
			"dataType":  dataType,
			"unit":      unit,
			"onlyRead":  onlyRead,
			"frequency": frequency,
			"needPush":  needPush,
			"tagDesc":   tagDesc,
			"isVector":  isVector,
			"groupId":   groupID,
		},
	}
	var out map[string]any
	if err := c.doRequest(ctx, http.MethodPost, DataHubTagAdd, body, &out, true); err != nil {
		return nil, err
	}
	return out, nil
}

// ListTags 分页列位号（MyBatis Page 结构）。
//
//   - sort: 排序字段（如 "-createTime" = createTime 降序）
//   - data: 过滤条件 dict
func (c *Client) ListTags(ctx context.Context, page, pageSize int, sort string, data map[string]any) (map[string]any, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 10
	}
	body := map[string]any{
		"data":        data,
		"requestBase": map[string]any{"page": fmt.Sprintf("%d-%d", page, pageSize), "sort": sort},
	}
	var raw map[string]any
	if err := c.doRequest(ctx, http.MethodPost, DataHubTagPage, body, &raw, false); err != nil {
		return nil, err
	}
	return raw, nil
}

// GetAllTags 自动翻页拉取所有位号，缓存到 c.datahubCache.tags。
func (c *Client) GetAllTags(ctx context.Context, pageSize int, sort string, data map[string]any) ([]map[string]any, error) {
	if pageSize < 1 {
		pageSize = 200
	}
	var all []map[string]any
	page := 1
	for {
		result, err := c.ListTags(ctx, page, pageSize, sort, data)
		if err != nil {
			return nil, err
		}
		records, _ := result["records"].([]any)
		if len(records) == 0 {
			break
		}
		for _, r := range records {
			if m, ok := r.(map[string]any); ok {
				all = append(all, m)
			}
		}
		if len(records) < pageSize {
			break
		}
		page++
	}
	c.datahubCache.setTags(all)
	return all, nil
}

// GetTagByName 通过 tagName 获取缓存的位号信息。
func (c *Client) GetTagByName(tagName string) map[string]any {
	return c.datahubCache.nameMap[tagName]
}

// GetAllTagsAllTypes 拉取全部位号，遍历所有 tagType 合并去重（按 id）。
//
// 避免 get_all_tags() 默认 data 为空时只返回默认类、漏掉其它 tagType 的位号。
func (c *Client) GetAllTagsAllTypes(ctx context.Context, pageSize int, tagTypes []int) ([]map[string]any, error) {
	if pageSize < 1 {
		pageSize = 2000
	}
	if len(tagTypes) == 0 {
		tagTypes = DefaultTagTypesAll
	}
	seen := make(map[float64]struct{})
	var all []map[string]any
	for _, tt := range tagTypes {
		records, err := c.GetAllTags(ctx, pageSize, "-createTime", map[string]any{"tagType": tt})
		if err != nil {
			// 静默跳过：单 tagType 拉不到不影响整体
			continue
		}
		for _, t := range records {
			id, ok := t["id"].(float64)
			if !ok {
				continue
			}
			if _, dup := seen[id]; dup {
				continue
			}
			seen[id] = struct{}{}
			all = append(all, t)
		}
	}
	c.datahubCache.setTags(all)
	return all, nil
}

// DeleteTags 批量逻辑删除位号（DELETE /api/tag-info/batchDeleteLogic，软删→回收站）。
//
// ids: int / []int。
func (c *Client) DeleteTags(ctx context.Context, ids []int) (ImportResponse, error) {
	if len(ids) == 0 {
		return ImportResponse{}, fmt.Errorf("ids 不能为空")
	}
	intIDs := make([]int, len(ids))
	for i, v := range ids {
		intIDs[i] = v
	}
	body := map[string]any{"data": map[string]any{"ids": intIDs}}
	return c.deleteImport(ctx, DataHubTagBatchDeleteLogic, body)
}

// DeleteTagsByName 按位号名批量删除。内部用 name_map 查 id 再调 DeleteTags。
//
// 返回 {"deleted": [...], "missing": [...], "result": ImportResponse}。
func (c *Client) DeleteTagsByName(ctx context.Context, tagNames []string, refresh bool) (map[string]any, error) {
	if refresh || len(c.datahubCache.nameMap) == 0 {
		if _, err := c.GetAllTags(ctx, 200, "-createTime", nil); err != nil {
			return nil, err
		}
	}
	deleted := []string{}
	missing := []string{}
	ids := []int{}
	for _, name := range tagNames {
		if t, ok := c.datahubCache.nameMap[name]; ok {
			if id, ok := t["id"].(float64); ok {
				ids = append(ids, int(id))
				deleted = append(deleted, name)
				continue
			}
		}
		missing = append(missing, name)
	}
	result := ImportResponse{}
	if len(ids) > 0 {
		r, err := c.DeleteTags(ctx, ids)
		if err != nil {
			return nil, err
		}
		result = r
	}
	return map[string]any{
		"deleted": deleted,
		"missing": missing,
		"result":  result,
	}, nil
}

// === 回收站 ===

// ListRecycleTags 查回收站位号（POST /api/tag-group/get），单页。
//
// 平台回收站用 groupId="1" 表示（实测）。
func (c *Client) ListRecycleTags(ctx context.Context, page, pageSize int, groupID string, tagType int, sort string) (map[string]any, error) {
	body := map[string]any{
		"data": map[string]any{
			"groupId":   groupID,
			"tagType":   tagType,
			"sortField": sort,
			"sortType":  1,
		},
		"requestBase": map[string]any{"page": fmt.Sprintf("%d-%d", page, pageSize), "sort": sort},
	}
	var raw map[string]any
	if err := c.doRequest(ctx, http.MethodPost, DataHubTagGroupGet, body, &raw, false); err != nil {
		return nil, err
	}
	return raw, nil
}

// GetAllRecycleTags 翻页拉取回收站全部位号。
//
// 注意：tag-group/get 的响应结构是 content.tagInfoList.records（位号藏在分组对象的 tagInfoList 里）。
//
// onPage(page, accumulated) 是可选的进度回调。
func (c *Client) GetAllRecycleTags(ctx context.Context, pageSize int, groupID string, tagType int, onPage func(page, accumulated int)) ([]map[string]any, error) {
	if pageSize < 1 {
		pageSize = 100
	}
	var all []map[string]any
	page := 1
	for {
		result, err := c.ListRecycleTags(ctx, page, pageSize, groupID, tagType, "-createTime")
		if err != nil {
			return nil, err
		}
		info, _ := result["tagInfoList"].(map[string]any)
		records, _ := info["records"].([]any)
		if len(records) == 0 {
			break
		}
		for _, r := range records {
			if m, ok := r.(map[string]any); ok {
				all = append(all, m)
			}
		}
		if onPage != nil {
			onPage(page, len(all))
		}
		if len(records) < pageSize {
			break
		}
		page++
	}
	return all, nil
}

// DeleteTagsPhysical 物理删除位号（DELETE /api/tag-info/batchDelete）— 清回收站，不可恢复。
func (c *Client) DeleteTagsPhysical(ctx context.Context, ids []int) (ImportResponse, error) {
	if len(ids) == 0 {
		return ImportResponse{}, fmt.Errorf("ids 不能为空")
	}
	intIDs := make([]int, len(ids))
	for i, v := range ids {
		intIDs[i] = v
	}
	body := map[string]any{"data": map[string]any{"ids": intIDs}}
	return c.deleteImport(ctx, DataHubTagBatchDelete, body)
}

// === 历史值导入 ===

// ImportTagValue 同步 JSON 批量导入历史值（一次最多 10000 条）。
//
// data: list[dict]，每个 dict 至少含 tagName/tagValue，可选 quality/tagTime/appTime。
// 时间格式 "yyyy-MM-dd HH:mm:ss"（空格分隔）。
// dsID: 数据源 ID，nil = 默认时序库。
func (c *Client) ImportTagValue(ctx context.Context, data []map[string]any, dsID *int) (ImportResponse, error) {
	body := map[string]any{"data": data}
	if dsID != nil {
		body["dsId"] = *dsID
	}
	raw, err := c.postImport(ctx, DataHubImportTagValue, body, nil, nil)
	if err != nil {
		return ImportResponse{}, err
	}
	return raw, nil
}

// ImportTagValueHistory 异步 Excel / ZIP 导入历史值。
//
// Excel A1 四段逗号："startTime,endTime,frequency,corn"
// A2 空，A3 起：时间, 位号1值, 位号2值, ...
func (c *Client) ImportTagValueHistory(ctx context.Context, filePath string, dsID *int,
	startTime, endTime, cron string, frequency *int) (ImportResponse, error) {
	ext := strings.ToLower(filepath.Ext(filePath))
	mimeMap := map[string]string{
		".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
		".xls":  "application/vnd.ms-excel",
		".zip":  "application/zip",
	}
	mime := mimeMap[ext]
	if mime == "" {
		mime = "application/octet-stream"
	}

	form := map[string]string{}
	if dsID != nil && *dsID != 0 {
		form["dsId"] = fmt.Sprintf("%d", *dsID)
	}
	if startTime != "" {
		form["startTime"] = startTime
	}
	if endTime != "" {
		form["endTime"] = endTime
	}
	if frequency != nil {
		form["frequency"] = fmt.Sprintf("%d", *frequency)
	}
	if cron != "" {
		form["corn"] = cron // API 拼写是 corn 不是 cron
	}

	return c.postImport(ctx, DataHubImportTagValueHistory, nil, form, &fileUpload{
		FieldName: "file",
		FilePath:  filePath,
		Mime:      mime,
	})
}

// ImportCSVTagValueHistory CSV 导入历史值（已废弃）。
func (c *Client) ImportCSVTagValueHistory(ctx context.Context, filePath string) (ImportResponse, error) {
	return c.postImport(ctx, DataHubImportCSVTagValueHistory, nil, nil, &fileUpload{
		FieldName: "file",
		FilePath:  filePath,
		Mime:      "text/csv",
	})
}

// GetHistoryValue 查位号历史值（单页）。
//
// tagNames: list[str]
// 时间格式 "yyyy-MM-dd HH:mm:ss"
// 返回 {tagName: {"pageNum", "pageSize", "totalPage", "total", "list": [...]}}
func (c *Client) GetHistoryValue(ctx context.Context, tagNames []string, begTime, endTime string,
	isSource, numberToString bool, page, pageSize int, sort string) (map[string]any, error) {
	body := map[string]any{
		"data": map[string]any{
			"tagNames":        tagNames,
			"begTime":         begTime,
			"endTime":         endTime,
			"isSource":        isSource,
			"numberToString":  numberToString,
		},
		"requestBase": map[string]any{"page": fmt.Sprintf("%d-%d", page, pageSize), "sort": sort},
	}
	var raw map[string]any
	if err := c.doRequest(ctx, http.MethodPost, DataHubGetHistoryValueFromDB, body, &raw, false); err != nil {
		return nil, err
	}
	return raw, nil
}

// GetAllHistory 翻页拉取所有历史值，返回 {tagName: [data points]}。
//
// 每个 tag 的所有数据点（按 API 返回顺序，固定最新在前），自动按 total 翻页。
func (c *Client) GetAllHistory(ctx context.Context, tagNames []string, begTime, endTime string,
	isSource, numberToString bool, pageSize int) (map[string][]any, error) {
	if pageSize < 1 {
		pageSize = 2000
	}
	result := make(map[string][]any, len(tagNames))
	for _, name := range tagNames {
		result[name] = []any{}
	}
	page := 1
	for {
		pageData, err := c.GetHistoryValue(ctx, tagNames, begTime, endTime, isSource, numberToString, page, pageSize, "-appTime")
		if err != nil {
			return nil, err
		}
		anyRemaining := false
		for tagName, infoAny := range pageData {
			info, ok := infoAny.(map[string]any)
			if !ok {
				continue
			}
			lst, _ := info["list"].([]any)
			if existing, ok := result[tagName]; ok {
				existing = append(existing, lst...)
				result[tagName] = existing
			}
			totalF, _ := info["total"].(float64)
			if float64(len(result[tagName])) < totalF {
				anyRemaining = true
			}
		}
		if !anyRemaining {
			break
		}
		page++
	}
	return result, nil
}

// === 内部：DELETE 写操作 + 文件上传 ===

type fileUpload struct {
	FieldName string
	FilePath  string
	Mime      string
}

func (c *Client) deleteImport(ctx context.Context, path string, body any) (ImportResponse, error) {
	u := c.baseURL + "/" + strings.TrimLeft(path, "/")
	jsonBody, err := json.Marshal(body)
	if err != nil {
		return ImportResponse{}, fmt.Errorf("marshal: %w", err)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete, u, bytes.NewReader(jsonBody))
	if err != nil {
		return ImportResponse{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if c.tenantID != "" && c.IsHTTPS() {
		req.Header.Set("Cookie", fmt.Sprintf("TptSaasUserTenantryId=%s; tenant-id=%s", c.tenantID, c.tenantID))
	}
	resp, err := c.hc.Do(req)
	if err != nil {
		return ImportResponse{}, fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return ImportResponse{}, fmt.Errorf("read body: %w", err)
	}
	return parseImportResp(resp, raw), nil
}

func (c *Client) postImport(ctx context.Context, path string, jsonBody any, form map[string]string, upload *fileUpload) (ImportResponse, error) {
	u := c.baseURL + "/" + strings.TrimLeft(path, "/")

	var (
		bodyBuf  bytes.Buffer
		writer   *multipart.Writer
		isMulti  bool
	)
	if upload != nil || len(form) > 0 {
		writer = multipart.NewWriter(&bodyBuf)
		isMulti = true
		if upload != nil {
			f, err := os.Open(upload.FilePath)
			if err != nil {
				return ImportResponse{}, fmt.Errorf("open file: %w", err)
			}
			defer f.Close()
			part, err := writer.CreateFormFile(upload.FieldName, filepath.Base(upload.FilePath))
			if err != nil {
				return ImportResponse{}, fmt.Errorf("create form file: %w", err)
			}
			if _, err := io.Copy(part, f); err != nil {
				return ImportResponse{}, fmt.Errorf("copy file: %w", err)
			}
		}
		for k, v := range form {
			if err := writer.WriteField(k, v); err != nil {
				return ImportResponse{}, fmt.Errorf("write field %s: %w", k, err)
			}
		}
		if err := writer.Close(); err != nil {
			return ImportResponse{}, fmt.Errorf("close multipart: %w", err)
		}
	} else if jsonBody != nil {
		b, err := json.Marshal(jsonBody)
		if err != nil {
			return ImportResponse{}, fmt.Errorf("marshal: %w", err)
		}
		bodyBuf.Write(b)
	}

	var req *http.Request
	var err error
	if isMulti {
		req, err = http.NewRequestWithContext(ctx, http.MethodPost, u, &bodyBuf)
		if err != nil {
			return ImportResponse{}, err
		}
		req.Header.Set("Content-Type", writer.FormDataContentType())
	} else {
		req, err = http.NewRequestWithContext(ctx, http.MethodPost, u, &bodyBuf)
		if err != nil {
			return ImportResponse{}, err
		}
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if c.tenantID != "" && c.IsHTTPS() {
		req.Header.Set("Cookie", fmt.Sprintf("TptSaasUserTenantryId=%s; tenant-id=%s", c.tenantID, c.tenantID))
	}

	resp, err := c.hc.Do(req)
	if err != nil {
		return ImportResponse{}, fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return ImportResponse{}, fmt.Errorf("read body: %w", err)
	}
	return parseImportResp(resp, raw), nil
}
