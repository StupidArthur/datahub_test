// native_test.go - NativeService 单测(使用 fake runner, 不开真实子进程)。
package automation

import (
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"ua_test_gui/internal/adapters/nativepytest"
)

const nativeSampleManifest = `{
  "schemaVersion": 1,
  "cases": [
    {"id":"UA-1-1-01","chapter":"UA-1-1","title":"t","nodeid":"tests/a.py::t_one"},
    {"id":"UA-1-1-02","chapter":"UA-1-1","title":"t","nodeid":"tests/a.py::t_two"}
  ]
}`

const nativeSampleJUnit = `<?xml version="1.0"?>
<testsuites><testsuite>
  <testcase classname="tests.a" name="t_one" time="0.01"/>
  <testcase classname="tests.a" name="t_two" time="0.02">
    <failure message="x">assert 1==2</failure>
  </testcase>
</testsuite></testsuites>`

type fakeNativeRunner struct {
	mu        sync.Mutex
	started   map[string]NativeStartSpec
	finished  map[string]int
	logFiles  map[string]string
}

func newFakeRunner() *fakeNativeRunner {
	return &fakeNativeRunner{
		started:  map[string]NativeStartSpec{},
		finished: map[string]int{},
		logFiles: map[string]string{},
	}
}

func (f *fakeNativeRunner) Start(spec NativeStartSpec) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.started[spec.RunID] = spec
	return nil
}

func (f *fakeNativeRunner) Stop(id string) error { return nil }

func (f *fakeNativeRunner) Wait(id string) (int, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.finished[id], nil
}

func (f *fakeNativeRunner) LogPath(id string) string {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.logFiles[id]
}

func (f *fakeNativeRunner) markFinished(id string, code int) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.finished[id] = code
}

