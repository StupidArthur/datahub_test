package tptapi

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"
)

// roundTripFunc 让测试可以注入自定义响应。
type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

// fakeResp 构造 *http.Response（含 io.ReadCloser body）。
func fakeResp(status int, body string) *http.Response {
	return &http.Response{
		StatusCode: status,
		Body:       io.NopCloser(strings.NewReader(body)),
		Header:     http.Header{},
	}
}

func TestLogin_Success(t *testing.T) {
	gotToken := ""
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		gotToken = r.Header.Get("Authorization")
		body := `{"code":"00000","msg":"OK","content":{"token":"abc123"}}`
		return fakeResp(200, body), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	if err := c.Login(context.Background(), "u", "p", ""); err != nil {
		t.Fatalf("Login: %v", err)
	}
	if c.Token() != "abc123" {
		t.Errorf("token = %q, want abc123", c.Token())
	}
	if !c.IsLoggedIn() {
		t.Error("expected IsLoggedIn=true")
	}
	if gotToken != "" {
		t.Errorf("expected no Authorization on login, got %q", gotToken)
	}
}

func TestLogin_AuthError(t *testing.T) {
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return fakeResp(200, `{"code":"A0230","msg":"登录已超时"}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	err := c.Login(context.Background(), "u", "p", "")
	if err == nil {
		t.Fatal("expected error")
	}
	if !IsAuthError(err) {
		t.Errorf("expected ErrAuthError, got %T: %v", err, err)
	}
}

func TestLogin_HTTPS_SetsTenantCookie(t *testing.T) {
	var cookie string
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		cookie = r.Header.Get("Cookie")
		return fakeResp(200, `{"code":"00000","msg":"OK","content":{"token":"abc"}}`), nil
	})
	c := NewClient("https://test", WithHTTPDoer(rt))
	if err := c.Login(context.Background(), "u", "p", "T1"); err != nil {
		t.Fatalf("Login: %v", err)
	}
	if !strings.Contains(cookie, "TptSaasUserTenantryId=T1") {
		t.Errorf("expected tenant cookie, got %q", cookie)
	}
	if !strings.Contains(cookie, "tenant-id=T1") {
		t.Errorf("expected tenant-id cookie, got %q", cookie)
	}
}

func TestDoRequest_BearerAttached(t *testing.T) {
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		auth := r.Header.Get("Authorization")
		if auth != "Bearer xyz" {
			t.Errorf("expected Bearer xyz, got %q", auth)
		}
		return fakeResp(200, `{"code":"00000","content":{"v":1}}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	c.token = "xyz"
	var out map[string]any
	if err := c.doRequest(context.Background(), http.MethodPost, "/x", nil, &out, true); err != nil {
		t.Fatalf("doRequest: %v", err)
	}
	if out["v"].(float64) != 1 {
		t.Errorf("content = %v, want v=1", out)
	}
}

func TestDoRequest_HTTPError(t *testing.T) {
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return fakeResp(500, "boom"), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	var out map[string]any
	err := c.doRequest(context.Background(), http.MethodPost, "/x", nil, &out, true)
	if err == nil {
		t.Fatal("expected error")
	}
	var he *ErrHTTP
	if !asErr(err, &he) {
		t.Fatalf("expected ErrHTTP, got %T", err)
	}
	if he.StatusCode != 500 {
		t.Errorf("status = %d, want 500", he.StatusCode)
	}
}

func TestDoRequest_MissingContent(t *testing.T) {
	rt := roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return fakeResp(200, `{"code":"00000"}`), nil
	})
	c := NewClient("http://test", WithHTTPDoer(rt))
	var out map[string]any
	err := c.doRequest(context.Background(), http.MethodPost, "/x", nil, &out, true)
	if err == nil {
		t.Fatal("expected error for missing content")
	}
}

func TestIsAuthResponseCode(t *testing.T) {
	cases := []struct {
		code, msg string
		want      bool
	}{
		{"00000", "OK", false},
		{"A0230", "登录已超时", true},
		{"A0201", "", true},
		{"A0400", "参数错误", false},
		{"X0001", "token过期", true},
		{"X0002", "Unauthorized", true},
		{"X0003", "无访问权限", true},
	}
	for _, tc := range cases {
		if got := IsAuthResponseCode(tc.code, tc.msg); got != tc.want {
			t.Errorf("IsAuthResponseCode(%q, %q) = %v, want %v", tc.code, tc.msg, got, tc.want)
		}
	}
}

// asErr 替身 errors.As（避免 import 依赖）。
func asErr(err error, target any) bool {
	type unwrapper interface{ Unwrap() error }
	for err != nil {
		switch v := target.(type) {
		case **ErrHTTP:
			if e, ok := err.(*ErrHTTP); ok {
				*v = e
				return true
			}
		case **ErrAPI:
			if e, ok := err.(*ErrAPI); ok {
				*v = e
				return true
			}
		case **ErrAuthError:
			if e, ok := err.(*ErrAuthError); ok {
				*v = e
				return true
			}
		}
		if u, ok := err.(unwrapper); ok {
			err = u.Unwrap()
		} else {
			return false
		}
	}
	return false
}

// 确保 stub json 导入不报 unused（被 TestDoRequest_BearerAttached 隐式使用）
var _ = json.Marshal
