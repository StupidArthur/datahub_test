// datahub_extra.go - datahub 扩展端点封装(对齐 tpt_api/datahub.py 新增接口)。
//
// 与 datahub.go 的差异:
//   - datahub.go 保留原有 UA-1/UA-3 测试用的核心接口
//   - 本文件按需新增 tpt_api 已封装的接口
package subject

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

// pageBaseSorted 构造 MyBatis 分页 requestBase,可指定 sort。
func pageBaseSorted(page, size int, sort string) map[string]any {
	if sort == "" {
		sort = "-createTime"
	}
	return map[string]any{
		"page": fmt.Sprintf("%d-%d", page, size),
		"sort": sort,
	}
}

// f64p 取 float64 指针(用于 AddTagParams 限值字段)。
func f64p(v float64) *float64 { return &v }

// ===================== 位号值 =====================

// GetHistoryValue 取位号历史值(POST /tag-value/getHistoryValue,IPage 分页)。
// 参数: tagNames/begTime/endTime/interval/isSecond/isSource/offset/option。
// 返回 IPage 结构(records/total/current/size/pages)。
// 注意:起始与结束时间间隔不能超过一个月。
func (c *TptClient) GetHistoryValue(tagNames []string, begTime, endTime string,
	interval int, isSecond, isSource bool, offset, option int,
	page, pageSize int, sort string) (json.RawMessage, error) {
	if sort == "" {
		sort = "-appTime"
	}
	if page == 0 {
		page = 1
	}
	if pageSize == 0 {
		pageSize = 10
	}
	body := map[string]any{
		"data": map[string]any{
			"tagNames": tagNames,
			"begTime":  begTime,
			"endTime":  endTime,
			"interval": interval,
			"isSecond": isSecond,
			"isSource": isSource,
			"offset":   offset,
			"option":   option,
		},
		"requestBase": map[string]any{
			"page": fmt.Sprintf("%d-%d", page, pageSize),
			"sort": sort,
		},
	}
	return c.request("POST", epGetHistoryValue, body, false)
}

// GetHistoryValueFromDB 取位号历史值(POST /tag-value/getHistoryValueFromDB,验证用旧接口)。
func (c *TptClient) GetHistoryValueFromDB(tagNames []string, begTime, endTime string,
	isSource bool, numberToString bool, page, pageSize int, sort string) (json.RawMessage, error) {
	if sort == "" {
		sort = "-appTime"
	}
	if page == 0 {
		page = 1
	}
	if pageSize == 0 {
		pageSize = 100
	}
	body := map[string]any{
		"data": map[string]any{
			"tagNames":       tagNames,
			"begTime":        begTime,
			"endTime":        endTime,
			"isSource":       isSource,
			"numberToString": numberToString,
		},
		"requestBase": map[string]any{
			"page": fmt.Sprintf("%d-%d", page, pageSize),
			"sort": sort,
		},
	}
	return c.request("POST", epGetHistoryValueFromDB, body, false)
}

// CollectTagValue 触发采集任务(POST /tag-value/collectTagValue)。
// esDTO: {taskId, jobType};groupID: 位号组 id。
func (c *TptClient) CollectTagValue(esDTO map[string]any, groupID int, tenantID string) error {
	body := map[string]any{
		"data": map[string]any{
			"esDTO":    esDTO,
			"groupId":  groupID,
			"tenantId": tenantID,
		},
	}
	_, err := c.request("POST", epCollectTagValue, body, false)
	return err
}

// ImportTagValue 同步导入 JSON 历史值(POST /tag-value/importTagValue)。
func (c *TptClient) ImportTagValue(body map[string]any) error {
	_, err := c.request("POST", epImportTagValue, body, false)
	return err
}

// ===================== 位号(扩展) =====================

// TagRecordWithQuality 含实时值的位号记录(queryWithQuality 返回)。
type TagRecordWithQuality struct {
	ID           int             `json:"id"`
	TagName      string          `json:"tagName"`
	TagBaseName  string          `json:"tagBaseName"`
	TagDesc      string          `json:"tagDesc"`
	TagType      int             `json:"tagType"`
	DsID         int             `json:"dsId"`
	DsName       string          `json:"dsName"`
	DataType     int             `json:"dataType"`
	DataTypeName string          `json:"dataTypeName"`
	BaseDataType int             `json:"baseDataType"`
	TagValue     json.RawMessage `json:"tagValue"`
	TagTime      string          `json:"tagTime"`
	Quality      int             `json:"quality"`
	CacheNum     int             `json:"cacheNum"`
	Frequency    int             `json:"frequency"`
	IsCollect    bool            `json:"isCollect"`
	IsVector     bool            `json:"isVector"`
	NeedPush     bool            `json:"needPush"`
	GroupName    string          `json:"groupName"`
}

