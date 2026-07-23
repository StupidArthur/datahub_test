// service.go - 数据源组态:接数据源 + 加位号 + smoke 验证。
//
// 对齐 python ua_test_harness/env/ds_provision.py。
//   - 数据源按 dsTarUrl(endpoint)找,有则复用,无则 AddDsInfo
//   - 重名位号:列出,二次确认后彻底删(软删 + 物理删)
//   - 加位号:AddTag(tagName=节点名, tagBaseName=1_{node});不支持类型 -> 跳过
//   - smoke:找 1 个 Double 可写位号,WriteTagValues + GetRTValue 回读
// 核心逻辑,不 import Wails,可独立 go test(需登录 + mock)。
package provision

import (
	"fmt"
	"time"

	"ua_test_gui/internal/mock"
	"ua_test_gui/internal/subject"
)

// FindDsByURL 按 dsTarUrl 找数据源。
func FindDsByURL(api *subject.TptClient, endpoint string) (*subject.DsInfo, error) {
	all, err := api.GetAllDsInfo()
	if err != nil {
		return nil, err
	}
	for i := range all {
		if all[i].DsTarUrl == endpoint {
			return &all[i], nil
		}
	}
	return nil, nil
}

// FindOrAddDS 找(复用)或新建数据源。返回 (dsID, reused, error)。
func FindOrAddDS(api *subject.TptClient, dsName, endpoint string) (int, bool, error) {
	d, err := FindDsByURL(api, endpoint)
	if err != nil {
		return 0, false, err
	}
	if d != nil {
		return d.ID, true, nil
	}
	rec, err := api.AddDsInfo(dsName, endpoint)
	if err != nil {
		return 0, false, err
	}
	return rec.ID, false, nil
}

// ListDuplicates 列出 names 中已存在的重名位号。
func ListDuplicates(api *subject.TptClient, names []string) []subject.TagRecord {
	all, err := api.GetAllTagsAllTypes()
	if err != nil {
		return nil
	}
	nameSet := make(map[string]bool, len(names))
	for _, n := range names {
		nameSet[n] = true
	}
	var dups []subject.TagRecord
	for _, t := range all {
		if nameSet[t.TagName] {
			dups = append(dups, t)
		}
	}
	return dups
}

// PhysicallyDeleteByNames 彻底删(软删 + 物理删)。返回 (deleted, missing, error)。
func PhysicallyDeleteByNames(api *subject.TptClient, names []string) ([]string, []string, error) {
	all, err := api.GetAllTagsAllTypes()
	if err != nil {
		return nil, nil, err
	}
	existing := make(map[string]int, len(all))
	for _, t := range all {
		existing[t.TagName] = t.ID
	}
	var ids []int
	var deleted, missing []string
	for _, n := range names {
		if id, ok := existing[n]; ok {
			ids = append(ids, id)
			deleted = append(deleted, n)
		} else {
			missing = append(missing, n)
		}
	}
	if len(ids) > 0 {
		if err := api.DeleteTags(ids); err != nil {
			return deleted, missing, err
		}
		if err := api.DeleteTagsPhysical(ids); err != nil {
			return deleted, missing, err
		}
	}
	return deleted, missing, nil
}

// AddTags 批量加位号(容错)。不支持类型 -> 跳过;个别 AddTag 报错 -> 记 failed 不中断。
// 返回 (added, skipped, failed)。failed 用于异常测试(bad_len 超长名被拒等)。
func AddTags(api *subject.TptClient, dsID int, specs []mock.TagSpec) (added, skipped []string, failed []TagFail) {
	for _, s := range specs {
		dt, ok := mock.TptDataType(s.MockerType)
		if !ok {
			skipped = append(skipped, s.Name)
			continue
		}
		err := api.AddTag(subject.AddTagParams{
			TagName:     s.Name,
			DataType:    dt,
			DsID:        dsID,
			TagBaseName: "1_" + s.Name, // ns=1 约定
			OnlyRead:    !s.Writable,
			Frequency:   s.Frequency,
		})
		if err != nil {
			failed = append(failed, TagFail{Name: s.Name, Error: err.Error()})
			continue
		}
		added = append(added, s.Name)
	}
	return
}

