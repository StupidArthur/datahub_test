// container.go - 组合根:装配所有依赖,暴露 bindings 给 main。
//
// 唯一组合根:所有 new() 集中在此,业务包只定义构造函数,不互相 new。
// 依赖方向:app -> bindings + adapters + features。
package app

import (
	"log/slog"
	"path/filepath"

	"ua_test_gui/internal/adapters/nativepytest"
	"ua_test_gui/internal/adapters/opcua"
	"ua_test_gui/internal/adapters/pytestrunner"
	"ua_test_gui/internal/adapters/pyworker"
	"ua_test_gui/internal/adapters/sqlite"
	"ua_test_gui/internal/automation"
	"ua_test_gui/internal/bindings"
	"ua_test_gui/internal/env"
	"ua_test_gui/internal/mock"
	"ua_test_gui/internal/platform"
	"ua_test_gui/internal/provision"
	"ua_test_gui/internal/subject"
	"ua_test_gui/internal/verify"
)

// Container 组合根,持有 7 个 binding + 需要生命周期管理的内部组件。
type Container struct {
	Subject    *bindings.SubjectBinding
	Env        *bindings.EnvBinding
	Mock       *bindings.MockBinding
	Provision  *bindings.ProvisionBinding
	Verify     *bindings.VerifyBinding
	History    *bindings.HistoryBinding
	Automation *bindings.AutomationBinding

	store        *sqlite.Store
	mockMgr      *pyworker.MockManager
	runnerMgr    *pytestrunner.Manager
	nativeMgr    *nativepytest.Manager
	automation   *automation.Service
	nativeSvc    *automation.NativeService
}

// NewContainer 装配所有依赖。
func NewContainer() *Container {
	cfg := DefaultConfig()

	store, err := sqlite.OpenStore(cfg.DBPath)
	if err != nil {
		slog.Error("打开数据库失败", "err", err, "path", cfg.DBPath)
		// store 为 nil,service 容错(store==nil 时不落库)
	}

	// store==nil 时传 nil 接口(避免 Go 接口 nil 陷阱:typed nil != nil)
	var resultStore verify.ResultStore
	var autoStore automation.Store
	if store != nil {
		resultStore = store
		autoStore = store
	}

	mockMgr := pyworker.NewMockManager(cfg.MockWorkDir, nil) // notifier 由 Startup 注入
	runnerMgr := pytestrunner.NewManager()
	nativeMgr := nativepytest.NewManager()

	subjSvc := subject.NewService()
	envSvc := env.NewService(subjSvc)
	mockSvc := mock.NewService(mockMgr, mockMgr) // Runtime + ConfigProvider 均由 MockManager 实现
	provSvc := provision.NewService(subjSvc)
	verSvc := verify.NewService(subjSvc, resultStore, opcua.Factory{})

	paths := automation.DefaultPaths()
	_ = paths.EnsureDirs()
	catalog := automation.Catalog{Version: 1}
	autoSvc := automation.NewService(autoStore, runnerMgr, paths, catalog, cfg.PythonExe, cfg.WorkDir, nil)

	// 原生 pytest 后端: 读取 docs/test_cases/case-manifest.json。
	// 工作目录配置为仓库根目录(让 pytest 收集器找到 tests/)。
	// 若 manifest 不存在, NativeService 留 nil;Wails bindings 仅返回空列表,
	// 不影响 legacy 默认执行路径。
	var nativeSvc *automation.NativeService
	manifestPath := defaultManifestPath(cfg)
	if platform.FileExists(manifestPath) {
		adapter := automation.NewPytestRunnerAdapter(nativeMgr, cfg.PythonExe, cfg.WorkDir)
		ns, nsErr := automation.NewNativeService(manifestPath, adapter)
		if nsErr != nil {
			slog.Warn("native pytest manifest load failed", "path", manifestPath, "err", nsErr)
		} else {
			nativeSvc = ns
		}
	} else {
		slog.Info("native pytest manifest not found; legacy mode only", "path", manifestPath)
	}

	return &Container{
		Subject:    bindings.NewSubjectBinding(subjSvc),
		Env:        bindings.NewEnvBinding(envSvc, mockSvc),
		Mock:       bindings.NewMockBinding(mockSvc),
		Provision:  bindings.NewProvisionBinding(provSvc),
		Verify:     bindings.NewVerifyBinding(verSvc),
		History:    bindings.NewHistoryBinding(verSvc),
		Automation: bindings.NewAutomationBindingWithNative(autoSvc, nativeSvc),
		store:      store,
		mockMgr:    mockMgr,
		runnerMgr:  runnerMgr,
		nativeMgr:  nativeMgr,
		automation: autoSvc,
		nativeSvc:  nativeSvc,
	}
}

// defaultManifestPath 推导 case-manifest.json 路径。
//
// 优先从当前进程工作目录的 docs/test_cases/case-manifest.json 加载;
// 找不到则返回 <WorkDir>/docs/test_cases/case-manifest.json 作为兜底,
// 由调用方再次 stat 决定是否使用。
func defaultManifestPath(cfg Config) string {
	// 工作目录在 Config.WorkDir 设置时通常是仓库根目录
	if cfg.WorkDir != "" {
		return filepath.Join(cfg.WorkDir, "docs", "test_cases", "case-manifest.json")
	}
	// 否则用当前进程工作目录
	if cwd, err := filepath.Abs("."); err == nil {
		return filepath.Join(cwd, "docs", "test_cases", "case-manifest.json")
	}
	return ""
}
