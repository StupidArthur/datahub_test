# UA Types Mock GUI

桌面 GUI 版 OPC UA Mock 服务器：内置 ua_types 风格固定组态（13 种 OPC UA 类型 ×
1 自变化只读 + 1 可写 = 26 节点），打开即用，外部客户端（UaExpert 等）可直连。

- 技术栈：Wails v2 + Go（GUI/管控） + 现有 Python asyncua 引擎（服务，零侵入复用）
- 前端：React 18 + TS + Shadcn UI + Tailwind v3（Notion 式浅色简约）
- 需求/设计文档见 `doc/`

## 开发

前置：Go ≥ 1.22、Node ≥ 18、Wails CLI v2（`wails doctor` 全绿）、Python + asyncua（开发形态跑服务用）。

```bash
cd gui
wails dev          # 开发模式：自动定位仓库根 main.py（定位规则#3），热刷新
go test ./...      # 单元测试 + E2E（E2E 依赖 python + asyncua，缺失自动 skip）
```

## 构建与分发

分发形态为**双 exe 并排**（同目录）：

```bash
# 1. GUI exe（build/bin/ua-types-gui.exe，≤15MB）
wails build

# 2. 服务端 exe（必须 --console：windowed 模式 stdout 为 None 会导致 print 崩溃；
#    GUI 以 CREATE_NO_WINDOW 方式拉起，不会弹黑窗）
cd ..   # 回到 ua_mocker 仓库根
pyinstaller --onefile --console --name ua_mocker main.py
# 产物 dist/ua_mocker.exe 复制到 gui/build/bin/ 与 GUI exe 并排
```

> 注意：仓库现有的 `main.spec` / `ua_mocker.spec` 为 `console=False`（windowed），
> 该模式下 `sys.stdout=None`，服务启动即因 print 崩溃，**不可用于本 GUI 的服务端打包**。

交付包 = `ua-types-gui.exe` + `ua_mocker.exe`（同目录），双击 GUI exe 即可。
终端用户无需安装 Python。

## 服务程序定位规则（launcher.go）

按序查找，命中即用：

1. GUI exe 同目录 `ua_mocker.exe`（分发形态）
2. 同目录 `main.py` + 系统 python
3. `<exe 目录>/../../../main.py` + 系统 python（开发形态：gui/build/bin → 仓库根）

## 就绪检测（实现期定稿的集成契约）

1. 轮询服务程序目录当日日志（`ua_mocker_YYYYMMDD.log`）出现 `服务器已启动`
   —— 不用控制台标记：打包 exe 的 stdout 在管道重定向下实测不可靠
2. 对 endpoint 做最小 OPC UA HEL/ACK 握手 —— 证明 bind 完成、协议栈就绪
   （日志标记先于 bind；端口占用失败后 asyncua 还有 ~1~2s 优雅停机才退出）

endpoint 固定为 `opc.tcp://0.0.0.0:<port>/ua_mocker/`（路径为服务端硬编码），
端口默认 18955、周期默认 1000ms，停止状态下可在界面修改。

## 已知约束

- 完整分发包约 27MB（GUI 10.9MB + 服务 16.3MB），GUI 自身守住 ≤15MB 红线
- Windows 上若另一进程以 SO_REUSEADDR 方式占用同端口，bind 可能不报错（系统语义所致），属极端场景
- 停止 = 强杀进程树（服务无持久化状态，安全）
