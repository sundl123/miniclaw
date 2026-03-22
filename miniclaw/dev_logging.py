"""开发者专用文件日志：不向终端输出，便于排查 API 与对话问题。"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from miniclaw.config import DEV_LOG_DIR

DEV_LOGGER_NAME = "miniclaw.dev"


def get_dev_logger() -> logging.Logger:
    return logging.getLogger(DEV_LOGGER_NAME)


def setup_dev_logging(log_dir: str | None = None) -> str:
    """按启动时间戳创建日志文件，整进程共用一个 FileHandler。返回日志文件绝对路径。"""
    root = log_dir if log_dir is not None else DEV_LOG_DIR
    os.makedirs(root, exist_ok=True)
    name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log"
    path = os.path.join(root, name)

    logger = get_dev_logger()
    for h in logger.handlers[:]:
        logger.removeHandler(h)
        h.close()

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("dev log file: %s", path)
    return path


_dev = get_dev_logger()
_dev.addHandler(logging.NullHandler())
_dev.propagate = False
