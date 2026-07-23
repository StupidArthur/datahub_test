// startup_test.go - 实测 performance mock(1w+ 节点)启动耗时,验证 startWaitTimeout 上限是否合理。
// 依赖真实 python + ua_mocker 环境(配置持久化在 LoadMockerConfig);未配置则 skip。
package pyworker

import (
	"testing"
	"time"

	"ua_test_gui/internal/mock"
)

func TestStartupTimePerformance(t *testing.T) {
	mgr := NewMockManager(t.TempDir(), nil)
	spec, ok := mock.FindSpec("performance")
	if !ok {
		t.Fatal("performance spec 未找到")
	}
	t.Logf("performance 节点数=%d, startWaitTimeout 上限=%v", spec.NodeCount(), startWaitTimeout(spec))
	start := time.Now()
	rt, err := mgr.Start(spec)
	if err != nil {
		t.Skipf("启动失败(环境未就绪/端口占用): %v", err)
	}
	// 异步启动:测量从发起启动到 ready 的总耗时。
	deadline := time.Now().Add(startWaitTimeout(spec))
	for time.Now().Before(deadline) {
		if mgr.Status("performance") == "ready" {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}
	elapsed := time.Since(start)
	status := mgr.Status("performance")
	t.Logf("performance 启动耗时(到 ready): %v, 最终状态=%s (err=%v)", elapsed, status, err)
	if status != "ready" {
		t.Fatalf("mock 未在预期时间内就绪")
	}
	if rt != nil {
		mgr.Stop("performance")
		// 给进程退出留时间,避免 testing.T 的 TempDir cleanup 因 server.log 被占用而失败。
		time.Sleep(2 * time.Second)
	}
}
