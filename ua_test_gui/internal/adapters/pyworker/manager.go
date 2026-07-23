// manager.go - ua_mocker 跨进程管理(起/停/状态),实现 mock.Runtime + mock.ConfigProvider。
//
// 对齐 python ua_test_harness/env/mock_manager.py(MockManager)+ python-worker.md 增强:
//   - 状态机:stopped -> starting -> ready -> failed(崩溃)/ stopping -> stopped
//   - 崩溃监听:go cmd.Wait() 检测非主动退出 -> failed + Notifier 推送
//   - 就绪探针:waitPort + gopcua Discover(见 ready.go),端口开 ≠ UA server ready
//   - 有限重启:autoRestart 默认关(避免掩盖问题);开启时仅重启非配置/非端口/非主动停止的退出
//
// 启动方式优先级:MockerExe(打包 exe,存在则用)> Python+MockerMain(源码,无窗口可调试)。
// 依赖方向:pyworker -> mock(实现接口)+ env(端口探测)+ opcua(就绪探针)+ platform。
// 日志用标准库 slog.Default(),不依赖 logging adapter。
package pyworker

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"time"

	"ua_test_gui/internal/env"
	"ua_test_gui/internal/mock"
	"ua_test_gui/internal/platform"
)

// runtimeEntry 一套 mock 的运行态(业务字段 + 实现细节)。
type runtimeEntry struct {
	mock.MockRuntime
	cmd       *exec.Cmd
	logFile   *os.File
	startedAt time.Time
	done      chan struct{} // watchProcess 完成时关闭
	mu        sync.Mutex
	stopping  bool // 主动停止标志(区分崩溃)
	ready     bool // 就绪(gopcua discover 成功)
}

// MockManager 起/停 4 套 mock server,实现 mock.Runtime + mock.ConfigProvider。
type MockManager struct {
	MockerMain  string         // python main.py 路径(源码模式)
	MockerExe   string         // 可选 exe 路径(优先用)
	Python      string         // python 可执行
	WorkDir     string         // mock 工作目录(写 yaml/log)
	run         map[string]*runtimeEntry
	mu          sync.Mutex
	notifier    mock.Notifier // 状态事件通知(app 注入,转 Wails EventsEmit)
	autoRestart bool          // 有限重启开关(默认关)
}

// NewMockManager 创建管理器,路径从持久化配置加载(含自动探测)。
// notifier 可为 nil(app Startup 后用 SetNotifier 注入)。
func NewMockManager(workDir string, notifier mock.Notifier) *MockManager {
	cfg := LoadMockerConfig()
	return &MockManager{
		MockerMain: mockerMainPath(cfg.Repo),
		MockerExe:  mockerExePath(cfg.Repo, cfg.Exe),
		Python:     cfg.Python,
		WorkDir:    workDir,
		run:        map[string]*runtimeEntry{},
		notifier:   notifier,
	}
}

// SetNotifier 注入状态事件通知器(app Startup 后调,wails ctx 就绪)。
func (m *MockManager) SetNotifier(n mock.Notifier) {
	m.mu.Lock()
	m.notifier = n
	m.mu.Unlock()
}

// SetAutoRestart 设置有限重启开关(默认关)。
func (m *MockManager) SetAutoRestart(on bool) {
	m.mu.Lock()
	m.autoRestart = on
	m.mu.Unlock()
}

func (m *MockManager) notify(entry *runtimeEntry) {
	m.mu.Lock()
	n := m.notifier
	m.mu.Unlock()
	if n == nil {
		return
	}
	entry.mu.Lock()
	rt := entry.MockRuntime
	entry.mu.Unlock()
	n.Emit("mock:state", rt)
}

