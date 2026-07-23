// Package tptapi 统一封装 Supcon SaaS / TPT 后台域的 HTTP 客户端。
//
// 一份代码覆盖三类业务端点（共享同一套登录 + 鉴权 + 错误码）：
//
//   - TPT admin 用户管理  (pkg/USER_MANAGER/internal/api  +  Python common/api.py 的 tpt-admin 部分)
//   - alg-manager 算法管理 (alg_update/common/api.py  +  alg_update/alg_toolbox/algapi.go)
//   - ibd-data-hub 位号 + 历史值 (data-hub-tool/common_api.py)
//
// 鉴权机制三家完全一致：POST /tpt-admin/system-manager/umsAdmin/login 拿 Bearer token，
// HTTPS 多租户场景额外带 TptSaasUserTenantryId / tenant-id cookie。
//
// 设计原则：
//   - 端点 URL、请求/响应字段、错误码语义与父级 Python 客户端 1:1 对齐
//   - 不依赖 Wails，可独立 go test
//   - 同一 Client 实例持有 token + cookies，Login 一次、其它方法共用
//   - 并发不保证安全（http.Client 自身并发安全，但 token/tenantID 字段写时需外层加锁）
package tptapi

import (
	"errors"
	"fmt"
	"net/http"
	"strings"
)

// 业务成功 code（与 common/api.py:21 / common_api.py 一致）。
const SuccessCode = "00000"

// 登录端点（与 common/api.py:52 / alg_update/alg_toolbox/algapi.go:157 一致）。
const LoginPath = "/tpt-admin/system-manager/umsAdmin/login"

// accountType 写死 "0"。
const LoginAccountType = "0"

// ErrAuthError 表示鉴权失败（登录态过期、token 无效等）。
// 由 doRequest 在 code ∈ {A0230,A0201,A0202,A0203} 或 msg 命中关键词时返回。
type ErrAuthError struct {
	Code string
	Msg  string
}

func (e *ErrAuthError) Error() string {
	return fmt.Sprintf("tpt auth error: [%s] %s", e.Code, e.Msg)
}

// IsAuthError 判断 err 是否为鉴权错误。
func IsAuthError(err error) bool {
	var ae *ErrAuthError
	return errors.As(err, &ae)
}

// ErrAPI 是平台返回的业务错误（非鉴权类），如 A0400 参数错误等。
type ErrAPI struct {
	Code string
	Msg  string
}

func (e *ErrAPI) Error() string {
	return fmt.Sprintf("tpt api error: [%s] %s", e.Code, e.Msg)
}

// IsAPIError 判断 err 是否为业务错误。
func IsAPIError(err error) bool {
	var ae *ErrAPI
	return errors.As(err, &ae)
}

// ErrHTTP 是 HTTP 层错误（4xx/5xx 非业务响应）。
type ErrHTTP struct {
	StatusCode int
	Body       string
}

func (e *ErrHTTP) Error() string {
	return fmt.Sprintf("http %d: %s", e.StatusCode, truncate(e.Body, 200))
}

// 鉴权码集合（与 common/api.py:30 / common_api.py:58 / algapi.go:119 对齐）。
var authCodes = map[string]bool{
	"A0230": true,
	"A0201": true,
	"A0202": true,
	"A0203": true,
}

// 鉴权关键词（与 common/api.py:34 / common_api.py:62 / algapi.go:124 对齐）。
var authKeywords = []string{
	"未登录", "登录已超时", "登录过期", "token过期", "无访问权限", "Unauthorized",
}

// IsAuthResponseCode 判断平台响应 code/msg 是否为鉴权错误。
func IsAuthResponseCode(code, msg string) bool {
	if authCodes[code] {
		return true
	}
	for _, kw := range authKeywords {
		if strings.Contains(msg, kw) {
			return true
		}
	}
	return false
}

// classifyHTTPError 把非 2xx HTTP 响应包成 ErrHTTP。
func classifyHTTPError(resp *http.Response, body []byte) error {
	return &ErrHTTP{
		StatusCode: resp.StatusCode,
		Body:       string(body),
	}
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n] + "..."
}
