// model.go - 验证结果数据模型。
//
// 错误模型:service 返回 (T, error),不再在 struct 内放 Error 字段。
package verify

import "encoding/json"

// VerifyOptions RunVerification 入参。
type VerifyOptions struct {
	Env       string  `json:"env"`
	MockKey   string  `json:"mockKey"`
	SettleSec float64 `json:"settleSec"` // 写入后等 RT 生效的秒数(源端 -> TPT ~1s)
	RunID     int64   `json:"runId"`     // >0 = 续跑该 run(跳过已落库 tag)
}

// VerifyTagResult 单 tag 验证结果。各值字段用 RawMessage 保留原值(类型随 dataType)。
type VerifyTagResult struct {
	RunID     int64           `json:"runId"`
	TagName   string          `json:"tagName"`
	Type      string          `json:"type"`
	RtBefore  json.RawMessage `json:"rtBefore"`
	SrcBefore json.RawMessage `json:"srcBefore"`
	WriteVal  json.RawMessage `json:"writeVal"`
	RtAfter   json.RawMessage `json:"rtAfter"`
	OK        bool            `json:"ok"`
	Msg       string          `json:"msg"`
}

// VerifyRunResult 一次验证 run 的汇总。
type VerifyRunResult struct {
	RunID   int64             `json:"runId"`
	Total   int               `json:"total"`
	Passed  int               `json:"passed"`
	Failed  int               `json:"failed"`
	Results []VerifyTagResult `json:"results"`
}

// RunRecord 一次验证 run 的持久化记录。
type RunRecord struct {
	ID         int64  `json:"id"`
	StartedAt  string `json:"startedAt"`
	FinishedAt string `json:"finishedAt"`
	Status     string `json:"status"` // running / finished
	Env        string `json:"env"`
	MockKey    string `json:"mockKey"`
	Total      int    `json:"total"`
	Passed     int    `json:"passed"`
	Failed     int    `json:"failed"`
	Progress   int    `json:"progress"`
}
