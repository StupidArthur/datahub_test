// state.go - 登录态服务,持有已登录的 TptClient(线程安全)。
//
// 替代原 App.tpt + mu:登录态集中在 SubjectService,ProvisionService/VerifyService/EnvService 依赖它取 client。
package subject

import (
	"sync"
	"time"
)

// Service 登录态服务。
type Service struct {
	mu       sync.Mutex
	tpt      *TptClient
	info     SubjectUrl
	baseURL  string
	user     string
	password string
	tenantID string
	timeout  time.Duration
}

// NewService 创建未登录的服务。
func NewService() *Service { return &Service{} }

// Login 登录并持有客户端。password 仅流转不落日志。
func (s *Service) Login(baseURL, user, password, tenantID string, timeout time.Duration) (SubjectUrl, error) {
	if timeout <= 0 {
		timeout = 10 * time.Second
	}
	cli, err := LoginSubject(baseURL, user, password, tenantID, timeout)
	if err != nil {
		return SubjectUrl{}, err
	}
	su, _ := ParseSubjectURL(baseURL)
	s.mu.Lock()
	s.tpt = cli
	s.info = su
	s.baseURL = baseURL
	s.user = user
	s.password = password
	s.tenantID = tenantID
	s.timeout = timeout
	s.mu.Unlock()
	return su, nil
}

// Client 返回已登录客户端(nil=未登录);若 token 即将过期会自动重新登录刷新。
func (s *Service) Client() *TptClient {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.tpt == nil {
		return nil
	}
	if s.tpt.Expired() {
		cli, err := LoginSubject(s.baseURL, s.user, s.password, s.tenantID, s.timeout)
		if err != nil {
			// 刷新失败,保留旧客户端,让上层收到 401 后再处理
			return s.tpt
		}
		s.tpt = cli
	}
	return s.tpt
}

// Info 返回当前被测对象 URL 信息。
func (s *Service) Info() SubjectUrl {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.info
}
