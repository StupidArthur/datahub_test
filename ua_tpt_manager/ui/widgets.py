"""通用小控件:状态灯、卡片容器。"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel


# 状态颜色(谷歌 Material 色板)
COLOR_GREEN = "#1e8e3e"   # 正常 / 已登录 / 已添加
COLOR_YELLOW = "#f9ab00"  # 警告 / 延迟较高
COLOR_RED = "#ea4335"     # 错误 / 断开 / 延迟过高
COLOR_GREY = "#9aa0a6"    # 未知 / 未登录 / 无数据
COLOR_BLUE = "#1a73e8"    # 进行中 / 信息


class StatusDot(QLabel):
    """彩色圆点状态灯。"""

    def __init__(self, color: str = COLOR_GREY, size: int = 14, parent=None):
        super().__init__(parent)
        self._size = size
        self.set_color(color)
        self.setFixedSize(size + 4, size + 4)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_color(self, color: str) -> None:
        self._color = color
        self.setText("●")
        self.setStyleSheet(f"color:{color}; font-size:{self._size}px;")


class Card(QFrame):
    """带轻阴影 + 圆角的卡片容器(objectName=Card,供 QSS 进一步美化)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(20)
        sh.setOffset(0, 1)
        sh.setColor(QColor(0, 0, 0, 30))
        self.setGraphicsEffect(sh)
