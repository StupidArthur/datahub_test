// runtime.go - mock 进程管理的业务接口(由 adapters/pyworker 实现)。
//
// mock 包只定义接口与数据模型,不持有 cmd/logFile 等实现细节(那些在 adapters/pyworker)。
// 依赖方向:adapters/pyworker -> mock(实现接口);mock 不反向依赖 adapter。
package mock

// Runtime mock 进程管理接口(起/停/状态/日志)。
type Runtime interface {
	Start(spec MockSpec) (*MockRuntime, error)
	Stop(key string)
	StopAll()
	Status(key string) string
	Runtime(key string) *MockRuntime
	ReadLogTail(key string, maxBytes int) string
}

// ConfigProvider ua_mocker 运行环境配置接口(路径探测 + 持久化)。
type ConfigProvider interface {
	Load() MockerConfig
	Save(MockerConfig) error
	MockerMainPath() string  // 探测到的 main.py 完整路径(源码模式)
	MockerExePath() string   // 可选 exe 路径(优先用;空=未配置)
	PythonPath() string      // python 可执行
	MainPathExists() bool    // 探测到的 main.py 是否存在
	ExePathExists() bool     // 探测到的 exe 是否存在
	SetPaths(repo, python, exe string)
	// 性能参数持久化(plan.md 10.5 #5)
	LoadPerf() PerfParams
	SavePerf(PerfParams) error
}

// Notifier 状态事件通知接口(由 app 层实现,转 Wails EventsEmit)。
// pyworker 检测到 mock 状态变化(ready/failed/crashed)时调用。
type Notifier interface {
	Emit(event string, data any)
}
