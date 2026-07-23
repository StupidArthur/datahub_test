// mock.go - mock 管理绑定:列表/启停/性能参数。
package bindings

import "ua_test_gui/internal/mock"

// MockBinding mock 绑定。
type MockBinding struct {
	svc *mock.Service
}

// NewMockBinding 创建。
func NewMockBinding(svc *mock.Service) *MockBinding {
	return &MockBinding{svc: svc}
}

// ListMocks 列出 4 套 mock 及状态。
func (b *MockBinding) ListMocks() (resp []mock.MockSummary, err error) {
	defer RecoverPanic(&err)
	resp = b.svc.ListMocks()
	return
}

// StartMock 启动一套 mock。
func (b *MockBinding) StartMock(key string) (resp *mock.MockRuntime, err error) {
	defer RecoverPanic(&err)
	resp, err = b.svc.StartMock(key)
	return
}

// MockStopResult 停止单套结果。
type MockStopResult struct {
	Key string `json:"key"`
	OK  bool   `json:"ok"`
	Msg string `json:"msg"`
}

// StopMock 停一套 mock。
func (b *MockBinding) StopMock(key string) (resp MockStopResult, err error) {
	defer RecoverPanic(&err)
	b.svc.StopMock(key)
	resp = MockStopResult{Key: key, OK: true, Msg: "已停止"}
	return
}

// StopAllResult 停止全部结果。
type StopAllResult struct {
	Stopped []string `json:"stopped"`
}

// StopAllMocks 停所有在跑的 mock(非 stopped 状态)。
func (b *MockBinding) StopAllMocks() (resp StopAllResult, err error) {
	defer RecoverPanic(&err)
	for _, m := range b.svc.ListMocks() {
		if m.Status != "stopped" {
			b.svc.StopMock(m.Key)
			resp.Stopped = append(resp.Stopped, m.Key)
		}
	}
	return
}

// StartAllResult 启动全部结果。
type StartAllResult struct {
	Started []string `json:"started"`
	Mocks   []mock.MockSummary `json:"mocks"`
}

// StartAllMocks 依次启动所有 stopped 的 mock。
func (b *MockBinding) StartAllMocks() (resp StartAllResult, err error) {
	defer RecoverPanic(&err)
	resp.Started, err = b.svc.StartAllMocks()
	resp.Mocks = b.svc.ListMocks()
	return
}

// GetPerformanceParams 取当前性能测试参数(0=默认 10000/1000/0.9)。
func (b *MockBinding) GetPerformanceParams() (resp mock.PerfParams, err error) {
	defer RecoverPanic(&err)
	resp = b.svc.GetPerfParams()
	return
}

// SetPerformanceParams 设置性能测试参数(0 值不覆盖),返回当前值。
func (b *MockBinding) SetPerformanceParams(p mock.PerfParams) (resp mock.PerfParams, err error) {
	defer RecoverPanic(&err)
	b.svc.SetPerfParams(p)
	resp = b.svc.GetPerfParams()
	return
}
