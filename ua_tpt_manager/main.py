"""ua_tpt_manager 入口。

本地依赖 tpt_api / supcon_io 未必 pip 安装,这里把它们的源码目录加进 sys.path。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# tpt_api 包源码在 tpt_api/python/tpt_api 下,需把 tpt_api/python 加进 path
_tpt_api_src = str(ROOT / "tpt_api" / "python")
if _tpt_api_src not in sys.path:
    sys.path.insert(0, _tpt_api_src)
# supcon_io 包直接在 ROOT 下(v0.1.0 未打包,走 sys.path)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from theme import apply_theme  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("ua_tpt_manager")
    apply_theme(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
