# -*- coding: utf-8 -*-
"""
OPC UA Mock Server 入口：仅支持唯一一个命令行参数（组态文件路径），
日志输出到执行程序所在目录。
"""

import asyncio
import logging
import sys

from log_util import get_executable_directory, setup_logging
from server_main import run_server

# 仅允许唯一一个命令行参数：组态文件路径
CONFIG_ARG_INDEX = 1


def main(config_path: str | None = None) -> None:
    """
    启动 OPC UA Mock Server。

    :param config_path: 组态文件路径（YAML）；若为 None 且通过命令行传入则使用该参数
    """
    if config_path is None and len(sys.argv) > 1:
        config_path = sys.argv[CONFIG_ARG_INDEX].strip()
    if not config_path:
        print("用法: python main.py <组态文件路径>", file=sys.stderr)
        sys.exit(1)
    if len(sys.argv) > 2:
        print("仅支持唯一一个参数：组态文件路径", file=sys.stderr)
        sys.exit(1)

    setup_logging(level=logging.INFO, console=False)
    logger = logging.getLogger(__name__)
    logger.info("执行目录: %s", get_executable_directory())

    try:
        asyncio.run(run_server(config_path))
    except KeyboardInterrupt:
        logger.info("用户中断退出")
    except FileNotFoundError as e:
        logger.error("%s", e)
        sys.exit(1)
    except ValueError as e:
        logger.error("组态错误: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
