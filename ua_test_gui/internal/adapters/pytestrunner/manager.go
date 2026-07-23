// Package pytestrunner 管理 Python 测试 runner 子进程。
//
// 约束(plan.md 6.3):
//   - 一次只允许一个 active run
//   - 跨平台 exec.Cmd
//   - 捕获 stdout/stderr
//   - 解析 NDJSON
//   - Windows 使用 Job Object 终止 Python 子进程树
package pytestrunner

import (
	"bufio"
	"context"
	"errors"
	"io"
	"log/slog"
	"os/exec"
	"sync"

	"ua_test_gui/internal/automation"
)

// EnvFunc 让测试注入环境变量。
var EnvFunc = func(cmd *exec.Cmd) {}

// KillFunc 让测试注入 kill。
var KillFunc = func(cmd *exec.Cmd) error { return killTree(cmd) }

// Manager 进程池。
type Manager struct {
	mu      sync.Mutex
	active  *processEntry
	onEvent func(automation.EvEnvelope)
	onLog   func(string)
}

type processEntry struct {
	cmd      *exec.Cmd
	cancel   context.CancelFunc
	stdout   io.ReadCloser
	stderr   io.ReadCloser
	done     chan struct{}
	runKey   string
	runID    string
	runDir   string
	logPath  string
}

// NewManager 构造。
func NewManager() *Manager { return &Manager{} }

// Start 启动新进程并接管 NDJSON 解析。
func (m *Manager) Start(spec automation.StartSpec, onEvent func(automation.EvEnvelope), onLog func(string)) (automation.ProcessInfo, error) {
	m.mu.Lock()
	if m.active != nil {
		m.mu.Unlock()
		return automation.ProcessInfo{}, errors.New("another automation run is active")
	}
	m.onEvent = onEvent
	m.onLog = onLog

	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, spec.PythonExe, spec.RunnerArgs...)
	cmd.Dir = spec.WorkDir
	platformSpecific(cmd)
	EnvFunc(cmd)
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		m.mu.Unlock()
		return automation.ProcessInfo{}, err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		cancel()
		m.mu.Unlock()
		return automation.ProcessInfo{}, err
	}
	if err := cmd.Start(); err != nil {
		cancel()
		m.mu.Unlock()
		return automation.ProcessInfo{}, err
	}

	entry := &processEntry{
		cmd: cmd, cancel: cancel, stdout: stdout, stderr: stderr,
		runKey: spec.RunKey, runID: spec.RunID, runDir: spec.RunDir, logPath: spec.RunDir + "/runner.log",
		done:   make(chan struct{}),
	}
	m.active = entry
	m.mu.Unlock()

	go m.consumeStdout(entry)
	go m.consumeStderr(entry)
	go m.waitProcess(entry)

	return automation.ProcessInfo{RunKey: spec.RunKey, PID: cmd.Process.Pid, Started: spec.RunID}, nil
}

// Stop 主动停止 active run。
func (m *Manager) Stop(runKey string) error {
	m.mu.Lock()
	entry := m.active
	m.mu.Unlock()
	if entry == nil {
		return errors.New("no active run")
	}
	if runKey != "" && entry.runKey != runKey {
		return errors.New("runKey mismatch")
	}
	entry.cancel()
	if err := KillFunc(entry.cmd); err != nil && err.Error() != "process already finished" {
		slog.Warn("kill failed", "err", err)
	}
	return nil
}

// Active 返回当前进程信息。
func (m *Manager) Active() *automation.ProcessInfo {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.active == nil {
		return nil
	}
	info := automation.ProcessInfo{
		RunKey:  m.active.runKey,
		PID:     m.active.cmd.Process.Pid,
		Started: m.active.runID,
	}
	return &info
}

// consumeStdout 解析 NDJSON。
func (m *Manager) consumeStdout(entry *processEntry) {
	defer entry.stdout.Close()
	scanner := bufio.NewScanner(entry.stdout)
	scanner.Buffer(make([]byte, 1024*1024), 1024*1024)
	for scanner.Scan() {
		line := scanner.Bytes()
		if len(line) == 0 {
			continue
		}
		env, err := ParseEventLine(line)
		if err != nil {
			if m.onLog != nil {
				m.onLog("[protocol] " + err.Error())
			}
			continue
		}
		if m.onEvent != nil {
			m.onEvent(env)
		}
	}
	if err := scanner.Err(); err != nil {
		slog.Warn("stdout scanner err", "err", err)
	}
}

// consumeStderr 透传 stderr 到 onLog + 文件。
func (m *Manager) consumeStderr(entry *processEntry) {
	defer entry.stderr.Close()
	scanner := bufio.NewScanner(entry.stderr)
	scanner.Buffer(make([]byte, 64*1024), 64*1024)
	for scanner.Scan() {
		line := scanner.Text()
		if m.onLog != nil {
			m.onLog(line)
		}
	}
}

// waitProcess 等待退出,清理状态。
func (m *Manager) waitProcess(entry *processEntry) {
	_ = entry.cmd.Wait()
	close(entry.done)
	m.mu.Lock()
	if m.active == entry {
		m.active = nil
	}
	m.mu.Unlock()
}