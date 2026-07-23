// -*- coding: utf-8 -*-
/*
launcher.go — 服务进程管控：定位服务程序、生成组态、启动、就绪检测、停止。

对外接口：
  - ServerProcess：已启动的服务进程（Endpoint/NodeCount/PID/Alive/Stop）
  - LaunchServer(port, cycleMs int) (*ServerProcess, error)
  - LocateServer() (ServerProgram, error)（供诊断用）

就绪检测契约（两级验证，不依赖 stdout）：
  1. 日志标记：服务程序目录的当日日志（log_util.py 以 utf-8 FileHandler 写入）
     出现「服务器已启动」—— server_main.py 在 TCP bind 前写的最后一条日志。
     之所以不用控制台标记：PyInstaller 打包 exe 的 stdout 在管道重定向下
     实测不可靠（print 内容到不了父进程），而日志文件与重定向行为无关。
  2. HEL/ACK 握手：对 endpoint 发最小 OPC UA Hello 并收到 ACK，
     证明 bind 已完成、协议栈就绪（「服务器已启动」日志先于 bind，
     端口占用等失败会在日志之后才令进程退出——经约 1~2s 优雅停机）。
endpoint 与节点数由 GUI 侧组态决定（确定性），不需要从输出解析。
失败时回读 stderr 末行 / 服务日志尾部作为错误详情。
*/
package main

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

const (
	// Windows 进程创建标志：不继承/不创建控制台窗口
	windowsCreateNoWindow = 0x08000000

	logReadyMarker  = "服务器已启动"       // 日志就绪标记（server_main.py：「服务器已启动，cycle=...」）
	endpointPath    = "/ua_mocker/"    // 服务端点路径（server_main.py 硬编码）
	startTimeout    = 20 * time.Second // 启动总超时：26 节点秒级可建，留足慢机器余量
	logPollInterval = 200 * time.Millisecond

	// HEL/ACK 握手参数
	listenVerifyTimeout = 3 * time.Second        // 等握手成功的最长时间
	dialInterval        = 150 * time.Millisecond // 握手重试间隔
	dialTimeout         = 300 * time.Millisecond // 单次连接/读超时基数
	postDialStabilize   = 300 * time.Millisecond // 握手成功后的存活复检窗口

	logFilePrefix    = "ua_mocker"         // 服务日志前缀（log_util.py：ua_mocker_YYYYMMDD.log）
	logDateFormat    = "20060102"          // Go 时间格式模板 = YYYYMMDD
	configFileName   = "ua_types_gui.yaml" // GUI 生成的组态文件名（置于程序目录）
	serverExeName    = "ua_mocker.exe"     // 分发包中的服务程序名（现有 PyInstaller 产物）
	serverScriptName = "main.py"           // 开发/半分发形态的服务脚本名
	tailLines        = 5                   // 错误详情回读的行数
)

// ServerProgram 定位到的服务程序：启动命令 + 参数前缀 + 程序所在目录（用于找日志）
type ServerProgram struct {
	Cmd  string
	Args []string
	Dir  string
}

// ServerProcess 一个已启动的服务进程
type ServerProcess struct {
	cmd       *exec.Cmd
	pid       int
	endpoint  string
	nodeCount int
	mu        sync.Mutex
	exited    bool
}

// Endpoint 返回服务 endpoint
func (p *ServerProcess) Endpoint() string { return p.endpoint }

// NodeCount 返回节点数
func (p *ServerProcess) NodeCount() int { return p.nodeCount }

// PID 返回服务进程号
func (p *ServerProcess) PID() int { return p.pid }

// Alive 进程是否仍在运行
func (p *ServerProcess) Alive() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return !p.exited
}

// markExited 由 Wait 监视 goroutine 调用
func (p *ServerProcess) markExited() {
	p.mu.Lock()
	p.exited = true
	p.mu.Unlock()
}

// killTree 杀进程树：Windows 用 taskkill /T（python 可能派生子进程），其他平台直接 Kill
func killTree(cmd *exec.Cmd, pid int) {
	if runtime.GOOS == "windows" {
		_ = exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(pid)).Run()
	} else if cmd.Process != nil {
		_ = cmd.Process.Kill()
	}
}

