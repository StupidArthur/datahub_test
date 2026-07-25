// manager_test.go - nativepytest.Manager 集成测试。
//
// 在临时目录创建一个最小 pytest 项目, 跑 Manager 启动真实 pytest 子进程,
// 验证: 一个 pass + 一个 fail + 一个 xfail + cancel 行为。
//
// 不依赖 DataHub / 不依赖 ua_mocker / 不依赖仓库真实 integration。
package nativepytest

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

// 最小 pytest 项目:
// - test_one: pass
// - test_two: fail
// - test_three: xfail
// - test_four: xpass (xfail 但实际通过)
func writePytestProject(t *testing.T, dir string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Join(dir, "tests"), 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "tests", "__init__.py"), "")
	writeFile(t, filepath.Join(dir, "tests", "conftest.py"), "")
	writeFile(t, filepath.Join(dir, "pyproject.toml"), "[tool.pytest.ini_options]\ntestpaths=[\"tests\"]\n")
	writeFile(t, filepath.Join(dir, "tests", "test_basic.py"), `
import pytest

def test_one():
    assert 1 == 1

def test_two():
    assert 1 == 2

@pytest.mark.xfail(reason="expected fail")
def test_three():
    assert 1 == 2

@pytest.mark.xfail(reason="unexpected pass")
def test_four():
    assert 1 == 1
`)
}

func TestManager_StartAndWait_RealPytest(t *testing.T) {
	dir := t.TempDir()
	writePytestProject(t, dir)
	m := NewManager()

	runDir := t.TempDir()
	junitPath, err := SafeJunitPath(runDir, "junit.xml")
	if err != nil {
		t.Fatal(err)
	}
	args := BuildPytestArgs("python", []string{"tests/test_basic.py"}, junitPath, "-v")

	if err := m.Start("python", "run-real", args, dir, nil, nil); err != nil {
		t.Fatal(err)
	}

	exitCode, err := m.Wait("run-real")
	if err != nil {
		t.Fatal(err)
	}
	// exit code 不为 0 是正常的(有 fail + xfail/xpass)
	if exitCode == 0 {
		t.Fatalf("expected non-zero exit, got %d", exitCode)
	}

	b, err := os.ReadFile(junitPath)
	if err != nil {
		t.Fatalf("junit not written: %v", err)
	}
	results, err := ParseJUnit(b)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	statuses := map[string]CaseStatus{}
	for _, r := range results {
		statuses[r.Name] = r.Status
	}
	if statuses["test_one"] != StatusPassed {
		t.Fatalf("test_one=%s", statuses["test_one"])
	}
	if statuses["test_two"] != StatusFailed {
		t.Fatalf("test_two=%s", statuses["test_two"])
	}
	if statuses["test_three"] != StatusXFail {
		t.Fatalf("test_three=%s", statuses["test_three"])
	}
	// test_four is xfail but actually passed: pytest records xpass as a
	// regular passing <testcase> in the JUnit XML (no <skipped> child).
	// xpass cannot be distinguished from pass via JUnit XML alone
	// without --strict-xfail; the parser correctly leaves it as passed.
	if statuses["test_four"] != StatusPassed {
		t.Fatalf("test_four=%s (xpass without strict-xfail is recorded as pass)", statuses["test_four"])
	}
}

func TestManager_Start_RejectsDuplicateID(t *testing.T) {
	dir := t.TempDir()
	writePytestProject(t, dir)
	m := NewManager()

	args := BuildPytestArgs("python", []string{"tests/test_basic.py"}, filepath.Join(t.TempDir(), "j.xml"), "-v")
	if err := m.Start("python", "dup", args, dir, nil, nil); err != nil {
		t.Fatal(err)
	}
	defer func() {
		_, _ = m.Wait("dup")
	}()
	if err := m.Start("python", "dup", args, dir, nil, nil); err == nil {
		t.Fatal("expected error for duplicate id")
	}
}

