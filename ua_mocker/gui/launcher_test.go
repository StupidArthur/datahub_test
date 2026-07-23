// -*- coding: utf-8 -*-
package main

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWaitForLogReadyDetectsNewMarker(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "svc.log")
	// 旧内容含标记但在 offset 之前：同日早先运行遗留，必须忽略
	old := "2026-01-01 10:00:00 [INFO] server_main: 服务器已启动，cycle=1000 ms\n"
	if err := os.WriteFile(logPath, []byte(old), 0o644); err != nil {
		t.Fatal(err)
	}
	offset := fileSize(logPath)

	// 300ms 后追加本次运行的标记
	go func() {
		time.Sleep(300 * time.Millisecond)
		f, err := os.OpenFile(logPath, os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			return
		}
		defer f.Close()
		_, _ = f.WriteString("2026-01-02 11:00:00 [INFO] server_main: 服务器已启动，cycle=500 ms\n")
	}()

	waitCh := make(chan error, 1)
	ready, exited := waitForLogReady(logPath, offset, waitCh, time.Now().Add(3*time.Second))
	if exited {
		t.Fatal("不应判定进程退出")
	}
	if !ready {
		t.Fatal("应检测到 offset 之后的新就绪标记")
	}
}

func TestWaitForLogReadyIgnoresOldMarker(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "svc.log")
	if err := os.WriteFile(logPath, []byte("2026-01-01 [INFO] server_main: 服务器已启动\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	offset := fileSize(logPath)
	waitCh := make(chan error, 1)
	// 不追加新内容 → 应超时返回 (false, false) 而非误判就绪
	ready, exited := waitForLogReady(logPath, offset, waitCh, time.Now().Add(600*time.Millisecond))
	if ready || exited {
		t.Fatalf("offset 之前的旧标记不应触发就绪: ready=%v exited=%v", ready, exited)
	}
}

func TestWaitForLogReadyProcessExitFirst(t *testing.T) {
	dir := t.TempDir()
	logPath := filepath.Join(dir, "svc.log") // 不存在也无妨
	waitCh := make(chan error, 1)
	waitCh <- errors.New("exit status 1")
	ready, exited := waitForLogReady(logPath, 0, waitCh, time.Now().Add(2*time.Second))
	if ready || !exited {
		t.Fatalf("进程退出应优先返回: ready=%v exited=%v", ready, exited)
	}
}

func TestTailBufferKeepsLastN(t *testing.T) {
	tb := &tailBuffer{n: 2}
	tb.add("a")
	tb.add("b")
	tb.add("c")
	if got := tb.String(); got != "b\nc" {
		t.Errorf("应只保留最后 2 行，实际 %q", got)
	}
}

func TestTailBufferEmpty(t *testing.T) {
	tb := &tailBuffer{n: 3}
	if got := tb.String(); got != "" {
		t.Errorf("空缓冲应为空串，实际 %q", got)
	}
}