// Stop 强杀进程树。服务无持久化状态，强杀安全（见设计文档 §6）。
func (p *ServerProcess) Stop() error {
	if !p.Alive() {
		return nil
	}
	killTree(p.cmd, p.pid)
	// 等 Wait 监视 goroutine 落地退出状态，最多 3s
	deadline := time.Now().Add(3 * time.Second)
	for p.Alive() && time.Now().Before(deadline) {
		time.Sleep(50 * time.Millisecond)
	}
	return nil
}

// executableDir 当前程序所在目录（wails dev 时为 build/bin，分发时为 exe 目录）
func executableDir() (string, error) {
	exe, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("无法获取程序路径: %w", err)
	}
	return filepath.Dir(exe), nil
}

func fileExists(p string) bool {
	info, err := os.Stat(p)
	return err == nil && !info.IsDir()
}

func fileSize(p string) int64 {
	info, err := os.Stat(p)
	if err != nil {
		return 0
	}
	return info.Size()
}

// serverLogPath 服务当日日志路径：log_util.py 把日志写在服务程序所在目录
// （打包运行 = exe 目录；脚本运行 = main.py 目录），即 LocateServer 给出的 Dir
func serverLogPath(serverDir string) string {
	return filepath.Join(serverDir, fmt.Sprintf("%s_%s.log", logFilePrefix, time.Now().Format(logDateFormat)))
}

// LocateServer 按优先级定位服务程序（见设计文档 §3）：
//  1. GUI exe 同目录的 ua_mocker.exe（分发形态）
//  2. GUI exe 同目录的 main.py + 系统 python
//  3. <exe 目录>/../../../main.py + 系统 python（开发形态：gui/build/bin → 仓库根）
func LocateServer() (ServerProgram, error) {
	exeDir, err := executableDir()
	if err != nil {
		return ServerProgram{}, err
	}
	serverExe := filepath.Join(exeDir, serverExeName)
	if fileExists(serverExe) {
		return ServerProgram{Cmd: serverExe, Dir: exeDir}, nil
	}
	// python 参数带 -u：脚本形态下 stdout 重定向默认块缓冲（日志检测虽不依赖
	// stdout，-u 仍可让 stderr 诊断信息及时可见）
	python, pyErr := exec.LookPath("python")
	localScript := filepath.Join(exeDir, serverScriptName)
	if pyErr == nil && fileExists(localScript) {
		return ServerProgram{Cmd: python, Args: []string{"-u", localScript}, Dir: exeDir}, nil
	}
	devScript := filepath.Join(exeDir, "..", "..", "..", serverScriptName)
	if pyErr == nil && fileExists(devScript) {
		abs, err := filepath.Abs(devScript)
		if err != nil {
			return ServerProgram{}, err
		}
		return ServerProgram{Cmd: python, Args: []string{"-u", abs}, Dir: filepath.Dir(abs)}, nil
	}
	msg := "未找到服务程序：请将 " + serverExeName + " 放到本程序同目录"
	if pyErr != nil {
		msg += "（或安装 Python 并提供 " + serverScriptName + "）"
	}
	return ServerProgram{}, errors.New(msg)
}

// waitForLogReady 轮询日志文件，等 offset 之后出现就绪标记。返回值：
//   - ready=检测到新标记
//   - exited=进程在等待期间退出（此时 ready 必为 false）
//
// offset 用于跳过同日早先运行遗留的日志（文件追加写）。
func waitForLogReady(logPath string, offset int64, waitCh <-chan error, deadline time.Time) (ready bool, exited bool) {
	marker := []byte(logReadyMarker)
	for {
		select {
		case <-waitCh:
			return false, true
		default:
		}
		if data, err := os.ReadFile(logPath); err == nil && int64(len(data)) > offset {
			if bytes.Contains(data[int(offset):], marker) {
				return true, false
			}
		}
		if time.Now().After(deadline) {
			return false, false
		}
		time.Sleep(logPollInterval)
	}
}

// tailBuffer 保留最后 n 行的环形缓冲（并发安全），用于错误详情
type tailBuffer struct {
	mu    sync.Mutex
	n     int
	lines []string
}

