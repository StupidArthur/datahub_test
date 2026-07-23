//go:build windows

// exec_windows.go - Windows 子进程隐藏控制台窗口(CREATE_NO_WINDOW)。
// env 调 netstat/tasklist/taskkill/ipconfig 时不弹 cmd 窗口(切环境页无闪烁)。
package env

import (
	"os/exec"
	"syscall"
)

func hideWindow(c *exec.Cmd) {
	c.SysProcAttr = &syscall.SysProcAttr{CreationFlags: 0x08000000} // CREATE_NO_WINDOW
}
