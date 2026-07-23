// config.go - ua_mocker 运行环境配置(仓库路径 + python),持久化到 ~/.ua_test_gui/config.json。
//
// 路径优先级:环境变量 UA_MOCKER_REPO/UA_MOCKER_PYTHON > 配置文件 > 自动探测(可执行目录上溯找 ua_mocker)。
// 实现 mock.ConfigProvider 接口。
package pyworker

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"

	"ua_test_gui/internal/mock"
	"ua_test_gui/internal/platform"
)

// configFilePath 配置文件路径。
func configFilePath() string {
	return filepath.Join(platform.UserHome(), ".ua_test_gui", "config.json")
}

// LoadMockerConfig 读配置;空字段用自动探测/python PATH/exe 兜底。
func LoadMockerConfig() mock.MockerConfig {
	var c mock.MockerConfig
	if b, err := os.ReadFile(configFilePath()); err == nil {
		_ = json.Unmarshal(b, &c)
	}
	if c.Repo == "" {
		c.Repo = detectMockerDir()
	}
	if c.Python == "" {
		c.Python = defaultPython()
	}
	if c.Exe == "" {
		c.Exe = detectMockerExe(c.Repo)
	}
	return c
}

// SaveMockerConfig 写配置。
func SaveMockerConfig(c mock.MockerConfig) error {
	if err := os.MkdirAll(filepath.Dir(configFilePath()), 0o755); err != nil {
		return err
	}
	b, err := json.MarshalIndent(c, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(configFilePath(), b, 0o644)
}

// loadFullConfig 读全部配置(含 perf)。
func loadFullConfig() persistedConfig {
	var p persistedConfig
	if b, err := os.ReadFile(configFilePath()); err == nil {
		_ = json.Unmarshal(b, &p)
	}
	if p.Repo == "" {
		p.Repo = detectMockerDir()
	}
	if p.Python == "" {
		p.Python = defaultPython()
	}
	if p.Exe == "" {
		p.Exe = detectMockerExe(p.Repo)
	}
	return p
}

// saveFullConfig 写全部配置。
func saveFullConfig(p persistedConfig) error {
	if err := os.MkdirAll(filepath.Dir(configFilePath()), 0o755); err != nil {
		return err
	}
	b, err := json.MarshalIndent(p, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(configFilePath(), b, 0o644)
}

type persistedConfig struct {
	mock.MockerConfig
	Perf mock.PerfParams `json:"perf"`
}

// LoadPerf 读性能参数。
func (m *MockManager) LoadPerf() mock.PerfParams {
	return loadFullConfig().Perf
}

// SavePerf 写性能参数(同时保留已有 MockerConfig 字段)。
func (m *MockManager) SavePerf(p mock.PerfParams) error {
	cfg := loadFullConfig()
	cfg.Perf = p
	return saveFullConfig(cfg)
}

// detectMockerDir 自动探测 ua_mocker 目录(同时含 main.py + config_loader.py 才算)。
// 优先级:UA_MOCKER_REPO 环境变量 > 可执行文件目录上溯 > cwd 上溯。
func detectMockerDir() string {
	isMockerDir := func(p string) bool {
		return platform.FileExists(filepath.Join(p, "main.py")) && platform.FileExists(filepath.Join(p, "config_loader.py"))
	}
	if r := os.Getenv("UA_MOCKER_REPO"); r != "" {
		if isMockerDir(r) {
			return r
		}
		if isMockerDir(filepath.Join(r, "ua_mocker")) {
			return filepath.Join(r, "ua_mocker")
		}
	}
	var starts []string
	if exe, err := os.Executable(); err == nil {
		starts = append(starts, filepath.Dir(exe))
	}
	if cwd, err := os.Getwd(); err == nil {
		starts = append(starts, cwd)
	}
	for _, start := range starts {
		dir := start
		for i := 0; i < 8; i++ {
			if isMockerDir(filepath.Join(dir, "ua_mocker")) {
				return filepath.Join(dir, "ua_mocker")
			}
			if isMockerDir(dir) {
				return dir
			}
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	return ""
}

// defaultPython 推导 python 可执行:UA_MOCKER_PYTHON > LookPath python/python3。
func defaultPython() string {
	if p := os.Getenv("UA_MOCKER_PYTHON"); p != "" {
		return p
	}
	if p, err := exec.LookPath("python"); err == nil {
		return p
	}
	if p, err := exec.LookPath("python3"); err == nil {
		return p
	}
	return "python"
}

// mockerMainPath 由 repo 推导 main.py 完整路径(repo=ua_mocker 目录或其父)。
func mockerMainPath(repo string) string {
	if repo == "" {
		return defaultMockerMain()
	}
	if platform.FileExists(filepath.Join(repo, "main.py")) {
		return filepath.Join(repo, "main.py")
	}
	if platform.FileExists(filepath.Join(repo, "ua_mocker", "main.py")) {
		return filepath.Join(repo, "ua_mocker", "main.py")
	}
	return filepath.Join(repo, "main.py") // 保留;Start 时检查并报清晰错误
}

func defaultMockerMain() string {
	if d := detectMockerDir(); d != "" {
		return filepath.Join(d, "main.py")
	}
	return "main.py" // 探测失败:Start 时报错,提示用户在环境页配置
}

// detectMockerExe 自动探测 ua_mocker.exe。
// 优先级:UA_MOCKER_EXE 环境变量 > 可执行文件目录 > cwd 上溯 > repo 同级 dist/ua_mocker.exe。
func detectMockerExe(repo string) string {
	isExe := func(p string) bool { return platform.FileExists(p) }
	if e := os.Getenv("UA_MOCKER_EXE"); e != "" && isExe(e) {
		return e
	}
	candidates := []string{}
	if exe, err := os.Executable(); err == nil {
		candidates = append(candidates, filepath.Join(filepath.Dir(exe), "ua_mocker.exe"))
	}
	if cwd, err := os.Getwd(); err == nil {
		candidates = append(candidates, filepath.Join(cwd, "ua_mocker.exe"))
	}
	if repo != "" {
		candidates = append(candidates,
			filepath.Join(repo, "dist", "ua_mocker.exe"),
			filepath.Join(filepath.Dir(repo), "ua_mocker", "dist", "ua_mocker.exe"),
		)
	}
	for _, start := range []string{repo, filepath.Dir(repo)} {
		if start == "" || start == "." {
			continue
		}
		dir := start
		for i := 0; i < 8; i++ {
			candidates = append(candidates, filepath.Join(dir, "ua_mocker.exe"))
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	for _, p := range candidates {
		if isExe(p) {
			return p
		}
	}
	return ""
}

// defaultMockerExe 由 repo 推导默认 exe 路径。
func defaultMockerExe(repo string) string {
	if e := detectMockerExe(repo); e != "" {
		return e
	}
	if repo != "" {
		return filepath.Join(repo, "dist", "ua_mocker.exe")
	}
	return "ua_mocker.exe" // 探测失败:Start 时走 python 源码
}

// mockerExePath 由配置推导 exe 完整路径。
func mockerExePath(repo, exe string) string {
	if exe != "" {
		return exe
	}
	return defaultMockerExe(repo)
}
