// event_test.go - NDJSON 事件投影单测。
package automation

import (
	"encoding/json"
	"sync"
	"testing"
)

// mockStore 实现 Store 接口,记录调用。
type mockStore struct {
	mu       sync.Mutex
	events   []TestEvent
	caseResults []CaseResult
	steps    []StepResult
	metrics  []Metric
	evidence []Evidence
	runPatches []RunPatch
}

func (m *mockStore) CreateAutomationRun(r TestRun) (int64, error) { return 1, nil }
func (m *mockStore) GetAutomationRun(id int64) (TestRun, error)    { return TestRun{ID: id}, nil }
func (m *mockStore) ListAutomationRuns(_ ListRunsRequest) ([]TestRun, error) { return nil, nil }
func (m *mockStore) MarkInterruptedRuns(_ int) error { return nil }

func (m *mockStore) AddAutomationEvent(ev TestEvent) (int64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.events = append(m.events, ev)
	return int64(len(m.events)), nil
}
func (m *mockStore) ListRunEvents(_ int64, _ int64, _ int) ([]TestEvent, error) {
	return m.events, nil
}

func (m *mockStore) UpsertCaseResult(cr CaseResult) (int64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	for i, e := range m.caseResults {
		if e.RunID == cr.RunID && e.CaseID == cr.CaseID {
			m.caseResults[i] = cr
			return int64(i + 1), nil
		}
	}
	m.caseResults = append(m.caseResults, cr)
	return int64(len(m.caseResults)), nil
}
func (m *mockStore) ListCaseResults(_ int64) ([]CaseResult, error) { return m.caseResults, nil }

func (m *mockStore) AddStepResult(s StepResult) (int64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.steps = append(m.steps, s)
	return int64(len(m.steps)), nil
}
func (m *mockStore) AddMetric(mt Metric) (int64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.metrics = append(m.metrics, mt)
	return int64(len(m.metrics)), nil
}
func (m *mockStore) ListMetrics(_ int64) ([]Metric, error) { return m.metrics, nil }
func (m *mockStore) AddEvidence(e Evidence) (int64, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.evidence = append(m.evidence, e)
	return int64(len(m.evidence)), nil
}
func (m *mockStore) ListEvidence(_ int64) ([]Evidence, error) { return m.evidence, nil }

func (m *mockStore) UpdateAutomationRun(_ int64, p RunPatch) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.runPatches = append(m.runPatches, p)
	return nil
}

func TestProjection_RunStarted(t *testing.T) {
	s := &mockStore{}
	payload, _ := json.Marshal(map[string]any{"total": 5})
	patch, err := EventProjection(s, 1, "run_started", payload)
	if err != nil {
		t.Fatal(err)
	}
	if patch.Status == nil || *patch.Status != StatusRunning {
		t.Fatalf("status=%v", patch.Status)
	}
	if patch.Total == nil || *patch.Total != 5 {
		t.Fatalf("total=%v", patch.Total)
	}
}

func TestProjection_CaseFinished_BumpsCounters(t *testing.T) {
	s := &mockStore{}
	payload, _ := json.Marshal(map[string]any{"caseId": "UA-1", "status": "PASS", "durationMs": 100})
	_, err := EventProjection(s, 1, "case_finished", payload)
	if err != nil {
		t.Fatal(err)
	}
	if len(s.caseResults) != 1 || s.caseResults[0].Status != "PASS" {
		t.Fatalf("caseResults=%+v", s.caseResults)
	}
}

func TestProjection_RunFinished(t *testing.T) {
	s := &mockStore{}
	payload, _ := json.Marshal(map[string]any{
		"status": "FINISHED", "total": 3, "passed": 2, "failed": 1,
		"observed": 0, "measured": 0, "cleanupFailed": 0,
	})
	patch, err := EventProjection(s, 1, "run_finished", payload)
	if err != nil {
		t.Fatal(err)
	}
	if patch.Status == nil || *patch.Status != StatusFinished {
		t.Fatalf("status=%v", patch.Status)
	}
	if patch.Passed == nil || *patch.Passed != 2 {
		t.Fatalf("passed=%v", patch.Passed)
	}
	if patch.Progress == nil || *patch.Progress != 3 {
		t.Fatalf("progress=%v", patch.Progress)
	}
}

func TestProjection_Unknown_NoOp(t *testing.T) {
	s := &mockStore{}
	payload := []byte(`{"hello":"world"}`)
	if _, err := EventProjection(s, 1, "log", payload); err != nil {
		t.Fatal(err)
	}
	if len(s.runPatches) != 0 {
		t.Fatalf("expected no patch for log, got %+v", s.runPatches)
	}
}

func TestProjection_Metric(t *testing.T) {
	s := &mockStore{}
	payload, _ := json.Marshal(map[string]any{"caseId": "UA-1", "name": "p95_ms", "value": 12.5, "unit": "ms"})
	if _, err := EventProjection(s, 1, "metric", payload); err != nil {
		t.Fatal(err)
	}
	if len(s.metrics) != 1 || s.metrics[0].Name != "p95_ms" {
		t.Fatalf("metrics=%+v", s.metrics)
	}
}