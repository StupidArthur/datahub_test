// lifecycle.go - 应用生命周期:Startup(日志 + 注入 notifier)/Shutdown(停 mock + 关库)。
//
// wails ctx 在 Startup 注入,经 wailsNotifier 转 EventsEmit(状态事件推送)。
package app

import (
	"context"
	"log/slog"

	"github.com/wailsapp/wails/v2/pkg/runtime"

	"ua_test_gui/internal/adapters/logging"
	"ua_test_gui/internal/automation"
)

// Startup 应用启动:初始化日志、注入 mock 状态事件通知器(wails ctx 就绪)。
func (c *Container) Startup(ctx context.Context) {
	logging.InitLogger("")
	slog.Info("应用启动", "db", DefaultConfig().DBPath)
	c.mockMgr.SetNotifier(wailsNotifier{ctx: ctx})
	if c.automation != nil {
		c.automation.RecoverInterruptedRun(0)
	}
}

// Shutdown 应用关闭:停所有 mock、关库。
func (c *Container) Shutdown(ctx context.Context) {
	if c.automation != nil {
		if active, _ := c.automation.GetActiveTestRun(); active != nil {
			_, _ = c.automation.StopTestRun(active.ID)
		}
	}
	c.mockMgr.StopAll()
	if c.store != nil {
		c.store.Close()
	}
	slog.Info("应用关闭")
}

// wailsNotifier 实现 mock.Notifier,转 Wails EventsEmit(mock:state 事件)。
type wailsNotifier struct {
	ctx context.Context
}

func (n wailsNotifier) Emit(event string, data any) {
	runtime.EventsEmit(n.ctx, event, data)
}

// _ = automation.Notifier 防止引入未使用的 import。
var _ automation.Notifier = nil