func TestManager_Stop_CancelsRunningProcess(t *testing.T) {
	dir := t.TempDir()
	if err := os.MkdirAll(filepath.Join(dir, "tests"), 0o755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "tests", "__init__.py"), "")
	writeFile(t, filepath.Join(dir, "pyproject.toml"), "[tool.pytest.ini_options]\ntestpaths=[\"tests\"]\n")
	writeFile(t, filepath.Join(dir, "tests", "test_slow.py"), `
import time
import pytest

@pytest.mark.parametrize("i", range(20))
def test_slow(i):
    time.sleep(0.5)
`)

	m := NewManager()
	runDir := t.TempDir()
	junitPath, _ := SafeJunitPath(runDir, "junit.xml")
	args := BuildPytestArgs("python", []string{"tests/test_slow.py"}, junitPath, "-v")

	start := time.Now()
	if err := m.Start("python", "cancel-run", args, dir, nil, nil); err != nil {
		t.Fatal(err)
	}
	time.Sleep(1 * time.Second)
	if err := m.Stop("cancel-run"); err != nil {
		t.Fatal(err)
	}
	exitCode, err := m.Wait("cancel-run")
	if err != nil {
		t.Fatal(err)
	}
	elapsed := time.Since(start)
	if elapsed > 10*time.Second {
		t.Fatalf("cancel took too long: %v", elapsed)
	}
	if exitCode == 0 {
		t.Logf("note: exit code 0 after cancel (process may have flushed)")
	}
}

func TestManager_Stop_UnknownID(t *testing.T) {
	m := NewManager()
	if err := m.Stop("nope"); err == nil {
		t.Fatal("expected error")
	}
}

func TestManager_Wait_UnknownID(t *testing.T) {
	m := NewManager()
	if _, err := m.Wait("nope"); err == nil {
		t.Fatal("expected error")
	}
}

func TestManager_Start_NoPytestExe_FailsGracefully(t *testing.T) {
	dir := t.TempDir()
	writePytestProject(t, dir)
	m := NewManager()
	args := BuildPytestArgs("python", []string{"tests/test_basic.py"}, filepath.Join(t.TempDir(), "j.xml"), "-v")
	if err := m.Start("/nonexistent/python", "bad", args, dir, nil, nil); err == nil {
		t.Fatal("expected error for missing python")
	}
}

func TestManager_StdoutSnapshot(t *testing.T) {
	dir := t.TempDir()
	writePytestProject(t, dir)
	m := NewManager()
	// Use -s to disable pytest stdout capture so prints reach cmd.Stdout directly.
	if err := os.WriteFile(filepath.Join(dir, "tests", "test_slow.py"), []byte(`
import time, pytest
@pytest.mark.parametrize("i", range(5))
def test_snap(i):
    print(f"PROGRESS_{i}", flush=True)
    time.sleep(0.2)
`), 0o644); err != nil {
		t.Fatal(err)
	}
	args := BuildPytestArgs("python", []string{"-s", "tests/test_slow.py"}, filepath.Join(t.TempDir(), "j.xml"), "-v")
	if err := m.Start("python", "snap", args, dir, nil, nil); err != nil {
		t.Fatal(err)
	}
	defer func() { _, _ = m.Wait("snap") }()

	deadline := time.Now().Add(3 * time.Second)
	var out []byte
	for time.Now().Before(deadline) {
		out, _ = m.SnapshotStdout("snap")
		if len(out) > 0 && strings.Contains(string(out), "PROGRESS_") {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatalf("stdout should contain PROGRESS_*; got: %s", out)
}

// TestManager_WaitAfterProcessAlreadyFinished deterministically exercises
// the lifecycle path where the subprocess finishes before the caller
// invokes Wait. The previous implementation deleted m.active[runID]
// from the background goroutine right after close(entry.done), which
// caused a subsequent Wait to return "unknown run id" with no way
// for the caller to retrieve the exit code.
//
// The new contract is: the background goroutine keeps the entry until
// Wait removes it; Wait is the sole consumer that frees the slot.
func TestManager_WaitAfterProcessAlreadyFinished(t *testing.T) {
	dir := t.TempDir()
	m := NewManager()

	if err := m.Start(
		"python",
		"finished-before-wait",
		[]string{"-c", "pass"},
		dir,
		nil,
		nil,
	); err != nil {
		t.Fatal(err)
	}

	m.mu.Lock()
	entry := m.active["finished-before-wait"]
	m.mu.Unlock()
	if entry == nil {
		t.Fatal("entry missing immediately after Start")
	}

	// 进程已结束: 不使用 sleep, 直接等待后台 goroutine 关闭 done。
	<-entry.done

	exitCode, err := m.Wait("finished-before-wait")
	if err != nil {
		t.Fatalf("Wait after process completion failed: %v", err)
	}
	if exitCode != 0 {
		t.Fatalf("exitCode=%d, want 0", exitCode)
	}

	// Wait 之后 entry 应当被移除, 第二次 Wait 必须报 "unknown run id"。
	m.mu.Lock()
	_, exists := m.active["finished-before-wait"]
	m.mu.Unlock()
	if exists {
		t.Fatal("entry should be removed after Wait")
	}

	if _, err := m.Wait("finished-before-wait"); err == nil {
		t.Fatal("second Wait should report consumed run id")
	}
}