// QueryTagsWithQuality 查位号(带实时值+质量码)(POST /tag-group/queryWithQuality)。
// groupID 必填("0"=Root);支持 tagName/tagBaseName 模糊过滤。
func (c *TptClient) QueryTagsWithQuality(dsID *int, groupID string, tagName, tagBaseName string,
	tagType, page, pageSize int, sort string) (json.RawMessage, error) {
	if sort == "" {
		sort = "-createTime"
	}
	data := map[string]any{
		"tagName":     tagName,
		"tagBaseName": tagBaseName,
		"tagType":     tagType,
		"sortField":   sort,
		"sortType":    1,
		"groupId":     groupID,
	}
	if dsID != nil {
		data["dsId"] = *dsID
	}
	body := map[string]any{
		"data":        data,
		"requestBase": pageBaseSorted(page, pageSize, sort),
	}
	return c.request("POST", epTagGroupQueryWithQuality, body, false)
}

// ListTags 分页列位号(POST /tag-info/page)。data 可传过滤条件如 {dsId, tagType, tagName}。
func (c *TptClient) ListTags(page, pageSize int, data map[string]any) (json.RawMessage, error) {
	if page == 0 {
		page = 1
	}
	if pageSize == 0 {
		pageSize = 10
	}
	if data == nil {
		data = map[string]any{}
	}
	body := map[string]any{
		"data":        data,
		"requestBase": pageBaseSorted(page, pageSize, ""),
	}
	return c.request("POST", epTagPage, body, false)
}

// GetTagByName 按位号名查(POST /tag-info/page 带 tagName 过滤)。
func (c *TptClient) GetTagByName(tagName string) (json.RawMessage, error) {
	return c.ListTags(1, 10, map[string]any{"tagName": tagName})
}

// GetAllTags 翻页拉全部位号(对齐 datahub.get_all_tags)。
func (c *TptClient) GetAllTags(pageSize int, sort string, data map[string]any) (json.RawMessage, error) {
	if pageSize == 0 {
		pageSize = 200
	}
	if data == nil {
		data = map[string]any{}
	}
	var all []json.RawMessage
	page := 1
	for {
		body := map[string]any{
			"data":        data,
			"requestBase": pageBaseSorted(page, pageSize, sort),
		}
		content, err := c.request("POST", epTagPage, body, false)
		if err != nil {
			return nil, err
		}
		var resp struct {
			Records []json.RawMessage `json:"records"`
			Total   int               `json:"total"`
		}
		if err := json.Unmarshal(content, &resp); err != nil {
			return nil, err
		}
		if len(resp.Records) == 0 {
			break
		}
		all = append(all, resp.Records...)
		if len(resp.Records) < pageSize {
			break
		}
		page++
	}
	out, _ := json.Marshal(all)
	return out, nil
}

// DeleteTagsByName 按位号名删(对齐 datahub.delete_tags_by_name)。
func (c *TptClient) DeleteTagsByName(names []string) (json.RawMessage, error) {
	body := map[string]any{"data": map[string]any{"tagNames": names}}
	return c.request("DELETE", epTagBatchDeleteLogic, body, false)
}

// BatchUpdateTags 批量修改位号参数(POST /tag-info/batchUpdate)。
// 只能改:groupId/unit/frequency。
func (c *TptClient) BatchUpdateTags(tagIDs []int, groupID *string, unit *string, frequency *int) (json.RawMessage, error) {
	data := map[string]any{"tagIds": tagIDs}
	if groupID != nil {
		data["groupId"] = *groupID
	}
	if unit != nil {
		data["unit"] = *unit
	}
	if frequency != nil {
		data["frequency"] = *frequency
	}
	body := map[string]any{"data": data}
	return c.request("POST", epTagBatchUpdate, body, false)
}

