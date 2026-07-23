"""TPT 数据源/位号 Tab。

上部:数据源卡片(按 endpoint 检查 TPT 是否已注册,一键添加)。
下部:位号表格(复选/全选/一键添加,已添加状态实时标记)。

位号命名约定(对齐 ua_tpt_loop / TPT README §5):
- tagBaseName = f"{ns}_{nodeid}"  (TPT 据此解析 OPC UA 节点)
- 普通位号 tagName = nodeid
- 心跳位号 tagName = heartbeat_tag(用户约定的固定名),tagBaseName = f"{ns}_{heartbeat_tag}1"
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
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

from app_config import UaInstance
from tpt_api.errors import TptAPIError
from tpt_service import TptService
from type_map import expand_node_ids, tpt_data_type
from workers import Worker
from .widgets import COLOR_GREEN, COLOR_GREY, COLOR_RED, COLOR_YELLOW, Card, StatusDot


def heartbeat_tag_name(inst: UaInstance, heartbeat_tag: str) -> str:
    """该实例心跳位号在 TPT 上的 tagName(全局唯一,带实例名前缀)。

    多实例下每个实例都注入了同名的 heartbeat UA 节点,tagBaseName 相同(按 ds 隔离);
    但 TPT tagName 全局唯一,故用「实例名_心跳名」保证唯一,监控按此查询。
    """
    return f"{inst.name}_{heartbeat_tag}"


def build_tag_specs(inst: UaInstance, heartbeat_tag: str, excel_columns: list[str] | None = None) -> list[dict]:
    """从实例展开待注册位号列表(含心跳)。String/DateTime 跳过(TPT 不支持)。

    命名约定:
    - tagBaseName = f"{ns}_{nodeid}"  (TPT 据此解析 OPC UA 节点,按 ds 隔离可重复)
    - tagName = f"{inst.name}_{nodeid}"  (全局唯一,多实例不碰撞)
    - 心跳 tagName = heartbeat_tag_name(inst, heartbeat_tag)

    模式差异:
    - config(ua_mocker):节点 id = name+index,心跳节点 id = heartbeat_tag+"1"
    - excel(ua_player):节点 id = 列名(无 index 展开),心跳节点 id = heartbeat_tag
    """
    ns = inst.namespace_index
    specs: list[dict] = []
    if inst.mode == "excel":
        for col in (excel_columns or []):
            specs.append({
                "tag_name": f"{inst.name}_{col}",
                "tag_base_name": f"{ns}_{col}",
                "data_type": 11,  # excel 列类型未知,默认 Double
                "is_heartbeat": False,
                "type": "Double",
                "nodeid": col,
            })
        hb_nodeid = heartbeat_tag  # ua_player 列名,无 count 展开
    else:
        for n in inst.nodes:
            dt = tpt_data_type(n.type)
            if dt is None:
                continue
            for nid in expand_node_ids(n.name, n.count):
                specs.append({
                    "tag_name": f"{inst.name}_{nid}",
                    "tag_base_name": f"{ns}_{nid}",
                    "data_type": dt,
                    "is_heartbeat": False,
                    "type": n.type,
                    "nodeid": nid,
                })
        hb_nodeid = f"{heartbeat_tag}1"  # ua_mocker name+count 展开
    specs.append({
        "tag_name": heartbeat_tag_name(inst, heartbeat_tag),
        "tag_base_name": f"{ns}_{hb_nodeid}",
        "data_type": tpt_data_type("Int32"),
        "is_heartbeat": True,
        "type": "Int32",
        "nodeid": hb_nodeid,
    })
    return specs


class DsTagPanel(QWidget):
    """数据源 + 位号管理面板。

    get_service: 返回当前已登录的 TptService | None(由 MainWindow 提供)。
    """

    def __init__(self, get_service: Callable[[], "TptService | None"], config, parent=None):
        super().__init__(parent)
        self.get_service = get_service
        self.config = config
        self.inst: UaInstance | None = None
        self.endpoint = ""
        self._worker: Worker | None = None
        self._ds_record: dict | None = None

        v = QVBoxLayout(self)
        v.setSpacing(10)

        # ---- 数据源卡片 ----
        ds_card = Card()
        dsl = QVBoxLayout(ds_card)
        dsl.setSpacing(6)
        dsl.addWidget(QLabel("TPT 数据源"))

        row1 = QHBoxLayout()
        self.ds_dot = StatusDot(COLOR_GREY)
        self.ds_status_label = QLabel("未检查")
        row1.addWidget(self.ds_dot)
        row1.addWidget(self.ds_status_label)
        row1.addStretch(1)
        dsl.addLayout(row1)

        self.ep_label = QLabel("endpoint: —")
        self.ep_label.setStyleSheet("color:#5f6368;")
        dsl.addWidget(self.ep_label)

        brow = QHBoxLayout()
        self.btn_check = QPushButton("检查/刷新")
        self.btn_check.clicked.connect(self._check)
        self.btn_add = QPushButton("一键添加数据源")
        self.btn_add.setObjectName("Primary")
        self.btn_add.clicked.connect(self._add)
        brow.addWidget(self.btn_check)
        brow.addWidget(self.btn_add)
        brow.addStretch(1)
        dsl.addLayout(brow)
        v.addWidget(ds_card)

        # ---- 位号卡片 ----
        tags_card = Card()
        tl = QVBoxLayout(tags_card)
        tl.setSpacing(6)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("位号"))
        hdr.addStretch(1)
        self.select_all = QCheckBox("全选")
        self.btn_refresh_tags = QPushButton("刷新已添加状态")
        self.btn_add_tags = QPushButton("一键添加选中位号")
        self.btn_add_tags.setObjectName("Primary")
        hdr.addWidget(self.select_all)
        hdr.addWidget(self.btn_refresh_tags)
        hdr.addWidget(self.btn_add_tags)
        tl.addLayout(hdr)

        self.tags_table = QTableWidget(0, 5)
        self.tags_table.setHorizontalHeaderLabels(["选", "tagName", "tagBaseName", "dataType", "状态"])
        self.tags_table.verticalHeader().setVisible(False)
        self.tags_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        h = self.tags_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        tl.addWidget(self.tags_table)
        v.addWidget(tags_card, 1)

        self.select_all.toggled.connect(self._on_select_all)
        self.btn_refresh_tags.clicked.connect(self._refresh_tags_status)
        self.btn_add_tags.clicked.connect(self._add_selected_tags)

        self._set_enabled(False)

    # ---- 加载 ----
    def load(self, inst, endpoint: str) -> None:
        self.inst = inst
        self.endpoint = endpoint or ""
        self._ds_record = None
        if inst is None:
            self.ep_label.setText("endpoint: —")
            self.ds_status_label.setText("未选择实例")
            self.ds_dot.set_color(COLOR_GREY)
            self._set_enabled(False)
            self._reload_tags()
            return
        self._set_enabled(True)
        self.ep_label.setText(f"endpoint: {self.endpoint or '(实例未启动)'}")
        self.ds_status_label.setText("未检查")
        self.ds_dot.set_color(COLOR_GREY)
        self._reload_tags()
        svc = self.get_service()
        if svc and svc.logged_in and self.endpoint:
            self._check()

    def on_service_changed(self) -> None:
        """登录/退出后刷新当前面板。"""
        if self.inst is not None:
            self.load(self.inst, self.endpoint)
        else:
            self._refresh_tags_status()

    def _set_enabled(self, on: bool) -> None:
        for w in (
            self.btn_check, self.btn_add, self.select_all,
            self.btn_refresh_tags, self.btn_add_tags,
        ):
            w.setEnabled(on)

    # ---- 数据源:检查 ----
    def _check(self) -> None:
        svc = self.get_service()
        if not svc or not svc.logged_in:
            QMessageBox.warning(self, "未登录", "请先登录 TPT")
            return
        if not self.endpoint:
            QMessageBox.warning(self, "未启动", "请先启动该 UA 实例")
            return
        if self._worker and self._worker.isRunning():
            return
        self.ds_status_label.setText("检查中...")
        self.ds_dot.set_color(COLOR_YELLOW)
        ep = self.endpoint

        def task(s):
            rec = svc.find_ds_by_url(ep)
            if rec is None:
                svc.list_ds(refresh=True)
                rec = svc.find_ds_by_url(ep)
            return rec

        self._worker = Worker(task)
        self._worker.signals.finished.connect(self._on_check_done)
        self._worker.signals.failed.connect(lambda m: self._on_fail("检查失败", m))
        self._worker.start()

    def _on_check_done(self, rec: dict | None) -> None:
        self._ds_record = rec
        if rec is None:
            self.ds_status_label.setText("未注册")
            self.ds_dot.set_color(COLOR_RED)
        else:
            alive = bool(rec.get("alive"))
            self.ds_status_label.setText(
                f"已注册 dsId={rec.get('id')}  {'在线' if alive else '离线'}"
            )
            self.ds_dot.set_color(COLOR_GREEN if alive else COLOR_RED)
        # 数据源确定后,刷新位号已添加状态
        self._refresh_tags_status()

    # ---- 数据源:添加 ----
    def _add(self) -> None:
        svc = self.get_service()
        if not svc or not svc.logged_in:
            QMessageBox.warning(self, "未登录", "请先登录 TPT")
            return
        if not self.endpoint:
            QMessageBox.warning(self, "未启动", "请先启动该 UA 实例")
            return
        if self._worker and self._worker.isRunning():
            return
        name = self.inst.name
        ep = self.endpoint
        self.ds_status_label.setText("添加中...")
        self.ds_dot.set_color(COLOR_YELLOW)

        def task(s):
            s.log("info", f"添加数据源 {name} -> {ep}")
            return svc.add_ds(name, ep)

        self._worker = Worker(task)
        self._worker.signals.finished.connect(self._on_add_done)
        self._worker.signals.failed.connect(lambda m: self._on_fail("添加失败", m))
        self._worker.start()

    def _on_add_done(self, rec: dict) -> None:
        self._ds_record = rec
        self.ds_status_label.setText(f"已添加 dsId={rec.get('id')}")
        self.ds_dot.set_color(COLOR_GREEN)
        self._refresh_tags_status()

    def _on_fail(self, title: str, msg: str) -> None:
        self.ds_status_label.setText(title)
        self.ds_dot.set_color(COLOR_RED)
        QMessageBox.warning(self, title, msg)

    def current_ds_id(self) -> int | None:
        return None if self._ds_record is None else self._ds_record.get("id")

    # ---- 位号:表格 ----
    def _reload_tags(self) -> None:
        self.tags_table.setRowCount(0)
        if self.inst is None:
            return
        if self.inst.mode == "config":
            specs = build_tag_specs(self.inst, self.config.heartbeat_tag)
        elif self.inst.mode == "excel":
            if not self.inst.excel_path or not Path(self.inst.excel_path).exists():
                self.tags_table.setRowCount(1)
                self.tags_table.setItem(0, 1, QTableWidgetItem("请在「配置」Tab 选择 excel 文件"))
                return
            try:
                from excel_to_player_csv import excel_tag_columns
                cols = excel_tag_columns(self.inst.excel_path, self.config.heartbeat_tag)
            except Exception as e:  # noqa: BLE001
                self.tags_table.setRowCount(1)
                self.tags_table.setItem(0, 1, QTableWidgetItem(f"读取 excel 失败: {e}"))
                return
            specs = build_tag_specs(self.inst, self.config.heartbeat_tag, excel_columns=cols)
        else:
            return
        for sp in specs:
            r = self.tags_table.rowCount()
            self.tags_table.insertRow(r)
            ck = QTableWidgetItem("")
            ck.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            ck.setCheckState(Qt.CheckState.Checked)
            self.tags_table.setItem(r, 0, ck)
            name_item = QTableWidgetItem(sp["tag_name"])
            name_item.setData(Qt.ItemDataRole.UserRole, sp)
            self.tags_table.setItem(r, 1, name_item)
            self.tags_table.setItem(r, 2, QTableWidgetItem(sp["tag_base_name"]))
            tlabel = f'{sp["type"]}({sp["data_type"]})'
            if sp["is_heartbeat"]:
                tlabel += "  心跳"
            self.tags_table.setItem(r, 3, QTableWidgetItem(tlabel))
            st_item = QTableWidgetItem("未添加")
            st_item.setForeground(QColor(COLOR_GREY))
            self.tags_table.setItem(r, 4, st_item)
        self._refresh_tags_status()

    def _on_select_all(self, on: bool) -> None:
        state = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for r in range(self.tags_table.rowCount()):
            it = self.tags_table.item(r, 0)
            if it and (it.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                it.setCheckState(state)

    def _refresh_tags_status(self) -> None:
        svc = self.get_service()
        if not svc or not svc.logged_in:
            return
        if self._worker and self._worker.isRunning():
            return
        if self.tags_table.rowCount() == 0:
            return

        def task(s):
            svc.list_tags(refresh=True)
            return list(svc.api.name_map.keys())

        self._worker = Worker(task)
        self._worker.signals.finished.connect(self._on_tags_listed)
        self._worker.signals.failed.connect(lambda m: self._on_fail("拉取位号失败", m))
        self._worker.start()

    def _on_tags_listed(self, names: list[str]) -> None:
        existing = set(names or [])
        for r in range(self.tags_table.rowCount()):
            name_item = self.tags_table.item(r, 1)
            st_item = self.tags_table.item(r, 4)
            if name_item is None or st_item is None:
                continue
            cur = st_item.text()
            if cur in ("添加中...", "失败"):
                continue  # 进行中/失败的,不覆盖
            tn = name_item.text()
            if tn in existing:
                st_item.setText("已添加")
                st_item.setForeground(QColor(COLOR_GREEN))
            elif cur != "已添加":
                # 未在 TPT 列表中:标未添加;但不降级已确认添加的(刚添加可能尚未索引)
                st_item.setText("未添加")
                st_item.setForeground(QColor(COLOR_GREY))

    def _add_selected_tags(self) -> None:
        svc = self.get_service()
        if not svc or not svc.logged_in:
            QMessageBox.warning(self, "未登录", "请先登录 TPT")
            return
        ds_id = self.current_ds_id()
        if ds_id is None:
            QMessageBox.warning(self, "无数据源", "请先在上方添加 TPT 数据源")
            return
        if self._worker and self._worker.isRunning():
            return

        selected: list[dict] = []
        for r in range(self.tags_table.rowCount()):
            ck = self.tags_table.item(r, 0)
            name_item = self.tags_table.item(r, 1)
            st_item = self.tags_table.item(r, 4)
            if not (ck and name_item and st_item):
                continue
            if ck.checkState() != Qt.CheckState.Checked:
                continue
            if st_item.text() == "已添加":
                continue  # 跳过已添加
            sp = name_item.data(Qt.ItemDataRole.UserRole)
            if not sp:
                continue
            selected.append(sp)
            st_item.setText("添加中...")
            st_item.setForeground(QColor(COLOR_YELLOW))
        if not selected:
            QMessageBox.information(self, "无选中", "没有需要添加的位号(已添加的会跳过)")
            return

        def task(s):
            results = []
            for i, sp in enumerate(selected):
                s.progress(i, len(selected), sp["tag_name"])
                try:
                    svc.add_tag(sp["tag_name"], sp["tag_base_name"], sp["data_type"], ds_id)
                    results.append((sp["tag_name"], True, ""))
                except TptAPIError as e:
                    # A0001 = 重复(已存在),视为已添加
                    results.append((sp["tag_name"], True, "已存在") if "A0001" in str(e.code)
                                   else (sp["tag_name"], False, str(e)))
                except Exception as e:  # noqa: BLE001
                    results.append((sp["tag_name"], False, str(e)))
            return results

        self._worker = Worker(task)
        self._worker.signals.progress.connect(
            lambda c, t, m: self.ds_status_label.setText(f"添加位号 {c + 1}/{t}: {m}")
        )
        self._worker.signals.finished.connect(self._on_tags_added)
        self._worker.signals.failed.connect(lambda m: self._on_fail("添加位号失败", m))
        self._worker.start()

    def _on_tags_added(self, results: list) -> None:
        ok_cnt = 0
        # 用 tagName 反查行
        row_by_name = {}
        for r in range(self.tags_table.rowCount()):
            ni = self.tags_table.item(r, 1)
            if ni:
                row_by_name[ni.text()] = r
        for tag_name, ok, extra in results:
            r = row_by_name.get(tag_name)
            if r is None:
                continue
            st_item = self.tags_table.item(r, 4)
            if ok:
                ok_cnt += 1
                st_item.setText("已添加")
                st_item.setForeground(QColor(COLOR_GREEN))
            else:
                st_item.setText("失败")
                st_item.setForeground(QColor(COLOR_RED))
                st_item.setToolTip(extra)
        self.ds_status_label.setText(f"位号添加完成:成功 {ok_cnt}/{len(results)}")
        self._refresh_tags_status()
