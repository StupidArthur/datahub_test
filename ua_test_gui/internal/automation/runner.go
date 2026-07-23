// runner.go - 任务编排与进程协调。
//
// 不重写 115 个用例逻辑;只负责:
//   - 校验前置条件
//   - 写 run-config.json
//   - 启动/停止 Python runner
//   - 解析 NDJSON 事件并投影到 SQLite
//   - 转发 Wails 事件
//   - 处理 INTERRUPTED 恢复
package automation

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"
)

// Service 业务编排入口。
type Service struct {
	mu        sync.Mutex
	store     Store
	runner    Runner
	paths     Paths
	catalog   Catalog
	catalogMu sync.RWMutex
	notifier  Notifier
	pythonExe string
	workdir   string
}

// Notifier 把事件转发给前端(由 Wails bindings 注入)。
type Notifier interface {
	RunUpdated(run TestRun)
	CaseUpdated(runID int64, cr CaseResult)
	StepUpdated(runID int64, sr StepResult)
	Log(runID int64, line string)
	Metric(runID int64, m Metric)
	Evidence(runID int64, e Evidence)
}

// NewService 构造。
func NewService(store Store, runner Runner, paths Paths, catalog Catalog, pythonExe, workdir string, notifier Notifier) *Service {
	return &Service{
		store:     store,
		runner:    runner,
		paths:     paths,
		catalog:   catalog,
		pythonExe: pythonExe,
		workdir:   workdir,
		notifier:  notifier,
	}
}

// SetCatalog 动态更新 catalog(导出后调用)。
func (s *Service) SetCatalog(c Catalog) {
	s.catalogMu.Lock()
	s.catalog = c
	s.catalogMu.Unlock()
}

// Catalog 返回当前 catalog(只读快照)。
func (s *Service) Catalog() Catalog {
	s.catalogMu.RLock()
	defer s.catalogMu.RUnlock()
	return s.catalog
}

// StartTestRun 前置检查 + 启动。
func (s *Service) StartTestRun(req StartRunRequest) (TestRun, error) {
	if s.runner.Active() != nil {
		return TestRun{}, errors.New("another automation run is active")
	}
	if len(req.SelectedCaseIDs) == 0 {
		return TestRun{}, errors.New("selectedCaseIds is empty")
	}
	catalog := s.Catalog()
	if err := catalog.ValidateCaseIDs(req.SelectedCaseIDs); err != nil {
		return TestRun{}, err
	}
	// 性能用例必须显式确认
	for _, id := range req.SelectedCaseIDs {
		cs, _ := catalog.FindCase(id)
		if cs.Kind == "performance" && !req.AllowPerformance {
			return TestRun{}, fmt.Errorf("case %s is performance; require allowPerformance=true", id)
		}
	}

	runID := NewRunID()
	runDir, err := s.paths.NewRunDir(runID)
	if err != nil {
		return TestRun{}, err
	}
	evidenceDir := runDir + string('/') + "evidence"
	reportPath := runDir + string('/') + "report.json"
	logPath := runDir + string('/') + "runner.log"

	cfgJSON, err := buildRunConfigJSON(runID, req.SelectedCaseIDs)
	if err != nil {
		return TestRun{}, err
	}
	cfgPath, err := WriteRunConfig(runDir, cfgJSON)
	if err != nil {
		return TestRun{}, err
	}

	run := TestRun{
		RunKey:        req.RunKey,
		Status:        StatusPending,
		CreatedAt:     nowRFC3339(),
		SelectedCases: req.SelectedCaseIDs,
		Total:         len(req.SelectedCaseIDs),
		RunDir:        runDir,
		ReportPath:    reportPath,
		LogPath:       logPath,
		Note:          req.Note,
	}
	id, err := s.store.CreateAutomationRun(run)
	if err != nil {
		return TestRun{}, err
	}
	run.ID = id

	startedPatch := RunPatch{
		Status:    ptrStatus(StatusRunning),
		StartedAt: strPtr(nowRFC3339()),
	}
	_ = s.store.UpdateAutomationRun(id, startedPatch)
	run.Status = StatusRunning
	run.StartedAt = startedPatch.StartedAtAt()

	// 启动 Python runner
	args := []string{"-m", "ua_test_harness.cli", "run", "--config", cfgPath}
	pi, err := s.runner.Start(StartSpec{
		RunID:         runID,
		RunKey:        req.RunKey,
		PythonExe:     s.pythonExe,
		RunnerArgs:    args,
		WorkDir:       s.workdir,
		RunDir:        runDir,
		EvidenceDir:   evidenceDir,
		ReportPath:    reportPath,
		RunConfigPath: cfgPath,
	}, func(env EvEnvelope) {
		s.onEvent(id, env)
	}, func(line string) {
		if s.notifier != nil {
			s.notifier.Log(id, line)
		}
	})
	if err != nil {
		failed := RunPatch{
			Status:       ptrStatus(StatusError),
			FinishedAt:   strPtr(nowRFC3339()),
			ErrorMessage: strPtr(err.Error()),
		}
		_ = s.store.UpdateAutomationRun(id, failed)
		run.Status = StatusError
		run.ErrorMessage = err.Error()
		return run, err
	}
	pidPatch := RunPatch{PID: &pi.PID}
	_ = s.store.UpdateAutomationRun(id, pidPatch)
	run.PID = pi.PID

	if s.notifier != nil {
		s.notifier.RunUpdated(run)
	}
	return run, nil
}

