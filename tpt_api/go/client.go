package tptapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// HTTPDoer 让 Client 可注入 mock transport（测试用）。
//
// 生产用 http.Client.Transport；测试可以用任意 http.RoundTripper 实现。
type HTTPDoer = http.RoundTripper

// Client 是 TPT 后台域的 HTTP 客户端，承载三套业务端点（user / algorithm / datahub）所需的全部鉴权态。
//
// 同一 Client 实例持有 token + tenantID + 业务缓存，所有方法共用。
// 不并发安全（http.Client 自身并发安全，但 token/tenantID / 缓存 字段写时需外层加锁）。
type Client struct {
	baseURL  string
	hc       *http.Client
	token    string
	tenantID string

	// 可选配置
	timeout time.Duration

	// 业务缓存（lazy 填充，单线程使用）
	cache        *algorithmsCache
	datahubCache *tagsCache
}

// algorithmsCache 是 alg-manager 算法的内存缓存（按需 lazy 填充）。
type algorithmsCache struct {
	algorithms []Algorithm
	sourceMap  map[string]Algorithm
	idMap      map[float64]Algorithm
}

func newAlgorithmsCache() *algorithmsCache {
	return &algorithmsCache{
		algorithms: nil,
		sourceMap:  make(map[string]Algorithm),
		idMap:      make(map[float64]Algorithm),
	}
}

func (a *algorithmsCache) reset(algos []Algorithm) {
	a.algorithms = algos
	a.sourceMap = make(map[string]Algorithm)
	a.idMap = make(map[float64]Algorithm)
	for _, algo := range algos {
		if sp, ok := algo["sourcePath"].(string); ok && sp != "" {
			a.sourceMap[sp] = algo
		}
		if id, ok := algo["id"].(float64); ok {
			a.idMap[id] = algo
		}
	}
}

// tagsCache 是 datahub tag 的内存缓存。
type tagsCache struct {
	tags    []map[string]any
	nameMap map[string]map[string]any
}

func newTagsCache() *tagsCache {
	return &tagsCache{
		tags:    nil,
		nameMap: make(map[string]map[string]any),
	}
}

func (t *tagsCache) setTags(records []map[string]any) {
	t.tags = records
	t.nameMap = make(map[string]map[string]any, len(records))
	for _, r := range records {
		if name, ok := r["tagName"].(string); ok && name != "" {
			t.nameMap[name] = r
		}
	}
}

// 业务默认值。
const defaultTimeout = 30 * time.Second

// Option 是构造 Client 的可选项。
type Option func(*Client)

// WithTimeout 覆盖默认 30s 超时。
func WithTimeout(d time.Duration) Option {
	return func(c *Client) { c.timeout = d }
}

// WithHTTPDoer 注入自定义 RoundTripper（测试用）。
//
// 注入后所有请求会经由这个 rt 转出；超时仍由 http.Client 自身控制。
func WithHTTPDoer(rt HTTPDoer) Option {
	return func(c *Client) { c.hc.Transport = rt }
}

// NewClient 构造一个未登录的 Client。
// baseURL 例：
//   - HTTP 单租户："http://10.16.11.1:31501"
//   - HTTPS 多租户："https://supcontpt.supcon.com"
func NewClient(baseURL string, opts ...Option) *Client {
	c := &Client{
		baseURL:      strings.TrimRight(baseURL, "/"),
		timeout:      defaultTimeout,
		hc:           &http.Client{Timeout: defaultTimeout},
		cache:        newAlgorithmsCache(),
		datahubCache: newTagsCache(),
	}
	for _, opt := range opts {
		opt(c)
	}
	if c.hc.Timeout == 0 {
		c.hc.Timeout = c.timeout
	}
	return c
}

// withTransport 替换底层 Transport（用于把 token 注入到 transport 上）。
// 不导出，避免误用。
func (c *Client) withTransport(rt http.RoundTripper) {
	c.hc.Transport = rt
}

// BaseURL 返回当前 base URL（去掉末尾 /）。
func (c *Client) BaseURL() string { return c.baseURL }

// Token 返回当前 token（未登录时为空）。
func (c *Client) Token() string { return c.token }

// TenantID 返回当前租户 ID。
func (c *Client) TenantID() string { return c.tenantID }

// IsLoggedIn 是否有可用 token。
func (c *Client) IsLoggedIn() bool { return c.token != "" }

// IsHTTPS 判定 baseURL 是否为 https 模式（HTTPS 模式才会带 tenant cookie）。
func (c *Client) IsHTTPS() bool { return strings.HasPrefix(c.baseURL, "https://") }

// Logout 清空登录态。
func (c *Client) Logout() {
	c.token = ""
}