// SmokeVerify write + 回读,验证数据源可写可读。
func SmokeVerify(api *subject.TptClient, tagName string, writeVal float64, settleSec float64) SmokeResult {
	if settleSec <= 0 {
		settleSec = 2.0
	}
	if err := api.WriteTagValues(map[string]any{tagName: writeVal}); err != nil {
		return SmokeResult{OK: false, Msg: "write 失败: " + err.Error(), Write: writeVal}
	}
	time.Sleep(time.Duration(settleSec * float64(time.Second)))
	pts, err := api.GetRTValue([]string{tagName})
	if err != nil {
		return SmokeResult{OK: false, Msg: "getRTValue 失败: " + err.Error(), Write: writeVal}
	}
	if len(pts) == 0 {
		return SmokeResult{OK: false, Msg: "getRTValue 返回空", Write: writeVal}
	}
	return SmokeResult{OK: true, Msg: "write+readback ok", Write: writeVal, Readback: pts[0].TagValue}
}

// Provision 完整组态:找/建 ds -> 列重名 -> (二次确认)彻底删 -> 加位号 -> smoke。
// 错误返回 error;DsProvisionResult 保留已完成的步骤结果(部分结果)。
func Provision(api *subject.TptClient, opts ProvisionOptions) (DsProvisionResult, error) {
	result := DsProvisionResult{}

	// 1. 数据源
	dsID, reused, err := FindOrAddDS(api, opts.DsName, opts.Endpoint)
	if err != nil {
		return result, fmt.Errorf("数据源失败: %w", err)
	}
	result.DsID = dsID
	result.DsReused = reused
	result.DsAlive = true // 走到这步说明能连;精细化 alive 检查后续补

	// 2. 重名位号
	names := make([]string, len(opts.TagSpecs))
	for i, s := range opts.TagSpecs {
		names[i] = s.Name
	}
	if dups := ListDuplicates(api, names); len(dups) > 0 {
		dupNames := make([]string, len(dups))
		for i, d := range dups {
			dupNames[i] = d.TagName
		}
		if opts.ConfirmDelete != nil && opts.ConfirmDelete(len(dups), firstN(dupNames, 10)) {
			deleted, missing, derr := PhysicallyDeleteByNames(api, dupNames)
			result.TagsDeleted = deleted
			result.TagsDeleteMissing = missing
			if derr != nil {
				return result, fmt.Errorf("删除重名位号失败: %w", derr)
			}
		}
		// 不删则后续 AddTag 会因重名报错(记入 failed)
	}

	// 3. 加位号
	added, skipped, failed := AddTags(api, dsID, opts.TagSpecs)
	result.TagsAdded = added
	result.TagsSkippedUnsupported = skipped
	result.TagsFailed = failed

	// 4. smoke
	if opts.SmokeTag != "" {
		result.Smoke = SmokeVerify(api, opts.SmokeTag, 888.88, opts.SmokeSettleSec)
	}
	return result, nil
}

