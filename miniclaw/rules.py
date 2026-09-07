"""项目规则系统：自动扫描工作区 AGENTS.md 和 .miniclaw/rules/*.md 文件。"""
from __future__ import annotations

import os


def _read_file_safely(path: str, max_bytes: int = 32768) -> str | None:
    """安全读取文件，超过限制返回 None。"""
    if not os.path.isfile(path):
        return None
    try:
        size = os.path.getsize(path)
        if size > max_bytes:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def load_rules(workspace: str) -> str | None:
    """扫描工作区规则文件，返回合并后的规则文本（用于拼入 system prompt）。

    扫描顺序：
    1. {workspace}/AGENTS.md
    2. {workspace}/.miniclaw/rules/*.md

    返回 None 表示无规则文件。
    """
    blocks: list[str] = []

    # 1. AGENTS.md
    agents_md = _read_file_safely(os.path.join(workspace, "AGENTS.md"))
    if agents_md:
        blocks.append(agents_md)

    # 2. .miniclaw/rules/*.md
    rules_dir = os.path.join(workspace, ".miniclaw", "rules")
    if os.path.isdir(rules_dir):
        for name in sorted(os.listdir(rules_dir)):
            if not name.endswith(".md"):
                continue
            filepath = os.path.join(rules_dir, name)
            content = _read_file_safely(filepath)
            if not content:
                continue
            # 用小标题区分来源文件
            rule_name = os.path.splitext(name)[0]
            blocks.append(f"### {rule_name}\n\n{content}")

    if not blocks:
        return None
    return "\n\n---\n\n".join(blocks)