// StopTestRun 主动取消 active run。
func (s *Service) StopTestRun(runID int64) (TestRun, error) {
	r, err := s.store.GetAutomationRun(runID)
	if err != nil {
		return r, err
	}
	if err := s.runner.Stop(r.RunKey); err != nil {
		return r, err
	}
	patch := RunPatch{Status: ptrStatus(StatusCancelled), FinishedAt: strPtr(nowRFC3339())}
	_ = s.store.UpdateAutomationRun(runID, patch)
	r.Status = StatusCancelled
	r.FinishedAt = patch.FinishedAtAt()
	if s.notifier != nil {
		s.notifier.RunUpdated(r)
	}
	return r, nil
}

// GetActiveTestRun 返回正在运行的 run。
func (s *Service) GetActiveTestRun() (*TestRun, error) {
	runs, err := s.store.ListAutomationRuns(ListRunsRequest{Limit: 50})
	if err != nil {
		return nil, err
	}
	for _, r := range runs {
		if r.Status == StatusRunning {
			rr := r
			return &rr, nil
		}
	}
	return nil, nil
}

// ListTestRuns 列出。
func (s *Service) ListTestRuns(req ListRunsRequest) ([]TestRun, error) {
	if req.Limit <= 0 || req.Limit > 500 {
		req.Limit = 100
	}
	return s.store.ListAutomationRuns(req)
}

// GetTestRunDetail 详情。
func (s *Service) GetTestRunDetail(runID int64) (RunDetail, error) {
	r, err := s.store.GetAutomationRun(runID)
	if err != nil {
		return RunDetail{}, err
	}
	cases, _ := s.store.ListCaseResults(runID)
	events, _ := s.store.ListRunEvents(runID, 0, 500)
	metrics, _ := s.store.ListMetrics(runID)
	evidence, _ := s.store.ListEvidence(runID)
	return RunDetail{Run: r, Cases: cases, Events: events, Metrics: metrics, Evidence: evidence}, nil
}

// GetRunEvents 增量拉取。
func (s *Service) GetRunEvents(req GetEventsRequest) ([]TestEvent, error) {
	if req.Limit <= 0 || req.Limit > 500 {
		req.Limit = 200
	}
	return s.store.ListRunEvents(req.RunID, req.AfterID, req.Limit)
}

// onEvent 处理一条事件:落库 + 投影 + 通知。
func (s *Service) onEvent(runID int64, env EvEnvelope) {
	if s.store == nil {
		return
	}
	if _, err := s.store.AddAutomationEvent(TestEvent{
		RunID:     runID,
		EventType: env.EventType,
		CaseID:    env.CaseID,
		Payload:   env.Payload,
		Ts:        env.Ts,
	}); err != nil {
		slog.Warn("add event failed", "err", err)
	}
	patch, err := EventProjection(s.store, runID, env.EventType, env.Payload)
	if err != nil {
		slog.Warn("project event failed", "err", err, "type", env.EventType)
		return
	}
	if hasPatch(patch) {
		_ = s.store.UpdateAutomationRun(runID, patch)
	}
	if s.notifier != nil {
		if env.EventType == "case_finished" {
			// 简化:整 case 触发一次通知(后续按 cr 重新读)
			if cr, err := s.fetchCaseByID(runID, env.CaseID); err == nil {
				s.notifier.CaseUpdated(runID, cr)
			}
		}
		if env.EventType == "step_finished" {
			var sr StepResult
			if err := json.Unmarshal(env.Payload, &struct {
				*StepResult
			}{StepResult: &sr}); err == nil {
				s.notifier.StepUpdated(runID, sr)
			}
		}
		if env.EventType == "metric" {
			var m Metric
			if err := json.Unmarshal(env.Payload, &m); err == nil {
				s.notifier.Metric(runID, m)
			}
		}
		if env.EventType == "evidence" {
			var e Evidence
			if err := json.Unmarshal(env.Payload, &e); err == nil {
				s.notifier.Evidence(runID, e)
			}
		}
		if env.EventType == "run_finished" {
			r, _ := s.store.GetAutomationRun(runID)
			s.notifier.RunUpdated(r)
		}
	}
}

