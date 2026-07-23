// provision.go - 数据源组态绑定。
package bindings

import (
	"ua_test_gui/internal/provision"
	"ua_test_gui/internal/subject"
)

// ProvisionBinding 组态绑定。
type ProvisionBinding struct {
	svc *provision.Service
}

// NewProvisionBinding 创建。
func NewProvisionBinding(svc *provision.Service) *ProvisionBinding {
	return &ProvisionBinding{svc: svc}
}

// Provision 执行组态:找/建 ds -> 列重名 -> (二次确认)彻底删 -> 加位号 -> smoke。
func (b *ProvisionBinding) Provision(req provision.ProvisionRequest) (resp provision.DsProvisionResult, err error) {
	defer RecoverPanic(&err)
	resp, err = b.svc.Provision(req)
	return
}

// GetProvisionState 查询当前 mock 对应的数据源组态状态。
func (b *ProvisionBinding) GetProvisionState(req provision.ProvisionStateRequest) (resp provision.ProvisionState, err error) {
	defer RecoverPanic(&err)
	resp, err = b.svc.GetProvisionState(req)
	return
}

// AddMissingTags 批量添加缺失位号。
func (b *ProvisionBinding) AddMissingTags(req provision.AddMissingTagsRequest) (added []string, failed []provision.TagFail, err error) {
	defer RecoverPanic(&err)
	added, failed, err = b.svc.AddMissingTags(req)
	return
}

// DeleteDuplicateTags 删除数据源下的重复位号。
func (b *ProvisionBinding) DeleteDuplicateTags(req provision.DeleteDuplicateTagsRequest) (err error) {
	defer RecoverPanic(&err)
	err = b.svc.DeleteDuplicateTags(req)
	return
}

// RebuildDataSource 删除并重建数据源。
func (b *ProvisionBinding) RebuildDataSource(req provision.RebuildDataSourceRequest) (resp provision.DsProvisionResult, err error) {
	defer RecoverPanic(&err)
	resp, err = b.svc.RebuildDataSource(req)
	return
}

// AddDataSource 只创建空数据源。
func (b *ProvisionBinding) AddDataSource(req provision.AddDataSourceRequest) (resp subject.DsInfo, err error) {
	defer RecoverPanic(&err)
	resp, err = b.svc.AddDataSource(req)
	return
}

// DeleteDataSource 删除数据源。
func (b *ProvisionBinding) DeleteDataSource(req provision.DeleteDataSourceRequest) (err error) {
	defer RecoverPanic(&err)
	err = b.svc.DeleteDataSource(req)
	return
}

// ChangeDsState 启用/禁用数据源。
func (b *ProvisionBinding) ChangeDsState(req provision.ChangeDsStateRequest) (err error) {
	defer RecoverPanic(&err)
	err = b.svc.ChangeDsState(req)
	return
}

// DeleteAllTags 删除数据源下所有位号。
func (b *ProvisionBinding) DeleteAllTags(req provision.DeleteAllTagsRequest) (err error) {
	defer RecoverPanic(&err)
	err = b.svc.DeleteAllTags(req)
	return
}

// GetHeartbeatValue 读取心跳位号实时值。
func (b *ProvisionBinding) GetHeartbeatValue(req provision.GetHeartbeatValueRequest) (resp provision.HeartbeatValue, err error) {
	defer RecoverPanic(&err)
	resp, err = b.svc.GetHeartbeatValue(req)
	return
}
