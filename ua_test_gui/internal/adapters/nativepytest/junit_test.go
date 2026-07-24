// junit_test.go - nativepytest.ParseJUnit 单测。
package nativepytest

import (
	"strings"
	"testing"
)

const sampleJUnit = `<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="0.123">
    <testcase classname="tests.test_a" name="test_pass" time="0.01"/>
    <testcase classname="tests.test_a" name="test_fail" time="0.02">
      <failure message="assert failed">assert 1 == 2</failure>
    </testcase>
    <testcase classname="tests.test_a" name="test_error" time="0.03">
      <error message="boom">Traceback...</error>
    </testcase>
    <testcase classname="tests.test_a" name="test_skip" time="0.00">
      <skipped message="reason">skip msg</skipped>
    </testcase>
  </testsuite>
</testsuites>`

func TestParseJUnit_AllStatuses(t *testing.T) {
	res, err := ParseJUnit([]byte(sampleJUnit))
	if err != nil {
		t.Fatal(err)
	}
	if len(res) != 4 {
		t.Fatalf("len=%d", len(res))
	}
	want := map[string]CaseStatus{
		"test_pass":  StatusPassed,
		"test_fail":  StatusFailed,
		"test_error": StatusError,
		"test_skip":  StatusSkipped,
	}
	for _, r := range res {
		if want[r.Name] != r.Status {
			t.Fatalf("%s: got %s want %s", r.Name, r.Status, want[r.Name])
		}
		if r.NodeID != "tests.test_a::"+r.Name {
			t.Fatalf("nodeid=%s", r.NodeID)
		}
	}
	if res[1].Message == "" || res[1].Details == "" {
		t.Fatalf("failure should populate message+details: %+v", res[1])
	}
}

func TestParseJUnit_XFail(t *testing.T) {
	body := `<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="t.x" name="t_xfail" time="0">
      <skipped message="xfail" type="pytest.xfail">reason: expected fail</skipped>
    </testcase>
  </testsuite>
</testsuites>`
	res, err := ParseJUnit([]byte(body))
	if err != nil {
		t.Fatal(err)
	}
	if len(res) != 1 || res[0].Status != StatusXFail {
		t.Fatalf("got %+v", res)
	}
}

func TestParseJUnit_XPass(t *testing.T) {
	body := `<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="t.x" name="t_xpass" time="0">
      <skipped message="xpass" type="pytest.xfail">XPASS: unexpectedly passed</skipped>
    </testcase>
  </testsuite>
</testsuites>`
	res, err := ParseJUnit([]byte(body))
	if err != nil {
		t.Fatal(err)
	}
	if len(res) != 1 || res[0].Status != StatusXPass {
		t.Fatalf("got %+v", res)
	}
}

func TestParseJUnit_XFail_NoType(t *testing.T) {
	body := `<?xml version="1.0"?>
<testsuites>
  <testsuite>
    <testcase classname="t.x" name="t_xfail" time="0">
      <skipped message="xfail">pytest.xfail reason</skipped>
    </testcase>
  </testsuite>
</testsuites>`
	res, err := ParseJUnit([]byte(body))
	if err != nil {
		t.Fatal(err)
	}
	if len(res) != 1 || res[0].Status != StatusXFail {
		t.Fatalf("got %+v", res)
	}
}

func TestParseJUnit_EmptyXML(t *testing.T) {
	if _, err := ParseJUnit(nil); err == nil {
		t.Fatal("expected error")
	}
	if _, err := ParseJUnit([]byte("   ")); err == nil {
		t.Fatal("expected error for whitespace only")
	}
}

func TestParseJUnit_MalformedXML(t *testing.T) {
	if _, err := ParseJUnit([]byte("<not-valid")); err == nil {
		t.Fatal("expected error")
	}
}

func TestParseJUnit_NoFailureNodeIDStillAssembled(t *testing.T) {
	body := `<?xml version="1.0"?>
<testsuites><testsuite>
<testcase classname="m1" name="t1" time="0.5"/>
</testsuite></testsuites>`
	res, err := ParseJUnit([]byte(body))
	if err != nil {
		t.Fatal(err)
	}
	if res[0].NodeID != "m1::t1" || res[0].Duration != 0.5 {
		t.Fatalf("got %+v", res[0])
	}
	if res[0].Status != StatusPassed {
		t.Fatalf("status=%s", res[0].Status)
	}
	if strings.TrimSpace(res[0].Message) != "" {
		t.Fatalf("expected empty message, got %q", res[0].Message)
	}
}