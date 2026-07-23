//go:build !windows

// process_other.go - 非 Windows 平台默认进程管理。
package pytestrunner

import (
	"os/exec"
	"syscall"
)

// platformSpecific POSIX: 子进程组杀。
func platformSpecific(cmd *exec.Cmd) {
	if cmd.SysProcAttr == nil {
		cmd.SysProcAttr = &syscall.SysProcAttr{}
	}
	cmd.SysProcAttr.Setpgid = true
}

// killTree 先 kill pgid。
func killTree(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil {
		return nil
	}
	pgid, err := syscall.Getpgid(cmd.Process.Pid)
	if err == nil {
		// negative PID = process group
		_ = syscall.Kill(-pgid, syscall.SIGKILL)
	}
	return cmd.Process.Kill()
}