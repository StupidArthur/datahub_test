// logger.go - 底层日志(slog),覆盖关键业务节点与异常。
//
// runtime-safety 横切规则:日志与业务逻辑分离,记录 登录/mock 启停/开通进度/验证结果/异常。
// 全局 logger,InitLogger 在 app startup 调用;未初始化时 LogInfo/LogError 安全降级。
package logging

import (
	"log/slog"
	"os"
	"path/filepath"

	"ua_test_gui/internal/platform"
)

var logger *slog.Logger

// InitLogger 初始化日志,写入 logDir/ua_test_gui.log。
func InitLogger(logDir string) {
	if logDir == "" {
		logDir = filepath.Join(platform.UserHome(), ".ua_test_gui", "logs")
	}
	if err := os.MkdirAll(logDir, 0o755); err != nil {
		logger = slog.Default()
		return
	}
	f, err := os.OpenFile(filepath.Join(logDir, "ua_test_gui.log"),
		os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		logger = slog.Default()
		return
	}
	logger = slog.New(slog.NewTextHandler(f, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger) // feature/adapter 用 slog.Default() 即得配置好的 logger,无需 import 本包
}

func LogInfo(msg string, args ...any) {
	if logger != nil {
		logger.Info(msg, args...)
	}
}

func LogError(msg string, args ...any) {
	if logger != nil {
		logger.Error(msg, args...)
	}
}
