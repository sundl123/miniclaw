"""Workspace 配置文件加载：读取 .miniclaw/config.json。"""
from __future__ import annotations

import json
import os
import re

_CONFIG_FILENAME = "config.json"
_CONFIG_SUBDIR = ".miniclaw"


def load_workspace_config(workspace_root: str) -> dict:
    """加载 {workspace}/.miniclaw/config.json，不存在或解析失败返回空 dict。"""
    path = os.path.join(workspace_root, _CONFIG_SUBDIR, _CONFIG_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[警告] 配置文件解析失败 ({path}): {e}")
        return {}


def get_plan_allowed_patterns(workspace_root: str) -> list[re.Pattern]:
    """从配置文件读取 plan_mode.allowed_bash_patterns，编译为正则列表。

    配置示例::

        {
          "plan_mode": {
            "allowed_bash_patterns": ["^firecrawl\\\\b", "^curl\\\\s+-s"]
          }
        }

    无效的正则会被跳过并打印警告。
    """
    config = load_workspace_config(workspace_root)
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
