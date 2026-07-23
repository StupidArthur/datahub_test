// subject.go - 登录绑定。薄层:DTO 转换 + 调 SubjectService,不碰 DB/Python。
package bindings

import (
	"time"

	"ua_test_gui/internal/subject"
)

// SubjectBinding 登录绑定。
type SubjectBinding struct {
	svc *subject.Service
}

// NewSubjectBinding 创建。
func NewSubjectBinding(svc *subject.Service) *SubjectBinding {
	return &SubjectBinding{svc: svc}
}

// LoginRequest 登录入参。Password 仅参数流转,不落日志。
type LoginRequest struct {
	BaseURL    string `json:"baseUrl"`
	Username   string `json:"username"`
	Password   string `json:"password"`
	TenantID   string `json:"tenantId"`
	TimeoutSec int    `json:"timeoutSec"`
}

// LoginResult 登录结果。
type LoginResult struct {
	OK       bool   `json:"ok"`
	BaseURL  string `json:"baseUrl"`
	TenantID string `json:"tenantId"`
}

// Login 登录 TPT,持有登录态。
func (b *SubjectBinding) Login(req LoginRequest) (resp LoginResult, err error) {
	defer RecoverPanic(&err)
	su, err := b.svc.Login(req.BaseURL, req.Username, req.Password, req.TenantID, time.Duration(req.TimeoutSec)*time.Second)
	if err != nil {
		return LoginResult{}, err
	}
	return LoginResult{OK: true, BaseURL: su.BaseURL, TenantID: su.TenantID}, nil
}
