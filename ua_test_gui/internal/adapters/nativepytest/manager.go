// Package nativepytest provides a subprocess Runner implementation for the
// native pytest mode of ua_test_gui.
//
// 与 internal/adapters/pytestrunner 完全独立:
//   - 不共享状态
//   - 不复用 NDJSON 解析(原 pytest mode 输出 NDJSON; native mode 解析 JUnit XML)
//   - exec.CommandContext 启动 python -m pytest <args>
//   - 不与外部 Python 进程混用 PID / 进程组
package nativepytest

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sync"
)

// ProcessState 子进程状态。
type ProcessState int

const (
	StateIdle ProcessState = iota
	StateRunning
	StateFinished
)

// Process 子进程记录。
type processEntry struct {
	cmd       *exec.Cmd
	cancel    context.CancelFunc
	stdoutBuf *bytes.Buffer
	stderrBuf *bytes.Buffer
	done      chan struct{}
	exitCode  int
	runErr    error
}

// Manager 子进程池(同一时刻只允许一个 active native pytest run)。
type Manager struct {
	mu     sync.Mutex
	active map[string]*processEntry
}

// NewManager 构造。
func NewManager() *Manager {
	return &Manager{active: map[string]*processEntry{}}
}

// Start 启动 pytest 子进程。
//
// args 应为 BuildPytestArgs 的输出,不修改。
// workDir 为子进程的工作目录。
// env 为附加环境变量;若包含敏感值,通过 env 注入而非命令行。
func (m *Manager) Start(pythonExe string, runID string, args []string, workDir string, env []string, logWriter io.Writer) error {
	m.mu.Lock()
	if _, exists := m.active[runID]; exists {
		m.mu.Unlock()
		return fmt.Errorf("run id %q already active", runID)
	}
	m.mu.Unlock()

	ctx, cancel := context.WithCancel(context.Background())
	cmd := exec.CommandContext(ctx, pythonExe, args...)
	cmd.Dir = workDir
	cmd.Env = append(os.Environ(), env...)

	stdoutBuf := &bytes.Buffer{}
	stderrBuf := &bytes.Buffer{}
	cmd.Stdout = stdoutBuf
	cmd.Stderr = stderrBuf

	if err := cmd.Start(); err != nil {
		cancel()
		return fmt.Errorf("start pytest: %w", err)
	}

	entry := &processEntry{
		cmd:       cmd,
		cancel:    cancel,
		stdoutBuf: stdoutBuf,
		stderrBuf: stderrBuf,
		done:      make(chan struct{}),
	}

	m.mu.Lock()
	m.active[runID] = entry
	m.mu.Unlock()

	if logWriter != nil {
		// 启动后异步把已缓冲的输出刷到 logWriter;不阻塞
		go func() {
			_, _ = io.Copy(logWriter, bytes.NewReader(stdoutBuf.Bytes()))
			_, _ = io.Copy(logWriter, bytes.NewReader(stderrBuf.Bytes()))
		}()
	}

	go func() {
		entry.exitCode = 0
		entry.runErr = cmd.Wait()
		if entry.runErr != nil {
			var ee *exec.ExitError
			if errors.As(entry.runErr, &ee) {
				entry.exitCode = ee.ExitCode()
				entry.runErr = nil
			} else {
				entry.exitCode = -1
			}
		}
		close(entry.done)
		// entry is kept in m.active so that a subsequent Wait call can
		// still retrieve the exit code. The entry is removed by Wait
		// itself after it reads the result. Stop is the only other path
		// that may race with Wait; it does not touch m.active.
	}()

	return nil
}

// Stop 取消子进程。
func (m *Manager) Stop(runID string) error {
	m.mu.Lock()
	entry, ok := m.active[runID]
	m.mu.Unlock()
	if !ok {
		return fmt.Errorf("unknown run id %q", runID)
	}
	entry.cancel()
	return nil
}

// Wait 阻塞直到 run 结束,返回 exit code。
//
// 生命周期: 进程结束后后台 goroutine 仅 close(entry.done), 保留 entry
// 在 m.active 中。Wait 等待 entry.done 后读取结果, 再从 m.active 移除
// entry. 这保证调用方在进程结束后任意时刻调用 Wait 都能拿到结果, 而
// 重复 Wait 会得到 "unknown run id" 错误。
func (m *Manager) Wait(runID string) (int, error) {
	m.mu.Lock()
	entry, ok := m.active[runID]
	m.mu.Unlock()
	if !ok {
		return -1, fmt.Errorf("unknown run id %q", runID)
	}

	<-entry.done

	exitCode := entry.exitCode
	runErr := entry.runErr

	m.mu.Lock()
	if cur, ok := m.active[runID]; ok && cur == entry {
		delete(m.active, runID)
	}
	m.mu.Unlock()

	return exitCode, runErr
}

// SnapshotStdout 返回子进程启动后到目前为止的 stdout 缓冲。
func (m *Manager) SnapshotStdout(runID string) ([]byte, bool) {
	m.mu.Lock()
	entry, ok := m.active[runID]
	m.mu.Unlock()
	if !ok || entry.stdoutBuf == nil {
		return nil, false
	}
	out := append([]byte(nil), entry.stdoutBuf.Bytes()...)
	return out, true
}

// SnapshotStderr 同上,stderr。
func (m *Manager) SnapshotStderr(runID string) ([]byte, bool) {
	m.mu.Lock()
	entry, ok := m.active[runID]
	m.mu.Unlock()
	if !ok || entry.stderrBuf == nil {
		return nil, false
	}
	out := append([]byte(nil), entry.stderrBuf.Bytes()...)
	return out, true
}