// UpdateTag 编辑单个位号(PUT /tag-info/update)。
// 全量更新:tagName/dataType 必填;未传可选字段会被重置默认值。
func (c *TptClient) UpdateTag(tagID int, tagName string, dataType int,
	tagType int, dsID int, groupID, unit string, onlyRead bool,
	frequency int, needPush bool, tagDesc, tagBaseName string,
	hiEU, loEU, limitUp, limitUpUp, limitUpUpUp *float64,
	limitDown, limitDownDown, limitDownDownDown *float64) (json.RawMessage, error) {
	if tagType == 0 {
		tagType = TagTypeOnce
	}
	if groupID == "" {
		groupID = GroupRoot
	}
	if frequency == 0 {
		frequency = 10
	}
	if tagDesc == "" {
		tagDesc = tagName + " 描述"
	}
	if tagBaseName == "" {
		tagBaseName = tagName
	}
	data := map[string]any{
		"id":          tagID,
		"tagName":     tagName,
		"dataType":    dataType,
		"tagType":     tagType,
		"dsId":        dsID,
		"groupId":     groupID,
		"unit":        unit,
		"onlyRead":    onlyRead,
		"frequency":   frequency,
		"needPush":    needPush,
		"tagDesc":     tagDesc,
		"isVector":    true,
		"tagBaseName": tagBaseName,
	}
	if hiEU != nil {
		data["hiEU"] = *hiEU
	}
	if loEU != nil {
		data["loEU"] = *loEU
	}
	if limitUp != nil {
		data["limitUp"] = *limitUp
	}
	if limitUpUp != nil {
		data["limitUpUp"] = *limitUpUp
	}
	if limitUpUpUp != nil {
		data["limitUpUpUp"] = *limitUpUpUp
	}
	if limitDown != nil {
		data["limitDown"] = *limitDown
	}
	if limitDownDown != nil {
		data["limitDownDown"] = *limitDownDown
	}
	if limitDownDownDown != nil {
		data["limitDownDownDown"] = *limitDownDownDown
	}
	body := map[string]any{"data": data}
	return c.request("PUT", epTagUpdate, body, false)
}

// ExportTags 导出位号为 Excel(POST /tag-info/export)。
// 返回 raw bytes(Excel 文件);savePath 设了就存文件。
func (c *TptClient) ExportTags(tagIDs []int, interval int, savePath string) ([]byte, error) {
	if interval == 0 {
		interval = 0
	}
	idStrs := make([]string, len(tagIDs))
	for i, id := range tagIDs {
		idStrs[i] = fmt.Sprintf("%d", id)
	}
	body := map[string]any{
		"data": map[string]any{
			"id_in":    joinStrings(idStrs, ","),
			"interval": interval,
		},
		"requestBase": pageBaseSorted(0, 0, "-createTime"),
	}
	content, err := c.downloadRequest("POST", epTagExport, body, false)
	if err != nil {
		return nil, err
	}
	if savePath != "" {
		if err := writeFile(savePath, content); err != nil {
			return content, err
		}
	}
	return content, nil
}

// ImportTagsFromFile 从 Excel 文件导入位号(POST /tag-info/importTagInfoStream)。
// conflictStrategy: 0=跳过,1=覆盖。
func (c *TptClient) ImportTagsFromFile(filePath string, conflictStrategy int) (json.RawMessage, error) {
	content, err := readFile(filePath)
	if err != nil {
		return nil, err
	}
	filename := baseName(filePath)
	var b bytes.Buffer
	boundary := "----opencodeBoundary7f3a"
	w := newMultipartWriter(&b, boundary)
	w.writeField("conflictStrategy", fmt.Sprintf("%d", conflictStrategy))
	w.writeFile("file", filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", content)
	w.close()

	url := c.baseURL + "/" + epTagImportStream
	req, err := http.NewRequest("POST", url, &b)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "multipart/form-data; boundary="+boundary)
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("http %d: %s", resp.StatusCode, truncate(string(data), 200))
	}
	var env struct {
		Code    string          `json:"code"`
		Msg     string          `json:"msg"`
		Content json.RawMessage `json:"content"`
	}
	if err := json.Unmarshal(data, &env); err != nil {
		return nil, fmt.Errorf("响应非 JSON: %s", truncate(string(data), 200))
	}
	if env.Code != successCode {
		return nil, &TptAPIError{Code: env.Code, Msg: env.Msg}
	}
	if len(env.Content) > 0 && string(env.Content) != "null" {
		return env.Content, nil
	}
	return data, nil
}

// GetNotUsedTags 查数据源未导入的位号(POST /tag-info/getNotUsedBaseTagInfoContinue)。
// 支持 continueID 游标分页;实测导入后仍可能返回已导入的位号(可能有缓存延迟)。
func (c *TptClient) GetNotUsedTags(dsID int, tagName, continueID string,
	page, pageSize int, sort string) (json.RawMessage, error) {
	if sort == "" {
		sort = "tagName"
	}
	if pageSize == 0 {
		pageSize = 1000
	}
	body := map[string]any{
		"data": map[string]any{
			"dsId":       dsID,
			"tagName":    tagName,
			"continueID": continueID,
		},
		"requestBase": pageBaseSorted(page, pageSize, sort),
	}
	return c.request("POST", epTagGetNotUsed, body, false)
}

