"""write / edit tool handlers."""
from __future__ import annotations

import json
import os

from miniclaw.config import resolve_path
from miniclaw.tools.config import ToolsConfig


def handle_write(args: dict, workspace_root: str, tools_cfg: ToolsConfig | None = None) -> str:
    """将 content 写入文件（覆盖），自动创建父目录。"""
    path = args.get("path") or ""
    content = args.get("content") or ""
    if not path:
        return json.dumps({"error": "write 需要 path 参数"}, ensure_ascii=False)
    abs_path = resolve_path(path, workspace_root)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Successfully wrote to {abs_path}"


def handle_edit(args: dict, workspace_root: str, tools_cfg: ToolsConfig | None = None) -> str:
    """精确字符串替换：old_string 必须在文件中恰好出现一次，替换为 new_string。"""
    path = args.get("path") or ""
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    if not path:
        return json.dumps({"error": "edit 需要 path 参数"}, ensure_ascii=False)
    if not old_string:
        return json.dumps({"error": "edit 需要 old_string 参数"}, ensure_ascii=False)
    abs_path = resolve_path(path, workspace_root)
    if not os.path.isfile(abs_path):
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    count = content.count(old_string)
    if count == 0:
        return json.dumps({"error": "old_string 未在文件中找到"}, ensure_ascii=False)
    if count > 1:
        return json.dumps({"error": f"old_string 在文件中出现了 {count} 次，需恰好 1 次"}, ensure_ascii=False)
    new_content = content.replace(old_string, new_string, 1)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return f"Successfully edited {abs_path}"
