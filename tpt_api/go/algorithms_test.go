package tptapi

import (
	"context"
	"net/http"
	"strings"
	"testing"
)

func TestListAlgorithms_PathHasExtend(t *testing.T) {
	var gotPath string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		gotPath = r.URL.Path + "?" + r.URL.RawQuery
		return fakeResp(200, `{"code":"00000","records":[]}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	_, err := c.ListAlgorithms(context.Background(), 1, 10, 0, "-createTime", "", "")
	if err != nil {
		t.Fatalf("ListAlgorithms: %v", err)
	}
	if !strings.Contains(gotPath, "extend=0") {
		t.Errorf("path = %q, want contains extend=0", gotPath)
	}
}

func TestGetAllAlgorithms_Paginates(t *testing.T) {
	calls := 0
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		calls++
		if calls == 1 {
			return fakeResp(200, `{"code":"00000","records":[{"id":1,"sourcePath":"a.py"},{"id":2,"sourcePath":"b.py"}]}`), nil
		}
		return fakeResp(200, `{"code":"00000","records":[]}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	all, err := c.GetAllAlgorithms(context.Background(), 2, "-createTime", "", "")
	if err != nil {
		t.Fatalf("GetAllAlgorithms: %v", err)
	}
	if len(all) != 2 {
		t.Errorf("len = %d, want 2", len(all))
	}
	if c.GetBySourcePath("a.py") == nil {
		t.Error("expected a.py in cache")
	}
	if c.GetByID(1) == nil {
		t.Error("expected id=1 in cache")
	}
}

func TestMatchLocalFiles_Mixed(t *testing.T) {
	dir := t.TempDir()
	for _, name := range []string{"in_platform.zip", "not_in_platform.py", "readme.txt"} {
		_ = writeFile(dir+"/"+name, "x")
	}
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return fakeResp(200, `{"code":"00000","records":[{"id":1,"sourcePath":"in_platform.zip","cores":2.0}]}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	if _, err := c.GetAllAlgorithms(context.Background(), 100, "-createTime", "", ""); err != nil {
		t.Fatalf("GetAllAlgorithms: %v", err)
	}
	matched, err := c.MatchLocalFiles(dir)
	if err != nil {
		t.Fatalf("MatchLocalFiles: %v", err)
	}
	// txt 被过滤掉；in_platform.zip 匹配；not_in_platform.py 不匹配
	gotExist, gotMissing := map[string]bool{}, map[string]bool{}
	for _, m := range matched {
		name := m["name"].(string)
		if m["isExist"].(bool) {
			gotExist[name] = true
		} else {
			gotMissing[name] = true
		}
	}
	if !gotExist["in_platform.zip"] {
		t.Error("expected in_platform.zip matched")
	}
	if !gotMissing["not_in_platform.py"] {
		t.Error("expected not_in_platform.py missing")
	}
}

func writeFile(path, content string) error {
	return writeFileImpl(path, []byte(content))
}
