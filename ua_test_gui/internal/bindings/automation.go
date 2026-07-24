// automation.go - automation 域的 Wails binding。
package bindings

import (
	"context"
	"errors"
	"fmt"

	"ua_test_gui/internal/automation"
)

// AutomationBinding 暴露给前端的 binding。
//
// Legacy bindings (ListTestCases / StartTestRun / ...) 走旧 Harness;
// New bindings (ListNativeTestCases / RunNativeTestCases /
// CancelNativeTestRun) 走原生 pytest 模式, 由 NativeService 提供。
// 两种 binding 并存, 调用方决定使用哪一种。
type AutomationBinding struct {
	svc     *automation.Service
	native  *automation.NativeService
}

// NewAutomationBinding 构造。
func NewAutomationBinding(svc *automation.Service) *AutomationBinding {
	return &AutomationBinding{svc: svc}
}

// NewAutomationBindingWithNative 构造, 同时注入原生 pytest Service。
func NewAutomationBindingWithNative(svc *automation.Service, native *automation.NativeService) *AutomationBinding {
	return &AutomationBinding{svc: svc, native: native}
}

// ListTestCases 返回 catalog。
func (a *AutomationBinding) ListTestCases() automation.Catalog {
	if a.svc == nil {
		return automation.Catalog{}
	}
	return a.svc.Catalog()
}

// RefreshTestCatalog 重新加载(此处返回当前 catalog;真实场景下需要注入 catalog 加载器)。
func (a *AutomationBinding) RefreshTestCatalog() automation.Catalog {
	if a.svc == nil {
		return automation.Catalog{}
	}
	return a.svc.Catalog()
}

// StartTestRun 启动。
func (a *AutomationBinding) StartTestRun(req automation.StartRunRequest) (automation.TestRun, error) {
	if a.svc == nil {
		return automation.TestRun{}, errors.New("automation service not initialized")
	}
	return a.svc.StartTestRun(req)
}

// StopTestRun 停止。
func (a *AutomationBinding) StopTestRun(runID int64) (automation.TestRun, error) {
	if a.svc == nil {
		return automation.TestRun{}, errors.New("automation service not initialized")
	}
	return a.svc.StopTestRun(runID)
}

// GetActiveTestRun 取活跃 run。
func (a *AutomationBinding) GetActiveTestRun() (*automation.TestRun, error) {
	if a.svc == nil {
		return nil, nil
	}
	return a.svc.GetActiveTestRun()
}

// ListTestRuns 列出。
func (a *AutomationBinding) ListTestRuns(req automation.ListRunsRequest) ([]automation.TestRun, error) {
	if a.svc == nil {
		return nil, nil
	}
	return a.svc.ListTestRuns(req)
}

// GetTestRunDetail 详情。
func (a *AutomationBinding) GetTestRunDetail(runID int64) (automation.RunDetail, error) {
	if a.svc == nil {
		return automation.RunDetail{}, errors.New("automation service not initialized")
	}
	return a.svc.GetTestRunDetail(runID)
}

// GetRunEvents 拉事件。
func (a *AutomationBinding) GetRunEvents(req automation.GetEventsRequest) ([]automation.TestEvent, error) {
	if a.svc == nil {
		return nil, errors.New("automation service not initialized")
	}
	return a.svc.GetRunEvents(req)
}

// ReadRunLog 分页读 runner.log。
func (a *AutomationBinding) ReadRunLog(req automation.ReadLogRequest) (automation.LogChunk, error) {
	if a.svc == nil {
		return automation.LogChunk{}, errors.New("automation service not initialized")
	}
	r, err := a.svc.GetTestRunDetail(req.RunID)
	if err != nil {
		return automation.LogChunk{}, err
	}
	if r.Run.LogPath == "" {
		return automation.LogChunk{}, fmt.Errorf("run %d has no log path", req.RunID)
	}
	chunk, err := readFileChunk(r.Run.LogPath, req.Offset, req.Limit)
	if err != nil {
		return chunk, err
	}
	chunk.RunID = req.RunID
	return chunk, nil
}

// OpenRunDirectory 触发 OS 打开目录(由前端后续调;这里返回路径供前端使用)。
func (a *AutomationBinding) OpenRunDirectory(runID int64) (string, error) {
	if a.svc == nil {
		return "", errors.New("automation service not initialized")
	}
	r, err := a.svc.GetTestRunDetail(runID)
	if err != nil {
		return "", err
	}
	return r.Run.RunDir, nil
}

// ListNativeTestCases 返回原生 pytest manifest 中的 case 列表。
//
// 仅在 native service 已注入时可用; 否则返回空列表。
func (a *AutomationBinding) ListNativeTestCases() []automation.ManifestCase {
	if a.native == nil {
		return []automation.ManifestCase{}
	}
	return a.native.ListCases()
}

// RunNativeTestCases 启动一次原生 pytest run。
func (a *AutomationBinding) RunNativeTestCases(req automation.NativeRunRequest) (automation.NativeRun, error) {
	if a.native == nil {
		return automation.NativeRun{}, errors.New("native pytest service not initialized")
	}
	return a.native.RunNative(req)
}

// CancelNativeTestRun 取消当前 native run。
func (a *AutomationBinding) CancelNativeTestRun(runID string) error {
	if a.native == nil {
		return errors.New("native pytest service not initialized")
	}
	return a.native.Cancel(runID)
}

// CollectNativeTestRun 等待 run 完成并解析 JUnit。
func (a *AutomationBinding) CollectNativeTestRun(runID string) (automation.NativeRun, error) {
	if a.native == nil {
		return automation.NativeRun{}, errors.New("native pytest service not initialized")
	}
	return a.native.Collect(runID)
}

// _ = context.Background 防止 linter 误删。
var _ = context.Background