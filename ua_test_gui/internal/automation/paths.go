// paths.go - run/run-config/evidence/report 等路径管理。
package automation

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

// Paths 路径集合。
type Paths struct {
	Root         string // ~/.ua_test_gui
	RunsRoot     string // Root/runs
	LogsRoot     string // Root/logs
	ReportsRoot  string // Root/reports
	CatalogPath  string // Root/catalog.json
	WorkDir      string // 工作目录(仓库根)
}

// DefaultPaths 根据 home 目录生成路径。
func DefaultPaths() Paths {
	home, _ := os.UserHomeDir()
	root := filepath.Join(home, ".ua_test_gui")
	wd, _ := os.Getwd()
	return Paths{
		Root:        root,
		RunsRoot:    filepath.Join(root, "runs"),
		LogsRoot:    filepath.Join(root, "logs"),
		ReportsRoot: filepath.Join(root, "reports"),
		CatalogPath: filepath.Join(root, "catalog.json"),
		WorkDir:     wd,
	}
}

// EnsureDirs 创建所需目录。
func (p Paths) EnsureDirs() error {
	for _, d := range []string{p.Root, p.RunsRoot, p.LogsRoot, p.ReportsRoot} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return err
		}
	}
	return nil
}

// NewRunDir 创建 run 目录。
func (p Paths) NewRunDir(runID string) (string, error) {
	if runID == "" {
		runID = NewRunID()
	}
	dir := filepath.Join(p.RunsRoot, runID)
	if err := os.MkdirAll(filepath.Join(dir, "evidence"), 0o755); err != nil {
		return "", err
	}
	return dir, nil
}

// NewRunID 生成 YYYYMMDD_HHMMSS_xxxx 形式的 run id。
func NewRunID() string {
	now := time.Now().UTC()
	suffix := fmt.Sprintf("%04x", now.UnixNano()&0xffff)
	return fmt.Sprintf("%s_%s", now.Format("20060102_150405"), suffix)
}

// WriteRunConfig 写入 run-config.json。
func WriteRunConfig(runDir string, payload []byte) (string, error) {
	p := filepath.Join(runDir, "run-config.json")
	if err := os.WriteFile(p, payload, 0o644); err != nil {
		return "", err
	}
	return p, nil
}

// IsWindows 当前是否 Windows。
func IsWindows() bool { return runtime.GOOS == "windows" }

// SafeJoin 防穿越。
func SafeJoin(parent, child string) (string, error) {
	full := filepath.Join(parent, child)
	clean := filepath.Clean(full)
	if !strings.HasPrefix(clean, filepath.Clean(parent)) {
		return "", fmt.Errorf("unsafe path: %s", child)
	}
	return clean, nil
}