func firstN(s []string, n int) []string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// GetState 查询当前 mock 对应的数据源组态状态。
func GetState(api *subject.TptClient, req ProvisionStateRequest) (ProvisionState, error) {
	state := ProvisionState{MockKey: req.MockKey, Endpoint: req.Endpoint}

	spec, ok := mock.FindSpec(req.MockKey)
	if !ok {
		return state, fmt.Errorf("未知 mock: %s", req.MockKey)
	}
	state.HeartbeatTag = spec.HeartbeatTag + "1"

	mockTags := mock.TagSpecsFromMock(spec, req.Frequency)
	state.MockTags = mockTags

	// 不支持类型(TptDataType 返回 ok=false 的)
	var supported, unsupported []mock.TagSpec
	for _, s := range mockTags {
		if _, ok := mock.TptDataType(s.MockerType); ok {
			supported = append(supported, s)
		} else {
			unsupported = append(unsupported, s)
		}
	}
	state.UnsupportedTags = unsupported

	// 查找数据源
	ds, err := FindDsByURL(api, req.Endpoint)
	if err != nil {
		return state, err
	}
	if ds == nil {
		// 无数据源:所有支持位号都是缺失
		state.MissingTags = supported
		state.TagStatuses = buildTagStatuses(mockTags, nil)
		return state, nil
	}

	state.DsInfo = ds
	state.DsAlive = ds.Alive

	// 获取数据源下位号
	tagsInDs, err := api.GetTagsByDsID(ds.ID)
	if err != nil {
		return state, err
	}
	state.TagsInDsCount = len(tagsInDs)

	// 按 tagName 分组
	tagNameMap := make(map[string][]subject.TagRecord)
	for _, t := range tagsInDs {
		tagNameMap[t.TagName] = append(tagNameMap[t.TagName], t)
	}

	// 计算缺失、重复、状态
	inDsSet := make(map[string]bool)
	for name := range tagNameMap {
		inDsSet[name] = true
	}

	var missing []mock.TagSpec
	var duplicates []DuplicateGroup
	for _, s := range supported {
		recs, ok := tagNameMap[s.Name]
		if !ok {
			missing = append(missing, s)
			continue
		}
		if len(recs) > 1 {
			ids := make([]int, len(recs))
			for i, r := range recs {
				ids[i] = r.ID
			}
			duplicates = append(duplicates, DuplicateGroup{
				TagName: s.Name,
				Count:   len(recs),
				IDs:     ids,
			})
		}
	}
	state.MissingTags = missing
	state.DuplicateTags = duplicates
	state.TagStatuses = buildTagStatuses(mockTags, tagNameMap)
	return state, nil
}

func buildTagStatuses(mockTags []mock.TagSpec, tagNameMap map[string][]subject.TagRecord) []TagStatus {
	out := make([]TagStatus, 0, len(mockTags))
	for _, s := range mockTags {
		recs, inDs := tagNameMap[s.Name]
		status := TagStatus{
			Name:       s.Name,
			MockerType: s.MockerType,
			Writable:   s.Writable,
			InDs:       inDs,
		}
		if inDs && len(recs) > 1 {
			status.Duplicate = true
			status.DuplicateCount = len(recs)
		}
		out = append(out, status)
	}
	return out
}

// AddMissingTags 批量添加 mock 有但数据源没有的位号。
func AddMissingTags(api *subject.TptClient, req AddMissingTagsRequest) ([]string, []TagFail, error) {
	state, err := GetState(api, ProvisionStateRequest(req))
	if err != nil {
		return nil, nil, err
	}
	if state.DsInfo == nil {
		return nil, nil, fmt.Errorf("数据源不存在")
	}

	added, _, failed := AddTags(api, state.DsInfo.ID, state.MissingTags)
	return added, failed, nil
}

// DeleteDuplicateTags 删除数据源下的重复位号(保留一条,删除其余)。
func DeleteDuplicateTags(api *subject.TptClient, req DeleteDuplicateTagsRequest) error {
	if req.DsID <= 0 {
		return fmt.Errorf("dsId 无效")
	}
	tags, err := api.GetTagsByDsID(req.DsID)
	if err != nil {
		return err
	}

	// 按 tagName 分组,每组保留一个,删除其余
	groups := make(map[string][]int)
	for _, t := range tags {
		groups[t.TagName] = append(groups[t.TagName], t.ID)
	}

	var toDelete []int
	for _, ids := range groups {
		if len(ids) > 1 {
			toDelete = append(toDelete, ids[1:]...)
		}
	}
	if len(toDelete) == 0 {
		return nil
	}

	if err := api.DeleteTags(toDelete); err != nil {
		return err
	}
	return api.DeleteTagsPhysical(toDelete)
}

