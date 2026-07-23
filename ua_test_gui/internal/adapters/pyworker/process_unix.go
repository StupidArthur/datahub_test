//go:build !windows

// process_unix.go - Unix 子进程属性:独立进程组(Setpgid),父退出不影响子进程。
package pyworker

import (
	"os/exec"
	"syscall"
)

func newProcSysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setpgid: true}
}

func killProcess(cmd *exec.Cmd) {
	if cmd == nil || cmd.Process == nil {
		return
	}
	_ = cmd.Process.Kill()
}
