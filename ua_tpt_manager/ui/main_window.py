"""主窗口:顶 env_bar + 左 UA 实例面板 + 右 Tab(配置/数据源位号/监控)。

Task1:env_bar 登录。
Task2:实例面板 + 配置 Tab(组态模式:位号编辑 + YAML 生成 + spawn ua_mocker + 多实例端口分配)。
Task3+:TPT 数据源/位号、实时监控(占位)。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_config import TptEnv, load_config, save_config
from tpt_service import TptService
from ua_process import UaProcessManager
from workers import Worker
from ui.config_tab import ConfigTab
from ui.ds_tag_panel import DsTagPanel
from ui.env_bar import EnvBar
from ui.instance_panel import InstancePanel
from ui.monitor_panel import MonitorPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UA × TPT 管理与跟手度监控")
        self.resize(1280, 820)
        self.config = load_config()
        self.service: TptService | None = None
        self.proc_mgr = UaProcessManager(self.config)
        self._worker: Worker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(10)

        # 顶部环境栏
        self.env_bar = EnvBar(self.config)
        v.addWidget(self.env_bar)

        # 左右分栏
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.inst_panel = InstancePanel(self.config, self.proc_mgr)
        splitter.addWidget(self.inst_panel)

        self.tabs = QTabWidget()
        self.tab_config = ConfigTab(self.config)
        self.tabs.addTab(self.tab_config, "配置")
        self.tab_dstag = DsTagPanel(lambda: self.service, self.config)
        self.tabs.addTab(self.tab_dstag, "TPT 数据源/位号")
        self.tab_monitor = MonitorPanel(lambda: self.service, self.config, self.proc_mgr)
        self.tabs.addTab(self.tab_monitor, "监控")
        splitter.addWidget(self.tabs)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 960])
        v.addWidget(splitter, 1)

        self.setStatusBar(QStatusBar())

        # 信号
        self.env_bar.login_requested.connect(self._on_login)
        self.env_bar.logout_requested.connect(self._on_logout)
        self.env_bar.env_changed.connect(self._on_env_changed)
        self.inst_panel.instance_selected.connect(self._on_instance_selected)
        self.inst_panel.runtime_changed.connect(self._on_runtime_changed)
        self.tab_config.saved.connect(self._on_config_saved)

        self._restore_state()

    # ---- 登录 ----
    def _on_login(self, env: TptEnv) -> None:
        if self._worker and self._worker.isRunning():
            return
        self.statusBar().showMessage("登录中...")
        self.env_bar.set_login_state(False, "登录中...")
        svc = TptService(env)

        def task(s, service):
            s.log("info", f"登录 {service.env.username}@{service.env.base_url}")
            service.login()
            return service

        self._worker = Worker(task, svc)
        self._worker.signals.log.connect(lambda lv, m: self.statusBar().showMessage(m))
        self._worker.signals.finished.connect(self._on_login_ok)
        self._worker.signals.failed.connect(self._on_login_fail)
        self._worker.start()

    def _on_login_ok(self, svc: TptService) -> None:
        self.service = svc
        self.env_bar.set_login_state(True, f"已登录: {svc.env.username}@{svc.env.base_url}")
        self.statusBar().showMessage("登录成功")
        self.tab_dstag.on_service_changed()

    def _on_login_fail(self, msg: str) -> None:
        self.service = None
        self.env_bar.set_login_state(False, f"登录失败: {msg}")
        self.statusBar().showMessage("登录失败")

    def _on_logout(self) -> None:
        self.tab_monitor.stop()
        if self.service:
            self.service.logout()
        self.service = None
        self.env_bar.set_login_state(False, "")
        self.statusBar().showMessage("已退出")
        self.tab_dstag.on_service_changed()

    def _on_env_changed(self, name: str) -> None:
        if name not in ("", "（新环境）"):
            self.config.current_env = name

    def _on_config_saved(self) -> None:
        self.inst_panel.on_saved()
        self.statusBar().showMessage("配置已保存", 3000)

    def _on_instance_selected(self, inst) -> None:
        self.tab_config.load(inst)
        ep = ""
        if inst is not None:
            rt = self.proc_mgr.runtime(inst.name)
            ep = rt.endpoint if rt else ""
        self.tab_dstag.load(inst, ep)

    def _on_runtime_changed(self) -> None:
        # 启停后 endpoint 变了,只刷新数据源/位号面板,不动配置编辑器
        inst = self.inst_panel._current()
        ep = ""
        if inst is not None:
            rt = self.proc_mgr.runtime(inst.name)
            ep = rt.endpoint if rt else ""
        self.tab_dstag.load(inst, ep)

    # ---- 窗口状态 ----
    def _restore_state(self) -> None:
        s = QSettings("yuzechao", "ua_tpt_manager")
        geo = s.value("geometry")
        if geo:
            self.restoreGeometry(geo)

    def closeEvent(self, e) -> None:
        self.proc_mgr.stop_all()
        save_config(self.config)
        s = QSettings("yuzechao", "ua_tpt_manager")
        s.setValue("geometry", self.saveGeometry())
        super().closeEvent(e)
