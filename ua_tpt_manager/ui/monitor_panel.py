"""实时监控 Tab:轮询 TPT 数据源连通性 + 心跳位号跟手度。

QTimer(主线程)按周期触发 → 后台 Worker 一次性查所有运行中实例的
ds alive + heartbeat 最新点 → 信号回主线程刷新表格。_busy 防重入。
"""
from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_config import AppConfig
from tpt_service import TptService
from ua_process import UaProcessManager
from workers import Worker
from .ds_tag_panel import heartbeat_tag_name
from .widgets import COLOR_GREEN, COLOR_GREY, COLOR_RED, COLOR_YELLOW, Card, StatusDot


def latency_color(latency, alive) -> str:
    if alive is False:
        return COLOR_RED
    if latency is None:
        return COLOR_GREY
    if latency < 5:
        return COLOR_GREEN
    if latency < 30:
        return COLOR_YELLOW
    return COLOR_RED


class MonitorPanel(QWidget):
    def __init__(self, get_service: Callable[[], "TptService | None"],
                 config: AppConfig, proc_mgr: UaProcessManager, parent=None):
        super().__init__(parent)
        self.get_service = get_service
        self.config = config
        self.proc = proc_mgr
        self._worker: Worker | None = None
        self._running = False

        v = QVBoxLayout(self)
        v.setSpacing(10)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("轮询周期"))
        self.interval_combo = QComboBox()
        for sec in (1, 3, 5):
            self.interval_combo.addItem(f"{sec} 秒", sec)
        # 默认选 config 里的值
        idx = self.interval_combo.findData(self.config.poll_interval_sec)
        if idx >= 0:
            self.interval_combo.setCurrentIndex(idx)
        self.interval_combo.currentIndexChanged.connect(self._on_interval_changed)
        self.btn_start = QPushButton("开始监控")
        self.btn_start.setObjectName("Primary")
        self.btn_start.clicked.connect(self._toggle)
        self.btn_once = QPushButton("立即刷新一次")
        self.btn_once.clicked.connect(self._tick)
        self.state_label = QLabel("未开始")
        self.state_label.setStyleSheet("color:#5f6368;")
        bar.addWidget(self.interval_combo)
        bar.addWidget(self.btn_start)
        bar.addWidget(self.btn_once)
        bar.addStretch(1)
        bar.addWidget(self.state_label)
        v.addLayout(bar)

        card = Card()
        cl = QVBoxLayout(card)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["实例", "endpoint", "ds在线", "心跳值", "appTime", "跟手度(s)", "状态"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        cl.addWidget(self.table)
        v.addWidget(card, 1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def _on_interval_changed(self, _idx: int) -> None:
        sec = self.interval_combo.currentData()
        self.config.poll_interval_sec = int(sec)
        if self._running:
            self._timer.setInterval(int(sec) * 1000)

    def _toggle(self) -> None:
        if self._running:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        svc = self.get_service()
        if not svc or not svc.logged_in:
            QMessageBox.warning(self, "未登录", "请先登录 TPT")
            return
        sec = int(self.interval_combo.currentData())
        self._running = True
        self._timer.setInterval(sec * 1000)
        self._timer.start()
        self.btn_start.setText("停止监控")
        self.state_label.setText("监控中…")
        self._tick()

    def stop(self) -> None:
        self._running = False
        self._timer.stop()
        self.btn_start.setText("开始监控")
        self.state_label.setText("已停止")

    def _tick(self) -> None:
        svc = self.get_service()
        if not svc or not svc.logged_in:
            return
        if self._worker and self._worker.isRunning():
            return  # 上一轮还没回,跳过
        running = [i for i in self.config.instances
                   if self.proc.status(i.name) == "running"]
        if not running:
            self.table.setRowCount(0)
            self.state_label.setText("没有运行中的 UA 实例")
            return
        heartbeat_tag = self.config.heartbeat_tag
        proc = self.proc

        def task(s):
            svc.list_ds(refresh=True)
            results = []
            for inst in running:
                rt = proc.runtime(inst.name)
                ep = rt.endpoint if rt else ""
                alive = svc.get_ds_alive(ep) if ep else None
                hb = heartbeat_tag_name(inst, heartbeat_tag)
                fr = svc.heartbeat_freshness(hb)
                results.append({
                    "name": inst.name, "endpoint": ep, "alive": alive, **fr,
                })
            return results

        self._worker = Worker(task)
        self._worker.signals.finished.connect(self._on_result)
        self._worker.signals.failed.connect(self._on_fail)
        self._worker.start()

    def _on_result(self, results: list) -> None:
        self._fill_table(results)
        ok = sum(1 for r in results if r.get("latency") is not None)
        self.state_label.setText(f"已刷新 {len(results)} 个实例,有数据 {ok}")

    def _on_fail(self, msg: str) -> None:
        self.state_label.setText(f"刷新失败: {msg}")

    def _fill_table(self, results: list) -> None:
        self.table.setRowCount(0)
        for r in results:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(r["name"]))
            self.table.setItem(row, 1, QTableWidgetItem(r["endpoint"]))
            alive = r.get("alive")
            alive_txt = "在线" if alive else ("离线" if alive is False else "—")
            a_item = QTableWidgetItem(alive_txt)
            a_item.setForeground(QColor(COLOR_GREEN if alive else (COLOR_RED if alive is False else COLOR_GREY)))
            self.table.setItem(row, 2, a_item)
            val = r.get("value")
            self.table.setItem(row, 3, QTableWidgetItem("—" if val is None else str(val)))
            self.table.setItem(row, 4, QTableWidgetItem(r.get("app_time") or "—"))
            lat = r.get("latency")
            self.table.setItem(row, 5, QTableWidgetItem("—" if lat is None else f"{int(lat)}"))
            dot = StatusDot(latency_color(lat, alive))
            self.table.setCellWidget(row, 6, dot)
