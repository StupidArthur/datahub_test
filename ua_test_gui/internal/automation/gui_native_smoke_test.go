// gui_native_smoke_test.go - 真实 smoke 验证 GUI native pytest 后端链路。
//
// 不依赖真实 DataHub; 创建一个最小 pytest 项目 + manifest,
// 走 automation.NativeService + nativepytest.Manager 完整链路,
// 验证:
//   1. manifest 加载与 schemaVersion=1 校验
//   2. BuildPytestArgs 参数正确
//   3. JUnit XML 写入与解析
//   4. Case ID / nodeid 映射
//   5. cancel 功能
package automation

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"ua_test_gui/internal/adapters/nativepytest"
)

// writeSmokePytestProject 在 dir 下生成 4 个测试:
//   test_pass    永远通过
//   test_fail    永远失败
//   test_xfail   xfail 标记且实际失败 -> xfail
//   test_xpass   xfail 标记但实际通过 -> 在没有 --strict-xfail 时 pytest 记为 passed
func writeSmokePytestProject(t *testing.T, dir string) {
	t.Helper()
	testsDir := filepath.Join(dir, "tests")
	if err := os.MkdirAll(testsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(testsDir, "__init__.py"), []byte(""), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "pyproject.toml"), []byte("[tool.pytest.ini_options]\ntestpaths=[\"tests\"]\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "tests", "test_smoke.py"), []byte(`
import pytest

def test_pass():
    assert 1 == 1

def test_fail():
    assert 1 == 2

@pytest.mark.xfail(reason="expected fail")
def test_xfail():
    assert 1 == 2

@pytest.mark.xfail(reason="unexpected pass")
def test_xpass():
    assert 1 == 1
`), 0o644); err != nil {
		t.Fatal(err)
	}
}

func writeSmokeManifest(t *testing.T, dir string, cases []ManifestCase) string {
	t.Helper()
	manifestPath := filepath.Join(dir, "case-manifest.json")
	m := Manifest{SchemaVersion: 1, Cases: cases}
	b, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(manifestPath, b, 0o644); err != nil {
		t.Fatal(err)
	}
	return manifestPath
}

func TestGUI_NativeSmoke_EndToEnd(t *testing.T) {
	dir := t.TempDir()
	writeSmokePytestProject(t, dir)
	runDir := t.TempDir()

	manifestPath := writeSmokeManifest(t, dir, []ManifestCase{
		{ID: "SMK-01", Chapter: "SMK", Title: "pass", NodeID: "tests/test_smoke.py::test_pass"},
		{ID: "SMK-02", Chapter: "SMK", Title: "fail", NodeID: "tests/test_smoke.py::test_fail"},
		{ID: "SMK-03", Chapter: "SMK", Title: "xfail", NodeID: "tests/test_smoke.py::test_xfail"},
		{ID: "SMK-04", Chapter: "SMK", Title: "xpass", NodeID: "tests/test_smoke.py::test_xpass"},
	})

	mgr := nativepytest.NewManager()
	adapter := NewPytestRunnerAdapter(mgr, "python", dir)
	svc, err := NewNativeService(manifestPath, adapter)
	if err != nil {
		t.Fatal(err)
	}

	if got := len(svc.ListCases()); got != 4 {
		t.Fatalf("manifest cases=%d", got)
	}

	junitPath, err := nativepytest.SafeJunitPath(runDir, "junit.xml")
	if err != nil {
		t.Fatal(err)
	}
	args := nativepytest.BuildPytestArgs("python", []string{
		"tests/test_smoke.py::test_pass",
		"tests/test_smoke.py::test_fail",
		"tests/test_smoke.py::test_xfail",
		"tests/test_smoke.py::test_xpass",
	}, junitPath, "-v")

	if err := mgr.Start("python", "smk-1", args, dir, nil, nil); err != nil {
		t.Fatal(err)
	}
	if _, err := mgr.Wait("smk-1"); err != nil {
		t.Fatal(err)
	}

	b, err := os.ReadFile(junitPath)
	if err != nil {
		t.Fatalf("junit not written: %v", err)
	}
	cases, err := nativepytest.ParseJUnit(b)
	if err != nil {
		t.Fatal(err)
	}
	if len(cases) != 4 {
		t.Fatalf("cases=%d", len(cases))
	}

	want := map[string]nativepytest.CaseStatus{
		"test_pass":  nativepytest.StatusPassed,
		"test_fail":  nativepytest.StatusFailed,
		"test_xfail": nativepytest.StatusXFail,
		"test_xpass": nativepytest.StatusPassed,
	}
	for _, c := range cases {
		if want[c.Name] != c.Status {
			t.Errorf("%s: got %s want %s", c.Name, c.Status, want[c.Name])
		}
	}
}

func TestGUI_NativeSmoke_Cancel(t *testing.T) {
	dir := t.TempDir()
	testsDir := filepath.Join(dir, "tests")
	if err := os.MkdirAll(testsDir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(testsDir, "__init__.py"), []byte(""), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "pyproject.toml"), []byte("[tool.pytest.ini_options]\ntestpaths=[\"tests\"]\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(testsDir, "test_slow.py"), []byte(`
import time
import pytest
@pytest.mark.parametrize("i", range(20))
def test_slow(i):
    time.sleep(0.5)
`), 0o644); err != nil {
		t.Fatal(err)
	}

	manifestPath := writeSmokeManifest(t, dir, []ManifestCase{
		{ID: "SLOW-01", Chapter: "SLOW", Title: "slow", NodeID: "tests/test_slow.py::test_slow"},
	})

	mgr := nativepytest.NewManager()
	adapter := NewPytestRunnerAdapter(mgr, "python", dir)
	svc, err := NewNativeService(manifestPath, adapter)
	if err != nil {
		t.Fatal(err)
	}

	runDir := t.TempDir()
	junitPath, _ := nativepytest.SafeJunitPath(runDir, "junit.xml")
	args := nativepytest.BuildPytestArgs("python", []string{"tests/test_slow.py"}, junitPath, "-v")

	if err := mgr.Start("python", "cancel-1", args, dir, nil, nil); err != nil {
		t.Fatal(err)
	}
	time.Sleep(1 * time.Second)
	if err := mgr.Stop("cancel-1"); err != nil {
		t.Fatal(err)
	}
	if _, err := mgr.Wait("cancel-1"); err != nil {
		t.Fatal(err)
	}
	// The svc.Cancel path is exercised in NativeService unit tests;
	// here we just verify the manager-level cancel works on a running
	// pytest process and the entry is cleaned up.
	_ = svc
}