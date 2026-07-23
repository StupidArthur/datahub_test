// datahub.go - datahub HTTP 端点封装(对齐 tpt_api/datahub.py),挂在 *TptClient 上。
//
// 端点契约(body 结构 / wrap 机制 / 返回字段)逐个对齐 datahub.py:
//   - add_tag:            body={data:{...}},           wrap=false
//   - tag-info/page:      body={data,requestBase},      wrap=false,返回 records
//   - ds-info/page:       body={data,requestBase},      wrap=false,返回 records
//   - ds-info/add:        body={data:{...}},            wrap=false,返回新建记录含 id
//   - getRTValue:         body={isFromDB,tagNames,...}, wrap=true, 返回 list
//   - writeTagValues:     body={values,...},            wrap=true
//   - batchDeleteLogic:   DELETE body={data:{ids}},     wrap=false
//   - batchDelete:        DELETE body={data:{ids}},     wrap=false
package subject

import (
	"encoding/json"
	"fmt"
)

// defaultTagTypesAll 全量扫描的 tagType 集合(对齐 types.DefaultTagTypesAll)。
// get_all_tags 默认空 data 会漏其它 tagType,故逐个遍历合并。
var defaultTagTypesAll = []int{1, 4, 0, 2, 3, 5}

// pageBase 构造 MyBatis 分页 requestBase(page 格式 "page-size",对齐 python)。
func pageBase(page, size int) map[string]any {
	return map[string]any{
		"page": fmt.Sprintf("%d-%d", page, size),
		"sort": "-createTime",
	}
}

// AddTag 注册一个位号(对齐 datahub.add_tag)。目前仅支持一次位号;二次/虚位号待补。
func (c *TptClient) AddTag(p AddTagParams) error {
	if p.TagType == 0 {
		p.TagType = TagTypeOnce
	}
	if p.GroupID == "" {
		p.GroupID = GroupRoot
	}
	if p.Frequency == 0 {
		p.Frequency = 10
	}
	if p.TagDesc == "" {
		p.TagDesc = p.TagName + " 描述"
	}
	if p.TagBaseName == "" {
		p.TagBaseName = p.TagName
	}
	data := map[string]any{
		"tagType":     p.TagType,
		"dsId":        p.DsID,
		"tagBaseName": p.TagBaseName,
		"tagName":     p.TagName,
		"dataType":    p.DataType,
		"unit":        p.Unit,
		"onlyRead":    p.OnlyRead,
		"frequency":   p.Frequency,
		"needPush":    true,
		"tagDesc":     p.TagDesc,
		"isVector":    true,
		"groupId":     p.GroupID,
	}
	if p.HiEU != nil {
		data["hiEU"] = *p.HiEU
	}
	if p.LoEU != nil {
		data["loEU"] = *p.LoEU
	}
	if p.LimitUp != nil {
		data["limitUp"] = *p.LimitUp
	}
	if p.LimitUpUp != nil {
		data["limitUpUp"] = *p.LimitUpUp
	}
	if p.LimitUpUpUp != nil {
		data["limitUpUpUp"] = *p.LimitUpUpUp
	}
	if p.LimitDown != nil {
		data["limitDown"] = *p.LimitDown
	}
	if p.LimitDownDown != nil {
		data["limitDownDown"] = *p.LimitDownDown
	}
	if p.LimitDownDownDown != nil {
		data["limitDownDownDown"] = *p.LimitDownDownDown
	}
	body := map[string]any{"data": data}
	_, err := c.request("POST", epTagAdd, body, false)
	return err
}

// GetRTValue 取位号实时值(对齐 datahub.get_rt_value,wrap=true 返回 list)。
func (c *TptClient) GetRTValue(tagNames []string) ([]RtValuePoint, error) {
	body := map[string]any{"isFromDB": false, "tagNames": tagNames}
	content, err := c.request("POST", epGetRTValue, body, true)
	if err != nil {
		return nil, err
	}
	var points []RtValuePoint
	if err := json.Unmarshal(content, &points); err != nil {
		return nil, fmt.Errorf("getRTValue 解析失败: %w", err)
	}
	return points, nil
}

// WriteTagValues 回写位号值(对齐 datahub.write_tag_values,wrap=true)。
// values: {tagName: tagValue},tagValue 为 number/string/bool(any)。
func (c *TptClient) WriteTagValues(values map[string]any) error {
	body := map[string]any{"values": values}
	_, err := c.request("POST", epWriteTagValues, body, true)
	return err
}

// GetAllDsInfo 翻页拉取所有数据源(对齐 datahub.get_all_ds_info)。
func (c *TptClient) GetAllDsInfo() ([]DsInfo, error) {
	var all []DsInfo
	page := 1
	const pageSize = 200
	for {
		body := map[string]any{
			"data":        map[string]any{},
			"requestBase": pageBase(page, pageSize),
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
			break
		}
		all = append(all, resp.Records...)
		if len(resp.Records) < pageSize {
			break
		}
		page++
	}
	return all, nil
}

