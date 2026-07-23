// ports.go - 自动化层接口。
//
// Store 接口(plan.md 6.2)由 sqlite 包实现;Runner 由 pytestrunner 实现;
// Service 通过这两个接口协作。
package automation

// Store 自动化 SQLite 持久化接口。
type Store interface {
	CreateAutomationRun(run TestRun) (int64, error)
	UpdateAutomationRun(runID int64, patch RunPatch) error
	GetAutomationRun(runID int64) (TestRun, error)
	ListAutomationRuns(filter ListRunsRequest) ([]TestRun, error)

	AddAutomationEvent(ev TestEvent) (int64, error)
	ListRunEvents(runID int64, afterID int64, limit int) ([]TestEvent, error)

	UpsertCaseResult(cr CaseResult) (int64, error)
	ListCaseResults(runID int64) ([]CaseResult, error)

	AddStepResult(s StepResult) (int64, error)

	AddMetric(m Metric) (int64, error)
	ListMetrics(runID int64) ([]Metric, error)

	AddEvidence(e Evidence) (int64, error)
	ListEvidence(runID int64) ([]Evidence, error)

	MarkInterruptedRuns(activePID int) error
}

// RunPatch 用于更新 run 的非空字段。
type RunPatch struct {
	Status         *RunStatus
	StartedAt      *string
	FinishedAt     *string
	Total          *int
	Progress       *int
	Passed         *int
	Failed         *int
	Errors         *int
	Skipped        *int
	Blocked        *int
	Observed       *int
	Measured       *int
	CleanupFailed  *int
	CurrentCaseID  *string
	CurrentStep    *string
	PID            *int
	ExitCode       *int
	ReportPath     *string
	LogPath        *string
	ErrorMessage   *string
}

// Runner 抽象 Python runner 子进程。
type Runner interface {
	Start(spec StartSpec, onEvent func(EvEnvelope), onLog func(string)) (ProcessInfo, error)
	Stop(runKey string) error
	Active() *ProcessInfo
}

// StartSpec 启动参数。
type StartSpec struct {
	RunID         string
	RunKey        string
	PythonExe     string
	RunnerArgs    []string
	WorkDir       string
	RunDir        string
	EvidenceDir   string
	ReportPath    string
	RunConfigPath string
}

// ProcessInfo 子进程信息。
type ProcessInfo struct {
	RunKey  string `json:"runKey"`
	PID     int    `json:"pid"`
	Started string `json:"started"`
}

// EvEnvelope 事件投递的轻量封装(避免循环引用)。
type EvEnvelope struct {
	RunID     int64
	EventType string
	CaseID    string
	Payload   []byte
	Ts        string
}