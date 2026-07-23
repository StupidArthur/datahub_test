// node_access_test.go - 验证分容器后节点仍可按 NodeId 直访(Read/Write/Readback)。
// 分容器改了 browse path(Objects/mocker/mocker_N/变量),但 Go 侧用 NodeId 直访,此处确认读写不破。
package pyworker

import (
	"context"
	"testing"
	"time"

	"ua_test_gui/internal/adapters/opcua"
	"ua_test_gui/internal/mock"
)

func TestPerformanceNodeAccess(t *testing.T) {
	mgr := NewMockManager(t.TempDir(), nil)
	spec, ok := mock.FindSpec("performance")
	if !ok {
		t.Fatal("performance spec 未找到")
	}
	rt, err := mgr.Start(spec)
	if err != nil {
		t.Skipf("启动失败(环境未就绪/端口占用): %v", err)
	}
	// 异步启动:轮询等待就绪,最多等 startWaitTimeout。
	deadline := time.Now().Add(startWaitTimeout(spec))
	for time.Now().Before(deadline) {
		if mgr.Status("performance") == "ready" {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}
	if mgr.Status("performance") != "ready" {
		t.Fatalf("mock 未在预期时间内就绪")
	}
	defer func() {
		mgr.Stop("performance")
		// 给进程退出留时间,避免 TempDir cleanup 因 server.log 被占用而失败。
		time.Sleep(2 * time.Second)
	}()

	// 取一个可写 Double 节点
	var ws mock.TagSpec
	for _, s := range mock.TagSpecsFromMock(spec, 10) {
		if s.Writable && s.MockerType == "Double" {
			ws = s
			break
		}
	}
	if ws.Name == "" {
		t.Fatal("无 writable Double 节点")
	}

	cl := opcua.NewUaSourceClient(rt.Endpoint, 1)
	ctx := context.Background()
	if err := cl.Connect(ctx); err != nil {
		t.Fatalf("连接 UA 失败: %v", err)
	}
	defer cl.Close(ctx)

	v, err := cl.Read(ctx, ws.Name)
	if err != nil {
		t.Fatalf("Read %s 失败: %v", ws.Name, err)
	}
	t.Logf("Read %s = %v", ws.Name, v)

	if err := cl.Write(ctx, ws.Name, 123.456); err != nil {
		t.Fatalf("Write %s 失败: %v", ws.Name, err)
	}
	v2, err := cl.Read(ctx, ws.Name)
	if err != nil {
		t.Fatalf("Readback %s 失败: %v", ws.Name, err)
	}
	t.Logf("Readback %s = %v (写入 123.456)", ws.Name, v2)
	if v2 == nil {
		t.Errorf("readback 为 nil,节点不可达或不可写")
	}
}
