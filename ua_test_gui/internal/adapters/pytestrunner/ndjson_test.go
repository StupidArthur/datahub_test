// ndjson_test.go - NDJSON 解析单测。
package pytestrunner

import (
	"testing"

	"ua_test_gui/internal/automation"
)

func TestParseEventLine_CaseStarted(t *testing.T) {
	line := []byte(`{"event":"case_started","caseId":"UA-1","ts":"2026-01-01T00:00:00Z","index":1,"total":5}`)
	env, err := ParseEventLine(line)
	if err != nil {
		t.Fatal(err)
	}
	if env.EventType != "case_started" {
		t.Fatalf("event=%s", env.EventType)
	}
	if env.CaseID != "UA-1" {
		t.Fatalf("caseId=%s", env.CaseID)
	}
	// payload 必须不含 event 字段
	if string(env.Payload) == "" {
		t.Fatal("empty payload")
	}
	if contains(env.Payload, []byte(`"event"`)) {
		t.Fatalf("payload leaks event: %s", env.Payload)
	}
}

func TestParseEventLine_NoTs_FilledNow(t *testing.T) {
	env, err := ParseEventLine([]byte(`{"event":"log","caseId":"X","message":"hi"}`))
	if err != nil {
		t.Fatal(err)
	}
	if env.Ts == "" {
		t.Fatal("ts missing")
	}
}

func TestParseEventLine_Empty(t *testing.T) {
	if _, err := ParseEventLine(nil); err == nil {
		t.Fatal("expected error for empty")
	}
	if _, err := ParseEventLine([]byte(`{"foo":1}`)); err == nil {
		t.Fatal("expected error for missing event")
	}
	if _, err := ParseEventLine([]byte(`not json`)); err == nil {
		t.Fatal("expected error for bad json")
	}
}

func contains(haystack, needle []byte) bool {
	if len(needle) == 0 {
		return true
	}
	for i := 0; i+len(needle) <= len(haystack); i++ {
		match := true
		for j := 0; j < len(needle); j++ {
			if haystack[i+j] != needle[j] {
				match = false
				break
			}
		}
		if match {
			return true
		}
	}
	return false
}

var _ automation.EvEnvelope