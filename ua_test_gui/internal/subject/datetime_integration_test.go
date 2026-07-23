package subject

import (
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

// 集成测试：用 Go TptClient 走 TPT 写 DateTime/String 值 + 读回 + 时间归一化比较。
// 验证 TPT 读回的 Java DateTime toString 格式能被正确比较。
func TestDateTimeStringWriteIntegration(t *testing.T) {
	baseURL := "http://10.10.58.153:31501"
	user := "admin"
	password := "123456"

	cli, err := LoginSubject(baseURL, user, password, "", 60*time.Second)
	if err != nil {
		t.Fatalf("登录失败: %v", err)
	}
	t.Log("登录成功")

	// === DateTime ===
	dtTag := "1_dt_wr_1"
	dtVal := "2025-06-01T12:00:00Z"
	t.Logf("=== DateTime: write %s = %s ===", dtTag, dtVal)
	if err := cli.WriteTagValues(map[string]any{dtTag: dtVal}); err != nil {
		t.Fatalf("DateTime 写值失败: %v", err)
	}
	t.Log("DateTime 写值成功")

	// 等待 TPT 采集 + UA 回写 + poller 刷新（poller 5s 周期，等 8s 确保 1 次完整轮询）
	time.Sleep(8 * time.Second)
	pts, err := cli.GetRTValue([]string{dtTag})
	if err != nil {
		t.Logf("DateTime 读回失败: %v", err)
	} else if len(pts) > 0 {
		p := pts[0]
		t.Logf("DateTime 读回: tagValue=[%s] tagTime=%s quality=%d", string(p.TagValue), p.TagTime, p.Quality)
		writeRaw, _ := json.Marshal(dtVal)
		eq := timeEqual(writeRaw, p.TagValue)
		t.Logf("DateTime 比较 equal=%v (write=%s readback=%s)", eq, string(writeRaw), string(p.TagValue))
		if !eq {
			t.Errorf("DateTime 比较失败: 写入 %s 读回 %s", string(writeRaw), string(p.TagValue))
		}
	} else {
		t.Log("DateTime 读回: 0 points")
	}

	// === String ===
	strTag := "1_str_wr_1"
	strVal := "verify_test_123"
	t.Logf("=== String: write %s = %s ===", strTag, strVal)
	if err := cli.WriteTagValues(map[string]any{strTag: strVal}); err != nil {
		t.Fatalf("String 写值失败: %v", err)
	}
	t.Log("String 写值成功")

	time.Sleep(8 * time.Second)
	pts2, err := cli.GetRTValue([]string{strTag})
	if err != nil {
		t.Logf("String 读回失败: %v", err)
	} else if len(pts2) > 0 {
		p := pts2[0]
		t.Logf("String 读回: tagValue=[%s] tagTime=%s quality=%d", string(p.TagValue), p.TagTime, p.Quality)
		writeRaw, _ := json.Marshal(strVal)
		eq := string(writeRaw) == string(p.TagValue)
		t.Logf("String 比较 equal=%v (write=%s readback=%s)", eq, string(writeRaw), string(p.TagValue))
		if !eq {
			t.Errorf("String 比较失败: 写入 %s 读回 %s", string(writeRaw), string(p.TagValue))
		}
	} else {
		t.Log("String 读回: 0 points")
	}
}

func timeEqual(a, b json.RawMessage) bool {
	var av, bv any
	if err := json.Unmarshal(a, &av); err != nil {
		return false
	}
	if err := json.Unmarshal(b, &bv); err != nil {
		return false
	}
	if ta, ok := tryParseTime(av); ok {
		if tb, ok := tryParseTime(bv); ok {
			return ta.Equal(tb)
		}
	}
	return fmt.Sprintf("%v", av) == fmt.Sprintf("%v", bv)
}

var dtLayouts = []string{
	time.RFC3339Nano,
	time.RFC3339,
	"2006-01-02T15:04:05.000Z07:00",
	"2006-01-02T15:04:05",
	"2006-01-02 15:04:05",
}

func tryParseTime(v any) (time.Time, bool) {
	if s, ok := v.(string); ok {
		// TPT Java DateTime: DateTime{utcTime=133801632000000000, ...}
		if t, ok := parseJavaDateTime(s); ok {
			return t, true
		}
		for _, layout := range dtLayouts {
			if t, err := time.Parse(layout, s); err == nil {
				return t, true
			}
		}
	}
	if f, ok := v.(float64); ok {
		if f > 1e12 {
			return time.UnixMilli(int64(f)), true
		}
		if f > 1e9 {
			return time.Unix(int64(f), 0), true
		}
	}
	return time.Time{}, false
}

func parseJavaDateTime(s string) (time.Time, bool) {
	idx := indexOf(s, "utcTime=")
	if idx < 0 {
		return time.Time{}, false
	}
	s = s[idx+8:]
	end := indexOf(s, ",")
	if end < 0 {
		end = indexOf(s, "}")
	}
	if end < 0 {
		return time.Time{}, false
	}
	n, err := parseInt64(s[:end])
	if err != nil {
		return time.Time{}, false
	}
	const oaToUnix100ns = 116444736000000000
	if n < oaToUnix100ns {
		return time.Time{}, false
	}
	return time.Unix(0, (n-oaToUnix100ns)*100), true
}

func indexOf(s, sub string) int {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}

func parseInt64(s string) (int64, error) {
	var n int64
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, fmt.Errorf("not a digit")
		}
		n = n*10 + int64(c-'0')
	}
	return n, nil
}
