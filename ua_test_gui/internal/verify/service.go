// service.go - 验证执行核心 + 验证服务。
//
// 对齐 python 补做的 11 类型读写回写遍历(summary 验证过)。
// runtime-safety:每跑完一个 tag 立即 store.AddTagResult 增量落库;支持 RunID>0 续跑跳过已落库 tag。
// 依赖:subject(TptClient)+ mock(TagSpec/SupportedTypes)+ ports(SourceClient/ResultStore/SourceClientFactory)。
// 日志用标准库 slog.Default()(由 app/logging.InitLogger 配置),不依赖 logging adapter。
package verify

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"ua_test_gui/internal/mock"
	"ua_test_gui/internal/subject"
)

// RunVerification 遍历 11 supported 类型,每类型取第一个可写位号做读写回写验证。
//   store=nil 时不落库;opts.RunID>0 时续跑(跳过已落库 tag)。
//   单 tag 失败记入 Results(OK=false),不中断;前置致命错误由 Service.RunVerification 返回 error。
func RunVerification(api *subject.TptClient, uaCl SourceClient, tagSpecs []mock.TagSpec, store ResultStore, opts VerifyOptions) VerifyRunResult {
	result := VerifyRunResult{}
	settle := opts.SettleSec
	if settle <= 0 {
		settle = 1.0
	}

	// 按类型找第一个可写位号(每类型验证 1 个,覆盖 11 类型)
	byType := map[string]mock.TagSpec{}
	for _, s := range tagSpecs {
		if s.Writable {
			if _, ok := byType[s.MockerType]; !ok {
				byType[s.MockerType] = s
			}
		}
	}

	// run:新建或续跑
	var runID int64
	done := map[string]bool{}
	if store != nil {
		if opts.RunID > 0 {
			runID = opts.RunID
			done = store.DoneTags(runID)
			slog.Info("续跑验证", "runId", runID, "doneTags", len(done))
		} else {
			runID = store.CreateRun(opts.Env, opts.MockKey, len(mock.SupportedTypes))
			slog.Info("新建验证 run", "runId", runID, "env", opts.Env, "mockKey", opts.MockKey)
		}
	}
	result.RunID = runID

	for _, t := range mock.SupportedTypes {
		s, ok := byType[t]
		if !ok {
			continue
		}
		if done[s.Name] {
			continue // 续跑跳过已落库 tag
		}
		slog.Info("验证位号", "type", t, "tag", s.Name)
		tr := verifyOneTag(api, uaCl, s, settle)
		tr.RunID = runID
		result.Results = append(result.Results, tr)
		if tr.OK {
			result.Passed++
		} else {
			result.Failed++
			slog.Error("验证失败", "tag", s.Name, "msg", tr.Msg)
		}
		result.Total++
		if store != nil {
			if err := store.AddTagResult(runID, tr); err != nil {
				slog.Error("落库失败", "tag", s.Name, "err", err)
			}
			store.UpdateRunProgress(runID, result.Total) // 断点续跑进度
		}
	}
	if store != nil {
		store.FinishRun(runID, result.Passed, result.Failed)
	}
	slog.Info("验证完成", "runId", runID, "passed", result.Passed, "failed", result.Failed)
	return result
}

// verifyOneTag 单 tag 验证:读 RT -> 读源端 -> 回写 -> readback -> 对照。
func verifyOneTag(api *subject.TptClient, uaCl SourceClient, s mock.TagSpec, settle float64) VerifyTagResult {
	tr := VerifyTagResult{TagName: s.Name, Type: s.MockerType, OK: true}
	ctx := context.Background()

	// 1. RT before
	pts, err := api.GetRTValue([]string{s.Name})
	if err != nil || len(pts) == 0 {
		tr.OK = false
		tr.Msg = "读 RT 失败"
		if err != nil {
			tr.Msg += ": " + err.Error()
		}
		return tr
	}
	tr.RtBefore = pts[0].TagValue

	// 2. 源端 before(绕过 TPT 直读 mock)
	v, err := uaCl.Read(ctx, s.Name)
	if err != nil {
		tr.OK = false
		tr.Msg = "读源端失败: " + err.Error()
		return tr
	}
	tr.SrcBefore = toJSONRaw(v)

	// 3. 回写测试值
	writeVal := testValueFor(s.MockerType)
	if err := api.WriteTagValues(map[string]any{s.Name: writeVal}); err != nil {
		tr.OK = false
		tr.Msg = "write 失败: " + err.Error()
		return tr
	}
	tr.WriteVal = toJSONRaw(writeVal)
	time.Sleep(time.Duration(settle * float64(time.Second)))

	// 4. RT after(readback)
	pts2, err := api.GetRTValue([]string{s.Name})
	if err != nil || len(pts2) == 0 {
		tr.OK = false
		tr.Msg = "readback RT 失败"
		if err != nil {
			tr.Msg += ": " + err.Error()
		}
		return tr
	}
	tr.RtAfter = pts2[0].TagValue

	// 5. 对照
	if !rawEqual(tr.RtAfter, tr.WriteVal) {
		tr.OK = false
		tr.Msg = "readback 与写入值不一致"
	}
	return tr
}

// VerifyRequest RunVerification 入参(DTO)。
type VerifyRequest struct {
	MockKey        string  `json:"mockKey"`
	Endpoint       string  `json:"endpoint"`
	NamespaceIndex int     `json:"namespaceIndex"`
	SettleSec      float64 `json:"settleSec"`
	RunID          int64   `json:"runId"` // >0 = 续跑该 run
}

// Service 验证服务,持有登录态 + 持久化 + 源端工厂。
type Service struct {
	subject *subject.Service
	store   ResultStore
	factory SourceClientFactory
}

// NewService 创建验证服务。
func NewService(subj *subject.Service, store ResultStore, factory SourceClientFactory) *Service {
	return &Service{subject: subj, store: store, factory: factory}
}

// RunVerification 执行验证。前置检查(未登录/未知 mock/连接失败)返回 error。
func (s *Service) RunVerification(req VerifyRequest) (VerifyRunResult, error) {
	cli := s.subject.Client()
	if cli == nil {
		return VerifyRunResult{}, errors.New("未登录")
	}
	spec, ok := mock.FindSpec(req.MockKey)
	if !ok {
		return VerifyRunResult{}, fmt.Errorf("未知 mock: %s", req.MockKey)
	}
	ns := req.NamespaceIndex
	if ns < 0 {
		ns = 0
	}
	uaCl := s.factory.NewSourceClient(req.Endpoint, ns)
	ctx := context.Background()
	if err := uaCl.Connect(ctx); err != nil {
		return VerifyRunResult{}, fmt.Errorf("连接 UA 源端失败: %w", err)
	}
	defer uaCl.Close(ctx)
	return RunVerification(cli, uaCl, mock.TagSpecsFromMock(spec, 10), s.store, VerifyOptions{
		MockKey:   req.MockKey,
		SettleSec: req.SettleSec,
		RunID:     req.RunID,
	}), nil
}

// ListRuns 列出历史 run。
func (s *Service) ListRuns() ([]RunRecord, error) {
	if s.store == nil {
		return nil, errors.New("数据库未初始化")
	}
	return s.store.ListRuns(), nil
}

// GetRunDetail 取单 run + 其全部 tag 结果。
func (s *Service) GetRunDetail(runID int64) (RunRecord, []VerifyTagResult, error) {
	if s.store == nil {
		return RunRecord{}, nil, errors.New("数据库未初始化")
	}
	return s.store.GetRunDetail(runID)
}