// Start 启动一套 mock(异步)。端口被占用则立即报错;否则立即返回 starting 状态,
// 后台 goroutine 完成就绪探针后通过 mock:state 事件通知前端。
func (m *MockManager) Start(spec mock.MockSpec) (*mock.MockRuntime, error) {
	m.mu.Lock()
	if rt := m.run[spec.Key]; rt != nil && (rt.Status == "ready" || rt.Status == "starting") {
		m.mu.Unlock()
		return nil, fmt.Errorf("%s(%d) 已在运行", spec.Name, spec.Port)
	}
	m.mu.Unlock()

	if !env.IsPortFree(spec.Port) {
		return nil, fmt.Errorf("端口 %d 被占用,先在环境页清理", spec.Port)
	}

	useExe := m.MockerExe != "" && platform.FileExists(m.MockerExe)
	mainPath := m.MockerMain
	pythonExe := m.Python
	if !useExe {
		if !platform.FileExists(mainPath) {
			return nil, fmt.Errorf("找不到 ua_mocker main.py(%s);请在「环境检测」页配置 ua_mocker 仓库路径", mainPath)
		}
		if pythonExe == "" {
			pythonExe = defaultPython()
		}
	}

	wdir := filepath.Join(m.WorkDir, spec.Key)
	if err := os.MkdirAll(wdir, 0o755); err != nil {
		return nil, err
	}
	yamlPath := filepath.Join(wdir, "config.yaml")
	if err := mock.BuildMockerYAML(spec, yamlPath); err != nil {
		return nil, fmt.Errorf("生成 yaml 失败: %w", err)
	}

	// 启动命令:优先 exe,否则 python 源码。
	// cmd.Dir 必须是 ua_mocker 目录(main.py 所在),否则 main.py 找不到且无法 import 同级模块。
	var cmd *exec.Cmd
	var runDir string
	if useExe {
		cmd = exec.Command(m.MockerExe, yamlPath)
		runDir = filepath.Dir(m.MockerExe)
	} else {
		cmd = exec.Command(pythonExe, mainPath, yamlPath)
		runDir = filepath.Dir(mainPath)
	}
	logPath := filepath.Join(wdir, "server.log")
	logFile, err := os.Create(logPath)
	if err != nil {
		return nil, err
	}
	cmd.Dir = runDir
	cmd.Stdout = logFile
	cmd.Stderr = logFile
	cmd.SysProcAttr = newProcSysProcAttr()
	if err := cmd.Start(); err != nil {
		logFile.Close()
		return nil, fmt.Errorf("启动 mock 失败: %w", err)
	}

	entry := &runtimeEntry{
		MockRuntime: mock.MockRuntime{
			Spec: spec, PID: cmd.Process.Pid,
			ConfigPath: yamlPath, LogPath: logPath,
			Status: "starting", Endpoint: spec.Endpoint(),
		},
		cmd: cmd, logFile: logFile, startedAt: time.Now(), done: make(chan struct{}),
	}

	m.mu.Lock()
	m.run[spec.Key] = entry
	m.mu.Unlock()

	// 崩溃监听 goroutine
	go m.watchProcess(spec.Key, entry)

	// 异步就绪探针:waitPort + gopcua Discover
	go m.waitReadyAsync(spec, entry, pythonExe, mainPath, useExe)

	entry.mu.Lock()
	rt := entry.MockRuntime
	entry.mu.Unlock()
	slog.Info("发起启动 mock", "key", spec.Key, "pid", rt.PID, "endpoint", rt.Endpoint)
	return &rt, nil
}

// waitReadyAsync 后台完成就绪探针并通知。
//
// 启动失败时保留 entry(plan.md 10.5 #1):保留 status="failed" + Reason + log/config 路径,
// 前端可在 list summary 中查看失败原因与日志。
func (m *MockManager) waitReadyAsync(spec mock.MockSpec, entry *runtimeEntry, pythonExe, mainPath string, useExe bool) {
	logPath := entry.LogPath
	if err := m.waitReady(spec, entry, startWaitTimeout(spec)); err != nil {
		entry.mu.Lock()
		wasStopping := entry.stopping
		entry.mu.Unlock()
		if wasStopping {
			return
		}
		tail := readLogTail(logPath, 1500)
		m.killEntry(entry)
		entry.mu.Lock()
		entry.Status = "failed"
		entry.Reason = fmt.Sprintf("启动失败:%v", err)
		if tail != "" {
			entry.Reason += "\nserver.log:\n" + tail
		}
		entry.mu.Unlock()
		m.notify(entry)
		return
	}

	entry.mu.Lock()
	entry.Status = "ready"
	entry.ready = true
	rt := entry.MockRuntime
	entry.mu.Unlock()
	m.notify(entry)
	slog.Info("mock 就绪", "key", spec.Key, "pid", rt.PID, "endpoint", rt.Endpoint)
}

// watchProcess 崩溃监听:cmd.Wait() 返回后判定主动停止/崩溃,更新状态并通知。
func (m *MockManager) watchProcess(key string, entry *runtimeEntry) {
	defer close(entry.done)
	err := entry.cmd.Wait()
	entry.mu.Lock()
	wasStopping := entry.stopping
	entry.cmd = nil
	if entry.logFile != nil {
		_ = entry.logFile.Close()
		entry.logFile = nil
	}
	if !wasStopping {
		// 非主动停止 = 崩溃
		entry.Status = "failed"
		entry.Reason = fmt.Sprintf("进程退出: %v", err)
		entry.mu.Unlock()
		slog.Error("mock 崩溃", "key", key, "pid", entry.PID, "err", err)
		m.notify(entry)
		// 有限重启(默认关);开启时仅重启非配置/非端口/非主动停止的退出
		m.mu.Lock()
		restart := m.autoRestart
		m.mu.Unlock()
		if restart {
			spec, ok := mock.FindSpec(key)
			if ok {
				slog.Info("尝试重启 mock", "key", key)
				if _, rerr := m.Start(spec); rerr != nil {
					slog.Error("重启 mock 失败", "key", key, "err", rerr)
				}
			}
		}
		return
	}
	entry.mu.Unlock()
}

