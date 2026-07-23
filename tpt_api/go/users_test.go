package tptapi

import (
	"context"
	"net/http"
	"strings"
	"testing"
)

func TestListUsers(t *testing.T) {
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		// 检查 adminWhere 字段构造
		body := `{"code":"00000","content":{"records":[{"id":1,"username":"u1","nickName":"n1"}],"total":1,"size":10,"current":1,"pages":1}}`
		return fakeResp(200, body), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	resp, err := c.ListUsers(context.Background(), 1, 10, "", "k", "-createTime")
	if err != nil {
		t.Fatalf("ListUsers: %v", err)
	}
	if len(resp.Records) != 1 || resp.Records[0].Username != "u1" {
		t.Errorf("records = %+v", resp.Records)
	}
}

func TestListUsers_EmptyKeyword(t *testing.T) {
	var sentBody string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		buf, _ := io_ReadAll(r.Body)
		sentBody = string(buf)
		return fakeResp(200, `{"code":"00000","content":{"records":[],"total":0,"size":10,"current":1,"pages":0}}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	_, _ = c.ListUsers(context.Background(), 1, 10, "", "", "")
	// 空 keyword 时 adminWhere 应为 {}
	if !strings.Contains(sentBody, `"adminWhere":{}`) {
		t.Errorf("expected empty adminWhere, got body=%s", sentBody)
	}
}

func TestCreateUser_DefaultsApplied(t *testing.T) {
	var sentBody string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		buf, _ := io_ReadAll(r.Body)
		sentBody = string(buf)
		return fakeResp(200, `{"code":"00000","msg":"OK"}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	_, err := c.CreateUser(context.Background(), UserDraft{
		Username: "alice", Password: "p", NickName: "A", Email: "a@x", Phone: "1",
	})
	if err != nil {
		t.Fatalf("CreateUser: %v", err)
	}
	for _, want := range []string{
		`"orgIds":[1]`, `"roleIds":"5"`, `"type":"2"`, `"gender":"1"`, `"orgName":"默认组织"`,
	} {
		if !strings.Contains(sentBody, want) {
			t.Errorf("missing %s in body: %s", want, sentBody)
		}
	}
}

func TestResetPassword(t *testing.T) {
	var sentBody string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method != http.MethodPost || !strings.Contains(r.URL.Path, "/resetPwd") {
			t.Errorf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		buf, _ := io_ReadAll(r.Body)
		sentBody = string(buf)
		return fakeResp(200, `{"code":"00000","msg":"OK"}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "t"
	_, err := c.ResetPassword(context.Background(), 42, "newPwd")
	if err != nil {
		t.Fatalf("ResetPassword: %v", err)
	}
	if !strings.Contains(sentBody, `"id":42`) || !strings.Contains(sentBody, `"newPwd":"newPwd"`) {
		t.Errorf("unexpected body: %s", sentBody)
	}
}
