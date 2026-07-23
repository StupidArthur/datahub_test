# UA 测试工具(ua_test_gui)

UA 客户端(datahub)功能测试的 go+wails 桌面 GUI,python 后端 `ua_test_harness` 的 GUI 化。

## 功能(6 页,左侧分组导航)

- **被测对象**:URL 实时截断(协议 / base_url / 租户)+ 登录验证 + 确认;密码存 localStorage(仅本机),不落日志。
- **操作系统环境检测**:18960-18969 端口表(占用 / PID / 进程 / 单杀)+ 一键清理(二次确认)+ 本地 IP 选择 + **ua_mocker 运行环境配置**(repo / python 路径,自动探测)。
- **ua-server-mock 管理**:4 套 mock 启停 + 性能参数(pollN / writeN / ratio)可编辑保存。
- **数据源组态**:选 mock + dsName + endpoint(本地 IP 自动拼)+ 采样周期 + 开通 + 结果 + 重名位号二次确认删除 + smoke 验证。
- **验证**:11 类型读写回写遍历 + 结果表;增量落库,支持续跑(崩溃只丢当前 tag)。
- **运行历史**:run 列表 + tag 级详情。

## 依赖

- **ua_mocker**(python):`F:\github\supcon_tools\ua_mocker`,需 python + asyncua + PyYAML。首次启动在「环境检测」页确认 ua_mocker 路径(默认自动探测,失败时手动填)。
- **被测对象**:datahub TPT API,登录页输入 base_url + 账号密码。

## 开发

```bash
wails dev      # 热重载开发
wails build    # 出 exe(build/bin/ua_test_gui.exe,~17MB)
```

## 架构

- **后端 Go**:`app.go`(wails 绑定,PascalCase 方法,错误进结果 struct 的 Error 字段)+ `subject` / `mock_spec` / `mock_manager` / `ds_provision` / `verifier` / `store` / `os_env` / `config`(核心逻辑,不 import wails,可独立 `go test`)。
- **前端 React+TS+Vite**:`src/pages`(6 页)+ `src/lib/api.ts`(wails 绑定封装,统一 unwrap error)+ `src/components`(Toast / Confirm)。
- **持久化** `~/.ua_test_gui/`:`ua_test_gui.db`(验证 run + tag 结果)、`config.json`(mocker 配置)、`mock_work/`(yaml + server.log)、`logs/`(应用日志)。

## 注意

- 性能 mock(11000 位号)启动约 47s,属正常(位号多初始化慢);小 mock(260 位号)1-2s。
- exe 一律用 `wails build`(带 production build tag + 图标),不要改 `go build`。
