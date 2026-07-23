// service.go - mock 服务,持有 Runtime + ConfigProvider + 性能参数,实现 mock 业务编排。
//
// 替代原 App.mockMgr + perf 参数:状态与编排集中在 MockService,binding 只调 service。
package mock

import (
	"fmt"
	"sync"
	"time"
)

// MockSummary mock 摘要(DTO)。
type MockSummary struct {
	Key       string `json:"key"`
	Name      string `json:"name"`
	Port      int    `json:"port"`
	Status    string `json:"status"` // stopped / starting / ready / failed / running(跨进程)
	Endpoint  string `json:"endpoint"`
	NodeCount int    `json:"nodeCount"`
}

// PerfParams 性能测试参数(DTO)。
type PerfParams struct {
	PollN  int     `json:"pollN"`
	WriteN int     `json:"writeN"`
	Ratio  float64 `json:"ratio"`
}

// MockerConfigResult ua_mocker 运行环境配置查询结果(DTO)。
type MockerConfigResult struct {
	Repo   string `json:"repo"`
	Python string `json:"python"`
	MainPy string `json:"mainPy"`
	Exe    string `json:"exe"`
	OK     bool   `json:"ok"`
	ExeOK  bool   `json:"exeOk"`
}

// Service mock 服务。
type Service struct {
	rt  Runtime
	cfg ConfigProvider
	mu  sync.Mutex

	// 性能测试可编辑参数(0=用默认 10000/1000/0.9);StartMock("performance") 时生效
	perfPollN  int
	perfWriteN int
	perfRatio  float64
}

// NewService 创建 mock 服务。
func NewService(rt Runtime, cfg ConfigProvider) *Service {
	s := &Service{rt: rt, cfg: cfg}
	// 从持久化加载性能参数(plan.md 10.5 #5)
	p := cfg.LoadPerf()
	if p.PollN > 0 {
		s.perfPollN = p.PollN
	}
	if p.WriteN > 0 {
		s.perfWriteN = p.WriteN
	}
	if p.Ratio > 0 {
		s.perfRatio = p.Ratio
	}
	return s
}

// ListMocks 列出 4 套 mock 及状态。
func (s *Service) ListMocks() []MockSummary {
	var out []MockSummary
	for _, spec := range AllSpecs() {
		out = append(out, MockSummary{
			Key:       spec.Key,
			Name:      spec.Name,
			Port:      spec.Port,
			Status:    s.rt.Status(spec.Key),
			Endpoint:  spec.Endpoint(),
			NodeCount: spec.NodeCount(),
		})
	}
	return out
}

// StartMock 启动;performance 用已设 perf 参数构建 spec。
func (s *Service) StartMock(key string) (*MockRuntime, error) {
	spec, ok := FindSpec(key)
	if !ok {
		return nil, fmt.Errorf("未知 mock: %s", key)
	}
	s.mu.Lock()
	pollN, writeN, ratio := s.perfPollN, s.perfWriteN, s.perfRatio
	s.mu.Unlock()
	if key == "performance" && (pollN > 0 || writeN > 0 || ratio > 0) {
		spec = BuildPerformance(pollN, writeN, ratio)
	}
	return s.rt.Start(spec)
}

// StartAllMocks 依次启动所有 stopped 的 mock;每个等待 ready/failed 后再启动下一个。
// 立即返回已发起启动的 key 列表,后台 goroutine 完成实际启动流程。
//
// 同步启动错误不再被吞掉(plan.md 10.5 #2):把错误通过 mock:state 事件的 Reason 字段
// 暴露给前端(binding 可读 Runtime().Reason),并 log 警告。
func (s *Service) StartAllMocks() ([]string, error) {
	var started []string
	for _, spec := range AllSpecs() {
		if s.rt.Status(spec.Key) != "stopped" {
			continue
		}
		started = append(started, spec.Key)
	}
	go func(keys []string) {
		for _, key := range keys {
			spec, ok := FindSpec(key)
			if !ok {
				continue
			}
			rt, err := s.rt.Start(spec)
			if err != nil {
				// 启动失败仍写一条 runtime,reason 填错误(启动失败由 pyworker 内部已写)
				if rt != nil {
					_ = rt
				}
				continue
			}
			// 等待当前 mock 就绪或失败,最多 120s(与 startWaitTimeout cap 一致)。
			deadline := time.Now().Add(120 * time.Second)
			for time.Now().Before(deadline) {
				status := s.rt.Status(key)
				if status == "ready" || status == "failed" {
					break
				}
				time.Sleep(200 * time.Millisecond)
			}
		}
	}(started)
	return started, nil
}

// StopMock 停一套。
func (s *Service) StopMock(key string) { s.rt.Stop(key) }

// StopAll 停所有。
func (s *Service) StopAll() { s.rt.StopAll() }

// ReadLogTail 读某 mock 的 server.log 尾部。
func (s *Service) ReadLogTail(key string, maxBytes int) string {
	return s.rt.ReadLogTail(key, maxBytes)
}

// GetPerfParams 取当前性能测试参数(0=默认)。
func (s *Service) GetPerfParams() PerfParams {
	s.mu.Lock()
	defer s.mu.Unlock()
	return PerfParams{PollN: s.perfPollN, WriteN: s.perfWriteN, Ratio: s.perfRatio}
}

// SetPerfParams 设置性能测试参数(0 值不覆盖)。同时持久化。
func (s *Service) SetPerfParams(p PerfParams) {
	s.mu.Lock()
	if p.PollN > 0 {
		s.perfPollN = p.PollN
	}
	if p.WriteN > 0 {
		s.perfWriteN = p.WriteN
	}
	if p.Ratio > 0 {
		s.perfRatio = p.Ratio
	}
	cur := PerfParams{PollN: s.perfPollN, WriteN: s.perfWriteN, Ratio: s.perfRatio}
	s.mu.Unlock()
	_ = s.cfg.SavePerf(cur)
}

// GetConfig 取 ua_mocker 运行环境配置(含自动探测结果)。
func (s *Service) GetConfig() MockerConfigResult {
	cfg := s.cfg.Load()
	return MockerConfigResult{
		Repo:   cfg.Repo,
		Python: cfg.Python,
		MainPy: s.cfg.MockerMainPath(),
		Exe:    s.cfg.MockerExePath(),
		OK:     s.cfg.MainPathExists(),
		ExeOK:  s.cfg.ExePathExists(),
	}
}

// SetConfig 设置 ua_mocker 仓库路径与 python/exe(空值不覆盖),持久化并即时生效。
func (s *Service) SetConfig(repo, python, exe string) (MockerConfigResult, error) {
	cfg := s.cfg.Load()
	if repo != "" {
		cfg.Repo = repo
	}
	if python != "" {
		cfg.Python = python
	}
	if exe != "" {
		cfg.Exe = exe
	}
	if err := s.cfg.Save(cfg); err != nil {
		return MockerConfigResult{}, err
	}
	s.cfg.SetPaths(cfg.Repo, cfg.Python, cfg.Exe)
	return s.GetConfig(), nil
}
