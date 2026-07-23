// ready.go - mock 就绪探针:waitPort(端口监听)+ gopcua Discover(UA server ready)。
//
// 端口开 ≠ UA server ready:ua_mocker(asyncua)启动后先开端口再初始化节点树,
// 大 mock(性能 11000 节点)初始化慢,仅 waitPort 会假报就绪。故追加 Discover 确认节点树就绪。
package pyworker

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"ua_test_gui/internal/adapters/opcua"
	"ua_test_gui/internal/env"
	"ua_test_gui/internal/mock"
)

// waitReady 就绪探针:waitPort + gopcua Discover。
func (m *MockManager) waitReady(spec mock.MockSpec, entry *runtimeEntry, timeout time.Duration) error {
	// 1. waitPort:轮询直到端口监听或超时(python 启动 + asyncua 开端口 = 这一阶段)
	portStart := time.Now()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !env.IsPortFree(spec.Port) {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}
	if env.IsPortFree(spec.Port) {
		return fmt.Errorf("端口 %d %v 内未监听", spec.Port, timeout)
	}
	portPhase := time.Since(portStart)

	// 2. gopcua Discover 确认 UA server ready(节点树已初始化)
	discStart := time.Now()
	cl := opcua.NewUaSourceClient(spec.Endpoint(), 1)
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	if err := cl.Connect(ctx); err != nil {
		return fmt.Errorf("端口已监听但 UA 连接失败(可能仍在初始化): %w", err)
	}
	defer cl.Close(ctx)
	nodes, err := cl.Discover(ctx)
	if err != nil {
		return fmt.Errorf("UA Discover 失败: %w", err)
	}
	discPhase := time.Since(discStart)
	entry.mu.Lock()
	entry.ready = true
	entry.mu.Unlock()
	// 节点数核对(warning,不阻塞就绪判定;ua_mocker Discover 只返回顶层 ns=1 节点,数量小于 NodeCount 属正常)
	want := spec.NodeCount()
	slog.Info("mock 就绪", "key", spec.Key, "wantNodes", want, "discoverTop", len(nodes),
		"端口阶段(py启动+开端口)", portPhase.String(), "Discover阶段", discPhase.String())
	return nil
}
