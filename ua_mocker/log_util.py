# -*- coding: utf-8 -*-
"""
日志工具：将日志输出到执行程序所在目录下的日志文件。
支持脚本运行与 PyInstaller 打包后运行两种场景。
"""

import logging
import os
import sys
from datetime import datetime


def get_executable_directory() -> str:
    """
    获取执行程序所在目录。
    - 若为 PyInstaller 打包运行，返回 exe 所在目录；
    - 否则返回脚本所在目录。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# 日志文件名：带日期，便于按天区分
LOG_FILENAME_PREFIX = "ua_mocker"
LOG_FILENAME_DATE_FORMAT = "%Y%m%d"


def _log_filename() -> str:
    """生成当日日志文件名。"""
    base_dir = get_executable_directory()
    date_str = datetime.now().strftime(LOG_FILENAME_DATE_FORMAT)
    return os.path.join(base_dir, f"{LOG_FILENAME_PREFIX}_{date_str}.log")


def setup_logging(
    level: int = logging.INFO,
    log_file: str | None = None,
    console: bool = False,
) -> None:
    """
    配置根日志：默认仅输出到文件；若 console=True 则同时输出到控制台。
    文件路径默认在执行程序目录下，可按天生成文件名。

    :param level: 日志级别，默认 INFO
    :param log_file: 日志文件路径；为 None 时使用执行目录下的默认文件名
    :param console: 是否向控制台输出常规日志；默认 False，控制台仅由业务打印指定信息
    """
    if log_file is None:
        log_file = _log_filename()

    handlers: list[logging.Handler] = [logging.FileHandler(log_file, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )
