package tptapi

import (
	"context"
	"fmt"
	"net/http"
)

// TPT admin 用户管理端点（与 USER_MANAGER/internal/api/users.go 1:1 对齐）。

const (
	// UserListByOrgPath 分页拉后台用户列表
	UserListByOrgPath = "/xpt-system/api/system-manager/umsAdmin/listByOrgId"
	// UserCreatePath 创建后台用户
	UserCreatePath = "/xpt-system/api/system-manager/umsAdmin"
	// UserResetPwdPath 重置后台用户密码
	UserResetPwdPath = "/xpt-system/api/system-manager/umsAdmin/resetPwd"
)

// User 是 listByOrgId 返回的单条记录。
type User struct {
	ID         int64  `json:"id"`
	Username   string `json:"username"`
	Code       string `json:"code"`
	NickName   string `json:"nickName"`
	Email      string `json:"email"`
	Phone      string `json:"phone"`
	Gender     int    `json:"gender"`
	Status     int    `json:"status"`
	Type       int    `json:"type"`
	TenantID   string `json:"tenantId"`
	DelFlag    int    `json:"delFlag"`
	CreateTime string `json:"createTime"`
	LoginTime  string `json:"loginTime"`
	UpdateTime string `json:"updateTime"`
}

// UserDraft 是 create 时的输入载荷。
//
// orgIds / roleIds 在 v1 不暴露给前端，写死 [1] / "5"。
type UserDraft struct {
	Username string `json:"username"` // 必填，登录账号
	Password string `json:"password"` // 必填，明文（平台 UMS 不做 hash）
	NickName string `json:"nickName"` // 必填，昵称 / 显示名
	Email    string `json:"email"`    // 可选
	Phone    string `json:"phone"`    // 可选
}

// PageResponse 是 list 接口的 MyBatis Page 结构。
type PageResponse struct {
	Records []User `json:"records"`
	Total   int64  `json:"total"`
	Size    int    `json:"size"`
	Current int    `json:"current"`
	Pages   int    `json:"pages"`
	Orders  []any  `json:"orders"`
}

// DefaultSearchFields 是 ListUsers 的默认模糊搜索字段。
var DefaultSearchFields = []string{"nickName", "username", "phone", "email"}

// ListUsers 分页拉后台用户列表。
//
//   - page 从 1 开始
//   - pageSize 默认 10
//   - orgID 空串表示全部组织
//   - keyword 空串表示不过滤；非空时跨 nickname/username/phone/email 任一字段模糊匹配
//   - searchFields 自定义模糊字段，默认 DefaultSearchFields
func (c *Client) ListUsers(ctx context.Context, page, pageSize int, orgID, keyword, sort string, searchFields ...string) (*PageResponse, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 {
		pageSize = 10
	}
	if len(searchFields) == 0 {
		searchFields = DefaultSearchFields
	}
	fieldKeys := ""
	for i, f := range searchFields {
		if i > 0 {
			fieldKeys += "|"
		}
		fieldKeys += "*" + f + "*"
	}
	adminWhere := map[string]string{}
	if keyword != "" {
		adminWhere[fieldKeys] = keyword
	}

	body := map[string]any{
		"data": map[string]any{
			"adminWhere": adminWhere,
			"orgId":      orgID,
		},
		"requestBase": map[string]any{
			"page": fmt.Sprintf("%d-%d", page, pageSize),
			"sort": sort,
		},
	}

	var out PageResponse
	if err := c.doRequest(ctx, http.MethodPost, UserListByOrgPath, body, &out, true); err != nil {
		return nil, err
	}
	return &out, nil
}

// GetAllUsers 自动翻页拉全部后台用户。
//
// 返回所有 users（不去重，不去重 caller 负责）。
func (c *Client) GetAllUsers(ctx context.Context, keyword, sort string, pageSize int, searchFields ...string) ([]User, error) {
	if pageSize < 1 {
		pageSize = 200
	}
	var all []User
	page := 1
	for {
		resp, err := c.ListUsers(ctx, page, pageSize, "", keyword, sort, searchFields...)
		if err != nil {
			return all, err
		}
		all = append(all, resp.Records...)
		if len(resp.Records) < pageSize {
			break
		}
		page++
	}
	return all, nil
}

// CreateUser 创建一个后台用户（POST /xpt-system/api/system-manager/umsAdmin）。
// 响应不含 userId，调用方需 GetAllUsers 反查 username 拿 id。
//
// 内部固定参数（v1 不暴露给前端）：
//   - status: 0
//   - orgIds: [1]
//   - orgName: "默认组织"
//   - type: "2" (普通用户)
//   - roleIds: "5"
//   - gender: "1"
//   - code: 沿用 username
//   - icon: ""
func (c *Client) CreateUser(ctx context.Context, draft UserDraft) (*OperationStatus, error) {
	body := map[string]any{
		"data": map[string]any{
			"status":   0,
			"orgIds":   []int{1},
			"username": draft.Username,
			"code":     draft.Username,
			"nickName": draft.NickName,
			"password": draft.Password,
			"gender":   "1",
			"email":    draft.Email,
			"phone":    draft.Phone,
			"orgName":  "默认组织",
			"type":     "2",
			"roleIds":  "5",
			"icon":     "",
		},
	}

	var out OperationStatus
	if err := c.doRequest(ctx, http.MethodPost, UserCreatePath, body, &out, false); err != nil {
		return nil, err
	}
	return &out, nil
}

// ResetPassword 重置指定用户的密码（POST /xpt-system/api/system-manager/umsAdmin/resetPwd）。
// userID 来自 listByOrgId 返回的 id 字段。
//
// 注意：平台行为是 reset 后旧密码仍可登录，重置成功 ≠ 旧密码失效。
func (c *Client) ResetPassword(ctx context.Context, userID int64, newPassword string) (*OperationStatus, error) {
	body := map[string]any{
		"data": map[string]any{
			"id":         userID,
			"newPwd":     newPassword,
			"confirmPwd": newPassword,
		},
	}

	var out OperationStatus
	if err := c.doRequest(ctx, http.MethodPost, UserResetPwdPath, body, &out, false); err != nil {
		return nil, err
	}
	return &out, nil
}