// Login 用账号密码登录 TPT 后台（POST /tpt-admin/system-manager/umsAdmin/login）。
//
//   - tenantID 为空时不发 tenantId body 字段也不设 cookie（HTTP 单租户场景）
//   - tenantID 非空时（HTTPS 多租户）会发 tenantId body 字段，并设 TptSaasUserTenantryId / tenant-id cookie
//
// 成功返回 nil；token 自动注入，后续方法自动带 Bearer。
//
// 平台端点要求 body 包成 {"data": {...}}，与父级 Python _request(wrap=True) 一致。
// 重要：login body 必须包 data 顶层键，否则平台报 A0400「用户请求参数错误」。
func (c *Client) Login(ctx context.Context, username, password, tenantID string) error {
	c.tenantID = tenantID

	innerBody := map[string]any{
		"username":     username,
		"password":     password,
		"remember":     false,
		"accountType":  LoginAccountType,
		"generateCode": false,
	}
	if tenantID != "" {
		innerBody["tenantId"] = tenantID
	}
	body := map[string]any{"data": innerBody}

	var resp LoginResponse
	if err := c.doRequest(ctx, http.MethodPost, LoginPath, body, &resp, true /* hasContent */); err != nil {
		return err
	}
	if resp.Token == "" {
		return &ErrAPI{Code: "EMPTY", Msg: "login response missing token"}
	}
	c.token = resp.Token
	return nil
}

// LoginResponse 是登录接口 content 字段的形态。
type LoginResponse struct {
	Token string `json:"token"`
}

// OperationStatus 是 create / resetPwd / deleteTags 等写操作的状态返回（无 content）。
type OperationStatus struct {
	Code string `json:"code"` // 业务 code，00000 = 成功
	Msg  string `json:"msg"`
}

// ResponseEnvelope 是平台所有响应的统一外壳。
type ResponseEnvelope struct {
	Code    string          `json:"code"`
	Msg     string          `json:"msg"`
	Content json.RawMessage `json:"content"`
	Success bool            `json:"success"`
}

// doRequest 是核心 HTTP 调用，被 Login / 业务方法 复用。
//
// 参数：
//   - method: HTTP 方法（POST/GET/DELETE/PUT）
//   - path:   业务路径（不含 baseURL）
//   - body:   请求体（任意可 JSON 序列化的对象；nil 表示无 body）
//   - out:    解码目标（hasContent=true 时解码 content，false 时解码整体）
//   - hasContent: 响应是否包 content 字段
//
// 返回的错误分类：
//   - 401/403/非 2xx → ErrHTTP
//   - code ∈ 鉴权码集合 / msg 命中关键词 → ErrAuthError
//   - code != "00000" → ErrAPI
//   - JSON 解码失败 → 包装的 error
func (c *Client) doRequest(ctx context.Context, method, path string, body any, out any, hasContent bool) error {
	u := c.baseURL + "/" + strings.TrimLeft(path, "/")

	var bodyReader io.Reader
	if body != nil {
		jsonBody, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("marshal body: %w", err)
		}
		bodyReader = bytes.NewReader(jsonBody)
	}

	req, err := http.NewRequestWithContext(ctx, method, u, bodyReader)
	if err != nil {
		return fmt.Errorf("new request: %w", err)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Accept-Language", "zh-CN")

	// Bearer token（登录后所有请求都带）
	if c.token != "" {
		req.Header.Set("Authorization", "Bearer "+c.token)
	}

	// HTTPS 多租户：每次请求都带 cookie（兼容服务端从 cookie 读租户的场景）
	// 注意：cookie 名 "TptSaasUserTenantryId" 是平台侧的实际拼写（多一个 r），与 Python 端保持一致
	if c.tenantID != "" && c.IsHTTPS() {
		req.Header.Set("Cookie", fmt.Sprintf("TptSaasUserTenantryId=%s; tenant-id=%s", c.tenantID, c.tenantID))
	}

	resp, err := c.hc.Do(req)
	if err != nil {
		return fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()

	rawBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read body: %w", err)
	}

	// HTTP 状态码异常
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return classifyHTTPError(resp, rawBody)
	}

	// 业务层响应
	var envelope ResponseEnvelope
	if err := json.Unmarshal(rawBody, &envelope); err != nil {
		return fmt.Errorf("decode envelope: %w (raw: %s)", err, truncate(string(rawBody), 200))
	}

	// 鉴权错误特殊处理
	if IsAuthResponseCode(envelope.Code, envelope.Msg) {
		return &ErrAuthError{Code: envelope.Code, Msg: envelope.Msg}
	}

	// 业务 code != 00000 视为失败
	if envelope.Code != SuccessCode {
		return &ErrAPI{Code: envelope.Code, Msg: envelope.Msg}
	}

	// 解码 content（或整体）到 out
	if hasContent {
		if len(envelope.Content) == 0 {
			return fmt.Errorf("response missing content (code=%s)", envelope.Code)
		}
		if err := json.Unmarshal(envelope.Content, out); err != nil {
			return fmt.Errorf("decode content: %w", err)
		}
	} else {
		if err := json.Unmarshal(rawBody, out); err != nil {
			return fmt.Errorf("decode body: %w", err)
		}
	}
	return nil
}
