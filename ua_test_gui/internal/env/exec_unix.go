//go:build !windows

// exec_unix.go - Unix 无控制台窗口概念,hideWindow 空实现。
package env

import "os/exec"

func hideWindow(c *exec.Cmd) {}