// AddDsInfo 新增数据源(对齐 datahub.add_ds_info,wrap=false 返回 content 含 id)。
func (c *TptClient) AddDsInfo(dsName, dsTarUrl string) (DsInfo, error) {
	if dsName == "" {
		return DsInfo{}, fmt.Errorf("dsName 必填")
	}
	if dsTarUrl == "" {
		return DsInfo{}, fmt.Errorf("dsTarUrl 必填")
	}
	body := map[string]any{
		"data": map[string]any{
			"dsName":    dsName,
			"dsType":    dsTypeRealTimeDB,
			"dsSubType": dsSubTypeOpcUaServer,
			"dsTarUrl":  dsTarUrl,
		},
	}
	content, err := c.request("POST", epDsInfoAdd, body, false)
	if err != nil {
		return DsInfo{}, err
	}
	var rec DsInfo
	if err := json.Unmarshal(content, &rec); err != nil {
		return DsInfo{}, fmt.Errorf("ds-info/add 解析失败: %w", err)
	}
	return rec, nil
}

// GetTagsByDsID 按数据源 ID 拉取位号列表(已实测 tag-info/page 支持 data.dsId 过滤)。
func (c *TptClient) GetTagsByDsID(dsID int) ([]TagRecord, error) {
	var all []TagRecord
	page := 1
	const pageSize = 500
	for {
		body := map[string]any{
			"data":        map[string]any{"dsId": dsID},
			"requestBase": pageBase(page, pageSize),
		}
		content, err := c.request("POST", epTagPage, body, false)
		if err != nil {
			return nil, err
		}
		var resp struct {
			Records []TagRecord `json:"records"`
		}
		if err := json.Unmarshal(content, &resp); err != nil {
			return nil, fmt.Errorf("tag-info/page 解析失败: %w", err)
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
	return all, nil
}

// GetAllTagsAllTypes 遍历所有 tagType 拉取位号,合并去重(对齐 datahub.get_all_tags_all_types)。
func (c *TptClient) GetAllTagsAllTypes() ([]TagRecord, error) {
	seen := map[int]bool{}
	var all []TagRecord
	for _, tt := range defaultTagTypesAll {
		recs, err := c.getAllTagsByType(tt)
		if err != nil {
			continue // 单 type 失败不阻塞(对齐 python except: records=[])
		}
		for _, r := range recs {
			if r.ID != 0 && !seen[r.ID] {
				seen[r.ID] = true
				all = append(all, r)
			}
		}
	}
	return all, nil
}

func (c *TptClient) getAllTagsByType(tagType int) ([]TagRecord, error) {
	var all []TagRecord
	page := 1
	const pageSize = 2000
	for {
		body := map[string]any{
			"data":        map[string]any{"tagType": tagType},
			"requestBase": pageBase(page, pageSize),
		}
		content, err := c.request("POST", epTagPage, body, false)
		if err != nil {
			return nil, err
		}
		var resp struct {
			Records []TagRecord `json:"records"`
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
	return all, nil
}

// DeleteTags 批量逻辑删除(软,对齐 datahub.delete_tags)。
func (c *TptClient) DeleteTags(ids []int) error {
	body := map[string]any{"data": map[string]any{"ids": ids}}
	_, err := c.request("DELETE", epTagBatchDeleteLogic, body, false)
	return err
}

// DeleteTagsPhysical 批量物理删除(对齐 datahub.delete_tags_physical)。
func (c *TptClient) DeleteTagsPhysical(ids []int) error {
	body := map[string]any{"data": map[string]any{"ids": ids}}
	_, err := c.request("DELETE", epTagBatchDelete, body, false)
	return err
}

// ChangeDsState 启用/禁用数据源。state=1 启用,state=0 禁用。
func (c *TptClient) ChangeDsState(dsID int, enabled bool) error {
	state := 0
	if enabled {
		state = 1
	}
	body := map[string]any{
		"data": map[string]any{
			fmt.Sprintf("%d", dsID): state,
		},
	}
	_, err := c.request("POST", epDsInfoChangeState, body, false)
	return err
}

// DeleteDsInfo 批量删除数据源。注意:数据源下有位号时会报 "currently in use";
// changeState 在有位号时会 ReadTimeout 且不生效,因此"删除重建"需先物理删除其下所有位号。
func (c *TptClient) DeleteDsInfo(ids []int) error {
	if len(ids) == 0 {
		return nil
	}
	body := map[string]any{"data": map[string]any{"ids": ids}}
	_, err := c.request("DELETE", epDsInfoBatchDelete, body, false)
	return err
}
