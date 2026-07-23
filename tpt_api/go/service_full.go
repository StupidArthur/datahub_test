// service.go - 被测对象连接层:URL 截断 + 登录 + 统一请求。
//
// 对齐 python ua_test_harness/env/subject.py + tpt_api/client.py(AlgAPI)。
// 核心逻辑,不 import Wails,可独立 go test。
//
// URL 截断规则(填到哪一级都截出有效 base_url):
//   - 协议 http/https
//   - base_url = 协议://host:port,丢弃其后 path/query(规避 tpt-admin/tpt-admin 这类 405)
//   - 租户:query tenantId/tenant_id/tenant 优先;其次 path /tenant/{id};都没有=空(单租户)
//
// 登录:POST {base}/tpt-admin/system-manager/umsAdmin/login,body 包 data 顶层键,
// 响应 content.token,设 Authorization: Bearer。HTTPS 多租户额外带 tenantId body +
// TptSaasUserTenantryId/tenant-id cookie。
//
// 安全:密码仅函数参数流转,绝不落日志。
package tptapi

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// ParseSubjectURL 截断 URL -> 协议 + base_url + 租户。
func ParseSubjectURL(raw string) (SubjectUrl, error) {
	s := strings.TrimSpace(raw)
	if !strings.Contains(s, "://") {
		return SubjectUrl{}, fmt.Errorf("URL 缺协议(http/https): %q", raw)
	}
	u, err := url.Parse(s)
	if err != nil {
		return SubjectUrl{}, fmt.Errorf("URL 解析失败: %w", err)
	}
	scheme := strings.ToLower(u.Scheme)
	if scheme != "http" && scheme != "https" {
		return SubjectUrl{}, fmt.Errorf("仅支持 http/https,得到 %q", u.Scheme)
	}
	host := u.Hostname()
	if host == "" {
		return SubjectUrl{}, fmt.Errorf("URL 解析不出 host: %q", raw)
	}
	netloc := host
	if u.Port() != "" {
		netloc += ":" + u.Port()
	}

	// 租户:query 优先(tenantId/tenant_id/tenant)
	tenantID := ""
	q := u.Query()
	for _, k := range []string{"tenantId", "tenant_id", "tenant"} {
		if v := strings.TrimSpace(q.Get(k)); v != "" {
			tenantID = v
			break
		}
	}
	// 再看 path /tenant/{id}
	if tenantID == "" {
		parts := strings.Split(strings.Trim(u.Path, "/"), "/")
		for i, p := range parts {
			if p == "tenant" && i+1 < len(parts) {
				tenantID = parts[i+1]
				break
			}
		}
	}
	return SubjectUrl{Raw: s, Protocol: scheme, BaseURL: scheme + "://" + netloc, TenantID: tenantID}, nil
}

// LoginSubject 登录 TPT,返回已登录客户端。password 仅流转不落日志。
func LoginSubject(baseURL, user, password, tenantID string, timeout time.Duration) (*TptClient, error) {
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	baseURL = strings.TrimRight(baseURL, "/")
	c := &TptClient{
		baseURL:  baseURL,
		https:    strings.HasPrefix(baseURL, "https://"),
		tenantID: tenantID,
		http:     &http.Client{Timeout: timeout},
	}

	// 登录 body 必须包 data 顶层键,否则平台报 A0400
	body := map[string]any{
		"username":     user,
		"password":     password,
		"remember":     false,
		"accountType":  loginAccountType,
		"generateCode": false,
	}
	if c.https && tenantID != "" {
		body["tenantId"] = tenantID
	}
	content, err := c.request("POST", loginPath, body, true)
	if err != nil {
		return nil, fmt.Errorf("登录失败: %w", err)
	}
	var resp struct {
		Token string `json:"token"`
	}
	if err := json.Unmarshal(content, &resp); err != nil {
		return nil, fmt.Errorf("登录响应解析失败: %w", err)
	}
	if resp.Token == "" {
		return nil, fmt.Errorf("登录响应无 token")
	}
	c.token = resp.Token
	c.tokenExp = parseTokenExp(resp.Token)
	return c, nil
}

// parseTokenExp 解析 JWT 的 exp 字段;失败返回零值(不阻塞登录)。
func parseTokenExp(token string) time.Time {
	parts := strings.Split(token, ".")
	if len(parts) < 2 {
		return time.Time{}
	}
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return time.Time{}
	}
	var claims struct {
		Exp int64 `json:"exp"`
	}
	if err := json.Unmarshal(payload, &claims); err != nil {
		return time.Time{}
	}
	if claims.Exp <= 0 {
		return time.Time{}
	}
	return time.Unix(claims.Exp, 0)
}

// request 统一请求方法(对齐 AlgAPI._request)。
//   wrap=true:body 包 {data: body};wrap=false:body 直接作 JSON(调用方自己包 data)。
//   成功返回 content(json.RawMessage);业务 code 非 00000 返回 *TptAPIError。
func (c *TptClient) request(method, path string, body any, wrap bool) (json.RawMessage, error) {
	u := c.baseURL + "/" + strings.TrimLeft(path, "/")

	var jsonBody any
	if wrap && body != nil {
		jsonBody = map[string]any{"data": body}
	} else {
		jsonBody = body
	}

	var reqBody io.Reader
	if jsonBody != nil {
		b, err := json.Marshal(jsonBody)
		if err != nil {
			return nil, fmt.Errorf("请求序列化失败: %w", err)
		}
		reqBody = bytes.NewReader(b)
	}

	req, err := http.NewRequest(method, u, reqBody)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}
	if c.https {
		// HTTPS 多租户:带 tenantry cookie;模拟 python 的 tpt-token cookie
		if c.tenantID != "" {
			req.AddCookie(&http.Cookie{Name: "TptSaasUserTenantryId", Value: c.tenantID})
			req.AddCookie(&http.Cookie{Name: "tenant-id", Value: c.tenantID})
		}
		if c.token != "" {
			req.AddCookie(&http.Cookie{Name: "tpt-token", Value: c.token})
		}
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("http %d: %s", resp.StatusCode, truncateStr(string(data), 200))
	}

	// 业务码判定:code=="00000" 即成功;HTTPS 模式额外要求 isSuccess
	var env struct {
		Code      string          `json:"code"`
		Msg       string          `json:"msg"`
		Content   json.RawMessage `json:"content"`
		IsSuccess bool            `json:"isSuccess"`
	}
	if err := json.Unmarshal(data, &env); err != nil {
		return nil, fmt.Errorf("响应非 JSON: %s", truncateStr(string(data), 200))
	}
	ok := env.Code == successCode
	if c.https && !env.IsSuccess {
		ok = false
	}
	if !ok {
		return nil, &TptAPIError{Code: env.Code, Msg: env.Msg}
	}
	if len(env.Content) > 0 && string(env.Content) != "null" {
		return env.Content, nil
	}
	return data, nil // 无 content 返回整个 data
}

