// event.go - NDJSON 事件 -> 数据库投影。
//
// 不允许通过字符串猜状态:每条事件落库,并按 event 类型更新 TestRun 字段。
package automation

import (
	"encoding/json"
	"log/slog"
	"strconv"
)

// EventProjection 把一条事件投影到 run/case/step/metric/evidence/事件表。
//
// 通过传入的 Store 落库;同时返回需要更新到 TestRun 的 RunPatch 字段集合,
// 由调用者(UpdateAutomationRun)合并写入。
func EventProjection(store Store, runID int64, evType string, payload []byte) (RunPatch, error) {
	patch := RunPatch{}
	switch evType {
	case "run_started":
		var p struct {
			Total int `json:"total"`
		}
		if err := json.Unmarshal(payload, &p); err == nil {
			patch.Status = ptrStatus(StatusRunning)
			patch.Total = &p.Total
			patch.Progress = intPtr(0)
		}
	case "case_started":
		var p struct {
			CaseID string `json:"caseId"`
		}
		if err := json.Unmarshal(payload, &p); err == nil && p.CaseID != "" {
			patch.CurrentCaseID = &p.CaseID
			patch.CurrentStep = strPtr("")
		}
	case "step_started":
		var p struct {
			CaseID string `json:"caseId"`
			StepID string `json:"stepId"`
			Title  string `json:"title"`
		}
		if err := json.Unmarshal(payload, &p); err == nil {
			patch.CurrentStep = &p.StepID
			_, _ = store.AddStepResult(StepResult{
				RunID:  runID,
				CaseID: p.CaseID,
				StepID: p.StepID,
				Title:  p.Title,
				Status: "RUNNING",
			})
		}
	case "step_finished":
		var p struct {
			CaseID     string `json:"caseId"`
			StepID     string `json:"stepId"`
			Status     string `json:"status"`
			DurationMs int    `json:"durationMs"`
			Message    string `json:"message"`
		}
		if err := json.Unmarshal(payload, &p); err == nil {
			_, _ = store.AddStepResult(StepResult{
				RunID:      runID,
				CaseID:     p.CaseID,
				StepID:     p.StepID,
				Status:     p.Status,
				DurationMs: int64(p.DurationMs),
				Message:    p.Message,
			})
		}
	case "case_finished":
		var p struct {
			CaseID     string `json:"caseId"`
			Status     string `json:"status"`
			DurationMs int    `json:"durationMs"`
			Summary    string `json:"summary"`
		}
		if err := json.Unmarshal(payload, &p); err == nil {
			id, _ := store.UpsertCaseResult(CaseResult{
				RunID:      runID,
				CaseID:     p.CaseID,
				Status:     p.Status,
				DurationMs: int64(p.DurationMs),
				Summary:    p.Summary,
			})
			_ = id
			// 更新计数
			bumpCounters(&patch, p.Status)
		}
	case "cleanup_finished":
		var p struct {
			CaseID string `json:"caseId"`
			Status string `json:"status"`
			Message string `json:"message"`
		}
		if err := json.Unmarshal(payload, &p); err == nil {
			_, _ = store.UpsertCaseResult(CaseResult{
				RunID:           runID,
				CaseID:          p.CaseID,
				CleanupStatus:   p.Status,
				CleanupMessage:  p.Message,
			})
			if p.Status == "CLEANUP_FAILED" {
				bumpCounters(&patch, p.Status)
			}
		}
	case "metric":
		var p struct {
			CaseID    string            `json:"caseId"`
			Name      string            `json:"name"`
			Value     *float64          `json:"value"`
			TextValue string            `json:"textValue"`
			Unit      string            `json:"unit"`
			Labels    map[string]string `json:"labels"`
		}
		if err := json.Unmarshal(payload, &p); err == nil && p.Name != "" {
			_, _ = store.AddMetric(Metric{
				RunID:     runID,
				CaseID:    p.CaseID,
				Name:      p.Name,
				Value:     p.Value,
				TextValue: p.TextValue,
				Unit:      p.Unit,
				Labels:    p.Labels,
			})
		}
	case "evidence":
		var p struct {
			CaseID string         `json:"caseId"`
			Kind   string         `json:"kind"`
			Path   string         `json:"path"`
			Title  string         `json:"title"`
			Meta   map[string]any `json:"metadata"`
		}
		if err := json.Unmarshal(payload, &p); err == nil && p.Path != "" {
			_, _ = store.AddEvidence(Evidence{
				RunID:  runID,
				CaseID: p.CaseID,
				Kind:   p.Kind,
				Path:   p.Path,
				Title:  p.Title,
				Meta:   p.Meta,
			})
		}
	case "run_finished":
		var p struct {
			Status   string `json:"status"`
			Total    int    `json:"total"`
			Passed   int    `json:"passed"`
			Failed   int    `json:"failed"`
			Errors   int    `json:"errors"`
			Skipped  int    `json:"skipped"`
			Blocked  int    `json:"blocked"`
			Observed int    `json:"observed"`
			Measured int    `json:"measured"`
			CleanupFailed int `json:"cleanupFailed"`
		}
		if err := json.Unmarshal(payload, &p); err == nil {
			st := RunStatus(p.Status)
			patch.Status = &st
			patch.Total = &p.Total
			patch.Passed = &p.Passed
			patch.Failed = &p.Failed
			patch.Errors = &p.Errors
			patch.Skipped = &p.Skipped
			patch.Blocked = &p.Blocked
			patch.Observed = &p.Observed
			patch.Measured = &p.Measured
			patch.CleanupFailed = &p.CleanupFailed
			progress := p.Passed + p.Failed + p.Errors + p.Skipped + p.Observed + p.Measured + p.CleanupFailed
			patch.Progress = &progress
		}
	default:
		// log / protocol_error: 仅落 events 表
		slog.Debug("event projection: ignored", "type", evType)
	}
	return patch, nil
}

func bumpCounters(p *RunPatch, status string) {
	inc := func(p **int) {
		if *p == nil {
			*p = intPtr(1)
			return
		}
		v := **p + 1
		*p = &v
	}
	progress := 1
	if p.Progress != nil {
		progress = *p.Progress + 1
	}
	p.Progress = &progress
	switch status {
	case "PASS":
		inc(&p.Passed)
	case "FAIL":
		inc(&p.Failed)
	case "ERROR":
		inc(&p.Errors)
	case "SKIP":
		inc(&p.Skipped)
	case "BLOCKED":
		inc(&p.Blocked)
	case "OBSERVED":
		inc(&p.Observed)
	case "MEASURED":
		inc(&p.Measured)
	case "CLEANUP_FAILED":
		inc(&p.CleanupFailed)
	}
}

func intPtr(i int) *int    { return &i }
func strPtr(s string) *string { return &s }
func ptrStatus(s RunStatus) *RunStatus { return &s }

// FormatExitCode 安全格式化 exit code。
func FormatExitCode(c *int) string {
	if c == nil {
		return ""
	}
	return strconv.Itoa(*c)
}