func (s *Service) fetchCaseByID(runID int64, caseID string) (CaseResult, error) {
	cases, _ := s.store.ListCaseResults(runID)
	for _, c := range cases {
		if c.CaseID == caseID {
			return c, nil
		}
	}
	return CaseResult{}, fmt.Errorf("case not found: %s", caseID)
}

func hasPatch(p RunPatch) bool {
	return p.Status != nil || p.StartedAt != nil || p.FinishedAt != nil ||
		p.Total != nil || p.Progress != nil || p.Passed != nil || p.Failed != nil ||
		p.Errors != nil || p.Skipped != nil || p.Blocked != nil || p.Observed != nil ||
		p.Measured != nil || p.CleanupFailed != nil || p.CurrentCaseID != nil ||
		p.CurrentStep != nil || p.PID != nil || p.ExitCode != nil || p.ReportPath != nil ||
		p.LogPath != nil || p.ErrorMessage != nil
}

// RecoverInterruptedRun 启动时将遗留 RUNNING 标记为 INTERRUPTED(plan.md 7)。
func (s *Service) RecoverInterruptedRun(activePID int) error {
	if s.store == nil {
		return nil
	}
	return s.store.MarkInterruptedRuns(activePID)
}

// buildRunConfigJSON 构造 run-config.json。
//
// 当前实现从环境/前端 binding 注入(StartTestRun 调用方传入凭证快照),这里留接口。
// 为保证可独立运行,实际由调用方通过 buildRunConfigJSONWith 构造。
func buildRunConfigJSON(runID string, caseIDs []string) ([]byte, error) {
	return buildRunConfigJSONWith(runID, caseIDs, SubjectSnapshot{}, "", MockSnapshot{})
}

// SubjectSnapshot 启动时携带的凭据快照(plan.md 6.5)。
type SubjectSnapshot struct {
	BaseURL  string `json:"baseUrl"`
	Username string `json:"username"`
	Password string `json:"password"`
	TenantID string `json:"tenantId"`
	Token    string `json:"token"`
}

// BuildRunConfigJSONWith 构建 run-config.json,完整字段。
func BuildRunConfigJSONWith(runID string, caseIDs []string, sub SubjectSnapshot, localIP string, mock MockSnapshot) ([]byte, error) {
	return buildRunConfigJSONWith(runID, caseIDs, sub, localIP, mock)
}

// MockSnapshot 启动时携带的 mock 配置。
type MockSnapshot struct {
	Functional string `json:"functional"`
	Reconnect  string `json:"reconnect"`
	Performance string `json:"performance"`
	Abnormal   string `json:"abnormal"`
}

func buildRunConfigJSONWith(runID string, caseIDs []string, sub SubjectSnapshot, localIP string, mock MockSnapshot) ([]byte, error) {
	cfg := map[string]any{
		"runId":          runID,
		"selectedCaseIds": caseIDs,
		"subject": map[string]string{
			"baseUrl":  sub.BaseURL,
			"tenantId": sub.TenantID,
			"username": sub.Username,
			"password": sub.Password,
			"token":    sub.Token,
		},
		"localIp": localIP,
		"mock": map[string]any{
			"controlMode": "wails-managed",
			"endpoints": map[string]string{
				"functional":  mock.Functional,
				"reconnect":   mock.Reconnect,
				"performance": mock.Performance,
				"abnormal":    mock.Abnormal,
			},
		},
		"timeouts": map[string]int{
			"pollIntervalMs":     500,
			"rtVisibilitySec":    30,
			"historyVisibilitySec": 120,
			"dsConnectSec":       60,
		},
	}
	return json.MarshalIndent(cfg, "", "  ")
}

// Patch 便捷方法:取指针字段值。
func (p RunPatch) FinishedAtAt() string {
	if p.FinishedAt == nil {
		return ""
	}
	return *p.FinishedAt
}

func (p RunPatch) StartedAtAt() string {
	if p.StartedAt == nil {
		return ""
	}
	return *p.StartedAt
}

// Sleep 仅用于 Service 内部短暂等待(测试中可替为 time.Sleep)。
var Sleep = time.Sleep

// Ctx 是空导出别名,避免 service.go 重复 import context。
type Ctx = context.Context