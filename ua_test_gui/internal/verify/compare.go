// compare.go - 验证值对照与测试值生成(13 类型读写回写遍历用)。
package verify

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"time"
)

// testValueFor 为每类型生成测试值(非默认值,避免与默认 0/false/""混淆)。
func testValueFor(mockerType string) any {
	switch mockerType {
	case "Boolean":
		return true
	case "Float", "Double":
		return 123.45
	case "Int64", "UInt64":
		return 9999999999 // 大数测精度(< 2^53,JSON float64 精确)
	case "String":
		return "verify_test"
	case "DateTime":
		return "2025-06-01T12:00:00Z"
	default:
		return 123
	}
}

func toJSONRaw(v any) json.RawMessage {
	if v == nil {
		return nil
	}
	b, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	return b
}

// rawEqual 比较两个 JSON RawMessage 是否语义相等(数值/bool/字符串)。
func rawEqual(a, b json.RawMessage) bool {
	if len(a) == 0 || len(b) == 0 {
		return false
	}
	var av, bv any
	if err := json.Unmarshal(a, &av); err != nil {
		return false
	}
	if err := json.Unmarshal(b, &bv); err != nil {
		return false
	}
	return equalAny(av, bv)
}

// equalAny 任意值比较:数值转 float64 比,bool/字符串直接比。
// DateTime 归一化:两侧都尝试解析为 time.Time,成功则比 UTC 时刻(容忍格式/时区/毫秒差异)。
func equalAny(a, b any) bool {
	if af, ok := toFloat(a); ok {
		if bf, ok := toFloat(b); ok {
			return af == bf
		}
	}
	if ab, ok := a.(bool); ok {
		if bb, ok := b.(bool); ok {
			return ab == bb
		}
	}
	if ta, ok := tryAsTime(a); ok {
		if tb, ok := tryAsTime(b); ok {
			return ta.Equal(tb)
		}
	}
	return fmt.Sprintf("%v", a) == fmt.Sprintf("%v", b)
}

// 常见 DateTime 布局(TPT 读回格式不确定,逐一尝试)。
var dtLayouts = []string{
	time.RFC3339Nano, // 2006-01-02T15:04:05.999999999Z07:00
	time.RFC3339,     // 2006-01-02T15:04:05Z07:00
	"2006-01-02T15:04:05.000Z07:00",
	"2006-01-02T15:04:05",
	"2006-01-02 15:04:05",
	"2006-01-02 15:04:05.000",
}

// tryAsTime 尝试将任意值解析为 time.Time。
//   string: 逐一尝试常见 DateTime 布局;也匹配 TPT Java DateTime toString 格式
//   float64/int: 视为 epoch 毫秒(TPT 可能返回毫秒时间戳)
func tryAsTime(v any) (time.Time, bool) {
	switch x := v.(type) {
	case string:
		// 先试 TPT Java DateTime 格式: DateTime{utcTime=133801632000000000, javaDate=...}
		if t, ok := parseJavaDateTime(x); ok {
			return t, true
		}
		for _, layout := range dtLayouts {
			if t, err := time.Parse(layout, x); err == nil {
				return t, true
			}
		}
	case float64:
		if x > 1e12 { // 毫秒级 epoch(2025+ 年 > 1.7e12)
			return time.UnixMilli(int64(x)), true
		}
		if x > 1e9 { // 秒级 epoch
			return time.Unix(int64(x), 0), true
		}
	case int64:
		if x > 1e12 {
			return time.UnixMilli(x), true
		}
		if x > 1e9 {
			return time.Unix(x, 0), true
		}
	case int:
		if x > 1e12 {
			return time.UnixMilli(int64(x)), true
		}
		if x > 1e9 {
			return time.Unix(int64(x), 0), true
		}
	}
	return time.Time{}, false
}

// javaDateTimeRe 匹配 TPT 读回的 Java DateTime toString:
//   DateTime{utcTime=133801632000000000, javaDate=Wed Jan 01 08:00:00 CST 2025}
var javaDateTimeRe = regexp.MustCompile(`utcTime=(\d+)`)

// parseJavaDateTime 从 TPT Java DateTime toString 字符串提取 utcTime(OPC UA 100ns 时间戳)。
// OPC UA 时间 = 1601-01-01 起的 100 纳秒间隔;Unix = 1970-01-01 起的纳秒。
// 转换:unix_nano = (utcTime - 116444736000000000) * 100
func parseJavaDateTime(s string) (time.Time, bool) {
	m := javaDateTimeRe.FindStringSubmatch(s)
	if m == nil {
		return time.Time{}, false
	}
	utcTime, err := strconv.ParseInt(m[1], 10, 64)
	if err != nil {
		return time.Time{}, false
	}
	// OPC UA epoch (1601-01-01) 到 Unix epoch (1970-01-01) = 11644473600 秒 = 116444736000000000 (100ns 单位)
	const oaToUnix100ns = 116444736000000000
	if utcTime < oaToUnix100ns {
		return time.Time{}, false
	}
	return time.Unix(0, (utcTime-oaToUnix100ns)*100), true
}

func toFloat(v any) (float64, bool) {
	switch x := v.(type) {
	case float64:
		return x, true
	case float32:
		return float64(x), true
	case int:
		return float64(x), true
	case int64:
		return float64(x), true
	case uint64:
		return float64(x), true
	case json.Number:
		f, err := x.Float64()
		return f, err == nil
	}
	return 0, false
}
