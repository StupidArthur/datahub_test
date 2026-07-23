// service_layer.go - 环境检测服务,封装 env 包级函数 + 查登录态。
package env

import "ua_test_gui/internal/subject"

// EnvStatus 环境状态(DTO,供前端环境页)。
type EnvStatus struct {
	Ports           []PortStatus `json:"ports"`
	LocalIPs        []string     `json:"localIps"`
	PickIP          string       `json:"pickIp"`
	ConnectivityOK  bool         `json:"connectivityOk"`
	ConnectivityMsg string       `json:"connectivityMsg"`
}

// Service 环境检测服务。
type Service struct {
	subject *subject.Service
}

// NewService 创建环境服务,依赖 SubjectService 查登录态。
func NewService(subj *subject.Service) *Service {
	return &Service{subject: subj}
}

// GetEnvStatus 扫描端口/IP,连通性以是否已登录判定(沿用原逻辑)。
func (s *Service) GetEnvStatus() EnvStatus {
	res := EnvStatus{
		Ports:    ScanPorts(),
		LocalIPs: ListLocalIPs(),
	}
	res.PickIP = PickLocalIP(res.LocalIPs)
	if cli := s.subject.Client(); cli != nil {
		res.ConnectivityOK = true
		res.ConnectivityMsg = "已登录: " + s.subject.Info().BaseURL
	}
	return res
}
