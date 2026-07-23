// service.go - OS 环境检测与清理:端口 / 进程 / 本地 IP / 连通性。
//
// 对齐 python ua_test_harness/env/os_env.py。核心逻辑,不 import Wails。
// 端口探测用 connect 握手(bind 探测会被 asyncua SO_REUSEADDR 误判)。
// 进程操作跨平台:Windows 用 netstat/tasklist/taskkill,Unix 用 lsof/ps/kill。
// 所有子进程经 runHiddenCmd 隐藏控制台窗口,避免切到环境页时 cmd 窗口闪烁。
package env

import (
	"fmt"
	"net"
	"os/exec"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"

	"ua_test_gui/internal/subject"
)

// runHiddenCmd 建子进程并隐藏控制台窗口(Windows CREATE_NO_WINDOW;Unix 无窗口)。
// netstat/tasklist/taskkill/ipconfig 必须隐藏,否则切环境页会弹 cmd 窗口闪烁。
func runHiddenCmd(name string, args ...string) *exec.Cmd {
	c := exec.Command(name, args...)
	hideWindow(c)
	return c
}

// mockPorts 返回 18960~18969 端口列表。
func mockPorts() []int {
	ports := make([]int, 0, PortEnd-PortStart+1)
	for p := PortStart; p <= PortEnd; p++ {
		ports = append(ports, p)
	}
	return ports
}

// IsPortFree connect 探测:连得上=占用(返回 false)。
// bind 探测会被 asyncua server 的 SO_REUSEADDR 误判(允许重复 bind),故用 connect 实际握手。
func IsPortFree(port int) bool {
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 300*time.Millisecond)
	if err != nil {
		return true
	}
	conn.Close()
	return false
}

// ScanPorts 扫描 mock 端口区间占用状态。
func ScanPorts() []PortStatus {
	pidMap := netstatPIDs()
	result := make([]PortStatus, 0, len(mockPorts()))
	for _, p := range mockPorts() {
		ps := PortStatus{Port: p, InUse: !IsPortFree(p), PID: pidMap[p]}
		if ps.PID != 0 {
			ps.Process = processName(ps.PID)
		}
		result = append(result, ps)
	}
	return result
}

// KillPort 杀占用 port 的进程。返回 (成功, 消息)。
func KillPort(port int) (bool, string) {
	pid := netstatPIDs()[port]
	if pid == 0 {
		return false, fmt.Sprintf("端口 %d 无占用进程", port)
	}
	if err := killPID(pid); err != nil {
		return false, fmt.Sprintf("%v。请在任务管理器手动结束 PID %d", err, pid)
	}
	return true, fmt.Sprintf("已杀 PID %d(%d)", pid, port)
}

// ListLocalIPs 枚举本地 IPv4(选 TPT 可连的那个)。
// 优先 net.InterfaceAddrs(跨平台);空则 fallback ipconfig(Windows)。
func ListLocalIPs() []string {
	var ips []string
	addrs, err := net.InterfaceAddrs()
	if err == nil {
		for _, a := range addrs {
			if ipnet, ok := a.(*net.IPNet); ok && !ipnet.IP.IsLoopback() {
				if v4 := ipnet.IP.To4(); v4 != nil {
					ips = append(ips, v4.String())
				}
			}
		}
	}
	if len(ips) == 0 {
		ips = ipconfigIPv4s()
	}
	return ips
}

// PickLocalIP 自动选 TPT 可连的本地 IP:优先 10.x,其次 172.x,最后任意。
// 对齐 cli._pick_local_ip。
func PickLocalIP(ips []string) string {
	for _, ip := range ips {
		if strings.HasPrefix(ip, "10.") {
			return ip
		}
	}
	for _, ip := range ips {
		if strings.HasPrefix(ip, "172.") {
			return ip
		}
	}
	if len(ips) > 0 {
		return ips[0]
	}
	return ""
}

// CheckConnectivity 通过能否登录判定与被测对象的连通性。password 仅流转不落日志。
func CheckConnectivity(baseURL, user, password, tenantID string) (bool, string) {
	_, err := subject.LoginSubject(baseURL, user, password, tenantID, 15*time.Second)
	if err != nil {
		return false, err.Error()
	}
	return true, "登录成功"
}

// ---- 进程/端口工具(跨平台)----

var netstatLineRe = regexp.MustCompile(`:(\d+)\s+\S+\s+LISTENING\s+(\d+)`)

// netstatPIDs 返回 port->pid(仅 LISTENING)。Windows: netstat -ano;Unix: lsof。
func netstatPIDs() map[int]int {
	out := map[int]int{}
	switch runtime.GOOS {
	case "windows":
		b, err := runHiddenCmd("netstat", "-ano").Output()
		if err != nil {
			return out
		}
		for _, line := range strings.Split(string(b), "\n") {
			if !strings.Contains(strings.ToUpper(line), "LISTENING") {
				continue
			}
			if m := netstatLineRe.FindStringSubmatch(line); m != nil {
				p, _ := strconv.Atoi(m[1])
				pid, _ := strconv.Atoi(m[2])
				out[p] = pid
			}
		}
	default:
		b, err := runHiddenCmd("lsof", "-i", "-P", "-n").Output()
		if err != nil {
			return out
		}
		portRe := regexp.MustCompile(`:(\d+)\s+\(LISTEN\)`)
		for _, line := range strings.Split(string(b), "\n") {
			if !strings.Contains(line, "LISTEN") {
				continue
			}
			fields := strings.Fields(line)
			if len(fields) < 2 {
				continue
			}
			pid, _ := strconv.Atoi(fields[1])
			if m := portRe.FindStringSubmatch(line); m != nil && pid != 0 {
				p, _ := strconv.Atoi(m[1])
				out[p] = pid
			}
		}
	}
	return out
}

// processName 查 PID 对应进程名。Windows: tasklist;Unix: ps。
func processName(pid int) string {
	if pid == 0 {
		return ""
	}
	switch runtime.GOOS {
	case "windows":
		b, err := runHiddenCmd("tasklist", "/FI", fmt.Sprintf("PID eq %d", pid), "/NH", "/FO", "CSV").Output()
		if err != nil {
			return ""
		}
		line := strings.TrimSpace(string(b))
		if line == "" {
			return ""
		}
		first := strings.SplitN(line, ",", 2)[0]
		return strings.Trim(first, "\"")
	default:
		b, err := runHiddenCmd("ps", "-p", strconv.Itoa(pid), "-o", "comm=").Output()
		if err != nil {
			return ""
		}
		return strings.TrimSpace(string(b))
	}
}

// killPID 杀进程。Windows: taskkill /PID /F;Unix: kill -9。
func killPID(pid int) error {
	switch runtime.GOOS {
	case "windows":
		return runHiddenCmd("taskkill", "/PID", strconv.Itoa(pid), "/F").Run()
	default:
		return runHiddenCmd("kill", "-9", strconv.Itoa(pid)).Run()
	}
}

// ipconfigIPv4s Windows ipconfig 解析 IPv4(fallback)。
func ipconfigIPv4s() []string {
	b, err := runHiddenCmd("ipconfig").Output()
	if err != nil {
		return nil
	}
	re := regexp.MustCompile(`IPv4[^\d:]*:\s*(\d+\.\d+\.\d+\.\d+)`)
	var ips []string
	for _, m := range re.FindAllStringSubmatch(string(b), -1) {
		ips = append(ips, m[1])
	}
	return ips
}
