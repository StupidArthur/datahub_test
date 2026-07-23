// service_layer.go - 组态服务,持有登录态,封装 Provision 调用。
package provision

import (
	"errors"

	"ua_test_gui/internal/mock"
	"ua_test_gui/internal/subject"
)

// ProvisionRequest 组态入参(DTO)。
type ProvisionRequest struct {
	MockKey        string  `json:"mockKey"`
	DsName         string  `json:"dsName"`
	Endpoint       string  `json:"endpoint"`
	Frequency      int     `json:"frequency"`
	SmokeTag       string  `json:"smokeTag"`
	SmokeSettleSec float64 `json:"smokeSettleSec"`
	ConfirmDelete  bool    `json:"confirmDelete"` // 有重复位号时是否物理删除后重建
}

// Service 组态服务。
type Service struct {
	subject *subject.Service
}

// NewService 创建组态服务,依赖 SubjectService 取登录态。
func NewService(subj *subject.Service) *Service {
	return &Service{subject: subj}
}

// Provision 执行组态:找/建 ds -> 列重名 -> (二次确认)彻底删 -> 加位号 -> smoke。
func (s *Service) Provision(req ProvisionRequest) (DsProvisionResult, error) {
	cli := s.subject.Client()
	if cli == nil {
		return DsProvisionResult{}, errors.New("未登录")
	}
	spec, ok := mock.FindSpec(req.MockKey)
	if !ok {
		return DsProvisionResult{}, errors.New("未知 mock: " + req.MockKey)
	}
	freq := req.Frequency
	if freq <= 0 {
		freq = 10
	}
	opts := ProvisionOptions{
		DsName:         req.DsName,
		Endpoint:       req.Endpoint,
		TagSpecs:       mock.TagSpecsFromMock(spec, freq),
		SmokeTag:       req.SmokeTag,
		SmokeSettleSec: req.SmokeSettleSec,
		ConfirmDelete:  func(_ int, _ []string) bool { return req.ConfirmDelete },
	}
	return Provision(cli, opts)
}

// GetProvisionState 查询当前 mock 对应的数据源组态状态。
func (s *Service) GetProvisionState(req ProvisionStateRequest) (ProvisionState, error) {
	cli := s.subject.Client()
	if cli == nil {
		return ProvisionState{}, errors.New("未登录")
	}
	if req.Frequency <= 0 {
		req.Frequency = 10
	}
	return GetState(cli, req)
}

// AddMissingTags 批量添加缺失位号。
func (s *Service) AddMissingTags(req AddMissingTagsRequest) ([]string, []TagFail, error) {
	cli := s.subject.Client()
	if cli == nil {
		return nil, nil, errors.New("未登录")
	}
	if req.Frequency <= 0 {
		req.Frequency = 10
	}
	return AddMissingTags(cli, req)
}

// DeleteDuplicateTags 删除数据源下的重复位号。
func (s *Service) DeleteDuplicateTags(req DeleteDuplicateTagsRequest) error {
	cli := s.subject.Client()
	if cli == nil {
		return errors.New("未登录")
	}
	return DeleteDuplicateTags(cli, req)
}

// RebuildDataSource 删除并重建数据源。
func (s *Service) RebuildDataSource(req RebuildDataSourceRequest) (DsProvisionResult, error) {
	cli := s.subject.Client()
	if cli == nil {
		return DsProvisionResult{}, errors.New("未登录")
	}
	if req.Frequency <= 0 {
		req.Frequency = 10
	}
	return RebuildDataSource(cli, req)
}

// AddDataSource 只创建空数据源。
func (s *Service) AddDataSource(req AddDataSourceRequest) (subject.DsInfo, error) {
	cli := s.subject.Client()
	if cli == nil {
		return subject.DsInfo{}, errors.New("未登录")
	}
	return AddDataSource(cli, req)
}

// DeleteDataSource 删除数据源（先清空位号）。
func (s *Service) DeleteDataSource(req DeleteDataSourceRequest) error {
	cli := s.subject.Client()
	if cli == nil {
		return errors.New("未登录")
	}
	return DeleteDataSource(cli, req)
}

// ChangeDsState 启用/禁用数据源。
func (s *Service) ChangeDsState(req ChangeDsStateRequest) error {
	cli := s.subject.Client()
	if cli == nil {
		return errors.New("未登录")
	}
	return cli.ChangeDsState(req.DsID, req.Enabled)
}

// DeleteAllTags 删除数据源下所有位号。
func (s *Service) DeleteAllTags(req DeleteAllTagsRequest) error {
	cli := s.subject.Client()
	if cli == nil {
		return errors.New("未登录")
	}
	return DeleteAllTags(cli, req)
}

// GetHeartbeatValue 读取心跳位号实时值。
func (s *Service) GetHeartbeatValue(req GetHeartbeatValueRequest) (HeartbeatValue, error) {
	cli := s.subject.Client()
	if cli == nil {
		return HeartbeatValue{}, errors.New("未登录")
	}
	return GetHeartbeatValue(cli, req)
}
