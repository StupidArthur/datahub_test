// junit.go - JUnit XML 解析与 pytest 状态映射。
//
// 解析 pytest --junitxml 输出; 输出每条 <testcase> 的标准化 CaseJUnitResult。
//
// 设计要点:
//   - 只识别 <testsuite>/<testcase>/<failure>/<error>/<skipped>;忽略其他元素
//   - xfail 识别: <skipped type="pytest.xfail"> 或 message 含 "xfail"
//   - xpass 识别: message 为 "xpass" (pytest 默认将 xpass 记录为普通 passing,
//     仅在 --strict-xfail 时区分; 本解析器保守标记, xpass 在普通模式下记为 passed)
//   - 不假设 JUnit XML 中存在 manifest; 只把 nodeid 作为字符串返回
package nativepytest

import (
	"bytes"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"strings"
)

// CaseStatus 来自 JUnit XML 的运行结果。
type CaseStatus string

const (
	StatusPassed  CaseStatus = "passed"
	StatusFailed  CaseStatus = "failed"
	StatusError   CaseStatus = "error"
	StatusSkipped CaseStatus = "skipped"
	StatusXFail   CaseStatus = "xfail"
	StatusXPass   CaseStatus = "xpass"
)

// CaseJUnitResult 单条 JUnit 用例结果。
type CaseJUnitResult struct {
	Classname string     `json:"classname"`
	Name      string     `json:"name"`
	NodeID    string     `json:"nodeid"`
	Status    CaseStatus `json:"status"`
	Duration  float64    `json:"duration"`
	Message   string     `json:"message,omitempty"`
	Details   string     `json:"details,omitempty"`
	skipType  string     `json:"-"`
}

// ParseJUnit 解析 pytest 输出的 JUnit XML。
func ParseJUnit(b []byte) ([]CaseJUnitResult, error) {
	if len(bytes.TrimSpace(b)) == 0 {
		return nil, errors.New("empty JUnit XML")
	}
	dec := xml.NewDecoder(bytes.NewReader(b))
	dec.Strict = false
	dec.CharsetReader = func(_ string, input io.Reader) (io.Reader, error) { return input, nil }

	var (
		results []CaseJUnitResult
		current *caseBuilder
	)
	for {
		tok, err := dec.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, fmt.Errorf("xml token: %w", err)
		}
		switch t := tok.(type) {
		case xml.StartElement:
			switch t.Name.Local {
			case "testcase":
				cb := &caseBuilder{}
				for _, a := range t.Attr {
					switch a.Name.Local {
					case "classname":
						cb.classname = a.Value
					case "name":
						cb.name = a.Value
					case "time":
						cb.duration = parseFloat(a.Value)
					}
				}
				current = cb
			case "failure":
				if current != nil {
					current.status = StatusFailed
					current.inDetails = "failure"
					for _, a := range t.Attr {
						if a.Name.Local == "message" {
							current.message = a.Value
						}
					}
				}
			case "error":
				if current != nil {
					current.status = StatusError
					current.inDetails = "error"
					for _, a := range t.Attr {
						if a.Name.Local == "message" {
							current.message = a.Value
						}
					}
				}
			case "skipped":
				if current != nil {
					current.status = StatusSkipped
					current.inDetails = "skipped"
					for _, a := range t.Attr {
						switch a.Name.Local {
						case "message":
							current.message = a.Value
						case "type":
							current.skipType = a.Value
						}
					}
				}
			}
		case xml.EndElement:
			switch t.Name.Local {
			case "testcase":
				if current != nil {
					res := current.build()
					results = append(results, res)
					current = nil
				}
			case "failure", "error", "skipped":
				if current != nil {
					current.inDetails = ""
				}
			}
		case xml.CharData:
			if current != nil && current.inDetails != "" {
				current.details.Write(t)
			}
		}
	}

	for i := range results {
		r := &results[i]
		if r.Status != StatusSkipped {
			continue
		}
		if r.skipType == "pytest.xfail" || r.skipType == "pytest.xpass" {
			r.Status = StatusXFail
			if strings.EqualFold(r.Message, "xpass") {
				r.Status = StatusXPass
			}
			continue
		}
		combined := r.Message + "\n" + r.Details
		lower := strings.ToLower(combined)
		switch {
		case strings.Contains(lower, "xpass"):
			r.Status = StatusXPass
		case strings.Contains(lower, "xfail"):
			r.Status = StatusXFail
		}
	}

	return results, nil
}

type caseBuilder struct {
	classname string
	name      string
	duration  float64
	status    CaseStatus
	message   string
	details   strings.Builder
	inDetails string
	skipType  string
}

func (cb *caseBuilder) build() CaseJUnitResult {
	r := CaseJUnitResult{
		Classname: cb.classname,
		Name:      cb.name,
		NodeID:    cb.classname + "::" + cb.name,
		Status:    cb.status,
		Duration:  cb.duration,
		Message:   strings.TrimSpace(cb.message),
		Details:   strings.TrimSpace(cb.details.String()),
		skipType:  cb.skipType,
	}
	if r.Status == "" {
		r.Status = StatusPassed
	}
	return r
}

func parseFloat(s string) float64 {
	var v float64
	_, _ = fmt.Sscanf(s, "%f", &v)
	return v
}