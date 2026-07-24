// command.go - 构造 python -m pytest 命令行参数 + 安全路径校验。
//
// 纯函数:不发起任何进程;仅返回参数切片。
// 调用方负责:
//   - nodeids 必须来自已加载并校验过的 manifest (避免任意字符串成为参数)
//   - junitPath 必须位于受控 run-dir 下
//   - 环境变量由 Runner 注入,绝不通过命令行传入凭据
package nativepytest

import (
	"path/filepath"
	"strings"
)

// BuildPytestArgs 构造 pytest 子进程参数。
//
// 返回: ["-m","pytest", verbosity, nodeids..., "--junitxml", junitPath]
func BuildPytestArgs(pythonExe string, nodeids []string, junitPath string, verbosity string) []string {
	if verbosity == "" {
		verbosity = "-v"
	}
	args := make([]string, 0, 6+len(nodeids))
	args = append(args, "-m", "pytest")
	args = append(args, verbosity)
	args = append(args, nodeids...)
	args = append(args, "--junitxml="+junitPath)
	return args
}

// SafeJunitPath 把 junit 文件名约束到 run-dir,防止路径穿越。
func SafeJunitPath(runDir, fileName string) (string, error) {
	if fileName == "" {
		fileName = "junit.xml"
	}
	clean := filepath.Clean(fileName)
	if clean != fileName || containsParent(clean) || strings.HasPrefix(clean, "/") || strings.HasPrefix(clean, `\`) {
		return "", &argError{msg: "unsafe junit file name: " + fileName}
	}
	return filepath.Join(runDir, clean), nil
}

func containsParent(p string) bool {
	for i := 0; i+1 < len(p); i++ {
		if p[i] == '.' && p[i+1] == '.' && (i == 0 || p[i-1] == '/') {
			return true
		}
	}
	return false
}

type argError struct{ msg string }

func (e *argError) Error() string { return e.msg }