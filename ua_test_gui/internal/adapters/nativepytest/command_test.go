// command_test.go - 命令行构造 + 路径安全校验单测。
package nativepytest

import (
	"path/filepath"
	"strings"
	"testing"
)

func TestBuildPytestArgs_Basic(t *testing.T) {
	args := BuildPytestArgs("python3", []string{"a.py::t1", "a.py::t2"}, "/tmp/junit.xml", "-v")
	want := []string{"-m", "pytest", "-v", "a.py::t1", "a.py::t2", "--junitxml=/tmp/junit.xml"}
	if !equalStrings(args, want) {
		t.Fatalf("args=%v want=%v", args, want)
	}
}

func TestBuildPytestArgs_DefaultVerbosity(t *testing.T) {
	args := BuildPytestArgs("python", []string{"x::t"}, "/tmp/x.xml", "")
	if args[2] != "-v" {
		t.Fatalf("default verbosity should be -v, got %s", args[2])
	}
}

func TestBuildPytestArgs_PreservesNodeidOrder(t *testing.T) {
	ids := []string{"c.py::a", "a.py::b", "b.py::c"}
	args := BuildPytestArgs("python", ids, "/tmp/x.xml", "-v")
	got := args[3 : 3+len(ids)]
	for i := range ids {
		if got[i] != ids[i] {
			t.Fatalf("order broken at %d: got %s want %s", i, got[i], ids[i])
		}
	}
}

func TestBuildPytestArgs_EmptyNodeidsProducesBaseOnly(t *testing.T) {
	args := BuildPytestArgs("python", nil, "/tmp/x.xml", "-v")
	want := []string{"-m", "pytest", "-v", "--junitxml=/tmp/x.xml"}
	if !equalStrings(args, want) {
		t.Fatalf("args=%v want=%v", args, want)
	}
}

func TestSafeJunitPath_OK(t *testing.T) {
	got, err := SafeJunitPath("/tmp/run", "junit.xml")
	if err != nil {
		t.Fatalf("err=%v", err)
	}
	want := filepath.Join("/tmp/run", "junit.xml")
	if got != want {
		t.Fatalf("got=%s want=%s", got, want)
	}
}

func TestSafeJunitPath_Default(t *testing.T) {
	got, err := SafeJunitPath("/tmp/run", "")
	if err != nil || !strings.HasSuffix(got, "junit.xml") {
		t.Fatalf("got=%s err=%v", got, err)
	}
}

func TestSafeJunitPath_RejectsTraversal(t *testing.T) {
	if _, err := SafeJunitPath("/tmp/run", "../etc/passwd"); err == nil {
		t.Fatal("expected error for traversal")
	}
}

func TestSafeJunitPath_RejectsAbsPath(t *testing.T) {
	if _, err := SafeJunitPath("/tmp/run", "/etc/passwd"); err == nil {
		t.Fatal("expected error for absolute path")
	}
}

func equalStrings(a, b []string) bool {
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