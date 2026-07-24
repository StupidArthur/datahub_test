// native.go - Native pytest 模式 Service。
//
// 与 legacy Service 并存,不替换; 通过 NativeRunner 接口隔离子进程实现。
// 默认执行路径仍走 legacy;native mode 由调用方(未来 frontend / CI)显式选择。
package automation

import (
	"context"
	"errors"
	"fmt"
	"os"
	"sync"
	"time"

	"ua_test_gui/internal/adapters/nativepytest"
)

// Re-export from nativepytest so callers can use the automation types
// uniformly without importing the lower-level package.
type (
	CaseStatus     = nativepytest.CaseStatus
	CaseJUnitResult = nativepytest.CaseJUnitResult
)

const (
	NativeStatusJunitPassed  = nativepytest.StatusPassed
	NativeStatusJunitFailed  = nativepytest.StatusFailed
	NativeStatusJunitError   = nativepytest.StatusError
	NativeStatusJunitSkipped = nativepytest.StatusSkipped
	NativeStatusJunitXFail   = nativepytest.StatusXFail
	NativeStatusJunitXPass   = nativepytest.StatusXPass
)

// NativeRunStatus 原生 pytest 模式的运行状态。
type NativeRunStatus string

const (
	NativeStatusIdle     NativeRunStatus = "IDLE"
	NativeStatusRunning  NativeRunStatus = "RUNNING"
	NativeStatusFinished NativeRunStatus = "FINISHED"
	NativeStatusError    NativeRunStatus = "ERROR"
	NativeStatusCanceled NativeRunStatus = "CANCELED"
)

// NativeRun 一次原生 pytest run。
type NativeRun struct {
	ID          string         `json:"id"`
	ManifestPath string         `json:"manifestPath"`
	RunDir      string         `json:"runDir"`
	WorkDir     string         `json:"workDir"`
	PythonExe   string         `json:"pythonExe"`
	Status      NativeRunStatus `json:"status"`
	StartedAt   string         `json:"startedAt,omitempty"`
	FinishedAt  string         `json:"finishedAt,omitempty"`
	ExitCode    *int           `json:"exitCode,omitempty"`
	ErrorMessage string        `json:"errorMessage,omitempty"`
	JUnitPath   string         `json:"junitPath"`
	LogPath     string         `json:"logPath"`
	Cases       []CaseJUnitResult `json:"cases,omitempty"`
}

// NativeRunner 接口: 子进程执行,启动后由 NativeService 通过事件消费结果。
type NativeRunner interface {
	Start(spec NativeStartSpec) error
	Stop(id string) error
	Wait(id string) (int, error)
	LogPath(id string) string
}

// NativeStartSpec 启动参数。
type NativeStartSpec struct {
	RunID    string
	Args     []string
	WorkDir  string
	PythonExe string
	Env      []string
}

// NativeService 原生 pytest 模式入口。
type NativeService struct {
	mu       sync.Mutex
	manifest Manifest
	path     string
	runner   NativeRunner
	active   map[string]*NativeRun
}

// NewNativeService 构造。
func NewNativeService(path string, runner NativeRunner) (*NativeService, error) {
	s := &NativeService{
		path:   path,
		runner: runner,
		active: map[string]*NativeRun{},
	}
	if err := s.ReloadManifest(); err != nil {
		return nil, err
	}
	return s, nil
}

// ReloadManifest 重新读取 manifest 文件。
func (s *NativeService) ReloadManifest() error {
	m, err := LoadManifestFromFile(s.path)
	if err != nil {
		return err
	}
	s.mu.Lock()
	s.manifest = m
	s.mu.Unlock()
	return nil
}

// Manifest 当前已加载的 manifest 副本。
func (s *NativeService) Manifest() Manifest {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.manifest
}

// ListCases 返回 manifest 中所有 case。
func (s *NativeService) ListCases() []ManifestCase {
	return s.Manifest().Cases
}

