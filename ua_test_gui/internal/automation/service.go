// service.go - Service 的 Wails binding 暴露层。
//
// 真正的 Service 类型见 runner.go;这里只暴露 Binding 需要的薄包装与
// service_test.go 用的纯函数 helper。
package automation

// BoolPtr 工具。
func BoolPtr(b bool) *bool { return &b }

// ServiceHasRunner 判断 service 是否已配置 runner(单元测试用)。
func ServiceHasRunner(s *Service) bool { return s != nil && s.runner != nil }

// ServiceHasStore 判断 service 是否已配置 store。
func ServiceHasStore(s *Service) bool { return s != nil && s.store != nil }