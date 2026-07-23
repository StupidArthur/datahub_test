// -*- coding: utf-8 -*-
/*
app.go — Wails 绑定层：暴露给前端的方法，全部委托核心层（nodespec/yamlgen/launcher）。

对外接口（Wails 绑定，前端经 lib/api.ts 调用）：
  - GetSettings() Settings                当前参数
  - SetSettings(port, cycleMs) SettingsResult   改参数（仅停止状态）
  - StartServer() StartResult             启动服务（幂等）
  - StopServer() StopResult               停止服务（幂等）
  - GetServerStatus() ServerStatus        运行状态
  - ListNodes() []NodeSpec                固定 26 节点列表

错误一律走结果结构体的 Error 字段，不 panic（见 wails-backend 规范）。
*/
package main

import (
	"context"
	"fmt"
	"sync"
)

// 参数默认值与边界
const (
	defaultPort  = 18955 // 默认端口：避开现有组态的 18950/18960/18964~18967/18970/18980
	defaultCycle = 1000  // 默认周期(ms)，与 config_example.yaml 一致
	minPort      = 1024
	maxPort      = 65535
	minCycleMs   = 100
	maxCycleMs   = 3600000 // 1 小时
)

// Settings 服务参数
type Settings struct {
	Port    int `json:"port"`
	CycleMs int `json:"cycleMs"`
}

// SettingsResult 改参结果
type SettingsResult struct {
	OK    bool   `json:"ok"`
	Error string `json:"error"`
}

// StartResult 启动结果
type StartResult struct {
	OK        bool   `json:"ok"`
	Endpoint  string `json:"endpoint"`
	NodeCount int    `json:"nodeCount"`
	Error     string `json:"error"`
}

// StopResult 停止结果
type StopResult struct {
	OK    bool   `json:"ok"`
	Error string `json:"error"`
}

// ServerStatus 运行状态
type ServerStatus struct {
	Running   bool   `json:"running"`
	Endpoint  string `json:"endpoint"`
	NodeCount int    `json:"nodeCount"`
	PID       int    `json:"pid"`
}

// App 绑定层实例：持有参数与服务进程句柄，互斥锁保护并发（前端多路调用 + 关窗钩子）
type App struct {
	ctx      context.Context
	mu       sync.Mutex
	settings Settings
	proc     *ServerProcess
}

// NewApp 创建 App，参数取默认值
func NewApp() *App {
	return &App{settings: Settings{Port: defaultPort, CycleMs: defaultCycle}}
}

func (a *App) startup(ctx context.Context) { a.ctx = ctx }

// shutdown 窗口关闭时由 Wails 调用：兜底释放服务进程（设计文档 §6 生命周期要求）
func (a *App) shutdown(_ context.Context) {
	a.mu.Lock()
	proc := a.proc
	a.proc = nil
	a.mu.Unlock()
	if proc != nil {
		_ = proc.Stop()
	}
}

// GetSettings 获取当前参数
func (a *App) GetSettings() Settings {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.settings
}

// SetSettings 修改参数：运行中禁改；端口/周期范围校验
func (a *App) SetSettings(port, cycleMs int) SettingsResult {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.proc != nil && a.proc.Alive() {
		return SettingsResult{Error: "服务运行中不能修改参数，请先停止"}
	}
	if port < minPort || port > maxPort {
		return SettingsResult{Error: fmt.Sprintf("端口须在 %d~%d 之间", minPort, maxPort)}
	}
	if cycleMs < minCycleMs || cycleMs > maxCycleMs {
		return SettingsResult{Error: fmt.Sprintf("周期须在 %d~%d ms 之间", minCycleMs, maxCycleMs)}
	}
	a.settings = Settings{Port: port, CycleMs: cycleMs}
	return SettingsResult{OK: true}
}

// StartServer 启动服务。幂等：已在运行则直接返回当前信息。
// 注意：持有 a.mu 期间最长阻塞 startTimeout(20s)，前端调用为异步，不影响 UI 响应。
func (a *App) StartServer() StartResult {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.proc != nil && a.proc.Alive() {
		return StartResult{OK: true, Endpoint: a.proc.Endpoint(), NodeCount: a.proc.NodeCount()}
	}
	proc, err := LaunchServer(a.settings.Port, a.settings.CycleMs)
	if err != nil {
		return StartResult{Error: err.Error()}
	}
	a.proc = proc
	return StartResult{OK: true, Endpoint: proc.Endpoint(), NodeCount: proc.NodeCount()}
}

// StopServer 停止服务。幂等：无进程即视为已停止。
func (a *App) StopServer() StopResult {
	a.mu.Lock()
	proc := a.proc
	a.proc = nil
	a.mu.Unlock()
	if proc == nil || !proc.Alive() {
		return StopResult{OK: true}
	}
	if err := proc.Stop(); err != nil {
		return StopResult{Error: err.Error()}
	}
	return StopResult{OK: true}
}

// GetServerStatus 运行状态（前端轮询 + 操作后刷新）
func (a *App) GetServerStatus() ServerStatus {
	a.mu.Lock()
	proc := a.proc
	a.mu.Unlock()
	if proc == nil || !proc.Alive() {
		return ServerStatus{Running: false}
	}
	return ServerStatus{
		Running:   true,
		Endpoint:  proc.Endpoint(),
		NodeCount: proc.NodeCount(),
		PID:       proc.PID(),
	}
}

// ListNodes 固定 26 节点列表（本地规格，不连真实服务）
func (a *App) ListNodes() []NodeSpec { return BuildNodeSpecs() }
