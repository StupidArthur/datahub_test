"""后台工作线程:长任务(登录 / 批量添加数据源位号)用 QThread + 信号。

参考 data-hub-tool/migrate_gui.py 的 WorkerSignals + MigrateWorker 模式,
抽成通用 Worker:在独立线程跑 fn(signals, *args)。
"""
from __future__ import annotations

from typing import Any, Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal


class WorkerSignals(QObject):
    log = pyqtSignal(str, str)           # level, msg
    progress = pyqtSignal(int, int, str) # cur, total, msg
    finished = pyqtSignal(object)        # result
    failed = pyqtSignal(str)


class Signals:
    """传给任务函数的信号代理(线程安全:emit 跨线程到主线程槽)。"""

    def __init__(self, qsignals: WorkerSignals):
        self._s = qsignals

    def log(self, level: str, msg: str) -> None:
        self._s.log.emit(level, msg)

    def progress(self, cur: int, total: int, msg: str = "") -> None:
        self._s.progress.emit(cur, total, msg)


class Worker(QThread):
    """通用后台任务。

    用法:
        w = Worker(login_task, service)
        w.signals.finished.connect(...)
        w.signals.failed.connect(...)
        w.start()
    其中 login_task 形如 def login_task(s, service): service.login(); return service
    """

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self._fn(Signals(self.signals), *self._args, **self._kwargs)
            self.signals.finished.emit(result)
        except Exception as e:  # noqa: BLE001 — 后台任务,异常回主线程
            self.signals.failed.emit(str(e))
