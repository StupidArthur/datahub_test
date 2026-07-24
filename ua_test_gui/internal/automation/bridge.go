// bridge.go - 适配 nativepytest.Manager 到 automation.NativeRunner 接口。
//
// NativeService 使用 NativeRunner 接口; nativepytest.Manager 有更具体的签名;
// 此处桥接两者, 不让 NativeService 直接依赖 nativepytest 子包。
package automation

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"

	"ua_test_gui/internal/adapters/nativepytest"
)

// PytestRunnerAdapter 把 nativepytest.Manager 适配为 NativeRunner。
type PytestRunnerAdapter struct {
	manager    *nativepytest.Manager
	pythonExe  string
	workDir    string
	logPathDir string
	mu         sync.Mutex
	logFiles   map[string]string
}

// NewPytestRunnerAdapter 构造。
func NewPytestRunnerAdapter(manager *nativepytest.Manager, pythonExe, workDir string) *PytestRunnerAdapter {
	return &PytestRunnerAdapter{
		manager:    manager,
		pythonExe:  pythonExe,
		workDir:    workDir,
		logPathDir: filepath.Join(workDir, "logs"),
		logFiles:   map[string]string{},
	}
}

// Start 启动 pytest 子进程。logWriter 可以为 nil。
func (a *PytestRunnerAdapter) Start(spec NativeStartSpec) error {
	logPath := a.logPathFor(spec.RunID)
	if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
		return fmt.Errorf("mkdir log dir: %w", err)
	}
	f, err := os.Create(logPath)
	if err != nil {
		return fmt.Errorf("create log file: %w", err)
	}
	a.mu.Lock()
	a.logFiles[spec.RunID] = logPath
	a.mu.Unlock()

	return a.manager.Start(spec.PythonExe, spec.RunID, spec.Args, spec.WorkDir, spec.Env, f)
}

// Stop 取消。
func (a *PytestRunnerAdapter) Stop(id string) error {
	return a.manager.Stop(id)
}

// Wait 阻塞等待, 返回 exit code。
func (a *PytestRunnerAdapter) Wait(id string) (int, error) {
	return a.manager.Wait(id)
}

// LogPath 返回日志文件路径(Start 后有效)。
func (a *PytestRunnerAdapter) LogPath(id string) string {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.logFiles[id]
}

func (a *PytestRunnerAdapter) logPathFor(id string) string {
	return filepath.Join(a.logPathDir, id+".log")
}

// _ 防止 io.Writer import 未使用(供将来扩展 streaming 输出时使用)。
var _ io.Writer = (*os.File)(nil)