// RunNative 启动一次原生 pytest run。
func (s *NativeService) RunNative(req NativeRunRequest) (NativeRun, error) {
	if len(req.CaseIDs) == 0 {
		return NativeRun{}, errors.New("caseIDs is empty")
	}
	if req.RunDir == "" {
		return NativeRun{}, errors.New("runDir is empty")
	}
	if req.PythonExe == "" {
		return NativeRun{}, errors.New("pythonExe is empty")
	}
	manifest := s.Manifest()
	if manifest.SchemaVersion == 0 {
		return NativeRun{}, errors.New("manifest not loaded")
	}

	nodeids := make([]string, 0, len(req.CaseIDs))
	for _, id := range req.CaseIDs {
		c, ok := manifest.FindByID(id)
		if !ok {
			return NativeRun{}, fmt.Errorf("case id %q not in manifest", id)
		}
		nodeids = append(nodeids, c.NodeID)
	}

	junitPath, err := nativepytest.SafeJunitPath(req.RunDir, "junit.xml")
	if err != nil {
		return NativeRun{}, err
	}
	logPath := req.RunDir + string('/') + "runner.log"

	args := nativepytest.BuildPytestArgs(req.PythonExe, nodeids, junitPath, "-v")

	run := &NativeRun{
		ID:          req.RunID,
		ManifestPath: s.path,
		RunDir:      req.RunDir,
		WorkDir:     req.WorkDir,
		PythonExe:   req.PythonExe,
		Status:      NativeStatusRunning,
		StartedAt:   time.Now().UTC().Format(time.RFC3339Nano),
		JUnitPath:   junitPath,
		LogPath:     logPath,
	}
	s.mu.Lock()
	s.active[req.RunID] = run
	s.mu.Unlock()

	err = s.runner.Start(NativeStartSpec{
		RunID:     req.RunID,
		Args:      args,
		WorkDir:   req.WorkDir,
		PythonExe: req.PythonExe,
		Env:       req.Env,
	})
	if err != nil {
		s.mu.Lock()
		delete(s.active, req.RunID)
		s.mu.Unlock()
		run.Status = NativeStatusError
		run.ErrorMessage = err.Error()
		return *run, err
	}
	return *run, nil
}

// NativeRunRequest RunNative 入参。
type NativeRunRequest struct {
	RunID     string
	CaseIDs   []string
	RunDir    string
	WorkDir   string
	PythonExe string
	Env       []string
}

// Cancel 取消当前 run。
func (s *NativeService) Cancel(runID string) error {
	s.mu.Lock()
	run, ok := s.active[runID]
	s.mu.Unlock()
	if !ok {
		return fmt.Errorf("unknown run id %q", runID)
	}
	if err := s.runner.Stop(runID); err != nil {
		return err
	}
	run.Status = NativeStatusCanceled
	run.FinishedAt = time.Now().UTC().Format(time.RFC3339Nano)
	return nil
}

// Collect 等待 run 结束并解析 JUnit 结果。
func (s *NativeService) Collect(runID string) (NativeRun, error) {
	s.mu.Lock()
	run, ok := s.active[runID]
	s.mu.Unlock()
	if !ok {
		return NativeRun{}, fmt.Errorf("unknown run id %q", runID)
	}
	if run.Status != NativeStatusRunning {
		return *run, nil
	}

	waitCtx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	done := make(chan struct{})
	go func() {
		_, _ = s.runner.Wait(runID)
		close(done)
	}()

	select {
	case <-done:
	case <-waitCtx.Done():
		run.Status = NativeStatusError
		run.ErrorMessage = "wait timeout"
		return *run, errors.New("wait timeout")
	}

	exitCode, err := s.runner.Wait(runID)
	if err != nil {
		run.Status = NativeStatusError
		run.ErrorMessage = err.Error()
	}
	run.ExitCode = &exitCode
	run.FinishedAt = time.Now().UTC().Format(time.RFC3339Nano)

	junit, jerr := readJUnit(run.JUnitPath)
	if jerr == nil {
		run.Cases = junit
		run.Status = NativeStatusFinished
	} else if run.Status != NativeStatusError {
		run.Status = NativeStatusError
		run.ErrorMessage = jerr.Error()
	}
	return *run, nil
}

// readJUnit 读取文件并解析; 不存在返回错误。
func readJUnit(path string) ([]CaseJUnitResult, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read junit: %w", err)
	}
	return nativepytest.ParseJUnit(b)
}