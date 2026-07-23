// paths.go - 跨平台路径与文件存在性工具(无业务依赖)。
package platform

import "os"

// UserHome 返回用户主目录;失败回退 "."。
func UserHome() string {
	h, err := os.UserHomeDir()
	if err != nil {
		return "."
	}
	return h
}

// FileExists 判断路径是否存在。
func FileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}