func writeManifest(t *testing.T, dir string) string {
	t.Helper()
	p := filepath.Join(dir, "manifest.json")
	if err := os.WriteFile(p, []byte(nativeSampleManifest), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestNewNativeService_OK(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	svc, err := NewNativeService(p, newFakeRunner())
	if err != nil {
		t.Fatal(err)
	}
	if got := len(svc.ListCases()); got != 2 {
		t.Fatalf("cases=%d", got)
	}
}

func TestNewNativeService_MissingFile(t *testing.T) {
	_, err := NewNativeService(filepath.Join(t.TempDir(), "missing.json"), newFakeRunner())
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestRunNative_BuildsCorrectArgs(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	runDir := t.TempDir()
	runner := newFakeRunner()
	svc, err := NewNativeService(p, runner)
	if err != nil {
		t.Fatal(err)
	}

	run, err := svc.RunNative(NativeRunRequest{
		RunID:     "run-1",
		CaseIDs:   []string{"UA-1-1-01", "UA-1-1-02"},
		RunDir:    runDir,
		WorkDir:   "/repo",
		PythonExe: "python",
	})
	if err != nil {
		t.Fatal(err)
	}
	if run.Status != NativeStatusRunning {
		t.Fatalf("status=%s", run.Status)
	}

	spec, ok := runner.started["run-1"]
	if !ok {
		t.Fatal("runner did not record start")
	}
	want := []string{"-m", "pytest", "-v",
		"tests/a.py::t_one", "tests/a.py::t_two",
		"--junitxml=" + filepath.Join(runDir, "junit.xml"),
	}
	if !slicesEqual(spec.Args, want) {
		t.Fatalf("args=%v want=%v", spec.Args, want)
	}
}

func TestRunNative_RejectsUnknownID(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	runner := newFakeRunner()
	svc, _ := NewNativeService(p, runner)
	_, err := svc.RunNative(NativeRunRequest{
		RunID: "r", CaseIDs: []string{"NOPE"}, RunDir: t.TempDir(), PythonExe: "python",
	})
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestRunNative_RejectsEmptyCaseIDs(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	svc, _ := NewNativeService(p, newFakeRunner())
	_, err := svc.RunNative(NativeRunRequest{RunID: "r", RunDir: t.TempDir(), PythonExe: "p"})
	if err == nil {
		t.Fatal("expected error for empty caseIDs")
	}
}

func TestRunNative_RejectsUnsafeJunitPath(t *testing.T) {
	// 直接走 nativepytest.SafeJunitPath 验证:不在 runDir 子路径下被拒绝
	if _, err := nativepytest.SafeJunitPath(t.TempDir(), "../escape.xml"); err == nil {
		t.Fatal("expected error")
	}
}

func TestCollect_ParsesJUnitAndMarksFinished(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	runDir := t.TempDir()
	if err := os.WriteFile(filepath.Join(runDir, "junit.xml"), []byte(nativeSampleJUnit), 0o644); err != nil {
		t.Fatal(err)
	}
	runner := newFakeRunner()
	svc, _ := NewNativeService(p, runner)

	_, err := svc.RunNative(NativeRunRequest{
		RunID: "r1", CaseIDs: []string{"UA-1-1-01", "UA-1-1-02"},
		RunDir: runDir, PythonExe: "python",
	})
	if err != nil {
		t.Fatal(err)
	}
	runner.markFinished("r1", 1)
	collected, err := svc.Collect("r1")
	if err != nil {
		t.Fatal(err)
	}
	if collected.Status != NativeStatusFinished {
		t.Fatalf("status=%s", collected.Status)
	}
	if len(collected.Cases) != 2 {
		t.Fatalf("cases=%d", len(collected.Cases))
	}
	if collected.Cases[0].Status != NativeStatusJunitPassed || collected.Cases[1].Status != NativeStatusJunitFailed {
		t.Fatalf("statuses=%v", collected.Cases)
	}
}

func TestCollect_MissingJUnitIsError(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	runDir := t.TempDir()
	runner := newFakeRunner()
	svc, _ := NewNativeService(p, runner)
	if _, err := svc.RunNative(NativeRunRequest{
		RunID: "r2", CaseIDs: []string{"UA-1-1-01"},
		RunDir: runDir, PythonExe: "python",
	}); err != nil {
		t.Fatal(err)
	}
	runner.markFinished("r2", 0)
	got, _ := svc.Collect("r2")
	if got.Status != NativeStatusError {
		t.Fatalf("expected ERROR, got %s", got.Status)
	}
}

func TestCancel_MarksCanceled(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	runner := newFakeRunner()
	svc, _ := NewNativeService(p, runner)
	if _, err := svc.RunNative(NativeRunRequest{
		RunID: "r3", CaseIDs: []string{"UA-1-1-01"},
		RunDir: t.TempDir(), PythonExe: "python",
	}); err != nil {
		t.Fatal(err)
	}
	if err := svc.Cancel("r3"); err != nil {
		t.Fatal(err)
	}
}

func TestCancel_UnknownID(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	svc, _ := NewNativeService(p, newFakeRunner())
	if err := svc.Cancel("nope"); err == nil {
		t.Fatal("expected error")
	}
}

func TestReloadManifest(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	svc, _ := NewNativeService(p, newFakeRunner())
	if len(svc.ListCases()) != 2 {
		t.Fatalf("expected 2 cases")
	}
	if err := svc.ReloadManifest(); err != nil {
		t.Fatal(err)
	}
}

func TestNativeRun_TimestampFormat(t *testing.T) {
	dir := t.TempDir()
	p := writeManifest(t, dir)
	svc, _ := NewNativeService(p, newFakeRunner())
	run, _ := svc.RunNative(NativeRunRequest{
		RunID: "r4", CaseIDs: []string{"UA-1-1-01"},
		RunDir: t.TempDir(), PythonExe: "python",
	})
	if run.StartedAt == "" {
		t.Fatal("startedAt should be set")
	}
	if _, err := time.Parse(time.RFC3339Nano, run.StartedAt); err != nil {
		t.Fatalf("startedAt=%s err=%v", run.StartedAt, err)
	}
}

func slicesEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}