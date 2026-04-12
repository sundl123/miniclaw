"""开发者专用文件日志：不向终端输出，便于排查 API 与对话问题。"""
from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime

from miniclaw.dirs import get_log_dir

DEV_LOGGER_NAME = "miniclaw.dev"


def get_dev_logger() -> logging.Logger:
    return logging.getLogger(DEV_LOGGER_NAME)


def setup_dev_logging(
    log_dir: str | None = None,
    workspace_root: str | None = None,
) -> str:
    """按启动时间戳创建日志文件，支持日志轮转。返回日志文件绝对路径。

    Args:
        log_dir: 日志目录，默认为 ~/.miniclaw/logs/
        workspace_root: 工作区目录，用于读取 config.json 中的 logging 配置
    """
    root = log_dir if log_dir is not None else get_log_dir()
    os.makedirs(root, exist_ok=True)
    name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log"
    path = os.path.join(root, name)

    # 获取轮转配置（get_log_config 内部已处理默认值）
    from miniclaw.settings import get_log_config
    log_config = get_log_config(workspace_root)
    max_bytes = log_config["max_bytes"]
    backup_count = log_config["backup_count"]

    logger = get_dev_logger()
    for h in logger.handlers[:]:
        logger.removeHandler(h)
        h.close()

    # 使用 RotatingFileHandler 实现日志轮转
    handler = logging.handlers.RotatingFileHandler(
        path,
        encoding="utf-8",
        maxBytes=max_bytes,
        backupCount=backup_count,
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("dev log file: %s", path)
    logger.info("log rotation: max_bytes=%d, backup_count=%d", max_bytes, backup_count)
    return path


_dev = get_dev_logger()
_dev.addHandler(logging.NullHandler())
_dev.propagate = False