// BatchAddTags 从数据源批量导入位号(POST /tag-info/batchAdd)。
// tagInfos 每项含 groupId/dsId/tagDesc/dataType/tagType/baseDataType/tagBaseName/tagName/frequency/isVector。
// conflictStrategy: 0=跳过,1=覆盖。
func (c *TptClient) BatchAddTags(tagInfos []map[string]any, conflictStrategy int) (json.RawMessage, error) {
	if conflictStrategy == 0 {
		conflictStrategy = 1
	}
	body := map[string]any{
		"data": map[string]any{
			"tagInfos":         tagInfos,
			"conflictStrategy": conflictStrategy,
		},
	}
	return c.request("POST", epTagBatchAdd, body, false)
}

// ===================== 位号分组 =====================

// TagGroupNode 分组节点。
type TagGroupNode struct {
	ID         string          `json:"id"`
	GroupName  string          `json:"groupName"`
	ParentID   string          `json:"parentId"`
	DisplayIdx int             `json:"displayIndex"`
	CreateBy   string          `json:"createBy"`
	UpdateBy   string          `json:"updateBy"`
	CreateTime string          `json:"createTime"`
	UpdateTime string          `json:"updateTime"`
	Children   []TagGroupNode  `json:"tagGroupList"`
}

// GetTagGroupTree 获取分组节点树(POST /tag-group/groupTree)。
func (c *TptClient) GetTagGroupTree() (json.RawMessage, error) {
	return c.request("POST", epTagGroupTree, bodyNull(), false)
}

// AddTagGroup 创建分组节点(POST /tag-group/add)。
func (c *TptClient) AddTagGroup(groupName, parentID string) (json.RawMessage, error) {
	if parentID == "" {
		parentID = GroupRoot
	}
	body := map[string]any{
		"data": map[string]any{
			"parentId":  parentID,
			"groupName": groupName,
		},
	}
	return c.request("POST", epTagGroupAdd, body, false)
}

// UpdateTagGroup 编辑分组节点(PUT /tag-group/update)。可改名或改父节点(移动)。
func (c *TptClient) UpdateTagGroup(groupID, groupName, parentID string) (json.RawMessage, error) {
	if parentID == "" {
		parentID = GroupRoot
	}
	body := map[string]any{
		"data": map[string]any{
			"id":        groupID,
			"parentId":  parentID,
			"groupName": groupName,
		},
	}
	return c.request("PUT", epTagGroupUpdate, body, false)
}

// DeleteTagGroup 删除分组节点(DELETE /tag-group/batchDelete)。
// isForce: true=同时删除节点下所有位号,false=只删节点位号保留。
func (c *TptClient) DeleteTagGroup(groupIDs []string, isForce bool) (json.RawMessage, error) {
	body := map[string]any{
		"data": map[string]any{
			"groupIds": groupIDs,
			"isForce":  isForce,
		},
	}
	return c.request("DELETE", epTagGroupBatchDelete, body, false)
}

// AddTagGroupRelation 收藏位号(POST /tag-group/batchAddRelation)。
func (c *TptClient) AddTagGroupRelation(groupID string, tagIDs []int) (json.RawMessage, error) {
	body := map[string]any{
		"data": map[string]any{
			groupID: tagIDs,
		},
	}
	return c.request("POST", epTagGroupBatchAddRelation, body, false)
}

// RemoveTagGroupRelation 从回收站恢复位号 / 取消收藏(DELETE /tag-group/batchDelRelation)。
// 同一端点兼做两个用途:
//   - groupID="1" + 回收站位号 ID 列表 = 恢复位号到 Root
//   - groupID="2" + 收藏位号 ID 列表 = 取消收藏
// 实测返回 false 但操作实际生效,以 ListRecycleTags / ListFavoriteTags 确认为准。
func (c *TptClient) RemoveTagGroupRelation(groupID string, tagIDs []int) (json.RawMessage, error) {
	body := map[string]any{
		"data": map[string]any{
			groupID: tagIDs,
		},
	}
	return c.request("DELETE", epTagGroupBatchDelRelation, body, false)
}

