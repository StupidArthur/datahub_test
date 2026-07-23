// -*- coding: utf-8 -*-
/*
launcher_e2e_test.go — launcher 端到端测试：对真实 Python 服务验证集成契约。

覆盖验收标准 4/5/6 在核心层的对应面：
  - 启动标记解析（endpoint + 节点数）来自真实服务输出
  - Stop 后进程退出、端口释放、可再次启动
  - 端口被占用时启动失败且错误可见

环境依赖：系统 python + asyncua（本仓库既有依赖）。缺失时 t.Skip，不在无环境处失败。
*/
package main

import (
	"bufio"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// pyServerSources 服务运行所需的全部 Python 模块（仓库根目录现有文件）
var pyServerSources = []string{
	"main.py",
	"server_main.py",
	"config_loader.py",
	"change_engines.py",
	"type_mapping.py",
	"log_util.py",
}

// prepareServerEnv 将服务源码复制到测试二进制所在目录，使 LocateServer 规则#2（同目录 main.py）命中。
// 返回 false 表示环境不满足（无 python / asyncua / 仓库源码），应跳过测试。
func prepareServerEnv(t *testing.T) bool {
	t.Helper()
	if _, err := exec.LookPath("python"); err != nil {
		t.Log("skip: 未找到 python")
		return false
	}
	// asyncua 可用性探测
	probe := exec.Command("python", "-c", "import asyncua")
	if err := probe.Run(); err != nil {
		t.Log("skip: python 环境缺少 asyncua")
		return false
	}
	// go test 的工作目录 = 包目录（gui/），仓库根为其父目录
	exeDir, err := executableDir()
	if err != nil {
		t.Fatalf("executableDir: %v", err)
	}
	for _, f := range pyServerSources {
		data, err := os.ReadFile(filepath.Join("..", f))
		if err != nil {
			t.Logf("skip: 仓库源码不可用 (%v)", err)
			return false
		}
		if err := os.WriteFile(filepath.Join(exeDir, f), data, 0o644); err != nil {
			t.Fatalf("复制 %s 失败: %v", f, err)
		}
	}
	// 若已构建服务端 exe（分发形态），一并复制到测试目录：
	// LocateServer 规则#1 优先于 python，E2E 将直接验证 ua_mocker.exe 管道路径
	if data, err := os.ReadFile(filepath.Join("dist_server", "ua_mocker.exe")); err == nil {
		if err := os.WriteFile(filepath.Join(exeDir, "ua_mocker.exe"), data, 0o755); err == nil {
			t.Log("使用分发形态: ua_mocker.exe（规则#1）")
		}
	} else {
		t.Log("使用开发形态: python main.py（规则#2/#3）")
	}
	return true
}

// portFree 端口是否空闲（可绑定即空闲）
func portFree(port int) bool {
	ln, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return false
	}
	_ = ln.Close()
	return true
}

func TestLaunchServerE2E(t *testing.T) {
	if !prepareServerEnv(t) {
		t.SkipNow()
	}
	const port = 18977
	if !portFree(port) {
		t.Skipf("skip: 端口 %d 被占用", port)
	}

	// ---- 启动：真实标记解析 ----
	proc, err := LaunchServer(port, 500)
	if err != nil {
		t.Fatalf("LaunchServer 失败: %v", err)
	}
	defer func() { _ = proc.Stop() }()

	if !proc.Alive() {
		t.Fatal("启动后进程应存活")
	}
	if !strings.Contains(proc.Endpoint(), fmt.Sprintf(":%d", port)) {
		t.Errorf("endpoint 应含端口 %d，实际 %q", port, proc.Endpoint())
	}
	if !strings.HasPrefix(proc.Endpoint(), "opc.tcp://") {
		t.Errorf("endpoint 应以 opc.tcp:// 开头，实际 %q", proc.Endpoint())
	}
	if proc.NodeCount() != 26 {
		t.Errorf("节点数应为 26，实际 %d", proc.NodeCount())
	}

	// ---- 停止：进程退出 + 端口释放 ----
	if err := proc.Stop(); err != nil {
		t.Fatalf("Stop 失败: %v", err)
	}
	if proc.Alive() {
		t.Fatal("Stop 后进程应退出")
	}
	if !portFree(port) {
		t.Errorf("Stop 后端口 %d 应释放", port)
	}

	// ---- 再启动：验证可重复启停 ----
	proc2, err := LaunchServer(port, 500)
	if err != nil {
		t.Fatalf("再次启动失败: %v", err)
	}
	if !proc2.Alive() || proc2.NodeCount() != 26 {
		t.Errorf("再次启动异常: alive=%v nodes=%d", proc2.Alive(), proc2.NodeCount())
	}
	_ = proc2.Stop()
}

func TestLaunchServerPortInUse(t *testing.T) {
	if !prepareServerEnv(t) {
		t.SkipNow()
	}
	const port = 18978
	// 用外部 python 进程占住端口（原生 socket 不带 SO_REUSEADDR，绑定冲突可复现）。
	// 不能用本进程 net.Listen：Windows 上 Go 监听默认带 SO_REUSEADDR，
	// 可与另一进程的同端口绑定共存，无法模拟真实占用
	holder := exec.Command("python", "-c",
		fmt.Sprintf(`import socket,sys,time
s=socket.socket(); s.bind(("0.0.0.0",%d)); s.listen(1)
print("READY", flush=True); time.sleep(30)`, port))
	holderOut, err := holder.StdoutPipe()
	if err != nil {
		t.Fatalf("StdoutPipe: %v", err)
	}
	if err := holder.Start(); err != nil {
		t.Skipf("skip: 无法启动占位进程: %v", err)
	}
	defer func() { _ = holder.Process.Kill() }()
	// 等占位监听真正就绪（读 READY 信号，避免 python 冷启动未完成导致的竞态）
	ready := make(chan struct{})
	go func() {
		line, _ := bufio.NewReader(holderOut).ReadString('\n')
		if strings.Contains(line, "READY") {
			close(ready)
		}
	}()
	select {
	case <-ready:
	case <-time.After(5 * time.Second):
		t.Skip("skip: 占位进程未在 5s 内就绪")
	}

	start := time.Now()
	proc, lerr := LaunchServer(port, 500)
	if proc != nil {
		defer func() { _ = proc.Stop() }() // 防御：万一意外启动成功也不泄漏进程
	}
	if lerr == nil {
		t.Fatal("端口被占用时应启动失败")
	}
	if time.Since(start) > startTimeout {
		t.Error("端口占用失败应快速返回，不应等到超时")
	}
	t.Logf("端口占用错误详情: %v", lerr)
}
