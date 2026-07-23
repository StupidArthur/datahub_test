package verify

import (
	"encoding/json"
	"testing"
)

func TestToFloat(t *testing.T) {
	cases := []struct {
		in   any
		want float64
		ok   bool
	}{
		{float64(1.5), 1.5, true},
		{int(3), 3, true},
		{int64(3), 3, true},
		{uint64(3), 3, true},
		{json.Number("3.5"), 3.5, true},
		{"abc", 0, false},
		{nil, 0, false},
	}
	for _, c := range cases {
		got, ok := toFloat(c.in)
		if got != c.want || ok != c.ok {
			t.Errorf("toFloat(%v) = (%v,%v), want (%v,%v)", c.in, got, ok, c.want, c.ok)
		}
	}
}

func TestEqualAny(t *testing.T) {
	cases := []struct {
		a, b any
		want bool
	}{
		{1, 1.0, true},   // 数值跨类型相等
		{1, 2, false},
		{true, true, true},
		{true, false, false},
		{true, 1, false}, // bool vs 数值不等
		{"a", "a", true},
		{"a", "b", false},
		// DateTime 归一化:格式/时区/毫秒差异应判等
		{"2025-06-01T12:00:00Z", "2025-06-01T12:00:00Z", true},
		{"2025-06-01T12:00:00Z", "2025-06-01T12:00:00.000Z", true},
		{"2025-06-01T12:00:00Z", "2025-06-01T20:00:00+08:00", true},
		{"2025-06-01T12:00:00Z", "2025-06-01 12:00:00", true},
		{"2025-06-01T12:00:00Z", "2025-06-02T12:00:00Z", false},
		// epoch 毫秒 vs ISO 字符串(同一时刻)
		{"2025-06-01T12:00:00Z", float64(1748779200000), true},
		// TPT Java DateTime toString 格式 vs ISO 字符串(同一时刻)
		// 2025-01-01T00:00:00Z 的 utcTime = 133801632000000000
		{"2025-01-01T00:00:00Z", "DateTime{utcTime=133801632000000000, javaDate=Wed Jan 01 08:00:00 CST 2025}", true},
		// 2025-06-01T12:00:00Z 的 utcTime = 133932528000000000
		{"2025-06-01T12:00:00Z", "DateTime{utcTime=133932528000000000, javaDate=Sun Jun 01 20:00:00 CST 2025}", true},
		// 不同时刻应判不等
		{"2025-06-01T12:00:00Z", "DateTime{utcTime=133801632000000000, javaDate=Wed Jan 01 08:00:00 CST 2025}", false},
	}
	for _, c := range cases {
		if got := equalAny(c.a, c.b); got != c.want {
			t.Errorf("equalAny(%v,%v) = %v, want %v", c.a, c.b, got, c.want)
		}
	}
}

func TestRawEqual(t *testing.T) {
	a, _ := json.Marshal(123.45)
	b, _ := json.Marshal(123.45)
	c, _ := json.Marshal(99)
	if !rawEqual(a, b) {
		t.Error("equal raw not equal")
	}
	if rawEqual(a, c) {
		t.Error("different raw should not equal")
	}
	if rawEqual(nil, a) {
		t.Error("nil should not equal")
	}
	if rawEqual(a, json.RawMessage{}) {
		t.Error("empty should not equal")
	}
}

func TestTestValueFor(t *testing.T) {
	cases := []struct {
		ty   string
		want any
	}{
		{"Boolean", true},
		{"Double", 123.45},
		{"Float", 123.45},
		{"Int64", 9999999999},
		{"UInt64", 9999999999},
		{"Int32", 123},
		{"String", "verify_test"},
		{"DateTime", "2025-06-01T12:00:00Z"},
	}
	for _, c := range cases {
		got := testValueFor(c.ty)
		if got != c.want {
			t.Errorf("testValueFor(%q) = %v, want %v", c.ty, got, c.want)
		}
	}
}

func TestToJSONRaw(t *testing.T) {
	got := toJSONRaw(123.45)
	var v any
	if err := json.Unmarshal(got, &v); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if f, ok := v.(float64); !ok || f != 123.45 {
		t.Errorf("toJSONRaw -> %v", v)
	}
	if toJSONRaw(nil) != nil {
		t.Error("nil not preserved")
	}
}
