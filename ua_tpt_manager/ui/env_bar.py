"""顶部 TPT 环境栏:环境切换 + 账号密码 + 登录/退出。

只负责持有输入字段并发出 login_requested(TptEnv) / logout_requested / env_changed,
真正的登录由 MainWindow 用 Worker 在后台线程执行。
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
)

from app_config import TptEnv, save_config
from .widgets import COLOR_GREEN, COLOR_GREY, COLOR_RED, StatusDot


class EnvBar(QFrame):
    login_requested = pyqtSignal(object)   # TptEnv
    logout_requested = pyqtSignal()
    env_changed = pyqtSignal(str)          # env name

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setObjectName("Card")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        self.env_combo = QComboBox()
        self.env_combo.setMinimumWidth(150)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("http://10.10.58.179:31501")
        self.url_edit.setMinimumWidth(220)
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("admin")
        self.user_edit.setMaximumWidth(120)
        self.pwd_edit = QLineEdit()
        self.pwd_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pwd_edit.setPlaceholderText("密码")
        self.pwd_edit.setMaximumWidth(140)
        self.tenant_edit = QLineEdit()
        self.tenant_edit.setPlaceholderText("tenant(可空)")
        self.tenant_edit.setMaximumWidth(120)
        self.remember = QCheckBox("记住密码")
        self.save_btn = QPushButton("保存环境")
        self.login_btn = QPushButton("登录")
        self.login_btn.setObjectName("Primary")
        self.logout_btn = QPushButton("退出")
        self.dot = StatusDot(COLOR_GREY)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color:#5f6368;")

        for w, lbl in [
            (self.env_combo, "环境"),
            (self.url_edit, "URL"),
            (self.user_edit, "账号"),
            (self.pwd_edit, "密码"),
            (self.tenant_edit, "tenant"),
        ]:
            lay.addWidget(QLabel(lbl))
            lay.addWidget(w)
        lay.addWidget(self.remember)
        lay.addStretch(1)
        lay.addWidget(self.save_btn)
        lay.addWidget(self.login_btn)
        lay.addWidget(self.logout_btn)
        lay.addWidget(self.dot)
        lay.addWidget(self.msg)

        self.logout_btn.hide()

        self.env_combo.currentIndexChanged.connect(self._on_env_changed)
        self.save_btn.clicked.connect(self._on_save)
        self.login_btn.clicked.connect(self._on_login)
        self.logout_btn.clicked.connect(self.logout_requested.emit)

        self.refresh()

    # ---- 环境列表 ----
    def refresh(self) -> None:
        self.env_combo.blockSignals(True)
        self.env_combo.clear()
        self.env_combo.addItem("（新环境）", None)
        idx_to_select = 0
        for i, e in enumerate(self.config.envs, start=1):
            self.env_combo.addItem(e.name, e)
            if e.name == self.config.current_env:
                idx_to_select = i
        self.env_combo.setCurrentIndex(idx_to_select)
        self.env_combo.blockSignals(False)
        self._on_env_changed(self.env_combo.currentIndex())

    def _on_env_changed(self, idx: int) -> None:
        e = self.env_combo.itemData(idx) if idx >= 0 else None
        self._fill(e if e else TptEnv())
        self.env_changed.emit(self.env_combo.currentText())

    def _fill(self, e: TptEnv) -> None:
        self.url_edit.setText(e.base_url)
        self.user_edit.setText(e.username)
        self.pwd_edit.setText(e.password)
        self.tenant_edit.setText(e.tenant_id)
        self.remember.setChecked(e.remember_password)

    def _build_env(self) -> TptEnv:
        name = self.env_combo.currentText().strip()
        if name in ("", "（新环境）"):
            # 用 URL 推一个默认名
            name = self.url_edit.text().strip() or "env"
        return TptEnv(
            name=name,
            base_url=self.url_edit.text().strip(),
            username=self.user_edit.text().strip(),
            password=self.pwd_edit.text(),
            tenant_id=self.tenant_edit.text().strip(),
            remember_password=self.remember.isChecked(),
        )

    def _on_save(self) -> None:
        env = self._build_env()
        for i, e in enumerate(self.config.envs):
            if e.name == env.name:
                self.config.envs[i] = env
                break
        else:
            self.config.envs.append(env)
        self.config.current_env = env.name
        save_config(self.config)
        self.refresh()

    def _on_login(self) -> None:
        env = self._build_env()
        if not env.base_url or not env.username:
            self.set_login_state(False, "请填写 URL 和账号")
            return
        self.login_requested.emit(env)

    # ---- 状态 ----
    def set_login_state(self, logged_in: bool, msg: str = "") -> None:
        self.dot.set_color(COLOR_GREEN if logged_in else COLOR_RED)
        self.msg.setText(msg)
        self.login_btn.setVisible(not logged_in)
        self.logout_btn.setVisible(logged_in)
        for w in (
            self.env_combo, self.url_edit, self.user_edit, self.pwd_edit,
            self.tenant_edit, self.remember, self.save_btn,
        ):
            w.setEnabled(not logged_in)