func (t *tailBuffer) add(s string) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.lines = append(t.lines, s)
	if len(t.lines) > t.n {
		t.lines = t.lines[len(t.lines)-t.n:]
	}
}

func (t *tailBuffer) String() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return strings.Join(t.lines, "\n")
}

// readLogTail 回读服务当日日志的尾部（stderr 无输出时的错误详情兜底）
func readLogTail(dir string) string {
	data, err := os.ReadFile(serverLogPath(dir))
	if err != nil {
		return ""
	}
	lines := strings.Split(strings.TrimSpace(string(data)), "\n")
	if len(lines) > tailLines {
		lines = lines[len(lines)-tailLines:]
	}
	return strings.Join(lines, "\n")
}

// appendU32 以小端追加 uint32（OPC UA Binary 编码为小端）
func appendU32(b []byte, v uint32) []byte {
	return append(b, byte(v), byte(v>>8), byte(v>>16), byte(v>>24))
}

// uaHelloOK 对 endpoint 做一次最小 OPC UA TCP 握手：发送 HEL，期望收到 ACK。
//
// 为什么需要协议级验证：就绪日志先于实际 bind，bind 失败后 asyncua 还要走
// 约 1~2s 的优雅停机（停内部服务 → 关会话 → 删订阅）才退出，固定时长窗口
// 无法可靠覆盖；只有真正完成 bind 的 OPC UA 服务才会回应 ACK。
//
// endpoint 形如 opc.tcp://0.0.0.0:18955/ua_mocker/；host 为 0.0.0.0 时用 127.0.0.1 探测。
func uaHelloOK(endpoint string) bool {
	u, err := url.Parse(endpoint)
	if err != nil || u.Port() == "" {
		return false
	}
	host := u.Hostname()
	if host == "" || host == "0.0.0.0" {
		host = "127.0.0.1"
	}
	conn, err := net.DialTimeout("tcp", net.JoinHostPort(host, u.Port()), dialTimeout)
	if err != nil {
		return false
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(dialTimeout * 3))

	// HEL 消息体：协议版本 + 收发缓冲 + 最大消息/块 + EndpointUrl（ByteString = u32 长度 + UTF-8）
	urlBytes := []byte(endpoint)
	body := make([]byte, 0, 24+len(urlBytes))
	body = appendU32(body, 0)    // ProtocolVersion
	body = appendU32(body, 8192) // ReceiveBufferSize
	body = appendU32(body, 8192) // SendBufferSize
	body = appendU32(body, 0)    // MaxMessageSize（0 = 不限）
	body = appendU32(body, 0)    // MaxChunkCount
	body = appendU32(body, uint32(len(urlBytes)))
	body = append(body, urlBytes...)
	// 消息头：类型 HELF + 总长（含头 8 字节）
	msg := []byte{'H', 'E', 'L', 'F'}
	msg = appendU32(msg, uint32(8+len(body)))
	msg = append(msg, body...)
	if _, err := conn.Write(msg); err != nil {
		return false
	}
	// ACK 响应头：'A' 'C' 'K' 'F' + 长度
	hdr := make([]byte, 8)
	if _, err := io.ReadFull(conn, hdr); err != nil {
		return false
	}
	return string(hdr[:4]) == "ACKF"
}

// waitServing 等 endpoint 上的 OPC UA 服务真正就绪（HEL/ACK 握手成功）。返回值：
//   - ok=握手成功
//   - exited=进程在等待期间退出（bind 失败等，此时 ok 必为 false）
func waitServing(endpoint string, waitCh <-chan error) (ok bool, exited bool) {
	deadline := time.Now().Add(listenVerifyTimeout)
	for {
		select {
		case <-waitCh:
			return false, true
		default:
		}
		if uaHelloOK(endpoint) {
			return true, false
		}
		if time.Now().After(deadline) {
			return false, false
		}
		time.Sleep(dialInterval)
	}
}

