# ua_tpt_manager 使用指南

UA × TPT 管理与跟手度监控工具。内嵌管理多个上游 UA server 实例(组态 / 播放 excel),
在 TPT 上一键注册数据源与位号,并实时监控数据源联通性与心跳跟手度(系统响应时间)。

## 启动

```bash
cd ua_tpt_manager
pip install -r requirements.txt
pip install -e ../tpt_api/python          # tpt_api 本地包
# supcon_io 走 sys.path(无需安装)
python main.py
```

> 依赖 tpt_api、supcon_io、ua_mocker、ua_player 四个兄弟目录,默认从 `../` 自动定位。

## 三大功能区(右侧 Tab)

### 1. 配置 Tab — 管理 UA 实例
左侧「UA 实例」列表:**新建 / 启动 / 停止 / 删除**。每个实例两种模式:
- **组态(ua_mocker)**:位号表格编辑(name/type/count/change/writable/default),工具自动注入心跳节点(`heartbeat` Int32,0~99 秒级 sawtooth),生成 YAML 并 spawn `ua_mocker`。
- **播放 excel(ua_player)**:选择 excel 文件,工具用 supcon_io 读取→转 ua_player CSV(自动注入心跳列 0~99)→spawn `ua_player`,按 1s/行播放。

- 端口默认自动分配(18950 起,多实例不冲突);命名空间索引默认 1;变化周期默认 1000ms。
- 启动后列表项显示 `[running] endpoint`。

### 2. TPT 数据源/位号 Tab — 一键接入 TPT
顶部环境栏登录 TPT 后:
- **数据源**:按实例 endpoint(`opc.tcp://host:port/ua_mocker/` 或 `/`)检查 TPT 是否已注册;未注册则「一键添加数据源」(OPC UA 类型)。
- **位号**:表格列出该实例全部位号(含心跳),复选/全选后「一键添加选中位号」到对应数据源。已添加的实时标记,重复添加安全跳过(A0001 视为已存在)。

### 3. 监控 Tab — 实时跟手度
选择轮询周期(1s/3s/5s)→「开始监控」。每轮对所有运行中实例查:
- **ds 在线**:TPT 数据源 `alive` 字段
- **心跳值 / appTime / 跟手度**:心跳位号最新历史点,跟手度 = `now - appTime`(秒)
- 状态灯:绿 <5s / 黄 <30s / 红 ≥30s或离线 / 灰无数据

> TPT 历史时间戳为秒级精度(`yyyy-MM-dd HH:mm:ss`),1s 轮询有 ±1s 误差,3s 足够。

## 命名约定(重要)

TPT `tagName` 全局唯一,多实例下每个实例都有同名心跳节点,故:
- `tagName = f"{实例名}_{节点id}"`(全局唯一)
- `tagBaseName = f"{ns}_{节点id}"`(TPT 据此解析 UA 节点,按数据源隔离可重复)
- 心跳 `tagName = f"{实例名}_heartbeat"`,监控按此查询
- 心跳 `tagBaseName`:组态模式 `1_heartbeat1`(ua_mocker count 展开),excel 模式 `1_heartbeat`(ua_player 列名)

## 配置与持久化

- 业务配置:`~/.ua_tpt_manager/config.json`(TPT 环境、UA 实例、exe 路径、心跳名、轮询周期)
- 窗口状态:QSettings
- 密码默认不落盘,勾选「记住密码」才存

## 已知限制 / 后续

- excel 模式心跳列按行 `ri % 100`,若 excel 行数 <100 则心跳范围 <0~99(跟手度延迟测量不受影响)。
- 监控为串行轮询各实例;实例很多时可改并行(QThreadPool)。
- 跟手度历史曲线、断流告警、PyInstaller 打包为后续增强。
