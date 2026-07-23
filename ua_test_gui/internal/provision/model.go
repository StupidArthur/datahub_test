// model.go - 数据源组态结果数据模型。
//
// 错误模型:service 返回 (T, error),DsProvisionResult 不再含 Error 字段。
package provision

import (
	"ua_test_gui/internal/mock"
	"ua_test_gui/internal/subject"
)

// TagFail AddTag 失败记录(异常测试 bad_len 超长名被拒等)。
type TagFail struct {
	Name  string `json:"name"`
	Error string `json:"error"`
}

// SmokeResult smoke 验证结果。
type SmokeResult struct {
	OK       bool `json:"ok"`
	Msg      string `json:"msg"`
	Write    any  `json:"write"`
	Readback any  `json:"readback"`
}

// DsProvisionResult 完整组态结果。
type DsProvisionResult struct {
	DsID                   int         `json:"dsId"`
	DsReused               bool        `json:"dsReused"`
	DsAlive                bool        `json:"dsAlive"`
	TagsAdded              []string    `json:"tagsAdded"`
	TagsSkippedUnsupported []string    `json:"tagsSkippedUnsupported"`
	TagsFailed             []TagFail   `json:"tagsFailed"`
	TagsDeleted            []string    `json:"tagsDeleted"`
	TagsDeleteMissing      []string    `json:"tagsDeleteMissing"`
	Smoke                  SmokeResult `json:"smoke"`
}

// ProvisionOptions Provision 入参。TagSpec 来自 mock 包(从 MockSpec 展开)。
type ProvisionOptions struct {
	DsName         string
	Endpoint       string                       // TPT 视角 endpoint(local_ip:port)
	TagSpecs       []mock.TagSpec
	ConfirmDelete  func(count int, names []string) bool // 重名位号二次确认;nil 则不删
	SmokeTag       string                       // smoke 用 Double 可写位号名;空则跳过
	SmokeSettleSec float64
}

// ProvisionStateRequest 查询组态状态入参。
type ProvisionStateRequest struct {
	MockKey  string `json:"mockKey"`
	Endpoint string `json:"endpoint"`
	Frequency int   `json:"frequency"`
}

// TagStatus 单个 mock 节点在 TPT 上的存在状态。
type TagStatus struct {
	Name           string `json:"name"`
	MockerType     string `json:"mockerType"`
	Writable       bool   `json:"writable"`
	InDs           bool   `json:"inDs"`
	Duplicate      bool   `json:"duplicate"`
	DuplicateCount int    `json:"duplicateCount"`
}

// DuplicateGroup 一组重复位号。
type DuplicateGroup struct {
	TagName string `json:"tagName"`
	Count   int    `json:"count"`
	IDs     []int  `json:"ids"`
}

// ProvisionState 数据源组态完整状态(供 ProvisionPage 展示)。
type ProvisionState struct {
	MockKey         string           `json:"mockKey"`
	Endpoint        string           `json:"endpoint"`
	HeartbeatTag    string           `json:"heartbeatTag"`
	DsInfo          *subject.DsInfo  `json:"dsInfo,omitempty"`
	DsAlive         bool             `json:"dsAlive"`
	TagsInDsCount   int              `json:"tagsInDsCount"`
	MockTags        []mock.TagSpec   `json:"mockTags"`
	TagStatuses     []TagStatus      `json:"tagStatuses"`
	MissingTags     []mock.TagSpec   `json:"missingTags"`
	DuplicateTags   []DuplicateGroup `json:"duplicateTags"`
	UnsupportedTags []mock.TagSpec   `json:"unsupportedTags"`
}

// AddMissingTagsRequest 批量添加缺失位号入参。
type AddMissingTagsRequest struct {
	MockKey   string `json:"mockKey"`
	Endpoint  string `json:"endpoint"`
	Frequency int    `json:"frequency"`
}

// DeleteDuplicateTagsRequest 删除重复位号入参。
type DeleteDuplicateTagsRequest struct {
	DsID int `json:"dsId"`
}

// RebuildDataSourceRequest 删除重建数据源入参。
type RebuildDataSourceRequest struct {
	MockKey   string `json:"mockKey"`
	DsName    string `json:"dsName"`
	Endpoint  string `json:"endpoint"`
	Frequency int    `json:"frequency"`
}

// AddDataSourceRequest 只创建空数据源入参。
type AddDataSourceRequest struct {
	DsName   string `json:"dsName"`
	Endpoint string `json:"endpoint"`
}

// DeleteDataSourceRequest 删除数据源入参。
type DeleteDataSourceRequest struct {
	DsID int `json:"dsId"`
}

// ChangeDsStateRequest 启用/禁用数据源入参。
type ChangeDsStateRequest struct {
	DsID    int  `json:"dsId"`
	Enabled bool `json:"enabled"`
}

// DeleteAllTagsRequest 删除数据源下所有位号入参。
type DeleteAllTagsRequest struct {
	DsID int `json:"dsId"`
}

// GetHeartbeatValueRequest 读取心跳位号值入参。
type GetHeartbeatValueRequest struct {
	DsID     int    `json:"dsId"`
	TagName  string `json:"tagName"`
}

// HeartbeatValue 心跳位号实时值。
type HeartbeatValue struct {
	TagName  string `json:"tagName"`
	TagValue any    `json:"tagValue"`
	Quality  int    `json:"quality"`
	OK       bool   `json:"ok"`
	Msg      string `json:"msg"`
}
