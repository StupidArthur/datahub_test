// paths_test.go - 路径工具单测。
package automation

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestNewRunID_Format(t *testing.T) {
	id := NewRunID()
	if len(id) < 20 {
		t.Fatalf("id too short: %s", id)
	}
	if !strings.Contains(id, "_") {
		t.Fatalf("missing underscore: %s", id)
	}
}

func TestPaths_NewRunDir_CreatesEvidence(t *testing.T) {
	tmp := t.TempDir()
	p := Paths{RunsRoot: filepath.Join(tmp, "runs")}
	dir, err := p.NewRunDir("test-run")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "evidence")); err != nil {
		t.Fatalf("evidence dir missing: %v", err)
	}
}

func TestIsWindows_Stable(t *testing.T) {
	if IsWindows() != (runtime.GOOS == "windows") {
		t.Fatalf("IsWindows mismatch")
	}
}

func TestSafeJoin(t *testing.T) {
	got, err := SafeJoin("/a/b", "c/d")
	if err != nil || got == "" {
		t.Fatalf("safe join fail: %s err=%v", got, err)
	}
	if _, err := SafeJoin("/a/b", "../escape"); err == nil {
		t.Fatal("expected unsafe error")
	}
}