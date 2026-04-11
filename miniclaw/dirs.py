"""目录解析中枢：用户级数据目录、日志目录、workspace 解析。"""
from __future__ import annotations

import os
import sys

USER_DATA_DIR = os.path.join(os.path.expanduser("~"), ".miniclaw")


def get_user_data_dir() -> str:
    """用户级数据目录：~/.miniclaw/，自动创建。"""
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    return USER_DATA_DIR


def get_log_dir() -> str:
    """日志目录：MINICLAW_DEV_LOG_DIR 环境变量 > ~/.miniclaw/logs/。"""
    custom = os.environ.get("MINICLAW_DEV_LOG_DIR", "").strip()
    if custom:
        return custom
    return os.path.join(get_user_data_dir(), "logs")


def resolve_workspace(cli_arg: str | None = None) -> str:
    """按优先级解析工作区目录：CLI 参数 > 环境变量 > CWD。"""
    raw = cli_arg or os.environ.get("MINICLAW_WORKSPACE", "").strip() or os.getcwd()
    workspace = os.path.abspath(raw)
    if not os.path.isdir(workspace):
        print(f"错误: 工作区目录不存在: {workspace}", file=sys.stderr)
        sys.exit(1)
    return workspace
