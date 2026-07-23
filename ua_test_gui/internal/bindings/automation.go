// automation.go - automation 域的 Wails binding。
package bindings

import (
	"context"
	"errors"
	"fmt"

	"ua_test_gui/internal/automation"
)

// AutomationBinding 暴露给前端的 binding。
type AutomationBinding struct {
	svc *automation.Service
}

// NewAutomationBinding 构造。
func NewAutomationBinding(svc *automation.Service) *AutomationBinding {
	return &AutomationBinding{svc: svc}
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

// _ = context.Background 防止 linter 误删。
var _ = context.Background