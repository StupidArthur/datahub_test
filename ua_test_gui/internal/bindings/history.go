// history.go - 历史 run 绑定。
package bindings

import "ua_test_gui/internal/verify"

// HistoryBinding 历史绑定(与 VerifyBinding 共享 verify.Service)。
type HistoryBinding struct {
	svc *verify.Service
}

// NewHistoryBinding 创建。
func NewHistoryBinding(svc *verify.Service) *HistoryBinding {
	return &HistoryBinding{svc: svc}
}

// RunDetailResponse 单 run 详情。
type RunDetailResponse struct {
	Run     verify.RunRecord         `json:"run"`
	Results []verify.VerifyTagResult `json:"results"`
}

// ListRuns 列出所有 run(新在前)。
func (b *HistoryBinding) ListRuns() (resp []verify.RunRecord, err error) {
	defer RecoverPanic(&err)
	resp, err = b.svc.ListRuns()
	return
}

// GetRunDetail 取单 run + 其全部 tag 结果。
func (b *HistoryBinding) GetRunDetail(runID int64) (resp RunDetailResponse, err error) {
	defer RecoverPanic(&err)
	run, results, err := b.svc.GetRunDetail(runID)
	if err != nil {
		return RunDetailResponse{}, err
	}
	resp = RunDetailResponse{Run: run, Results: results}
	return
}
