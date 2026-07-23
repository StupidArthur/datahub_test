// automation_store_test.go - SQLite automation store 单测(用临时 DB)。
package sqlite

import (
	"path/filepath"
	"testing"

	"ua_test_gui/internal/automation"
)

func openTestStore(t *testing.T) *Store {
	t.Helper()
	dir := t.TempDir()
	s, err := OpenStore(filepath.Join(dir, "test.db"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = s.Close() })
	return s
}

func TestAutomationRunLifecycle(t *testing.T) {
	s := openTestStore(t)
	id, err := s.CreateAutomationRun(automation.TestRun{
		RunKey:        "k1",
		Status:        automation.StatusRunning,
		CreatedAt:     "now",
		SelectedCases: []string{"UA-A-1"},
		Total:         1,
		RunDir:        "/tmp/r1",
		ReportPath:    "/tmp/r1/report.json",
		LogPath:       "/tmp/r1/runner.log",
		Note:          "smoke",
	})
	if err != nil {
		t.Fatal(err)
	}
	if id <= 0 {
		t.Fatalf("id=%d", id)
	}

	// patch
	status := automation.StatusFinished
	if err := s.UpdateAutomationRun(id, automation.RunPatch{
		Status:     &status,
		Passed:     intPtr(1),
		Failed:     intPtr(0),
		Progress:   intPtr(1),
	}); err != nil {
		t.Fatal(err)
	}

	// event
	if _, err := s.AddAutomationEvent(automation.TestEvent{
		RunID: id, Ts: "t", EventType: "log", Payload: []byte(`{"msg":"hi"}`),
	}); err != nil {
		t.Fatal(err)
	}
	evs, err := s.ListRunEvents(id, 0, 10)
	if err != nil || len(evs) != 1 {
		t.Fatalf("events=%v err=%v", evs, err)
	}

	// case result
	if _, err := s.UpsertCaseResult(automation.CaseResult{
		RunID: id, CaseID: "UA-A-1", Status: "PASS", DurationMs: 100,
	}); err != nil {
		t.Fatal(err)
	}
	cases, err := s.ListCaseResults(id)
	if err != nil || len(cases) != 1 {
		t.Fatalf("cases=%v err=%v", cases, err)
	}

	// step
	if _, err := s.AddStepResult(automation.StepResult{
		RunID: id, CaseID: "UA-A-1", StepID: "s1", Status: "PASS",
	}); err != nil {
		t.Fatal(err)
	}

	// metric
	val := 12.5
	if _, err := s.AddMetric(automation.Metric{
		RunID: id, CaseID: "UA-A-1", Name: "p95_ms", Value: &val, Unit: "ms",
	}); err != nil {
		t.Fatal(err)
	}

	// evidence
	if _, err := s.AddEvidence(automation.Evidence{
		RunID: id, CaseID: "UA-A-1", Kind: "api", Path: "/tmp/x.json",
	}); err != nil {
		t.Fatal(err)
	}

	// fetch full
	got, err := s.GetAutomationRun(id)
	if err != nil {
		t.Fatal(err)
	}
	if got.Status != automation.StatusFinished {
		t.Fatalf("status=%v", got.Status)
	}
	if got.Passed != 1 {
		t.Fatalf("passed=%d", got.Passed)
	}
	if len(got.SelectedCases) != 1 {
		t.Fatalf("selected=%v", got.SelectedCases)
	}

	// mark interrupted
	if err := s.MarkInterruptedRuns(0); err != nil {
		t.Fatal(err)
	}
}

func intPtr(i int) *int { return &i }