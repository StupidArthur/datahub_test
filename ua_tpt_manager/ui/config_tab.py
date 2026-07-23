"""配置 Tab:编辑选中 UA 实例(模式/端口/命名空间/位号表格 或 excel 路径)。

组态模式:位号表格(name/type/count/change/writable/default)+ 心跳自动注入提示。
保存写回 UaInstance 并持久化。
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_config import UaInstance, UaNodeSpec, save_config
from type_map import ALL_TYPES, default_for


def _coerce_default(typ: str, txt: str):
    if txt is None or txt == "":
        return default_for(typ)
    t = (typ or "").strip()
    try:
        if t == "Boolean":
            return txt.strip().lower() in ("true", "1", "yes", "y")
        if t in ("Float", "Double"):
            return float(txt)
        if t in ("SByte", "Byte", "Int16", "UInt16", "Int32", "UInt32", "Int64", "UInt64"):
            return int(txt)
        return txt
    except ValueError:
        return txt


class ConfigTab(QWidget):
    saved = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.inst: UaInstance | None = None

        v = QVBoxLayout(self)
        v.setSpacing(10)

        # 顶部字段
        top = QFormLayout()
        self.name_edit = QLineEdit()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("组态(ua_mocker)", "config")
        self.mode_combo.addItem("播放 excel(ua_player)", "excel")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.host_edit = QLineEdit("127.0.0.1")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(0, 65535)
        self.port_spin.setValue(0)
        self.port_spin.setSpecialValueText("自动")
        self.ns_spin = QSpinBox()
        self.ns_spin.setRange(0, 65535)
        self.ns_spin.setValue(1)
        self.cycle_spin = QSpinBox()
        self.cycle_spin.setRange(100, 60000)
        self.cycle_spin.setValue(1000)
        self.cycle_spin.setSuffix(" ms")
        top.addRow("实例名", self.name_edit)
        top.addRow("模式", self.mode_combo)
        top.addRow("绑定地址", self.host_edit)
        top.addRow("端口(0=自动)", self.port_spin)
        top.addRow("命名空间索引", self.ns_spin)
        top.addRow("变化周期", self.cycle_spin)
        v.addLayout(top)

        # 模式堆叠
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_config_page())
        self.stack.addWidget(self._build_excel_page())
        self.placeholder = QLabel("（未选择实例,请从左侧新建或选择）")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.placeholder)
        v.addWidget(self.stack, 1)

        # 保存
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        self.btn_save = QPushButton("保存配置")
        self.btn_save.setObjectName("Primary")
        self.btn_save.clicked.connect(self.save)
        save_row.addWidget(self.btn_save)
        v.addLayout(save_row)

        self._set_enabled(False)

    def _build_config_page(self) -> QWidget:
        page = QWidget()
        cp = QVBoxLayout(page)
        hb = QHBoxLayout()
        hb.addWidget(QLabel(
            f"位号(自动注入心跳节点: <{self.config.heartbeat_tag}> Int32 0~99 秒级)")
        )
        hb.addStretch(1)
        self.btn_add_row = QPushButton("添加位号")
        self.btn_del_row = QPushButton("删除选中行")
        hb.addWidget(self.btn_add_row)
        hb.addWidget(self.btn_del_row)
        cp.addLayout(hb)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["name", "type", "count", "change", "writable", "default"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        cp.addWidget(self.table)

        self.btn_add_row.clicked.connect(self._add_row)
        self.btn_del_row.clicked.connect(self._del_row)
        return page

    def _build_excel_page(self) -> QWidget:
        page = QWidget()
        ep = QHBoxLayout(page)
        self.excel_edit = QLineEdit()
        self.excel_edit.setPlaceholderText("选择 excel 文件(需含时间戳列 + 各位号列)")
        self.btn_browse = QPushButton("浏览")
        self.btn_browse.clicked.connect(self._browse)
        ep.addWidget(self.excel_edit)
        ep.addWidget(self.btn_browse)
        return page

    # ---- 加载/保存 ----
    def load(self, inst: UaInstance | None) -> None:
        self.inst = inst
        if inst is None:
            self.stack.setCurrentWidget(self.placeholder)
            self._set_enabled(False)
            return
        self._set_enabled(True)
        self.name_edit.setText(inst.name)
        self.mode_combo.setCurrentIndex(0 if inst.mode == "config" else 1)
        self.host_edit.setText(inst.host)
        self.port_spin.setValue(inst.port)
        self.ns_spin.setValue(inst.namespace_index)
        self.cycle_spin.setValue(inst.cycle_ms)
        self.excel_edit.setText(inst.excel_path)
        self._fill_table(inst.nodes)
        self._on_mode_changed(self.mode_combo.currentIndex())

    def _on_mode_changed(self, idx: int) -> None:
        if self.inst is None:
            self.stack.setCurrentWidget(self.placeholder)
            return
        # 0=config, 1=excel
        self.stack.setCurrentIndex(0 if idx == 0 else 1)

    def _set_enabled(self, on: bool) -> None:
        for w in (
            self.name_edit, self.mode_combo, self.host_edit, self.port_spin,
            self.ns_spin, self.cycle_spin, self.table, self.btn_add_row,
            self.btn_del_row, self.excel_edit, self.btn_browse, self.btn_save,
        ):
            w.setEnabled(on)

    # ---- 位号表格 ----
    def _add_row(self) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._set_row(r, UaNodeSpec(name="tag_", type="Double", count=1,
                                    change=True, writable=False))

    def _del_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def _fill_table(self, nodes: list[UaNodeSpec]) -> None:
        self.table.setRowCount(0)
        for n in nodes:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._set_row(r, n)

    def _set_row(self, r: int, n: UaNodeSpec) -> None:
        self.table.setItem(r, 0, QTableWidgetItem(n.name))
        cb = QComboBox()
        cb.addItems(ALL_TYPES)
        cb.setCurrentText(n.type)
        self.table.setCellWidget(r, 1, cb)
        sp = QSpinBox()
        sp.setRange(1, 100000)
        sp.setValue(int(n.count))
        self.table.setCellWidget(r, 2, sp)
        ch = QCheckBox()
        ch.setChecked(bool(n.change))
        self.table.setCellWidget(r, 3, ch)
        wr = QCheckBox()
        wr.setChecked(bool(n.writable))
        self.table.setCellWidget(r, 4, wr)
        self.table.setItem(r, 5, QTableWidgetItem("" if n.default is None else str(n.default)))

    def _read_table(self) -> list[UaNodeSpec]:
        nodes: list[UaNodeSpec] = []
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            name = name_item.text().strip() if name_item else ""
            if not name:
                continue
            cb = self.table.cellWidget(r, 1)
            sp = self.table.cellWidget(r, 2)
            ch = self.table.cellWidget(r, 3)
            wr = self.table.cellWidget(r, 4)
            default_item = self.table.item(r, 5)
            default_txt = default_item.text() if default_item else ""
            typ = cb.currentText()
            change = ch.isChecked()
            nodes.append(UaNodeSpec(
                name=name, type=typ, count=sp.value(),
                change=change, writable=wr.isChecked(),
                default=None if change else _coerce_default(typ, default_txt),
            ))
        return nodes

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(self, "选择 excel", "", "Excel (*.xlsx *.xls)")
        if p:
            self.excel_edit.setText(p)

    def save(self) -> None:
        if not self.inst:
            return
        inst = self.inst
        new_name = self.name_edit.text().strip() or inst.name
        # 重名校验
        for other in self.config.instances:
            if other is not inst and other.name == new_name:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "重名", f"已存在实例名: {new_name}")
                return
        inst.name = new_name
        inst.mode = self.mode_combo.currentData()
        inst.host = self.host_edit.text().strip() or "127.0.0.1"
        inst.port = self.port_spin.value()
        inst.namespace_index = self.ns_spin.value()
        inst.cycle_ms = self.cycle_spin.value()
        inst.excel_path = self.excel_edit.text().strip()
        if inst.mode == "config":
            inst.nodes = self._read_table()
        save_config(self.config)
        self.saved.emit()
