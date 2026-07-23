// model.go - UA 自动化领域模型(plan.md 6.1)。
//
// 包含 RunStatus / TestRun / CaseResult / StepResult / Metric / Evidence / TestEvent。
package automation

import (
	"encoding/json"
	"time"
)

// RunStatus 运行状态。
type RunStatus string

const (
	StatusPending    RunStatus = "PENDING"
	StatusRunning    RunStatus = "RUNNING"
	StatusFinished   RunStatus = "FINISHED"
	StatusFailed     RunStatus = "FAILED"
	StatusError      RunStatus = "ERROR"
	StatusCancelled  RunStatus = "CANCELLED"
	StatusInterrupted RunStatus = "INTERRUPTED"
)

// TestRun 一次自动化任务。
type TestRun struct {
	ID             int64  `json:"id"`
	RunKey         string `json:"runKey"`
	Status         RunStatus `json:"status"`
	CreatedAt      string `json:"createdAt"`
	StartedAt      string `json:"startedAt"`
	FinishedAt     string `json:"finishedAt"`
	SelectedCases  []string `json:"selectedCases"`
	Total          int    `json:"total"`
	Progress       int    `json:"progress"`
	Passed         int    `json:"passed"`
	Failed         int    `json:"failed"`
	Errors         int    `json:"errors"`
	Skipped        int    `json:"skipped"`
	Blocked        int    `json:"blocked"`
	Observed       int    `json:"observed"`
	Measured       int    `json:"measured"`
	CleanupFailed  int    `json:"cleanupFailed"`
	CurrentCaseID  string `json:"currentCaseId"`
	CurrentStep    string `json:"currentStep"`
	PID            int    `json:"pid"`
	ExitCode       *int   `json:"exitCode,omitempty"`
	RunDir         string `json:"runDir"`
	ReportPath     string `json:"reportPath"`
	LogPath        string `json:"logPath"`
	ErrorMessage   string `json:"errorMessage"`
	Note           string `json:"note"`
}

// CaseResult 用例结果。
type CaseResult struct {
	ID            int64  `json:"id"`
	RunID         int64  `json:"runId"`
	CaseID        string `json:"caseId"`
	Title         string `json:"title"`
	Status        string `json:"status"`
	StartedAt     string `json:"startedAt"`
	FinishedAt    string `json:"finishedAt"`
	DurationMs    int64  `json:"durationMs"`
	Summary       string `json:"summary"`
	CleanupStatus string `json:"cleanupStatus"`
	CleanupMessage string `json:"cleanupMessage"`
}

// StepResult 步骤结果。
type StepResult struct {
	ID         int64  `json:"id"`
	RunID      int64  `json:"runId"`
	CaseID     string `json:"caseId"`
	StepID     string `json:"stepId"`
	Title      string `json:"title"`
	Status     string `json:"status"`
	StartedAt  string `json:"startedAt"`
	FinishedAt string `json:"finishedAt"`
	DurationMs int64  `json:"durationMs"`
	Message    string `json:"message"`
}

// Metric 指标。
type Metric struct {
	ID        int64             `json:"id"`
	RunID     int64             `json:"runId"`
	CaseID    string            `json:"caseId"`
	Name      string            `json:"name"`
	Value     *float64          `json:"value,omitempty"`
	TextValue string            `json:"textValue,omitempty"`
	Unit      string            `json:"unit"`
	Labels    map[string]string `json:"labels"`
}

// Evidence 证据。
type Evidence struct {
	ID     int64          `json:"id"`
	RunID  int64          `json:"runId"`
	CaseID string         `json:"caseId"`
	Kind   string         `json:"kind"`
	Path   string         `json:"path"`
	Title  string         `json:"title"`
	Meta   map[string]any `json:"metadata"`
}

// TestEvent 一条原始 NDJSON 事件。
type TestEvent struct {
	ID        int64           `json:"id"`
	RunID     int64           `json:"runId"`
	EventType string          `json:"eventType"`
	CaseID    string          `json:"caseId"`
	Payload   json.RawMessage `json:"payload"`
	Ts        string          `json:"ts"`
}

// Catalog catalog.json 顶层。
type Catalog struct {
	Version    int       `json:"version"`
	GeneratedAt string   `json:"generatedAt"`
	Chapters   []Chapter `json:"chapters"`
}

// Chapter 一个章节。
type Chapter struct {
	ID    string `json:"id"`
	Title string `json:"title"`
	Cases []Case `json:"cases"`
}

// Case catalog 中一个用例条目。
type Case struct {
	ID                 string   `json:"id"`
	Title              string   `json:"title"`
	Kind               string   `json:"kind"`
	Implemented        bool     `json:"implemented"`
	Tags               []string `json:"tags"`
	TimeoutSec         int      `json:"timeoutSec"`
	Destructive        bool     `json:"destructive"`
	ExclusiveResources []string `json:"exclusiveResources"`
	DocPath            string   `json:"docPath"`
	Description        string   `json:"description"`
	Steps              []CaseStep `json:"steps"`
	Assertions         []string `json:"assertions"`
}

// CaseStep 用例的一个步骤。
type CaseStep struct {
	StepID string `json:"stepId"`
	Title  string `json:"title"`
}

// StartRunRequest 启动测试任务的入参。
type StartRunRequest struct {
	SelectedCaseIDs []string `json:"selectedCaseIds"`
	Note            string   `json:"note"`
	AllowPerformance bool     `json:"allowPerformance"`
	RunKey          string   `json:"runKey"`
}

// ListRunsRequest 列出任务的过滤条件。
type ListRunsRequest struct {
	Limit  int    `json:"limit"`
	Status string `json:"status"`
	Keyword string `json:"keyword"`
}

// RunDetail 单 run 的全量详情。
type RunDetail struct {
	Run      TestRun      `json:"run"`
	Cases    []CaseResult `json:"cases"`
	Events   []TestEvent  `json:"events"`
	Metrics  []Metric     `json:"metrics"`
	Evidence []Evidence   `json:"evidence"`
}

// GetEventsRequest 拉事件的过滤条件。
type GetEventsRequest struct {
	RunID  int64 `json:"runId"`
	AfterID int64 `json:"afterId"`
	Limit  int   `json:"limit"`
}

// ReadLogRequest 日志分页读取。
type ReadLogRequest struct {
	RunID  int64 `json:"runId"`
	Offset int64 `json:"offset"`
	Limit  int   `json:"limit"`
}

// LogChunk 日志分片。
type LogChunk struct {
	RunID   int64  `json:"runId"`
	Offset  int64  `json:"offset"`
	Next    int64  `json:"next"`
	EOF     bool   `json:"eof"`
	Content string `json:"content"`
}

// nowRFC3339 工具:生成 UTC RFC3339 时间戳。
func nowRFC3339() string {
	return time.Now().UTC().Format(time.RFC3339Nano)
}