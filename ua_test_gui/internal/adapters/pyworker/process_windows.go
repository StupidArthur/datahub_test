//go:build windows

// process_windows.go - Windows 子进程属性:新进程组 + 无窗口。
// 对齐 python creationflags = CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW:
// cli/wails 退出后 mock 继续跑(新进程组),且不弹控制台窗口(CREATE_NO_WINDOW)。
package pyworker

import (
	"os/exec"
	"syscall"
)

const (
	createNewProcessGroup = 0x00000200
	createNoWindow        = 0x08000000
)

func newProcSysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{CreationFlags: createNewProcessGroup | createNoWindow}
}

// killProcess 终止 Windows 子进程。
// 标准库 cmd.Process.Kill 在 CREATE_NEW_PROCESS_GROUP 场景下可能返回 Access denied,
// 这里用 taskkill /F /T /PID 强制终止进程树。
func killProcess(cmd *exec.Cmd) {
	if cmd == nil || cmd.Process == nil {
		return
	}
	_ = exec.Command("taskkill", "/F", "/T", "/PID", itoa(cmd.Process.Pid)).Run()
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var buf [20]byte
	i := len(buf)
	neg := n < 0
	if neg {
		n = -n
	}
	for n > 0 {
		i--
		buf[i] = byte('0' + n%10)
		n /= 10
	}
	if neg {
		i--
		buf[i] = '-'
	}
	return string(buf[i:])
}
