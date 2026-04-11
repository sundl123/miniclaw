"""Workspace 配置文件加载：支持全局（~/.miniclaw/）+ workspace 两级合并。"""
from __future__ import annotations

import json
import os
import re

from miniclaw.dirs import get_user_data_dir

_CONFIG_FILENAME = "config.json"
_CONFIG_SUBDIR = ".miniclaw"


def _load_json(path: str) -> dict:
    """加载单个 JSON 文件，不存在或解析失败返回空 dict。"""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[警告] 配置文件解析失败 ({path}): {e}")
        return {}


def load_workspace_config(workspace_root: str) -> dict:
    """加载 {workspace}/.miniclaw/config.json，不存在或解析失败返回空 dict。"""
    path = os.path.join(workspace_root, _CONFIG_SUBDIR, _CONFIG_FILENAME)
    return _load_json(path)


def load_merged_config(workspace_root: str) -> dict:
    """合并全局配置（~/.miniclaw/config.json）和 workspace 配置。

    workspace 配置优先：对于 dict 类型的顶层字段做 shallow merge，
    其他类型直接用 workspace 的值覆盖。
    """
    global_cfg = _load_json(os.path.join(get_user_data_dir(), _CONFIG_FILENAME))
    local_cfg = load_workspace_config(workspace_root)

    merged = {**global_cfg}
    for key, val in local_cfg.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **val}
        else:
            merged[key] = val
    return merged


def get_api_key_from_config(workspace_root: str) -> str:
    """从合并后的配置读取 api_key，返回空字符串如果未配置。"""
    return load_merged_config(workspace_root).get("api_key", "")


def get_plan_allowed_patterns(workspace_root: str) -> list[re.Pattern]:
    """从合并后的配置读取 plan_mode.allowed_bash_patterns，编译为正则列表。

    配置示例::

        {
          "plan_mode": {
            "allowed_bash_patterns": ["^firecrawl\\b", "^curl\\s+-s"]
          }
        }

    无效的正则会被跳过并打印警告。
    """
    config = load_merged_config(workspace_root)
    raw = config.get("plan_mode", {}).get("allowed_bash_patterns", [])
    if not isinstance(raw, list):
        return []
    patterns = []
    for p in raw:
        if not isinstance(p, str):
            continue
        try:
            patterns.append(re.compile(p))
        except re.error as e:
            print(f"[警告] 正则编译失败: {p!r} — {e}")
    return patterns
