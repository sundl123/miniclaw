"""目录解析中枢：用户级数据目录、日志目录、workspace 解析、首次初始化。"""
from __future__ import annotations

import importlib.resources as pkg_resources
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


_CONFIG_FILENAME = "config.json"


def _load_default_config_text() -> str:
    """从包内读取 default_config.json 模板。"""
    ref = pkg_resources.files("miniclaw").joinpath("default_config.json")
    return ref.read_text(encoding="utf-8")


def ensure_user_config(force: bool = False) -> tuple[str, bool]:
    """确保 ~/.miniclaw/config.json 存在。

    返回 (config_path, created)。
    - 文件不存在时从包内模板创建，返回 created=True
    - 文件已存在且 force=False，返回 created=False
    - force=True 时覆盖已有文件，返回 created=True
    """
    data_dir = get_user_data_dir()
    config_path = os.path.join(data_dir, _CONFIG_FILENAME)

    if os.path.isfile(config_path) and not force:
        return config_path, False

    content = _load_default_config_text()
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)
    return config_path, True