// LaunchServer 生成组态 → 启动服务 → 两级就绪验证，返回受管的 ServerProcess。
// 失败时返回含 stderr/日志尾部详情的错误。
func LaunchServer(port, cycleMs int) (*ServerProcess, error) {
	prog, err := LocateServer()
	if err != nil {
		return nil, err
	}
	exeDir, err := executableDir()
	if err != nil {
		return nil, err
	}
	yamlPath := filepath.Join(exeDir, configFileName)
	if err := os.WriteFile(yamlPath, []byte(GenerateYAML(port, cycleMs)), 0o644); err != nil {
		return nil, fmt.Errorf("写入组态失败: %w", err)
	}

	// 就绪检测基于日志：记录启动前的文件偏移，只认其后新写入的标记
	logPath := serverLogPath(prog.Dir)
	logOffset := fileSize(logPath)

	cmd := exec.Command(prog.Cmd, append(prog.Args, yamlPath)...)
	// 强制 UTF-8 输出：Windows 控制台重定向默认 GBK，stderr 诊断信息会乱码
	// PYTHONUNBUFFERED=1：对 PyInstaller exe 形态同样强制无缓冲
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PYTHONUNBUFFERED=1")
	if runtime.GOOS == "windows" {
		// CREATE_NO_WINDOW：python / 服务端 exe 均为控制台程序，
		// GUI（无控制台进程）拉起时不加此标志会弹出黑色控制台窗口
		cmd.SysProcAttr = &syscall.SysProcAttr{CreationFlags: windowsCreateNoWindow}
	}
	// stdout 只排空不解析：打包 exe 的 stdout 在重定向下不可靠，
	// 但子进程必须持有有效 stdout 句柄（否则 print 异常），故接管并丢弃
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("启动服务程序失败: %w", err)
	}
	p := &ServerProcess{
		cmd:       cmd,
		pid:       cmd.Process.Pid,
		endpoint:  fmt.Sprintf("opc.tcp://%s:%d%s", serverHost, port, endpointPath),
		nodeCount: len(BuildNodeSpecs()),
	}

	// stderr 末行缓冲（错误详情来源之一）
	stderrTail := &tailBuffer{n: tailLines}
	go func() {
		sc := bufio.NewScanner(stderr)
		for sc.Scan() {
			stderrTail.add(sc.Text())
		}
	}()
	go func() { _, _ = io.Copy(io.Discard, stdout) }()

	// 进程退出监视
	waitCh := make(chan error, 1)
	go func() { waitCh <- cmd.Wait() }()

	// fail 组装失败错误：reason + stderr 末行 / 日志尾部
	fail := func(reason string) (*ServerProcess, error) {
		time.Sleep(150 * time.Millisecond) // 等 stderr goroutine 收尾
		detail := stderrTail.String()
		if detail == "" {
			detail = readLogTail(prog.Dir)
		}
		if detail == "" {
			detail = "无错误输出"
		}
		return nil, fmt.Errorf("%s：%s", reason, detail)
	}

	// 第一关：日志就绪标记（与 stdout 行为无关，打包前后一致）
	ready, exited := waitForLogReady(logPath, logOffset, waitCh, time.Now().Add(startTimeout))
	if exited {
		p.markExited()
		return fail("服务启动失败（进程提前退出）")
	}
	if !ready {
		killTree(cmd, p.pid)
		<-waitCh
		p.markExited()
		return nil, fmt.Errorf("服务启动超时（%s），日志未出现就绪标记", startTimeout)
	}
	// 第二关：HEL/ACK 握手，确认 bind 完成、协议栈就绪
	ok, exited2 := waitServing(p.endpoint, waitCh)
	if exited2 {
		p.markExited()
		return fail("服务启动后意外退出")
	}
	if !ok {
		killTree(cmd, p.pid)
		<-waitCh
		p.markExited()
		return nil, fmt.Errorf("服务已就绪但 endpoint 握手失败: %s", p.endpoint)
	}
	// 握手后短稳定窗复检存活（兜底握手成功后的即刻崩溃）
	time.Sleep(postDialStabilize)
	select {
	case <-waitCh:
		p.markExited()
		return fail("服务启动后意外退出")
	default:
	}
	// 启动成功：后台跟踪退出状态（服务崩溃时前端轮询可感知）
	go func() {
		<-waitCh
		p.markExited()
	}()
	return p, nil
}
