"""左侧 UA 实例面板:列表 + 新建/启动/停止/删除 + 状态轮询。"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_config import UaInstance, UaNodeSpec, save_config
from ua_process import UaProcessManager

STATUS_COLOR = {
    "running": "#1e8e3e",
    "starting": "#f9ab00",
    "failed": "#ea4335",
    "stopped": "#9aa0a6",
}


class InstancePanel(QWidget):
    instance_selected = pyqtSignal(object)  # UaInstance | None
    runtime_changed = pyqtSignal()          # 启动/停止后发出(刷新依赖 endpoint 的面板)

    def __init__(self, config, proc_mgr: UaProcessManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.proc = proc_mgr
        self._counter = 0

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(QLabel("UA 实例"))

        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_sel)
        v.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.btn_new = QPushButton("新建")
        self.btn_start = QPushButton("启动")
        self.btn_stop = QPushButton("停止")
        self.btn_del = QPushButton("删除")
        for b in (self.btn_new, self.btn_start, self.btn_stop, self.btn_del):
            row.addWidget(b)
        v.addLayout(row)

        self.btn_new.clicked.connect(self._new)
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_del.clicked.connect(self._delete)

        self.refresh()

        # 1s 轮询进程状态(检测崩溃/退出)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._refresh_status)
        self.timer.start()

    # ---- 列表 ----
    def refresh(self, select_name: str | None = None) -> None:
        self._rebuild_list()
        row = -1
        if select_name:
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.ItemDataRole.UserRole).name == select_name:
                    row = i
                    break
        if row < 0 and self.list.count() > 0:
            row = 0
        # 单次 setCurrentRow → 只触发一次 load,避免重入重建表格控件导致崩溃
        self.list.setCurrentRow(row)
        if row < 0:
            self._on_sel(-1)
        self._refresh_status()

    def _rebuild_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for inst in self.config.instances:
            it = QListWidgetItem(inst.name)
            it.setData(Qt.ItemDataRole.UserRole, inst)
            self.list.addItem(it)
        self.list.blockSignals(False)

    def _update_item(self, it: QListWidgetItem) -> None:
        inst = it.data(Qt.ItemDataRole.UserRole)
        st = self.proc.status(inst.name)
        rt = self.proc.runtime(inst.name)
        ep = rt.endpoint if rt else ""
        it.setText(f"{inst.name}   [{st}]   {ep}")
        it.setForeground(QColor(STATUS_COLOR.get(st, "#9aa0a6")))

    def _refresh_status(self) -> None:
        for i in range(self.list.count()):
            self._update_item(self.list.item(i))

    def _on_sel(self, row: int) -> None:
        inst = None
        if 0 <= row < self.list.count():
            inst = self.list.item(row).data(Qt.ItemDataRole.UserRole)
        self.instance_selected.emit(inst)

    def _current(self) -> UaInstance | None:
        r = self.list.currentRow()
        if 0 <= r < self.list.count():
            return self.list.item(r).data(Qt.ItemDataRole.UserRole)
        return None

    # ---- 操作 ----
    def _new(self) -> None:
        existing = {i.name for i in self.config.instances}
        name = f"ua_instance_{self._counter + 1}"
        while name in existing:
            self._counter += 1
            name = f"ua_instance_{self._counter + 1}"
        self._counter += 1
        inst = UaInstance(name=name, mode="config")
        inst.nodes.append(UaNodeSpec(name="demo_", type="Double", count=2,
                                     change=True, writable=False))
        self.config.instances.append(inst)
        save_config(self.config)
        self.refresh(select_name=inst.name)

    def _start(self) -> None:
        inst = self._current()
        if not inst:
            return
        try:
            rt = self.proc.start(inst)
            QMessageBox.information(self, "启动", f"{inst.name} 已启动\nendpoint: {rt.endpoint}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "启动失败", str(e))
        self._refresh_status()
        self.runtime_changed.emit()

    def _stop(self) -> None:
        inst = self._current()
        if not inst:
            return
        self.proc.stop(inst.name)
        self._refresh_status()
        self.runtime_changed.emit()

    def _delete(self) -> None:
        inst = self._current()
        if not inst:
            return
        if self.proc.status(inst.name) == "running":
            self.proc.stop(inst.name)
        self.config.instances.remove(inst)
        save_config(self.config)
        self.refresh()

    def on_saved(self) -> None:
        """配置保存后刷新显示(实例名可能改了)。"""
        cur = self._current()
        self.refresh(select_name=cur.name if cur else None)
