"""Workspace 配置文件加载：支持全局（~/.miniclaw/）+ workspace 两级合并。"""
from __future__ import annotations

import json
import os
import re
import sys

from miniclaw.config import DEFAULT_BASE_URL, DEFAULT_HTTP_TIMEOUT, DEFAULT_MODEL
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
    cfg = load_merged_config(workspace_root)
    return cfg.get("llm", {}).get("api_key", "") or cfg.get("api_key", "")


def get_llm_config(workspace_root: str) -> dict:
    """解析完整 LLM 配置，优先级：环境变量 > config llm.* > 硬编码默认值。

    返回 {"api_key", "model", "base_url", "timeout"} 四个字段。
    api_key 为空时打印提示并退出。
    """
    cfg_llm = load_merged_config(workspace_root).get("llm", {})
    if not isinstance(cfg_llm, dict):
        cfg_llm = {}

    api_key = (os.environ.get("LLM_API_KEY", "").strip()
               or get_api_key_from_config(workspace_root).strip())
    if not api_key:
        print("错误: 未找到 API Key。请通过以下方式之一设置：", file=sys.stderr)
        print("  1. 环境变量: export LLM_API_KEY=your_key", file=sys.stderr)
        print("  2. 配置文件: config.json 的 llm.api_key 字段", file=sys.stderr)
        sys.exit(1)

    model = (os.environ.get("LLM_MODEL", "").strip()
             or str(cfg_llm.get("model", "")).strip()
             or DEFAULT_MODEL)

    base_url = (os.environ.get("LLM_BASE_URL", "").strip()
                or str(cfg_llm.get("base_url", "")).strip()
                or DEFAULT_BASE_URL)

    raw_timeout = os.environ.get("LLM_HTTP_TIMEOUT", "").strip()
    if not raw_timeout:
        raw_timeout = cfg_llm.get("timeout")
    try:
        timeout = int(raw_timeout) if raw_timeout else DEFAULT_HTTP_TIMEOUT
        if timeout <= 0:
            timeout = DEFAULT_HTTP_TIMEOUT
    except (ValueError, TypeError):
        timeout = DEFAULT_HTTP_TIMEOUT

    return {
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "timeout": timeout,
    }


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
