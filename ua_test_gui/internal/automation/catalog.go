// catalog.go - 加载 catalog.json。
//
// catalog 是由 Python ua_test_harness.catalog export 导出的 JSON。
package automation

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

// LoadCatalogFromFile 直接读 JSON。
func LoadCatalogFromFile(path string) (Catalog, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return Catalog{}, fmt.Errorf("read catalog: %w", err)
	}
	return ParseCatalog(b)
}

// ParseCatalog 解析字节流。
func ParseCatalog(b []byte) (Catalog, error) {
	var c Catalog
	if err := json.Unmarshal(b, &c); err != nil {
		return c, fmt.Errorf("parse catalog: %w", err)
	}
	if c.Version == 0 {
		return c, errors.New("catalog version missing")
	}
	return c, nil
}

// FindCase 查 case 定义。
func (c Catalog) FindCase(id string) (Case, bool) {
	for _, ch := range c.Chapters {
		for _, cs := range ch.Cases {
			if cs.ID == id {
				return cs, true
			}
		}
	}
	return Case{}, false
}

// CaseIDs 返回全部 case id(排序)。
func (c Catalog) CaseIDs() []string {
	out := make([]string, 0)
	for _, ch := range c.Chapters {
		for _, cs := range ch.Cases {
			out = append(out, cs.ID)
		}
	}
	sort.Strings(out)
	return out
}

// ValidateCaseIDs 检查 selectedCaseIds 是否都在 catalog 中。
func (c Catalog) ValidateCaseIDs(ids []string) error {
	set := map[string]bool{}
	for _, id := range c.CaseIDs() {
		set[id] = true
	}
	for _, id := range ids {
		if !set[id] {
			return fmt.Errorf("case id not in catalog: %s", id)
		}
	}
	return nil
}

// FilterByChapters 按章节筛选用例。
func (c Catalog) FilterByChapters(chapters []string) []Case {
	set := map[string]bool{}
	for _, ch := range chapters {
		set[ch] = true
	}
	out := []Case{}
	for _, ch := range c.Chapters {
		if !set[ch.ID] {
			continue
		}
		out = append(out, ch.Cases...)
	}
	return out
}

// FilterByIDs 按 id 筛选用例。
func (c Catalog) FilterByIDs(ids []string) []Case {
	set := map[string]bool{}
	for _, id := range ids {
		set[id] = true
	}
	out := []Case{}
	for _, ch := range c.Chapters {
		for _, cs := range ch.Cases {
			if set[cs.ID] {
				out = append(out, cs)
			}
		}
	}
	return out
}

// DefaultCatalogPath 默认 catalog 路径(测试子包目录)。
func DefaultCatalogPath(workdir string) string {
	return filepath.Join(workdir, "ua_test_gui", "catalog.json")
}