// main.go - Wails 启动入口(仅启动,业务在 internal/app 组合根)。
package main

import (
	"embed"

	"ua_test_gui/internal/app"

	"github.com/wailsapp/wails/v2"
	"github.com/wailsapp/wails/v2/pkg/options"
	"github.com/wailsapp/wails/v2/pkg/options/assetserver"
)

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	c := app.NewContainer()

	err := wails.Run(&options.App{
		Title:  "UA 测试工具",
		Width:  1180,
		Height: 780,
		AssetServer: &assetserver.Options{
			Assets: assets,
		},
		BackgroundColour: &options.RGBA{R: 255, G: 255, B: 255, A: 1},
		OnStartup:        c.Startup,
		OnShutdown:       c.Shutdown,
		Bind: []interface{}{
			c.Subject,
			c.Env,
			c.Mock,
			c.Provision,
			c.Verify,
			c.History,
			c.Automation,
		},
	})

	if err != nil {
		println("Error:", err.Error())
	}
}
