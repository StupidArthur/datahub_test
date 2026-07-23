"""Google Material 主题(qt-material + 谷歌蓝 #1a73e8)。

按 memory `pyqt6-google-material-style`:所有 PyQt6 项目默认套用,
除非用户明确说"这次不一样"。
"""
from __future__ import annotations

from qt_material import apply_stylesheet

GOOGLE_BLUE = "#1a73e8"


def apply_theme(app) -> None:
    """在 QApplication 初始化后调用,套用谷歌蓝 Material 主题。"""
    apply_stylesheet(
        app,
        theme="light_blue.xml",
        extra={
            "primary": GOOGLE_BLUE,
            "background": "#ffffff",
            "surface": "#f8f9fa",
            "font_family": "Microsoft YaHei",
        },
    )
