"""开发者专用文件日志：不向终端输出，便于排查 API 与对话问题。"""
from __future__ import annotations

import logging
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
    """配置日志文件，支持日志轮转。返回日志文件绝对路径。

    轮转文件名格式：dev.log.20260412-120000-000000

    Args:
        log_dir: 日志目录，默认为 ~/.miniclaw/logs/
        workspace_root: 工作区目录，用于读取 config.json 中的 logging 配置
    """
    root = log_dir if log_dir is not None else get_log_dir()
    os.makedirs(root, exist_ok=True)

    # 获取轮转配置
    from miniclaw.settings import get_log_config
    log_config = get_log_config(workspace_root)
    max_bytes = log_config["max_bytes"]
    backup_count = log_config["backup_count"]

    # 当前日志文件
    current_log = os.path.join(root, "dev.log")

    # 启动时检查是否需要轮转
    _rotate_if_needed(root, current_log, max_bytes, backup_count)

    logger = get_dev_logger()
    for h in logger.handlers[:]:
        logger.removeHandler(h)
        h.close()

    # 使用普通 FileHandler（轮转已在启动时处理）
    handler = logging.FileHandler(current_log, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("dev log started at %s", datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    logger.info("log rotation: max_bytes=%d, backup_count=%d", max_bytes, backup_count)
    return current_log


def _rotate_if_needed(
    log_dir: str,
    current_log: str,
    max_bytes: int,
    backup_count: int,
) -> None:
    """检查并执行轮转。如果 current_log 超过 max_bytes，则轮转到带时间戳的文件。"""
    if not os.path.exists(current_log):
        return

    size = os.path.getsize(current_log)
    if size < max_bytes:
        return

    # 生成带时间戳的轮转文件名
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    rotated_name = f"dev.log.{timestamp}"
    rotated_path = os.path.join(log_dir, rotated_name)

    os.rename(current_log, rotated_path)
    _cleanup_old_backups(log_dir, backup_count)


def _cleanup_old_backups(log_dir: str, backup_count: int) -> None:
    """清理超过数量的旧备份文件（按修改时间排序，删除最旧的）。"""
    if backup_count <= 0:
        return

    prefix = "dev.log."
    backups = []
    for name in os.listdir(log_dir):
        if name.startswith(prefix):
            path = os.path.join(log_dir, name)
            backups.append((path, os.path.getmtime(path)))

    if not backups:
        return

    # 按修改时间升序排序（最旧的在前）
    backups.sort(key=lambda x: x[1])

    # 删除超过数量的最旧文件
    while len(backups) > backup_count:
        oldest = backups.pop(0)[0]
        os.remove(oldest)


_dev = get_dev_logger()
_dev.addHandler(logging.NullHandler())
_dev.propagate = False
