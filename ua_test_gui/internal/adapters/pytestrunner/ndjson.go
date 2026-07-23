// ndjson.go - NDJSON 行解析。
package pytestrunner

import (
	"encoding/json"
	"errors"
	"time"

	"ua_test_gui/internal/automation"
)

// ParseEventLine 解析一行 JSON,提取 event/caseId/payload/ts。
func ParseEventLine(line []byte) (automation.EvEnvelope, error) {
	if len(line) == 0 {
		return automation.EvEnvelope{}, errors.New("empty line")
	}
	// 兼容 Python json.dumps 的默认分隔符(无空格)
	var raw struct {
		Event   string          `json:"event"`
		CaseID  string          `json:"caseId"`
		Payload json.RawMessage `json:"-"`
		Ts      string          `json:"ts"`
	}
	// 用 map 解出全部字段再重组 payload。
	var all map[string]json.RawMessage
	if err := json.Unmarshal(line, &all); err != nil {
		return automation.EvEnvelope{}, err
	}
	raw.Event = decodeStr(all["event"])
	raw.CaseID = decodeStr(all["caseId"])
	raw.Ts = decodeStr(all["ts"])
	if raw.Event == "" {
		return automation.EvEnvelope{}, errors.New("missing event field")
	}
	if raw.Ts == "" {
		raw.Ts = time.Now().UTC().Format(time.RFC3339Nano)
	}
	// 重新序列化原 map(去掉 event)为 payload
	delete(all, "event")
	payload, _ := json.Marshal(all)
	return automation.EvEnvelope{
		EventType: raw.Event,
		CaseID:    raw.CaseID,
		Payload:   payload,
		Ts:        raw.Ts,
	}, nil
}

func decodeStr(b json.RawMessage) string {
	if len(b) == 0 {
		return ""
	}
	var s string
	_ = json.Unmarshal(b, &s)
	return s
}