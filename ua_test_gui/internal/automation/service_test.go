// service_test.go - Service.StartTestRun 关键路径单测(用 fake store/runner)。
package automation

import (
	"errors"
	"sync"
	"testing"
)

type fakeRunner struct {
	mu     sync.Mutex
	active *ProcessInfo
}

func (f *fakeRunner) Start(spec StartSpec, onEvent func(EvEnvelope), onLog func(string)) (ProcessInfo, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.active != nil {
		return ProcessInfo{}, errors.New("busy")
	}
	f.active = &ProcessInfo{RunKey: spec.RunKey, PID: 9999, Started: spec.RunID}
	go func() {
		// 模拟发送 run_finished
		if onEvent != nil {
			onEvent(EvEnvelope{RunID: 1, EventType: "run_finished", Ts: "now", Payload: []byte(`{"status":"FINISHED","total":1,"passed":1}`)})
		}
	}()
	return *f.active, nil
}

func (f *fakeRunner) Stop(key string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.active = nil
	return nil
}

func (f *fakeRunner) Active() *ProcessInfo {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.active == nil {
		return nil
	}
	c := *f.active
	return &c
}

func TestService_StartStopRun(t *testing.T) {
	s := &mockStore{}
	r := &fakeRunner{}
	catalog := Catalog{Version: 1, Chapters: []Chapter{
		{ID: "UA-A", Cases: []Case{{ID: "UA-A-1", Kind: "regression", Implemented: true}}},
	}}
	paths := DefaultPaths()
	svc := NewService(s, r, paths, catalog, "python", "", nil)
	run, err := svc.StartTestRun(StartRunRequest{SelectedCaseIDs: []string{"UA-A-1"}})
	if err != nil {
		t.Fatal(err)
	}
	if run.Status != StatusRunning {
		t.Fatalf("status=%v", run.Status)
	}
	if run.PID != 9999 {
		t.Fatalf("pid=%d", run.PID)
	}
	if _, err := svc.StopTestRun(run.ID); err != nil {
		t.Fatal(err)
	}
}

func TestService_RejectsPerformanceWithoutAllow(t *testing.T) {
	s := &mockStore{}
	r := &fakeRunner{}
	catalog := Catalog{Version: 1, Chapters: []Chapter{
		{ID: "UA-B", Cases: []Case{{ID: "UA-B-1", Kind: "performance"}}},
	}}
	paths := DefaultPaths()
	svc := NewService(s, r, paths, catalog, "python", "", nil)
	_, err := svc.StartTestRun(StartRunRequest{SelectedCaseIDs: []string{"UA-B-1"}})
	if err == nil {
		t.Fatal("expected error for performance without allowPerformance")
	}
}

func TestService_AllowsPerformanceWithFlag(t *testing.T) {
	s := &mockStore{}
	r := &fakeRunner{}
	catalog := Catalog{Version: 1, Chapters: []Chapter{
		{ID: "UA-B", Cases: []Case{{ID: "UA-B-1", Kind: "performance"}}},
	}}
	paths := DefaultPaths()
	svc := NewService(s, r, paths, catalog, "python", "", nil)
	run, err := svc.StartTestRun(StartRunRequest{SelectedCaseIDs: []string{"UA-B-1"}, AllowPerformance: true})
	if err != nil {
		t.Fatal(err)
	}
	if run.Status != StatusRunning {
		t.Fatalf("status=%v", run.Status)
	}
}

func TestService_RejectsUnknownCaseID(t *testing.T) {
	s := &mockStore{}
	r := &fakeRunner{}
	catalog := Catalog{Version: 1, Chapters: []Chapter{
		{ID: "UA-A", Cases: []Case{{ID: "UA-A-1", Kind: "regression"}}},
	}}
	svc := NewService(s, r, DefaultPaths(), catalog, "python", "", nil)
	_, err := svc.StartTestRun(StartRunRequest{SelectedCaseIDs: []string{"NOPE"}})
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestService_RejectSecondRun(t *testing.T) {
	s := &mockStore{}
	r := &fakeRunner{}
	catalog := Catalog{Version: 1, Chapters: []Chapter{{ID: "UA-A", Cases: []Case{{ID: "UA-A-1", Kind: "regression"}}}}}
	svc := NewService(s, r, DefaultPaths(), catalog, "python", "", nil)
	if _, err := svc.StartTestRun(StartRunRequest{SelectedCaseIDs: []string{"UA-A-1"}}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.StartTestRun(StartRunRequest{SelectedCaseIDs: []string{"UA-A-1"}}); err == nil {
		t.Fatal("expected error")
	}
}