// ListGroupTags 通用:按 groupId 查某分组下的位号(POST /tag-group/get)。
// groupID: "0"=Root, "1"=Recycle, "2"=Favorites。
// 返回 group 对象,其 tagInfoList.records[] 含位号。
func (c *TptClient) ListGroupTags(groupID, tagName string, tagType, page, pageSize int, sort string) (json.RawMessage, error) {
	if sort == "" {
		sort = "-createTime"
	}
	if pageSize == 0 {
		pageSize = 100
	}
	if tagType == 0 {
		tagType = TagTypeOnce
	}
	body := map[string]any{
		"data": map[string]any{
			"groupId":   groupID,
			"tagType":   tagType,
			"sortField": sort,
			"sortType":  1,
		},
		"requestBase": pageBaseSorted(page, pageSize, sort),
	}
	if tagName != "" {
		body["data"].(map[string]any)["tagName"] = tagName
	}
	return c.request("POST", epTagGroupGet, body, false)
}

// ListRecycleTags 查回收站位号(groupId="1")。
func (c *TptClient) ListRecycleTags(page, pageSize int) (json.RawMessage, error) {
	return c.ListGroupTags(GroupRecycle, "", TagTypeOnce, page, pageSize, "-createTime")
}

// ListFavoriteTags 查收藏位号(groupId="2")。
func (c *TptClient) ListFavoriteTags(page, pageSize int) (json.RawMessage, error) {
	return c.ListGroupTags(GroupFavorites, "", TagTypeOnce, page, pageSize, "-createTime")
}

// ===================== 数据源扩展 =====================

// DsTestResult 数据源测试(ds-info/test)返回的统一结构。
type DsTestResult struct {
	SuccessTagNames []string                     `json:"successTagNames"`
	Successes       []map[string]any             `json:"successes"`
	FailTagNames    []string                     `json:"failTagNames"`
	FailMsg         map[string]string           `json:"failMsg"`
	HistoryValueMap map[string]any               `json:"historyValueMap"`
	IsAllSuccess    bool                        `json:"isAllSuccess"`
	Total           int                         `json:"total"`
	PageNum         int                         `json:"pageNum"`
	PageSize        int                         `json:"pageSize"`
	TotalPage       int                         `json:"totalPage"`
	ContinueID      string                      `json:"continueID"`
}

// TestDsInfo 数据源测试(POST /ds-info/test)。
// testType: 1=枚举位号 2=读RT(源端) 3=读RT(库) 4=历史值 5=写值。
func (c *TptClient) TestDsInfo(dsID int, dsName string, testType int,
	tagName, tagValue, beginTime, endTime string,
	interval int, dsExtInfo map[string]any) (json.RawMessage, error) {
	data := map[string]any{
		"dsId":       dsID,
		"dsName":     dsName,
		"testType":   testType,
		"tagValue":   tagValue,
		"timeStamp":  "",
		"dsExtInfo":  dsExtInfo,
		"beginTime":  beginTime,
		"endTime":    endTime,
		"interval":   interval,
	}
	if tagName != "" {
		data["tagName"] = tagName
	}
	body := map[string]any{"data": data}
	return c.request("POST", epDsInfoTest, body, false)
}

// GetDsInfoByName 按名查数据源(POST /ds-info/page 带 dsName 过滤)。
func (c *TptClient) GetDsInfoByName(name string) ([]DsInfo, error) {
	body := map[string]any{
		"data":        map[string]any{"dsName": name},
		"requestBase": pageBaseSorted(1, 10, ""),
	}
	content, err := c.request("POST", epDsInfoPage, body, false)
	if err != nil {
		return nil, err
	}
	var resp struct {
		Records []DsInfo `json:"records"`
	}
	if err := json.Unmarshal(content, &resp); err != nil {
		return nil, fmt.Errorf("ds-info/page 解析失败: %w", err)
	}
	return resp.Records, nil
}

// GetDsInfoByID 按 ID 查数据源(POST /ds-info/page 带 id 过滤)。
func (c *TptClient) GetDsInfoByID(id int) (*DsInfo, error) {
	body := map[string]any{
		"data":        map[string]any{"id": id},
		"requestBase": pageBaseSorted(1, 10, ""),
	}
	content, err := c.request("POST", epDsInfoPage, body, false)
	if err != nil {
		return nil, err
	}
	var resp struct {
		Records []DsInfo `json:"records"`
	}
	if err := json.Unmarshal(content, &resp); err != nil {
		return nil, fmt.Errorf("ds-info/page 解析失败: %w", err)
	}
	if len(resp.Records) == 0 {
		return nil, fmt.Errorf("数据源 id=%d 不存在", id)
	}
	d := resp.Records[0]
	return &d, nil
}