// Status 查状态。本进程用运行态;跨进程用端口探测。
func (m *MockManager) Status(key string) string {
	m.mu.Lock()
	entry := m.run[key]
	m.mu.Unlock()
	if entry == nil {
		spec, ok := mock.FindSpec(key)
		if !ok {
			return "stopped"
		}
		if !env.IsPortFree(spec.Port) {
			return "running" // 跨进程在跑(无法判定 ready/starting)
		}
		return "stopped"
	}
	entry.mu.Lock()
	defer entry.mu.Unlock()
	return entry.Status
}

// Stop 停一套 mock。本进程起的用 Process.Kill + stopping 标志;跨进程用 KillPort。
func (m *MockManager) Stop(key string) {
	m.mu.Lock()
	entry := m.run[key]
	m.mu.Unlock()
	if entry != nil {
		entry.mu.Lock()
		entry.stopping = true
		cmd := entry.cmd
		done := entry.done
		entry.Status = "stopped"
		entry.mu.Unlock()
		killProcess(cmd)
		if done != nil {
			select {
			case <-done:
			case <-time.After(5 * time.Second):
			}
		}
		entry.mu.Lock()
		if entry.logFile != nil {
			_ = entry.logFile.Close()
			entry.logFile = nil
		}
		entry.cmd = nil
		entry.mu.Unlock()
		m.notify(entry)
		return
	}
	if spec, ok := mock.FindSpec(key); ok {
		env.KillPort(spec.Port)
	}
}

// StopAll 停所有 mock。
func (m *MockManager) StopAll() {
	for _, s := range mock.AllSpecs() {
		m.Stop(s.Key)
	}
}

// Runtime 查运行态(仅本进程起的)。
func (m *MockManager) Runtime(key string) *mock.MockRuntime {
	m.mu.Lock()
	entry := m.run[key]
	m.mu.Unlock()
	if entry == nil {
		return nil
	}
	entry.mu.Lock()
	defer entry.mu.Unlock()
	rt := entry.MockRuntime
	return &rt
}

// ReadLogTail 读某 mock 的 server.log 尾部(供 binding 查日志)。
func (m *MockManager) ReadLogTail(key string, maxBytes int) string {
	m.mu.Lock()
	entry := m.run[key]
	m.mu.Unlock()
	if entry == nil {
		return ""
	}
	entry.mu.Lock()
	logPath := entry.LogPath
	entry.mu.Unlock()
	return readLogTail(logPath, maxBytes)
}

// ---- mock.ConfigProvider 实现 ----

func (m *MockManager) Load() mock.MockerConfig        { return LoadMockerConfig() }
func (m *MockManager) Save(c mock.MockerConfig) error { return SaveMockerConfig(c) }
func (m *MockManager) MockerMainPath() string         { return m.MockerMain }
func (m *MockManager) MockerExePath() string          { return m.MockerExe }
func (m *MockManager) PythonPath() string             { return m.Python }
func (m *MockManager) MainPathExists() bool           { return platform.FileExists(m.MockerMain) }
func (m *MockManager) ExePathExists() bool            { return platform.FileExists(m.MockerExe) }

// SetPaths 更新 ua_mocker 仓库路径与 python/exe(空值不覆盖)。
func (m *MockManager) SetPaths(repo, python, exe string) {
	if repo != "" {
		m.MockerMain = mockerMainPath(repo)
		m.MockerExe = mockerExePath(repo, m.MockerExe)
	}
	if python != "" {
		m.Python = python
	}
	if exe != "" {
		m.MockerExe = exe
	}
}

// ---- 辅助 ----

// startWaitTimeout 按位号数推算启动等待上限:小 mock 8s;大 mock 按 8ms/节点(实测 11000 节点 ~51s,
// 瓶颈在 python asyncua 初始化节点树),cap 120s 防慢机误杀。
func startWaitTimeout(spec mock.MockSpec) time.Duration {
	nc := spec.NodeCount()
	if nc <= 500 {
		return 8 * time.Second
	}
	d := time.Duration(nc) * 8 * time.Millisecond
	if d < 8*time.Second {
		d = 8 * time.Second
	}
	if d > 120*time.Second {
		d = 120 * time.Second
	}
	return d
}

// readLogTail 读日志文件尾部(最多 maxBytes 字节)。
func readLogTail(path string, maxBytes int) string {
	f, err := os.Open(path)
	if err != nil {
		return "(无法读取日志: " + err.Error() + ")"
	}
	defer f.Close()
	if stat, err := f.Stat(); err == nil && stat.Size() > int64(maxBytes) {
		_, _ = f.Seek(stat.Size()-int64(maxBytes), 0)
	}
	b, _ := io.ReadAll(f)
	return string(b)
}

// killEntry 杀掉运行态进程并关日志(启动失败清理用)。
func (m *MockManager) killEntry(entry *runtimeEntry) {
	entry.mu.Lock()
	entry.stopping = true
	cmd := entry.cmd
	done := entry.done
	entry.mu.Unlock()
	killProcess(cmd)
	if done != nil {
		select {
		case <-done:
		case <-time.After(5 * time.Second):
		}
	}
	entry.mu.Lock()
	if entry.logFile != nil {
		_ = entry.logFile.Close()
		entry.logFile = nil
	}
	entry.cmd = nil
	entry.mu.Unlock()
}
