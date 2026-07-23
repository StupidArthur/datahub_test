// catalog_test.go - catalog loader 单测。
package automation

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadCatalogFromFile_OK(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "c.json")
	body := `{
	  "version": 1,
	  "generatedAt": "2026-07-12T00:00:00Z",
	  "chapters": [
	    {"id":"UA-A","title":"A","cases":[{"id":"UA-A-1","title":"a","implemented":true,"kind":"regression"}]},
	    {"id":"UA-B","title":"B","cases":[{"id":"UA-B-1","title":"b","implemented":true,"kind":"performance"}]}
	  ]
	}`
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	c, err := LoadCatalogFromFile(p)
	if err != nil {
		t.Fatal(err)
	}
	if len(c.Chapters) != 2 {
		t.Fatalf("chapters=%d", len(c.Chapters))
	}
	if ids := c.CaseIDs(); len(ids) != 2 || ids[0] != "UA-A-1" || ids[1] != "UA-B-1" {
		t.Fatalf("ids=%v", ids)
	}
	if err := c.ValidateCaseIDs([]string{"UA-A-1"}); err != nil {
		t.Fatal(err)
	}
	if err := c.ValidateCaseIDs([]string{"NOPE"}); err == nil {
		t.Fatal("expected error")
	}
	cs, ok := c.FindCase("UA-B-1")
	if !ok || !cs.Destructive == false && cs.Kind != "performance" {
		t.Fatalf("FindCase=%+v ok=%v", cs, ok)
	}
}

func TestParseCatalog_VersionMissing(t *testing.T) {
	_, err := ParseCatalog([]byte(`{"chapters":[]}`))
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestFilterByChapters(t *testing.T) {
	c := Catalog{Version: 1, Chapters: []Chapter{
		{ID: "UA-A", Cases: []Case{{ID: "UA-A-1"}, {ID: "UA-A-2"}}},
		{ID: "UA-B", Cases: []Case{{ID: "UA-B-1"}}},
	}}
	out := c.FilterByChapters([]string{"UA-A"})
	if len(out) != 2 {
		t.Fatalf("filter chapters=%v", out)
	}
	out2 := c.FilterByIDs([]string{"UA-B-1", "UA-A-1"})
	if len(out2) != 2 {
		t.Fatalf("filter ids=%v", out2)
	}
}