// manifest.go - case-manifest.json 模型 + 校验。
//
// 生成的 docs/test_cases/case-manifest.json (schemaVersion=1) 的 Go 表示。
// 约束 (与生成器约定一致):
//   - schemaVersion 必须为 1
//   - 每个 Case 必须有 id/chapter/title/nodeid; id/nodeid 全文档唯一
//   - 不做执行调度; 仅作为 Case 列表和 nodeid 索引
package automation

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"sort"
)

// Manifest 顶层。
type Manifest struct {
	SchemaVersion int            `json:"schemaVersion"`
	GeneratedAt   string         `json:"generatedAt,omitempty"`
	Cases         []ManifestCase `json:"cases"`
}

// ManifestCase 一条 Case。
type ManifestCase struct {
	ID            string   `json:"id"`
	Chapter       string   `json:"chapter"`
	Title         string   `json:"title"`
	NodeID        string   `json:"nodeid"`
	Preconditions []string `json:"preconditions"`
	Steps         []string `json:"steps"`
	Expected      []string `json:"expected"`
	Markers       []string `json:"markers"`
}

// LoadManifestFromFile 读 JSON 文件。
func LoadManifestFromFile(path string) (Manifest, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return Manifest{}, fmt.Errorf("read manifest: %w", err)
	}
	return ParseManifest(b)
}

// ParseManifest 解析 JSON 字节流。
func ParseManifest(b []byte) (Manifest, error) {
	var m Manifest
	if err := json.Unmarshal(b, &m); err != nil {
		return m, fmt.Errorf("parse manifest: %w", err)
	}
	if err := m.Validate(); err != nil {
		return m, err
	}
	return m, nil
}

// Validate 校验 schemaVersion=1 与 Case 字段。
func (m Manifest) Validate() error {
	if m.SchemaVersion != 1 {
		return fmt.Errorf("unsupported schemaVersion=%d (want 1)", m.SchemaVersion)
	}
	if len(m.Cases) == 0 {
		return errors.New("manifest has no cases")
	}
	seenID := map[string]string{}
	seenNode := map[string]string{}
	for _, c := range m.Cases {
		if c.ID == "" {
			return errors.New("case missing id")
		}
		if c.Chapter == "" {
			return fmt.Errorf("case %q missing chapter", c.ID)
		}
		if c.Title == "" {
			return fmt.Errorf("case %q missing title", c.ID)
		}
		if c.NodeID == "" {
			return fmt.Errorf("case %q missing nodeid", c.ID)
		}
		if prev, ok := seenID[c.ID]; ok {
			return fmt.Errorf("duplicate case id %q (nodeid=%s vs %s)", c.ID, prev, c.NodeID)
		}
		if prev, ok := seenNode[c.NodeID]; ok {
			return fmt.Errorf("duplicate nodeid %s (cases %q vs %q)", c.NodeID, prev, c.ID)
		}
		seenID[c.ID] = c.NodeID
		seenNode[c.NodeID] = c.ID
	}
	return nil
}

// IDs 按字典序返回全部 case id。
func (m Manifest) IDs() []string {
	out := make([]string, 0, len(m.Cases))
	for _, c := range m.Cases {
		out = append(out, c.ID)
	}
	sort.Strings(out)
	return out
}

// FindByID 按 id 查找。
func (m Manifest) FindByID(id string) (ManifestCase, bool) {
	for _, c := range m.Cases {
		if c.ID == id {
			return c, true
		}
	}
	return ManifestCase{}, false
}

// FindByNodeID 按 pytest nodeid 查找。
func (m Manifest) FindByNodeID(nodeid string) (ManifestCase, bool) {
	for _, c := range m.Cases {
		if c.NodeID == nodeid {
			return c, true
		}
	}
	return ManifestCase{}, false
}