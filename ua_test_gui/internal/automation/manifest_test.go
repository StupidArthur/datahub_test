// manifest_test.go - case-manifest.json 解析/校验单测。
package automation

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseManifest_OK(t *testing.T) {
	body := `{
	  "schemaVersion": 1,
	  "generatedAt": "2026-07-24T00:00:00Z",
	  "cases": [
	    {"id":"UA-1-1-01","chapter":"UA-1-1","title":"t","nodeid":"tests/integration/ua1/test_x.py::test_a","preconditions":[],"steps":["s"],"expected":["e"],"markers":["integration"]}
	  ]
	}`
	m, err := ParseManifest([]byte(body))
	if err != nil {
		t.Fatal(err)
	}
	if len(m.Cases) != 1 {
		t.Fatalf("cases=%d", len(m.Cases))
	}
	if m.Cases[0].ID != "UA-1-1-01" {
		t.Fatalf("id=%s", m.Cases[0].ID)
	}
}

func TestParseManifest_SchemaVersionMissing(t *testing.T) {
	_, err := ParseManifest([]byte(`{"cases":[]}`))
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestParseManifest_WrongVersion(t *testing.T) {
	_, err := ParseManifest([]byte(`{"schemaVersion":2,"cases":[{"id":"X","chapter":"X","title":"x","nodeid":"x::x"}]}`))
	if err == nil {
		t.Fatal("expected error for unsupported schemaVersion")
	}
}

func TestParseManifest_EmptyCases(t *testing.T) {
	_, err := ParseManifest([]byte(`{"schemaVersion":1,"cases":[]}`))
	if err == nil {
		t.Fatal("expected error for empty cases")
	}
}

func TestParseManifest_DuplicateID(t *testing.T) {
	body := `{"schemaVersion":1,"cases":[
		{"id":"DUP","chapter":"C","title":"t","nodeid":"a::x"},
		{"id":"DUP","chapter":"C","title":"t","nodeid":"b::y"}
	]}`
	_, err := ParseManifest([]byte(body))
	if err == nil || !strings.Contains(err.Error(), "duplicate case id") {
		t.Fatalf("expected duplicate id error, got %v", err)
	}
}

func TestParseManifest_DuplicateNodeID(t *testing.T) {
	body := `{"schemaVersion":1,"cases":[
		{"id":"A","chapter":"C","title":"t","nodeid":"same"},
		{"id":"B","chapter":"C","title":"t","nodeid":"same"}
	]}`
	_, err := ParseManifest([]byte(body))
	if err == nil || !strings.Contains(err.Error(), "duplicate nodeid") {
		t.Fatalf("expected duplicate nodeid error, got %v", err)
	}
}

func TestParseManifest_MissingFields(t *testing.T) {
	cases := map[string]string{
		"chapter": `{"schemaVersion":1,"cases":[{"id":"A","title":"t","nodeid":"a::x"}]}`,
		"title":   `{"schemaVersion":1,"cases":[{"id":"A","chapter":"C","nodeid":"a::x"}]}`,
		"nodeid":  `{"schemaVersion":1,"cases":[{"id":"A","chapter":"C","title":"t"}]}`,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := ParseManifest([]byte(body))
			if err == nil {
				t.Fatalf("expected error for missing %s", name)
			}
		})
	}
}

func TestLoadManifestFromFile(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "manifest.json")
	body := `{
	  "schemaVersion": 1,
	  "cases": [
	    {"id":"UA-1-1-01","chapter":"UA-1-1","title":"t","nodeid":"x.py::t"}
	  ]
	}`
	if err := os.WriteFile(p, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadManifestFromFile(p); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadManifestFromFile(filepath.Join(dir, "missing.json")); err == nil {
		t.Fatal("expected error for missing file")
	}
}

func TestManifest_FindByID(t *testing.T) {
	m, _ := ParseManifest([]byte(`{
		"schemaVersion": 1,
		"cases": [
			{"id":"UA-A","chapter":"A","title":"t","nodeid":"a.py::t"}
		]
	}`))
	if _, ok := m.FindByID("UA-A"); !ok {
		t.Fatal("expected to find UA-A")
	}
	if _, ok := m.FindByID("NOPE"); ok {
		t.Fatal("expected not found")
	}
}

func TestManifest_FindByNodeID(t *testing.T) {
	m, _ := ParseManifest([]byte(`{
		"schemaVersion": 1,
		"cases": [
			{"id":"UA-A","chapter":"A","title":"t","nodeid":"a.py::t"}
		]
	}`))
	if c, ok := m.FindByNodeID("a.py::t"); !ok || c.ID != "UA-A" {
		t.Fatalf("FindByNodeID ok=%v c=%+v", ok, c)
	}
}

func TestManifest_IDs_Sorted(t *testing.T) {
	m, _ := ParseManifest([]byte(`{
		"schemaVersion": 1,
		"cases": [
			{"id":"Z","chapter":"A","title":"t","nodeid":"z.py::t"},
			{"id":"A","chapter":"A","title":"t","nodeid":"a.py::t"}
		]
	}`))
	ids := m.IDs()
	if ids[0] != "A" || ids[1] != "Z" {
		t.Fatalf("ids=%v", ids)
	}
}