// verify.go - 验证执行绑定。
package bindings

import "ua_test_gui/internal/verify"

// VerifyBinding 验证绑定。
type VerifyBinding struct {
	svc *verify.Service
}

// NewVerifyBinding 创建。
func NewVerifyBinding(svc *verify.Service) *VerifyBinding {
	return &VerifyBinding{svc: svc}
}

// RunVerification 执行 11 类型读写回写验证。
func (b *VerifyBinding) RunVerification(req verify.VerifyRequest) (resp verify.VerifyRunResult, err error) {
	defer RecoverPanic(&err)
	resp, err = b.svc.RunVerification(req)
	return
}
