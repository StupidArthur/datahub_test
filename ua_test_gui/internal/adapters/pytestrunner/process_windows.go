//go:build windows

// process_windows.go - Windows 进程管理(Job Object 杀进程树)。
package pytestrunner

import (
	"os/exec"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	jobObj windows.Handle
)

// createJobObject 创建一个 Job Object,把进程放进去,关闭时自动结束所有子进程。
func createJobObject() (windows.Handle, error) {
	h, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return 0, err
	}
	var info windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION
	info.BasicLimitInformation.LimitFlags = windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	if _, err := windows.SetInformationJobObject(
		h,
		windows.JobObjectExtendedLimitInformation,
		uintptr(unsafe.Pointer(&info)),
		uint32(unsafe.Sizeof(info)),
	); err != nil {
		windows.CloseHandle(h)
		return 0, err
	}
	return h, nil
}

func init() {
	if h, err := createJobObject(); err == nil {
		jobObj = h
	}
}

// EnvFunc 把进程放进 Job Object。
//
//nolint:unused // referenced via init only
func assignToJob(pid uintptr) bool {
	if jobObj == 0 {
		return false
	}
	h, err := windows.OpenProcess(windows.PROCESS_SET_QUOTA|windows.PROCESS_TERMINATE, false, uint32(pid))
	if err != nil {
		return false
	}
	defer windows.CloseHandle(h)
	if err := windows.AssignProcessToJobObject(jobObj, h); err != nil {
		return false
	}
	return true
}

// platformSpecific 让 Command 隐藏子窗口。
func platformSpecific(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: windows.CREATE_NO_WINDOW,
	}
}

// KillTree 杀进程树(优先 CloseHandle Job)。
func killTree(cmd *exec.Cmd) error {
	if cmd == nil || cmd.Process == nil {
		return nil
	}
	if jobObj != 0 {
		// 关闭 JobObject 会强制杀所有进程,无需单个 Kill
		return nil
	}
	return cmd.Process.Kill()
}