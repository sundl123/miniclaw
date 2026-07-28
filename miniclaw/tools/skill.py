"""Skill tool handler."""
from __future__ import annotations

import json

from miniclaw.skills import normalize_skill_name


def handle_skill(args: dict, workspace_root: str, context: dict | None = None) -> str:
    """加载 skill：读取 SKILL.md 正文并注入 Base directory 前缀。"""
    raw_name = args.get("skill") or ""
    name = normalize_skill_name(raw_name)
    if not name:
        return json.dumps({"error": "Skill 需要 skill 参数"}, ensure_ascii=False)

    registry = (context or {}).get("skill_registry")
    if registry is None:
        return json.dumps({"error": "skill 注册表未初始化"}, ensure_ascii=False)

    entry = registry.lookup(name)
    if entry is None:
        return json.dumps({"error": f"未找到 skill: {name}"}, ensure_ascii=False)

    try:
        body = registry.load_skill_body(name)
    except OSError as e:
        return json.dumps({"error": f"读取 skill 失败: {e}"}, ensure_ascii=False)

    return body