// RebuildDataSource 删除重建数据源:清位号 -> 删数据源 -> 新建 -> 加位号。
func RebuildDataSource(api *subject.TptClient, req RebuildDataSourceRequest) (DsProvisionResult, error) {
	result := DsProvisionResult{}

	// 1. 找旧数据源
	oldDs, err := FindDsByURL(api, req.Endpoint)
	if err != nil {
		return result, err
	}

	// 2. 清位号 + 删数据源
	if oldDs != nil {
		result.DsID = oldDs.ID
		tags, err := api.GetTagsByDsID(oldDs.ID)
		if err != nil {
			return result, err
		}
		if len(tags) > 0 {
			ids := make([]int, len(tags))
			for i, t := range tags {
				ids[i] = t.ID
			}
			if err := api.DeleteTags(ids); err != nil {
				return result, fmt.Errorf("软删旧位号失败: %w", err)
			}
			if err := api.DeleteTagsPhysical(ids); err != nil {
				return result, fmt.Errorf("物理删旧位号失败: %w", err)
			}
			for _, t := range tags {
				result.TagsDeleted = append(result.TagsDeleted, t.TagName)
			}
		}
		if err := api.DeleteDsInfo([]int{oldDs.ID}); err != nil {
			return result, fmt.Errorf("删除旧数据源失败: %w", err)
		}
	}

	// 3. 新建数据源
	newDs, err := api.AddDsInfo(req.DsName, req.Endpoint)
	if err != nil {
		return result, fmt.Errorf("新建数据源失败: %w", err)
	}
	result.DsID = newDs.ID
	result.DsReused = false
	result.DsAlive = newDs.Alive

	// 4. 加位号
	spec, ok := mock.FindSpec(req.MockKey)
	if !ok {
		return result, fmt.Errorf("未知 mock: %s", req.MockKey)
	}
	tagSpecs := mock.TagSpecsFromMock(spec, req.Frequency)
	added, skipped, failed := AddTags(api, newDs.ID, tagSpecs)
	result.TagsAdded = added
	result.TagsSkippedUnsupported = skipped
	result.TagsFailed = failed

	return result, nil
}

// AddDataSource 只创建空数据源(不添加位号)。
func AddDataSource(api *subject.TptClient, req AddDataSourceRequest) (subject.DsInfo, error) {
	if req.DsName == "" {
		return subject.DsInfo{}, fmt.Errorf("dsName 必填")
	}
	if req.Endpoint == "" {
		return subject.DsInfo{}, fmt.Errorf("endpoint 必填")
	}
	return api.AddDsInfo(req.DsName, req.Endpoint)
}

// DeleteDataSource 删除数据源;若下有位号则先清空(软删+物理删)。
func DeleteDataSource(api *subject.TptClient, req DeleteDataSourceRequest) error {
	if req.DsID <= 0 {
		return fmt.Errorf("dsId 无效")
	}
	tags, err := api.GetTagsByDsID(req.DsID)
	if err != nil {
		return err
	}
	if len(tags) > 0 {
		ids := make([]int, len(tags))
		for i, t := range tags {
			ids[i] = t.ID
		}
		if err := api.DeleteTags(ids); err != nil {
			return fmt.Errorf("软删位号失败: %w", err)
		}
		if err := api.DeleteTagsPhysical(ids); err != nil {
			return fmt.Errorf("物理删位号失败: %w", err)
		}
	}
	return api.DeleteDsInfo([]int{req.DsID})
}

// DeleteAllTags 删除数据源下所有位号(软删+物理删)。
func DeleteAllTags(api *subject.TptClient, req DeleteAllTagsRequest) error {
	if req.DsID <= 0 {
		return fmt.Errorf("dsId 无效")
	}
	tags, err := api.GetTagsByDsID(req.DsID)
	if err != nil {
		return err
	}
	if len(tags) == 0 {
		return nil
	}
	ids := make([]int, len(tags))
	for i, t := range tags {
		ids[i] = t.ID
	}
	if err := api.DeleteTags(ids); err != nil {
		return fmt.Errorf("软删位号失败: %w", err)
	}
	return api.DeleteTagsPhysical(ids)
}

// GetHeartbeatValue 读取心跳位号实时值。
func GetHeartbeatValue(api *subject.TptClient, req GetHeartbeatValueRequest) (HeartbeatValue, error) {
	result := HeartbeatValue{TagName: req.TagName}
	if req.DsID <= 0 {
		return result, fmt.Errorf("dsId 无效")
	}
	if req.TagName == "" {
		return result, fmt.Errorf("tagName 必填")
	}
	pts, err := api.GetRTValue([]string{req.TagName})
	if err != nil {
		result.Msg = err.Error()
		return result, err
	}
	if len(pts) == 0 {
		result.Msg = "未返回心跳值"
		return result, nil
	}
	p := pts[0]
	result.TagValue = p.TagValue
	result.Quality = p.Quality
	result.OK = true
	result.Msg = "ok"
	return result, nil
}
