package mock

import "testing"

func TestTptDataType(t *testing.T) {
	cases := []struct {
		in   string
		want int
		ok   bool
	}{
		{"Boolean", 1, true},
		{"Double", 11, true},
		{"Int64", 8, true},
		{"String", 12, true},   // TPT 已支持(2026-07-10)
		{"DateTime", 13, true}, // TPT 已支持(2026-07-10)
		{" Double ", 11, true}, // trim
		{"unknown", 0, false},
	}
	for _, c := range cases {
		got, ok := TptDataType(c.in)
		if got != c.want || ok != c.ok {
			t.Errorf("TptDataType(%q) = (%d,%v), want (%d,%v)", c.in, got, ok, c.want, c.ok)
		}
	}
}

func TestExpandNodeIDs(t *testing.T) {
	got := ExpandNodeIDs("mock_Double_r_", 3)
	want := []string{"mock_Double_r_1", "mock_Double_r_2", "mock_Double_r_3"}
	if len(got) != len(want) {
		t.Fatalf("len=%d, want %d", len(got), len(want))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("[%d] %q != %q", i, got[i], want[i])
		}
	}
	// count<1 -> 1
	if got := ExpandNodeIDs("x", 0); len(got) != 1 || got[0] != "x1" {
		t.Errorf("count=0 -> %v, want [x1]", got)
	}
}

func TestDefaultFor(t *testing.T) {
	cases := []struct {
		in   string
		want any
	}{
		{"Boolean", false},
		{"Double", 0.0},
		{"Float", 0.0},
		{"String", ""},
		{"DateTime", "2025-01-01T00:00:00Z"},
		{"Int32", 0},
		{"UInt64", 0},
	}
	for _, c := range cases {
		got := DefaultFor(c.in)
		if got != c.want {
			t.Errorf("DefaultFor(%q) = %v (%T), want %v (%T)", c.in, got, got, c.want, c.want)
		}
	}
}

func TestSupportedTypesIncludesStringDateTime(t *testing.T) {
	for _, ty := range SupportedTypes {
		if ty == "String" || ty == "DateTime" {
			return // found
		}
	}
	t.Errorf("SupportedTypes 应含 String 和 DateTime")
	if len(SupportedTypes) != 13 {
		t.Errorf("SupportedTypes len=%d, want 13", len(SupportedTypes))
	}
	if len(AllTypes()) != 13 {
		t.Errorf("AllTypes len=%d, want 13", len(AllTypes()))
	}
}
