// env.go - 环境检测绑定:端口/IP/连通性 + ua_mocker 路径配置。
package bindings

import (
	"ua_test_gui/internal/env"
	"ua_test_gui/internal/mock"
)

// EnvBinding 环境绑定。
type EnvBinding struct {
	envSvc  *env.Service
	mockSvc *mock.Service
}

// NewEnvBinding 创建。mockSvc 用于 ua_mocker 路径配置(GetMockerConfig/SetMockerConfig)。
func NewEnvBinding(envSvc *env.Service, mockSvc *mock.Service) *EnvBinding {
	return &EnvBinding{envSvc: envSvc, mockSvc: mockSvc}
}

// GetEnvStatus 扫描端口/IP,连通性以是否已登录判定。
func (b *EnvBinding) GetEnvStatus() (resp env.EnvStatus, err error) {
	defer RecoverPanic(&err)
	resp = b.envSvc.GetEnvStatus()
	return
}

// KillPortResult 杀端口结果。
type KillPortResult struct {
	Port int    `json:"port"`
	OK   bool   `json:"ok"`
	Msg  string `json:"msg"`
}

// KillPort 杀掉占用某端口的进程(环境页用,非 mock 也可杀)。
func (b *EnvBinding) KillPort(port int) (resp KillPortResult, err error) {
	defer RecoverPanic(&err)
	ok, msg := env.KillPort(port)
	resp = KillPortResult{Port: port, OK: ok, Msg: msg}
	return
}

// SetMockerConfigRequest ua_mocker 路径配置入参。
type SetMockerConfigRequest struct {
	Repo   string `json:"repo"`
	Python string `json:"python"`
	Exe    string `json:"exe"`
}

// GetMockerConfig 取当前 ua_mocker 运行环境配置(含自动探测结果)。
func (b *EnvBinding) GetMockerConfig() (resp mock.MockerConfigResult, err error) {
	defer RecoverPanic(&err)
	resp = b.mockSvc.GetConfig()
	return
}

// SetMockerConfig 设置 ua_mocker 仓库路径与 python/exe(空值不覆盖),持久化并即时生效。
func (b *EnvBinding) SetMockerConfig(req SetMockerConfigRequest) (resp mock.MockerConfigResult, err error) {
	defer RecoverPanic(&err)
	resp, err = b.mockSvc.SetConfig(req.Repo, req.Python, req.Exe)
	return
}
